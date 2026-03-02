from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

# Importujemy AuthService, żeby hashowanie było spójne z aplikacją
from src.core.auth import AuthService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OLD_DB = PROJECT_ROOT / "budget.db"             # stara baza "wszystko w jednym"
AUTH_DB = PROJECT_ROOT / "auth.db"              # nowa baza globalna: users + settings
DATA_DIR = PROJECT_ROOT / "data"                # katalog na bazy userów


BUDGET_TABLES = [
    "accounts",
    "transactions",
    "archive",
    "categories",
    "piggy_banks",
    "recurring_payments",
]


def ensure_auth_db() -> None:
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUTH_DB))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    # settings + users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # minimalne ustawienia globalne (bez app_password i bez default_balance_*)
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('dev_mode', '0')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('skip_delete_confirm', '0')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auth_enabled', '1')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('run_wizard_on_boot', '0')")
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('first_run_done', '0')")

    conn.commit()
    conn.close()


def get_or_create_user(username: str, plain_password: str) -> str:
    """
    Tworzy użytkownika w auth.db, jeśli nie istnieje.
    Jeśli istnieje - zwraca jego id (nie zmienia hasła).
    """
    conn = sqlite3.connect(str(AUTH_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row["id"]

    user_id = AuthService.hash_password("seed")  # tylko żeby wymusić import; nie używamy
    # generujemy UUID bez zależności zewnętrznych
    import uuid
    user_id = uuid.uuid4().hex

    pwd_hash = AuthService.hash_password(plain_password)

    cur.execute("""
        INSERT INTO users (id, username, password_hash, created_at, is_active)
        VALUES (?, ?, ?, date('now'), 1)
    """, (user_id, username, pwd_hash))

    conn.commit()
    conn.close()
    return user_id


def backup_old_db() -> Path:
    if not OLD_DB.exists():
        raise FileNotFoundError(f"Nie znaleziono {OLD_DB}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = PROJECT_ROOT / f"budget_backup_{ts}.db"
    shutil.copy2(OLD_DB, backup_path)
    return backup_path


def create_or_overwrite_user_db(user_id: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    user_db = DATA_DIR / f"{user_id}.db"

    if user_db.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        renamed = DATA_DIR / f"{user_id}_backup_{ts}.db"
        shutil.move(user_db, renamed)

    # tworzymy pusty plik (sqlite zrobi resztę)
    sqlite3.connect(str(user_db)).close()
    return user_db


def get_create_sql(src: sqlite3.Connection, table: str) -> str:
    cur = src.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
    row = cur.fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"Brak definicji tabeli {table} w starej bazie.")
    return row[0]


def migrate_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> int:
    s_cur = src.cursor()
    d_cur = dst.cursor()

    # odtwórz tabelę 1:1 (DROP + CREATE z definicji starej bazy)
    d_cur.execute(f"DROP TABLE IF EXISTS {table}")
    create_sql = get_create_sql(src, table)
    d_cur.execute(create_sql)

    # pobierz kolumny
    s_cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in s_cur.fetchall()]  # name
    col_list = ", ".join(cols)
    qmarks = ", ".join(["?"] * len(cols))

    # skopiuj dane
    s_cur.execute(f"SELECT {col_list} FROM {table}")
    rows = s_cur.fetchall()

    if rows:
        d_cur.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({qmarks})", rows)

    return len(rows)


def main() -> None:
    print(">>> [BOOTSTRAP] Start")

    # 1) backup starej bazy
    backup_path = backup_old_db()
    print(f">>> [BOOTSTRAP] Backup starej bazy: {backup_path.name}")

    # 2) auth.db
    ensure_auth_db()
    print(f">>> [BOOTSTRAP] auth.db gotowe: {AUTH_DB}")

    # 3) użytkownik Artur / 000000
    user_id = get_or_create_user("Artur", "000000")
    print(f">>> [BOOTSTRAP] Użytkownik: Artur | user_id={user_id}")

    # 4) user db
    user_db = create_or_overwrite_user_db(user_id)
    print(f">>> [BOOTSTRAP] Baza użytkownika: {user_db}")

    # 5) migracja danych budżetowych
    src = sqlite3.connect(str(OLD_DB))
    dst = sqlite3.connect(str(user_db))
    try:
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row
        dst.execute("PRAGMA foreign_keys = OFF")  # bezpieczniej na czas kopiowania
        dst.execute("BEGIN")

        total = 0
        for t in BUDGET_TABLES:
            count = migrate_table(src, dst, t)
            total += count
            print(f">>> [MIGRATE] {t}: {count} rekordów")

        dst.commit()
        print(f">>> [BOOTSTRAP] Migracja OK. Łącznie skopiowano wierszy: {total}")

    except Exception as e:
        dst.rollback()
        print("!!! [BOOTSTRAP] BŁĄD migracji. Wycofano zmiany.")
        raise
    finally:
        src.close()
        dst.close()

    print(">>> [BOOTSTRAP] GOTOWE")
    print(">>> Teraz możesz dopasować aplikację do trybu per-user DB (data/<user_id>.db).")


if __name__ == "__main__":
    main()