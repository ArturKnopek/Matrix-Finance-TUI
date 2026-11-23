"""
Jednorazowa migracja starej bazy „wszystko w jednym” (budget.db) do układu
per-użytkownik używanego przez aplikację (~/.matrix_finance/auth.db + data/<user_id>.db).

Użycie:
    python -m src.migrate --old-db sciezka/do/budget.db --user Jan
    (hasło zostanie pobrane interaktywnie; można też podać --password)
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

# Importujemy AuthService, żeby hashowanie było spójne z aplikacją
from src.core.auth import AuthService
from src.finance.storage import AUTH_DB as _AUTH_DB, DATA_DIR, init_auth_db, init_user_db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OLD_DB = PROJECT_ROOT / "budget.db"             # domyślna lokalizacja starej bazy
AUTH_DB = Path(_AUTH_DB)                        # ta sama baza logowania, której używa aplikacja


BUDGET_TABLES = [
    "accounts",
    "transactions",
    "archive",
    "categories",
    "piggy_banks",
    "recurring_payments",
]


def ensure_auth_db() -> None:
    """Tworzy auth.db dokładnie tak jak aplikacja."""
    init_auth_db()


def _legacy_ensure_auth_db() -> None:
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


def backup_old_db(old_db: Path = OLD_DB) -> Path:
    if not old_db.exists():
        raise FileNotFoundError(f"Nie znaleziono {old_db}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = old_db.with_name(f"budget_backup_{ts}.db")
    shutil.copy2(old_db, backup_path)
    return backup_path


def create_or_overwrite_user_db(user_id: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migracja starej bazy budget.db do Matrix Finance")
    parser.add_argument("--old-db", type=Path, default=OLD_DB, help="ścieżka do starej bazy budget.db")
    parser.add_argument("--user", required=True, help="nazwa użytkownika, do którego trafią dane")
    parser.add_argument("--password", help="hasło (gdy pominięte – zostanie pobrane interaktywnie)")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    password = args.password or getpass.getpass(f"Hasło dla użytkownika {args.user} (min. 6 znaków): ")
    if len(password) < 6:
        raise SystemExit("Hasło musi mieć co najmniej 6 znaków.")

    print(">>> [BOOTSTRAP] Start")

    # 1) backup starej bazy
    backup_path = backup_old_db(args.old_db)
    print(f">>> [BOOTSTRAP] Backup starej bazy: {backup_path}")

    # 2) auth.db
    ensure_auth_db()
    print(f">>> [BOOTSTRAP] auth.db gotowe: {AUTH_DB}")

    # 3) użytkownik
    user_id = get_or_create_user(args.user, password)
    print(f">>> [BOOTSTRAP] Użytkownik: {args.user} | user_id={user_id}")

    # 4) user db
    user_db = create_or_overwrite_user_db(user_id)
    print(f">>> [BOOTSTRAP] Baza użytkownika: {user_db}")

    # 5) migracja danych budżetowych
    src = sqlite3.connect(str(args.old_db))
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

    except Exception:
        dst.rollback()
        print("!!! [BOOTSTRAP] BŁĄD migracji. Wycofano zmiany.")
        raise
    finally:
        src.close()
        dst.close()

    # 6) dociągnięcie schematu do aktualnej wersji aplikacji
    init_user_db(str(user_db))
    print(">>> [BOOTSTRAP] GOTOWE – możesz zalogować się w aplikacji.")


if __name__ == "__main__":
    main()
