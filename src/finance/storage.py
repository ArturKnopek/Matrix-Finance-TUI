"""
Warstwa przechowywania danych: ścieżki, połączenia SQLite, schemat i migracje,
użytkownicy (auth.db) oraz ustawienia.

Układ plików (~/.matrix_finance):
    auth.db                 – użytkownicy + ustawienia globalne
    data/<user_id>.db       – dane budżetu użytkownika (w trakcie sesji)
    data/<user_id>.db.enc   – zaszyfrowana baza (gdy włączone szyfrowanie na dysku)
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

from src.utils.paths import data_home

PROJECT_ROOT = data_home()
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)

AUTH_DB = str(PROJECT_ROOT / "auth.db")
DATA_DIR = PROJECT_ROOT / "data"
USER_SCHEMA_VERSION = 4

DEFAULT_CATEGORIES: Tuple[str, ...] = (
    "Jedzenie", "Transport", "Rachunki", "Zdrowie", "Rozrywka", "Zakupy", "Wynagrodzenie", "Inne",
)
SAVINGS_CATEGORY = "Oszczędności"
INTEREST_CATEGORY = "Odsetki i zyski"

_ACTIVE_USER_DB: Optional[str] = None
log = logging.getLogger(__name__)


# =============================================================================
# Ścieżki i aktywna baza
# =============================================================================

def generate_id() -> str:
    return uuid.uuid4().hex


def user_db_path(user_id: str) -> Path:
    return DATA_DIR / f"{user_id}.db"


def set_active_user_db(user_id: str) -> str:
    """Ustawia aktywną bazę użytkownika: data/<user_id>.db."""
    global _ACTIVE_USER_DB
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ACTIVE_USER_DB = str(user_db_path(user_id))
    return _ACTIVE_USER_DB


def get_active_user_db() -> str:
    """Ścieżka aktywnej bazy (bez sesji: data/_guest.db)."""
    if _ACTIVE_USER_DB:
        return _ACTIVE_USER_DB
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(DATA_DIR / "_guest.db")


def clear_active_user_db() -> None:
    global _ACTIVE_USER_DB
    _ACTIVE_USER_DB = None


# =============================================================================
# Połączenia
# =============================================================================

def _py_lower(value: Any) -> Any:
    """lower() z obsługą polskich znaków (SQLite LOWER działa tylko dla ASCII)."""
    return value.lower() if isinstance(value, str) else value


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_path(path: str) -> sqlite3.Connection:
    """Połączenie z plikiem albo z bazą w pamięci (URI „file:…?mode=memory&cache=shared”)."""
    return sqlite3.connect(path, timeout=10, uri=str(path).startswith("file:"))


def get_auth_connection() -> sqlite3.Connection:
    return _configure(sqlite3.connect(AUTH_DB, timeout=10))


def get_connection() -> sqlite3.Connection:
    """Połączenie z aktywną bazą użytkownika (plik albo zaszyfrowana sesja w pamięci)."""
    conn = _configure(connect_path(get_active_user_db()))
    conn.create_function("py_lower", 1, _py_lower, deterministic=True)
    return conn


def set_active_user_db_uri(uri: str) -> str:
    """Aktywuje bazę w pamięci (sesja zaszyfrowana — patrz src/core/vault.py)."""
    global _ACTIVE_USER_DB
    _ACTIVE_USER_DB = uri
    return uri


@contextmanager
def open_user_db(write: bool = False) -> Iterator[sqlite3.Connection]:
    """
    Kontekst połączenia z bazą użytkownika.
    write=True -> jedna transakcja (BEGIN IMMEDIATE), commit na końcu, rollback przy błędzie.
    """
    conn = get_connection()
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def open_auth_db(write: bool = False) -> Iterator[sqlite3.Connection]:
    conn = get_auth_connection()
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_code(prefix: str, n: int) -> str:
    """Kod czytelny dla człowieka, np. TX000042."""
    return f"{prefix}{int(n):06d}"


_code = make_code  # zgodność wsteczna


# =============================================================================
# Pomocnicze: kolumny / ustawienia w połączeniu
# =============================================================================

def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_setting_in(conn: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else row[0]


def set_setting_in(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


# zgodność wsteczna
_ensure_column = ensure_column
_column_exists = column_exists
_get_setting_from_conn = get_setting_in
_set_setting_in_conn = set_setting_in


# =============================================================================
# auth.db – użytkownicy i ustawienia globalne
# =============================================================================

def init_auth_db() -> None:
    with open_auth_db(write=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                is_active     INTEGER NOT NULL DEFAULT 1
            )
        """)
        # bezpieczeństwo (v1.2): szyfrowanie na dysku + klucz sprzętowy
        ensure_column(conn, "users", "encrypt_at_rest", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "users", "yubikey_enabled", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "users", "yubikey_slot", "INTEGER NOT NULL DEFAULT 2")
        ensure_column(conn, "users", "yubikey_challenge", "TEXT")
        ensure_column(conn, "users", "yubikey_response_hash", "TEXT")
        ensure_column(conn, "users", "recovery_hash", "TEXT")
        for key, value in (
            ("dev_mode", "0"),
            ("skip_delete_confirm", "0"),
            ("auth_enabled", "1"),
            ("run_wizard_on_boot", "0"),
            ("first_run_done", "0"),
            ("ui_theme", "matrix"),
            ("ui_animations", "1"),
        ):
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def user_exists() -> bool:
    with open_auth_db() as conn:
        return conn.execute("SELECT 1 FROM users WHERE is_active = 1 LIMIT 1").fetchone() is not None


def get_user_by_username(username: str):
    with open_auth_db() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_id(user_id: str):
    with open_auth_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(username: str, password_hash: str):
    uid = generate_id()
    try:
        with open_auth_db(write=True) as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at, is_active) VALUES (?, ?, ?, date('now'), 1)",
                (uid, username, password_hash),
            )
        return True, "", uid
    except sqlite3.IntegrityError:
        return False, "Nazwa użytkownika zajęta.", None
    except Exception as e:
        return False, str(e), None


def update_user_password(user_id: str, new_hash: str) -> bool:
    try:
        with open_auth_db(write=True) as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        return True
    except Exception:
        return False


def update_user_fields(user_id: str, **fields: Any) -> None:
    """Aktualizuje wybrane kolumny użytkownika (np. encrypt_at_rest, yubikey_*)."""
    allowed = {"encrypt_at_rest", "yubikey_enabled", "yubikey_slot", "yubikey_challenge",
               "yubikey_response_hash", "recovery_hash", "is_active"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Niedozwolone pola: {', '.join(sorted(bad))}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with open_auth_db(write=True) as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))


def get_all_users():
    with open_auth_db() as conn:
        return conn.execute("SELECT id, username, is_active FROM users ORDER BY username ASC").fetchall()


def delete_user(user_id: str) -> bool:
    try:
        with open_auth_db(write=True) as conn:
            deleted = conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount > 0
    except Exception:
        return False
    if deleted:
        for suffix in ("", "-wal", "-shm", ".enc"):
            path = Path(str(user_db_path(user_id)) + suffix)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return deleted


def get_setting(key: str, default_value: str = "0") -> str:
    """Ustawienie globalne (auth.db)."""
    with open_auth_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default_value


def set_setting(key: str, value: Any) -> None:
    with open_auth_db(write=True) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


# =============================================================================
# Baza użytkownika – schemat
# =============================================================================

_USER_TABLES_SQL = [
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)",
    """
    CREATE TABLE IF NOT EXISTS accounts (
        name    TEXT PRIMARY KEY,
        balance REAL DEFAULT 0.0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ct_code      TEXT,
        name         TEXT UNIQUE NOT NULL,
        limit_amount REAL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_uid        TEXT,
        human_code    TEXT,
        date          TEXT NOT NULL,
        type          TEXT DEFAULT 'Wydatek',
        category      TEXT,
        account_type  TEXT DEFAULT 'Karta',
        shop          TEXT,
        amount        REAL,
        description   TEXT,
        is_registered INTEGER DEFAULT 1,
        FOREIGN KEY (category) REFERENCES categories (name) ON DELETE SET NULL ON UPDATE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive (
        id           INTEGER PRIMARY KEY,
        date         TEXT,
        type         TEXT,
        category     TEXT,
        account_type TEXT,
        shop         TEXT,
        amount       REAL,
        description  TEXT,
        archived_at  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS piggy_banks (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        pb_code        TEXT,
        name           TEXT UNIQUE NOT NULL,
        target_amount  REAL DEFAULT 0,
        current_amount REAL DEFAULT 0,
        account_type   TEXT DEFAULT 'Karta'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recurring_payments (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        rr_code           TEXT,
        name              TEXT NOT NULL,
        amount            REAL NOT NULL,
        type              TEXT NOT NULL,
        category          TEXT,
        account_type      TEXT DEFAULT 'Karta',
        cycle             TEXT NOT NULL,
        start_date        TEXT NOT NULL,
        last_payment_date TEXT,
        is_registered     INTEGER DEFAULT 1,
        piggy_id          INTEGER DEFAULT NULL,
        FOREIGN KEY (piggy_id) REFERENCES piggy_banks (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS envelope_adjustments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        ym          TEXT NOT NULL,
        amount      REAL NOT NULL,
        note        TEXT,
        created_at  TEXT,
        FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
    )
    """,
    # synchronizacja telefon ↔ PC (nie są częścią eksportu danych)
    """
    CREATE TABLE IF NOT EXISTS sync_applied (
        op_id      TEXT PRIMARY KEY,
        device     TEXT,
        op         TEXT,
        status     TEXT NOT NULL,
        message    TEXT,
        applied_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_outbox (
        op_id   TEXT PRIMARY KEY,
        ts      TEXT NOT NULL,
        op      TEXT NOT NULL,
        data    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS autosave_rules (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT,
        source_account TEXT NOT NULL,
        mode           TEXT NOT NULL DEFAULT 'income_percent',
        value          REAL NOT NULL,
        target_kind    TEXT NOT NULL DEFAULT 'account',
        target         TEXT NOT NULL,
        is_active      INTEGER NOT NULL DEFAULT 1,
        created_at     TEXT
    )
    """,
]


def init_user_db(db_path: str, start_card: float = 0.0, start_cash: float = 0.0) -> None:
    """Tworzy/aktualizuje schemat bazy użytkownika (bezpieczne przy każdym logowaniu)."""
    conn = _configure(connect_path(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        for sql in _USER_TABLES_SQL:
            conn.execute(sql)
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('active_view_month', ?)",
            (datetime.now().strftime("%Y-%m"),),
        )
        if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
            conn.execute("INSERT INTO accounts (name, balance) VALUES ('Karta', ?)", (float(start_card),))
            conn.execute("INSERT INTO accounts (name, balance) VALUES ('Gotówka', ?)", (float(start_cash),))
        ensure_user_schema(conn)
        _seed_default_categories(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _ensure_codes(conn)
        conn.close()


def ensure_user_schema(conn: sqlite3.Connection, start_card: float = 0.0, start_cash: float = 0.0) -> None:
    """Migracje kolumn (idempotentne). Wersja 3: rodzaje kont, lokaty, koperty, cele z terminem."""
    stamp = now_iso()

    # --- KONTA ---
    for column, ddl in (
        ("currency", "TEXT NOT NULL DEFAULT 'PLN'"),
        ("account_kind", "TEXT NOT NULL DEFAULT 'checking'"),
        ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("include_in_reports", "INTEGER NOT NULL DEFAULT 1"),
        ("include_in_net_worth", "INTEGER NOT NULL DEFAULT 1"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
        ("institution", "TEXT"),
        ("interest_rate", "REAL NOT NULL DEFAULT 0"),
        ("tax_rate", "REAL NOT NULL DEFAULT 19"),
        ("opened_at", "TEXT"),
        ("maturity_date", "TEXT"),
        ("term_months", "INTEGER"),
        ("principal", "REAL NOT NULL DEFAULT 0"),
        ("linked_account", "TEXT"),
        ("auto_renew", "INTEGER NOT NULL DEFAULT 0"),
        ("yearly_limit", "REAL NOT NULL DEFAULT 0"),
        ("notes", "TEXT"),
        ("closed_at", "TEXT"),
        # wersja 4: własne rodzaje kont, kredyty i raty
        ("custom_label", "TEXT"),
        ("custom_group", "TEXT"),
        ("custom_flags", "TEXT"),
        ("loan_installment", "REAL NOT NULL DEFAULT 0"),
        ("loan_category", "TEXT"),
        ("loan_first_due", "TEXT"),
    ):
        ensure_column(conn, "accounts", column, ddl)

    conn.execute("UPDATE accounts SET currency='PLN' WHERE currency IS NULL OR TRIM(currency) = ''")
    conn.execute("UPDATE accounts SET is_active=1 WHERE is_active IS NULL")
    conn.execute("UPDATE accounts SET created_at=? WHERE created_at IS NULL OR TRIM(created_at) = ''", (stamp,))
    conn.execute("UPDATE accounts SET updated_at=? WHERE updated_at IS NULL OR TRIM(updated_at) = ''", (stamp,))
    # stare rodzaje kont -> nowe
    conn.execute("UPDATE accounts SET account_kind='cash' WHERE name = 'Gotówka' AND account_kind IN ('wallet', '')")
    conn.execute("UPDATE accounts SET account_kind='checking' "
                 "WHERE account_kind IS NULL OR account_kind IN ('wallet', 'card', '')")
    conn.execute("UPDATE accounts SET sort_order = 10 WHERE name = 'Karta' AND sort_order = 0")
    conn.execute("UPDATE accounts SET sort_order = 20 WHERE name = 'Gotówka' AND sort_order = 0")

    # --- KOPERTY (kategorie) ---
    ensure_column(conn, "categories", "rollover", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "categories", "rollover_since", "TEXT")
    ensure_column(conn, "categories", "created_at", "TEXT")
    conn.execute("UPDATE categories SET created_at=? WHERE created_at IS NULL", (stamp,))

    # --- CELE ---
    for column, ddl in (
        ("currency", "TEXT NOT NULL DEFAULT 'PLN'"),
        ("bucket_type", "TEXT NOT NULL DEFAULT 'piggy_bank'"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("include_in_net_worth", "INTEGER NOT NULL DEFAULT 1"),
        ("notes", "TEXT"),
        ("target_date", "TEXT"),
    ):
        ensure_column(conn, "piggy_banks", column, ddl)

    # --- TRANSAKCJE / ARCHIWUM ---
    for table in ("transactions", "archive"):
        ensure_column(conn, table, "entry_subtype", "TEXT NOT NULL DEFAULT 'regular'")
        ensure_column(conn, table, "linked_group_id", "TEXT")
        ensure_column(conn, table, "goal_id", "INTEGER")

    # --- CYKLICZNE ---
    ensure_column(conn, "recurring_payments", "entry_subtype", "TEXT NOT NULL DEFAULT 'regular'")
    ensure_column(conn, "recurring_payments", "pause_until", "TEXT")
    ensure_column(conn, "recurring_payments", "starts_paused", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "recurring_payments", "target_account", "TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_group ON transactions(linked_group_id)")

    set_setting_in(conn, "schema_version", USER_SCHEMA_VERSION)
    set_setting_in(conn, "schema_updated_at", stamp)


def _seed_default_categories(conn: sqlite3.Connection) -> None:
    """Domyślne koperty tylko dla zupełnie nowej bazy (jednorazowo)."""
    if get_setting_in(conn, "defaults_seeded", "0") == "1":
        return
    has_categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0
    has_transactions = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 0
    if not has_categories and not has_transactions:
        for name in DEFAULT_CATEGORIES:
            cur = conn.execute("INSERT OR IGNORE INTO categories (name, limit_amount, created_at) VALUES (?, 0, ?)",
                               (name, now_iso()))
            if cur.lastrowid:
                conn.execute("UPDATE categories SET ct_code = ? WHERE id = ?",
                             (make_code("CT", cur.lastrowid), cur.lastrowid))
    set_setting_in(conn, "defaults_seeded", "1")


def _ensure_codes(conn: sqlite3.Connection) -> None:
    """Uzupełnia brakujące kody (TX/CT/PB/RR) i identyfikatory transakcji."""
    try:
        ensure_column(conn, "transactions", "tx_uid", "TEXT")
        ensure_column(conn, "transactions", "human_code", "TEXT")
        for (t_id,) in conn.execute("SELECT id FROM transactions WHERE tx_uid IS NULL OR tx_uid = ''").fetchall():
            conn.execute("UPDATE transactions SET tx_uid = ? WHERE id = ?", (uuid.uuid4().hex, t_id))
        for table, column, prefix in (
            ("transactions", "human_code", "TX"),
            ("categories", "ct_code", "CT"),
            ("piggy_banks", "pb_code", "PB"),
            ("recurring_payments", "rr_code", "RR"),
        ):
            ensure_column(conn, table, column, "TEXT")
            rows = conn.execute(f"SELECT id FROM {table} WHERE {column} IS NULL OR {column} = ''").fetchall()
            for (row_id,) in rows:
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (make_code(prefix, row_id), row_id))
        conn.commit()
    except Exception as e:
        log.warning("Nie udało się uzupełnić kodów: %s", e)


def get_schema_version() -> int:
    with open_user_db() as conn:
        try:
            return int(get_setting_in(conn, "schema_version", "1"))
        except ValueError:
            return 1


# =============================================================================
# Ustawienia użytkownika
# =============================================================================

def get_user_setting(key: str, default: str = "") -> str:
    with open_user_db() as conn:
        return get_setting_in(conn, key, default)


def set_user_setting(key: str, value: Any) -> None:
    with open_user_db(write=True) as conn:
        set_setting_in(conn, key, value)


def get_active_month_str() -> str:
    return get_user_setting("active_view_month", datetime.now().strftime("%Y-%m")) or datetime.now().strftime("%Y-%m")


def set_active_month_str(yyyy_mm: str) -> None:
    datetime.strptime(yyyy_mm, "%Y-%m")  # walidacja
    set_user_setting("active_view_month", yyyy_mm)


def shift_active_month(delta: int) -> str:
    """Przesuwa miesiąc roboczy o delta miesięcy; zwraca nowy YYYY-MM."""
    y, m = map(int, get_active_month_str().split("-"))
    idx = y * 12 + (m - 1) + delta
    new = f"{idx // 12:04d}-{idx % 12 + 1:02d}"
    set_active_month_str(new)
    return new


def sync_active_month() -> None:
    now_month = datetime.now().strftime("%Y-%m")
    if get_active_month_str() != now_month:
        set_active_month_str(now_month)


def reset_user_db_hard() -> None:
    with open_user_db(write=True) as conn:
        for table in ("transactions", "accounts", "categories", "piggy_banks", "recurring_payments", "archive",
                      "autosave_rules", "envelope_adjustments", "sync_applied", "sync_outbox", "settings"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    init_user_db(get_active_user_db(), 0.0, 0.0)


def list_user_tables() -> List[str]:
    return ["settings", "accounts", "categories", "piggy_banks", "transactions", "archive",
            "recurring_payments", "autosave_rules", "envelope_adjustments"]
