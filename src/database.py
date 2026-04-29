from __future__ import annotations

import sqlite3
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

# ==============================================================================
# ŚCIEŻKI BAZ DANYCH (AUTH + USER DB) - FIX BŁĄD 10 (Bezpieczna lokalizacja dla .exe)
# ==============================================================================

PROJECT_ROOT = Path.home() / ".matrix_finance"
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)

AUTH_DB = str(PROJECT_ROOT / "auth.db")  # logowanie + ustawienia globalne
DATA_DIR = PROJECT_ROOT / "data"  # bazy użytkowników: data/<user_id>.db
USER_SCHEMA_VERSION = 2
_ACTIVE_USER_DB: str | None = None


def generate_id() -> str:
    """Generator tekstowego ID (UUID4) bez dodatkowych zależności."""
    import uuid
    return uuid.uuid4().hex


def set_active_user_db(user_id: str) -> str:
    """Ustawia aktywną bazę danych użytkownika: data/<user_id>.db"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = str(DATA_DIR / f"{user_id}.db")
    global _ACTIVE_USER_DB
    _ACTIVE_USER_DB = db_path
    return db_path


def get_active_user_db() -> str:
    """Zwraca ścieżkę do aktywnej bazy usera, a gdy brak sesji -> _guest.db"""
    if _ACTIVE_USER_DB:
        return _ACTIVE_USER_DB
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(DATA_DIR / "_guest.db")


def clear_active_user_db() -> None:
    """Czyści aktywną bazę użytkownika (powrót do _guest.db)."""
    global _ACTIVE_USER_DB
    _ACTIVE_USER_DB = None


# ==============================================================================
# CONNECTIONS - FIX BŁĄD 13 (Złudzenie integralności)
# ==============================================================================

def get_auth_connection() -> sqlite3.Connection:
    """Połączenie do bazy autoryzacji (auth.db)."""
    conn = sqlite3.connect(AUTH_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")  # Zabezpiecza relacje
    return conn


def get_connection() -> sqlite3.Connection:
    """Połączenie do aktywnej bazy użytkownika (data/<user_id>.db)."""
    conn = sqlite3.connect(get_active_user_db(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")  # Zabezpiecza relacje
    return conn

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cur.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _get_setting_from_conn(conn: sqlite3.Connection, key: str, default: str = "0") -> str:
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    if row is None:
        return default
    if isinstance(row, sqlite3.Row):
        return row["value"]
    return row[0]


def _set_setting_in_conn(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value)),
    )


def ensure_user_schema(conn: sqlite3.Connection, start_card: float = 0.0, start_cash: float = 0.0) -> None:
    """
    PATCH 0:
    - wprowadza wersjonowanie schematu,
    - rozszerza tabelę accounts,
    - rozszerza piggy_banks pod aktywa / brak limitu,
    - dodaje kolumny techniczne pod przyszłe transfery i auto-oszczędzanie,
    - zachowuje kompatybilność ze starym UI.
    """
    cur = conn.cursor()

    # settings musi istnieć zanim zapiszemy schema_version
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # --- ACCOUNTS: rozszerzenie pod wiele kont ---
    _ensure_column(conn, "accounts", "currency", "TEXT NOT NULL DEFAULT 'PLN'")
    _ensure_column(conn, "accounts", "account_kind", "TEXT NOT NULL DEFAULT 'wallet'")
    _ensure_column(conn, "accounts", "sort_order", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "accounts", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "accounts", "include_in_reports", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "accounts", "include_in_net_worth", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "accounts", "created_at", "TEXT")
    _ensure_column(conn, "accounts", "updated_at", "TEXT")

    now_iso = datetime.now().isoformat(timespec="seconds")

    conn.execute("UPDATE accounts SET currency='PLN' WHERE currency IS NULL OR TRIM(currency) = ''")
    conn.execute("UPDATE accounts SET account_kind='wallet' WHERE account_kind IS NULL OR TRIM(account_kind) = ''")
    conn.execute("UPDATE accounts SET is_active=1 WHERE is_active IS NULL")
    conn.execute("UPDATE accounts SET include_in_reports=1 WHERE include_in_reports IS NULL")
    conn.execute("UPDATE accounts SET include_in_net_worth=1 WHERE include_in_net_worth IS NULL")
    conn.execute("UPDATE accounts SET created_at=? WHERE created_at IS NULL OR TRIM(created_at) = ''", (now_iso,))
    conn.execute("UPDATE accounts SET updated_at=? WHERE updated_at IS NULL OR TRIM(updated_at) = ''", (now_iso,))

    # Bezpieczne zasianie domyślnych kont, jeśli DB jest nowa / pusta
    cur.execute("SELECT COUNT(*) FROM accounts")
    count_accounts = cur.fetchone()[0]
    if count_accounts == 0:
        cur.execute("""
            INSERT INTO accounts
            (name, balance, currency, account_kind, sort_order, is_active, include_in_reports, include_in_net_worth, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
        """, ("Karta", float(start_card or 0.0), "PLN", "card", 10, now_iso, now_iso))
        cur.execute("""
            INSERT INTO accounts
            (name, balance, currency, account_kind, sort_order, is_active, include_in_reports, include_in_net_worth, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
        """, ("Gotówka", float(start_cash or 0.0), "PLN", "cash", 20, now_iso, now_iso))

    # --- PIGGY BANKS / AKTYWA ---
    _ensure_column(conn, "piggy_banks", "currency", "TEXT NOT NULL DEFAULT 'PLN'")
    _ensure_column(conn, "piggy_banks", "bucket_type", "TEXT NOT NULL DEFAULT 'piggy_bank'")
    _ensure_column(conn, "piggy_banks", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "piggy_banks", "include_in_net_worth", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "piggy_banks", "notes", "TEXT")

    conn.execute("UPDATE piggy_banks SET currency='PLN' WHERE currency IS NULL OR TRIM(currency) = ''")
    conn.execute("UPDATE piggy_banks SET bucket_type='piggy_bank' WHERE bucket_type IS NULL OR TRIM(bucket_type) = ''")
    conn.execute("UPDATE piggy_banks SET is_active=1 WHERE is_active IS NULL")
    conn.execute("UPDATE piggy_banks SET include_in_net_worth=1 WHERE include_in_net_worth IS NULL")

    # --- TRANSAKCJE / ARCHIWUM: techniczne kolumny pod transfery i autosave ---
    _ensure_column(conn, "transactions", "entry_subtype", "TEXT NOT NULL DEFAULT 'regular'")
    _ensure_column(conn, "transactions", "linked_group_id", "TEXT")
    _ensure_column(conn, "archive", "entry_subtype", "TEXT NOT NULL DEFAULT 'regular'")
    _ensure_column(conn, "archive", "linked_group_id", "TEXT")

    # --- CYKLICZNE: start pod pauzę / autooszczędzanie ---
    _ensure_column(conn, "recurring_payments", "entry_subtype", "TEXT NOT NULL DEFAULT 'regular'")
    _ensure_column(conn, "recurring_payments", "pause_until", "TEXT")
    _ensure_column(conn, "recurring_payments", "starts_paused", "INTEGER NOT NULL DEFAULT 0")

    # --- METADATA SCHEMATU ---
    _set_setting_in_conn(conn, "schema_version", USER_SCHEMA_VERSION)
    _set_setting_in_conn(conn, "schema_updated_at", now_iso)
    conn.commit()


def get_schema_version() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'schema_version'")
        row = cur.fetchone()
        if not row:
            return 1
        raw = row["value"] if isinstance(row, sqlite3.Row) else row[0]
        try:
            return int(raw)
        except Exception:
            return 1
    finally:
        conn.close()


def get_all_accounts_data(active_only: bool = False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM accounts"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY sort_order ASC, name ASC"
        cur.execute(query)
        return cur.fetchall()
    finally:
        conn.close()


def get_account_names(active_only: bool = True) -> List[str]:
    rows = get_all_accounts_data(active_only=active_only)
    return [row["name"] for row in rows]


def get_account_options(active_only: bool = True) -> List[Tuple[str, str]]:
    rows = get_all_accounts_data(active_only=active_only)
    if not rows:
        return [("Karta", "Karta"), ("Gotówka", "Gotówka")]

    out: List[Tuple[str, str]] = []
    for row in rows:
        label = row["name"]
        if row["currency"] and row["currency"] != "PLN":
            label = f"{row['name']} ({row['currency']})"
        out.append((label, row["name"]))
    return out


def add_account(
    name: str,
    opening_balance: float = 0.0,
    currency: str = "PLN",
    account_kind: str = "wallet",
    include_in_reports: bool = True,
    include_in_net_worth: bool = True,
) -> Tuple[bool, str]:
    name = (name or "").strip()
    currency = (currency or "PLN").strip().upper()
    account_kind = (account_kind or "wallet").strip()

    if not name:
        return False, "Podaj nazwę konta."

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM accounts")
        next_order = cur.fetchone()[0] or 10
        now_iso = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO accounts
            (name, balance, currency, account_kind, sort_order, is_active, include_in_reports, include_in_net_worth, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (
            name,
            float(opening_balance or 0.0),
            currency,
            account_kind,
            int(next_order),
            1 if include_in_reports else 0,
            1 if include_in_net_worth else 0,
            now_iso,
            now_iso,
        ))
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Konto o tej nazwie już istnieje."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def update_account_name_everywhere(old_name: str, new_name: str) -> Tuple[bool, str]:
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()

    if not old_name or not new_name:
        return False, "Niepoprawna nazwa konta."

    conn = get_connection()
    try:
        cur = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")

        cur.execute("UPDATE accounts SET name=?, updated_at=? WHERE name=?", (
            new_name,
            datetime.now().isoformat(timespec="seconds"),
            old_name,
        ))
        cur.execute("UPDATE transactions SET account_type=? WHERE account_type=?", (new_name, old_name))
        cur.execute("UPDATE archive SET account_type=? WHERE account_type=?", (new_name, old_name))
        cur.execute("UPDATE piggy_banks SET account_type=? WHERE account_type=?", (new_name, old_name))
        cur.execute("UPDATE recurring_payments SET account_type=? WHERE account_type=?", (new_name, old_name))

        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Konto o tej nazwie już istnieje."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ==============================================================================
# INIT AUTH DB (users + global settings)
# ==============================================================================

def init_auth_db() -> None:
    """Tworzy bazę auth.db: users + global settings (bez budżetu)."""
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings
                    (
                        key
                        TEXT
                        PRIMARY
                        KEY,
                        value
                        TEXT
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS users
                    (
                        id
                        TEXT
                        PRIMARY
                        KEY,
                        username
                        TEXT
                        UNIQUE
                        NOT
                        NULL,
                        password_hash
                        TEXT
                        NOT
                        NULL,
                        created_at
                        TEXT
                        NOT
                        NULL,
                        is_active
                        INTEGER
                        NOT
                        NULL
                        DEFAULT
                        1
                    )
                    """)
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('dev_mode', '0')")
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('skip_delete_confirm', '0')")
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auth_enabled', '1')")
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('run_wizard_on_boot', '0')")
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('first_run_done', '0')")
        conn.commit()
    finally:
        conn.close()


# ==============================================================================
# INIT USER DB (budget tables + user-local settings)
# ==============================================================================

def init_user_db(db_path: str, start_card: float = 0.0, start_cash: float = 0.0) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 8000")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("PRAGMA foreign_keys = ON")

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings
                    (
                        key
                        TEXT
                        PRIMARY
                        KEY,
                        value
                        TEXT
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS accounts
                    (
                        name
                        TEXT
                        PRIMARY
                        KEY,
                        balance
                        REAL
                        DEFAULT
                        0.0
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS transactions
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY
                        AUTOINCREMENT,
                        tx_uid
                        TEXT,
                        human_code
                        TEXT,
                        date
                        TEXT
                        NOT
                        NULL,
                        type
                        TEXT
                        DEFAULT
                        'Wydatek',
                        category
                        TEXT,
                        account_type
                        TEXT
                        DEFAULT
                        'Karta',
                        shop
                        TEXT,
                        amount
                        REAL,
                        description
                        TEXT,
                        is_registered
                        INTEGER
                        DEFAULT
                        1,
                        FOREIGN
                        KEY
                    (
                        category
                    ) REFERENCES categories
                    (
                        name
                    ) ON DELETE SET NULL
                      ON UPDATE CASCADE
                        )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS archive
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY,
                        date
                        TEXT,
                        type
                        TEXT,
                        category
                        TEXT,
                        account_type
                        TEXT,
                        shop
                        TEXT,
                        amount
                        REAL,
                        description
                        TEXT,
                        archived_at
                        TEXT
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS categories
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY
                        AUTOINCREMENT,
                        ct_code
                        TEXT,
                        name
                        TEXT
                        UNIQUE
                        NOT
                        NULL,
                        limit_amount
                        REAL
                        DEFAULT
                        0
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS piggy_banks
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY
                        AUTOINCREMENT,
                        pb_code
                        TEXT,
                        name
                        TEXT
                        UNIQUE
                        NOT
                        NULL,
                        target_amount
                        REAL
                        DEFAULT
                        0,
                        current_amount
                        REAL
                        DEFAULT
                        0,
                        account_type
                        TEXT
                        DEFAULT
                        'Karta'
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS recurring_payments
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY
                        AUTOINCREMENT,
                        rr_code
                        TEXT,
                        name
                        TEXT
                        NOT
                        NULL,
                        amount
                        REAL
                        NOT
                        NULL,
                        type
                        TEXT
                        NOT
                        NULL,
                        category
                        TEXT,
                        account_type
                        TEXT
                        DEFAULT
                        'Karta',
                        cycle
                        TEXT
                        NOT
                        NULL,
                        start_date
                        TEXT
                        NOT
                        NULL,
                        last_payment_date
                        TEXT,
                        is_registered
                        INTEGER
                        DEFAULT
                        1,
                        piggy_id
                        INTEGER
                        DEFAULT
                        NULL,
                        FOREIGN
                        KEY
                    (
                        piggy_id
                    ) REFERENCES piggy_banks
                    (
                        id
                    ) ON DELETE CASCADE
                        )
                    """)
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('active_view_month', ?)",
            (datetime.now().strftime("%Y-%m"),)
        )
        cur.execute("SELECT count(*) FROM accounts")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO accounts (name, balance) VALUES ('Karta', ?)", (float(start_card),))
            cur.execute("INSERT INTO accounts (name, balance) VALUES ('Gotówka', ?)", (float(start_cash),))
        ensure_user_schema(conn, start_card=start_card, start_cash=start_cash)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        ensure_transaction_identifiers(conn)
        ensure_category_codes(conn)
        ensure_piggy_codes(conn)
        ensure_recurring_codes(conn)
        conn.close()


# ==============================================================================
# MIGRACJE KOLUMN
# ==============================================================================
def _code(prefix: str, n: int) -> str:
    return f"{prefix}{int(n):06d}"


def ensure_transaction_identifiers(conn: sqlite3.Connection) -> None:
    import uuid
    try:
        cur = conn.cursor()
        _ensure_column(conn, "transactions", "tx_uid", "TEXT")
        _ensure_column(conn, "transactions", "human_code", "TEXT")
        cur.execute("SELECT id FROM transactions WHERE tx_uid IS NULL OR tx_uid = ''")
        for r in cur.fetchall():
            t_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
            cur.execute("UPDATE transactions SET tx_uid = ? WHERE id = ?", (uuid.uuid4().hex, t_id))
        cur.execute("SELECT id FROM transactions WHERE human_code IS NULL OR human_code = ''")
        for r in cur.fetchall():
            t_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
            cur.execute("UPDATE transactions SET human_code = ? WHERE id = ?", (_code("TX", int(t_id)), t_id))
        conn.commit()
    except Exception:
        pass


def ensure_category_codes(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        _ensure_column(conn, "categories", "ct_code", "TEXT")
        cur.execute("SELECT id FROM categories WHERE ct_code IS NULL OR ct_code = ''")
        for r in cur.fetchall():
            c_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
            cur.execute("UPDATE categories SET ct_code = ? WHERE id = ?", (_code("CT", int(c_id)), c_id))
        conn.commit()
    except Exception:
        pass


def ensure_piggy_codes(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        _ensure_column(conn, "piggy_banks", "pb_code", "TEXT")
        cur.execute("SELECT id FROM piggy_banks WHERE pb_code IS NULL OR pb_code = ''")
        for r in cur.fetchall():
            p_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
            cur.execute("UPDATE piggy_banks SET pb_code = ? WHERE id = ?", (_code("PB", int(p_id)), p_id))
        conn.commit()
    except Exception:
        pass


def ensure_recurring_codes(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        _ensure_column(conn, "recurring_payments", "rr_code", "TEXT")
        cur.execute("SELECT id FROM recurring_payments WHERE rr_code IS NULL OR rr_code = ''")
        for r in cur.fetchall():
            rr_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
            cur.execute("UPDATE recurring_payments SET rr_code = ? WHERE id = ?", (_code("RR", int(rr_id)), rr_id))
        conn.commit()
    except Exception:
        pass


def _insert_transaction_row(
        conn: sqlite3.Connection,
        date: str,
        t_type: str,
        category: str,
        account: str,
        shop: str,
        amount: float,
        desc: str,
        is_reg: int,
) -> int:
    import uuid
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO transactions
        (date, type, category, account_type, shop, amount, description, is_registered)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (date, t_type, category, account, shop, abs(float(amount)), desc, int(is_reg)),
    )
    new_id = cur.lastrowid
    cur.execute(
        "UPDATE transactions SET tx_uid = ?, human_code = ? WHERE id = ?",
        (uuid.uuid4().hex, _code("TX", int(new_id)), int(new_id)),
    )
    return int(new_id)


# ==============================================================================
# USERS (AUTH DB)
# ==============================================================================

def user_exists() -> bool:
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE is_active = 1 LIMIT 1")
        return cur.fetchone() is not None
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        return cur.fetchone()
    finally:
        conn.close()


def create_user(username: str, password_hash: str):
    uid = generate_id()
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_active) VALUES (?, ?, ?, date('now'), 1)",
            (uid, username, password_hash),
        )
        conn.commit()
        return True, "", uid
    except sqlite3.IntegrityError:
        return False, "Nazwa użytkownika zajęta.", None
    except Exception as e:
        return False, str(e), None
    finally:
        conn.close()


def update_user_password(user_id: str, new_hash: str) -> bool:
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_all_users():
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, is_active FROM users ORDER BY username ASC")
        return cur.fetchall()
    finally:
        conn.close()


def delete_user(user_id: str) -> bool:
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        deleted = cur.rowcount > 0
    except Exception:
        conn.rollback()
        deleted = False
    finally:
        conn.close()

    if deleted:
        try:
            user_db_path = DATA_DIR / f"{user_id}.db"
            if user_db_path.exists():
                user_db_path.unlink()
        except Exception:
            pass
    return deleted


# ==============================================================================
# SETTINGS
# ==============================================================================

def get_setting(key: str, default_value: str = "0") -> str:
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default_value
    finally:
        conn.close()


def set_setting(key: str, value: Any) -> None:
    conn = get_auth_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def get_active_month_str() -> str:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='active_view_month'")
        row = cur.fetchone()
        return row["value"] if row else datetime.now().strftime("%Y-%m")
    finally:
        conn.close()


def set_active_month_str(yyyy_mm: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('active_view_month', ?)", (yyyy_mm,))
        conn.commit()
    finally:
        conn.close()


def reset_user_db_hard() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        for t in ["transactions", "accounts", "categories", "piggy_banks", "recurring_payments", "archive", "settings"]:
            cur.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
    finally:
        conn.close()
    init_user_db(get_active_user_db(), 0.0, 0.0)


# ==============================================================================
# KONTA (SALDO)
# ==============================================================================

def get_account_balance(account_name: str) -> float:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM accounts WHERE name = ?", (account_name,))
        row = cursor.fetchone()
        return float(row["balance"]) if row else 0.0
    finally:
        conn.close()


def update_account_balance(account_name: str, amount_change: float) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (amount_change, account_name))
        conn.commit()
    finally:
        conn.close()


def set_account_balance(account_name: str, new_balance: float) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET balance = ? WHERE name = ?", (new_balance, account_name))
        conn.commit()
    finally:
        conn.close()


# ==============================================================================
# TRANSAKCJE
# ==============================================================================

def _balance_delta(t_type: str, amount: float) -> float:
    amt = abs(float(amount or 0.0))
    return -amt if t_type == "Wydatek" else amt


def add_transaction(date: str, t_type: str, category: str, account: str, shop: str, amount: float, desc: str,
                    is_reg: bool) -> None:
    amount = float(amount or 0.0)
    delta = _balance_delta(t_type, amount)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")
        cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (delta, account))
        if is_reg:
            _insert_transaction_row(conn, date, t_type, category, account, shop, amount, desc, 1)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_transaction_by_id(t_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE id = ?", (t_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def delete_transaction(t_id: int) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE id = ?", (t_id,))
        row = cursor.fetchone()
        if not row: return

        if int(row["is_registered"] or 0) == 1:
            revert = -_balance_delta(row["type"], float(row["amount"] or 0.0))
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (revert, row["account_type"]))

        cursor.execute("DELETE FROM transactions WHERE id = ?", (t_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_transaction(t_id: int, date: str, t_type: str, category: str, account: str, shop: str, amount: float,
                       desc: str, is_reg: bool) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE id = ?", (t_id,))
        old = cursor.fetchone()
        if not old: return

        new_amount = float(amount or 0.0)
        new_is_reg = 1 if is_reg else 0

        if int(old["is_registered"] or 0) == 1:
            revert = -_balance_delta(old["type"], float(old["amount"] or 0.0))
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (revert, old["account_type"]))

        cursor.execute(
            "UPDATE transactions SET date=?, type=?, category=?, account_type=?, shop=?, amount=?, description=?, is_registered=? WHERE id=?",
            (date, t_type, category, account, shop, abs(new_amount), desc, new_is_reg, t_id),
        )

        if new_is_reg == 1:
            delta = _balance_delta(t_type, new_amount)
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (delta, account))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_transactions_by_month(ym_str: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE date LIKE ?", (f"{ym_str}-%",))
        return cursor.fetchall()
    finally:
        conn.close()


def fetch_transactions(search_text: Optional[str] = None, category_filter: Optional[str] = None,
                       month_filter: Optional[str] = None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM transactions WHERE 1=1"
        params: List[Any] = []

        if month_filter:
            query += " AND date LIKE ?"
            params.append(f"{month_filter}%")

        if category_filter and str(category_filter) not in ("CLEAR", "Select.BLANK") and "NoSelection" not in str(
                category_filter):
            query += " AND category = ?"
            params.append(category_filter)

        if search_text:
            query += " AND (shop LIKE ? OR description LIKE ?)"
            wildcard = f"%{search_text}%"
            params.extend([wildcard, wildcard])

        query += " ORDER BY date DESC, id DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


def get_unique_categories() -> List[str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories ORDER BY name ASC")
        return [row["name"] for row in cursor.fetchall()]
    finally:
        conn.close()


# ==============================================================================
# KATEGORIE - FIX BŁĄD 2 (Automatyczny update starych wpisów)
# ==============================================================================

def get_all_categories_data():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories ORDER BY name ASC")
        return cursor.fetchall()
    finally:
        conn.close()


def get_category_by_id(c_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = ?", (c_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def add_category(name: str, limit_amount: float):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name, limit_amount) VALUES (?, ?)", (name, limit_amount))
        new_id = cursor.lastrowid
        cursor.execute("UPDATE categories SET ct_code=? WHERE id=?", (_code("CT", int(new_id)), int(new_id)))
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Kategoria istnieje!"
    finally:
        conn.close()


def update_category(c_id: int, name: str, limit_amount: float):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories WHERE id=?", (c_id,))
        old_row = cursor.fetchone()
        if not old_row: return False, "Nie ma takiej kategorii"

        old_name = old_row["name"]
        cursor.execute("UPDATE categories SET name=?, limit_amount=? WHERE id=?", (name, limit_amount, c_id))

        # Zabezpieczenie integralności transakcji przy zmianie nazwy kategorii
        if old_name != name:
            cursor.execute("UPDATE transactions SET category=? WHERE category=?", (name, old_name))

        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Nazwa zajęta!"
    finally:
        conn.close()


def delete_category(c_id: int) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE id = ?", (c_id,))
        conn.commit()
    finally:
        conn.close()


def get_category_spent(category_name: str, month_str: str) -> float:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE category=? AND type='Wydatek' AND date LIKE ?",
                       (category_name, f"{month_str}%"))
        spent = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE category=? AND type='Dochód' AND date LIKE ?",
                       (category_name, f"{month_str}%"))
        refunds = cursor.fetchone()[0] or 0.0
        return float(spent) - float(refunds)
    finally:
        conn.close()



# ==============================================================================
# SKARBONKI
# ==============================================================================

def ensure_internal_category(conn: sqlite3.Connection, name: str = "Oszczędności", limit_amount: float = 0.0) -> str:
    """
    Upewnia się, że techniczna kategoria istnieje.
    Zwraca nazwę kategorii, której można bezpiecznie użyć przy zapisie transakcji.
    """
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row["name"] if isinstance(row, sqlite3.Row) else row[1]

    cur.execute(
        "INSERT INTO categories (name, limit_amount) VALUES (?, ?)",
        (name, float(limit_amount or 0.0)),
    )
    new_id = cur.lastrowid

    # Jeśli system kodów kategorii już działa, uzupełniamy ct_code
    try:
        cur.execute(
            "UPDATE categories SET ct_code = ? WHERE id = ?",
            (_code("CT", int(new_id)), int(new_id)),
        )
    except Exception:
        pass

    return name


def get_all_piggy_banks():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM piggy_banks ORDER BY name ASC")
        return cursor.fetchall()
    finally:
        conn.close()


def get_piggy_bank_by_id(p_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM piggy_banks WHERE id = ?", (p_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def add_piggy_bank(name: str, target: float, account_type: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO piggy_banks (name, target_amount, current_amount, account_type) VALUES (?, ?, 0, ?)",
            (name, target, account_type))
        new_id = cursor.lastrowid
        cursor.execute("UPDATE piggy_banks SET pb_code=? WHERE id=?", (_code("PB", int(new_id)), int(new_id)))
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Istnieje!"
    finally:
        conn.close()


def update_piggy_bank(p_id: int, name: str, target: float, account_type: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE piggy_banks SET name=?, target_amount=?, account_type=? WHERE id=?",
                       (name, target, account_type, p_id))
        conn.commit()
        return True, ""
    except Exception:
        return False, "Błąd!"
    finally:
        conn.close()


def delete_piggy_bank(p_id: int) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # FIX BŁĄD 8 - Najpierw usuń sieroce wpłaty cykliczne powiązane z celem
        cursor.execute("DELETE FROM recurring_payments WHERE piggy_id = ?", (p_id,))
        cursor.execute("DELETE FROM piggy_banks WHERE id = ?", (p_id,))
        conn.commit()
    finally:
        conn.close()


def update_piggy_bank_balance(
    p_id: int,
    amount_change: float,
    selected_account: str,
    is_registered: bool = True
) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")

        # 1) Pobierz skarbonkę
        cursor.execute(
            "SELECT id, name, current_amount FROM piggy_banks WHERE id = ?",
            (p_id,)
        )
        piggy = cursor.fetchone()
        if not piggy:
            raise Exception("Nie znaleziono skarbonki o podanym ID")

        piggy_name = piggy["name"] if isinstance(piggy, sqlite3.Row) else piggy[1]
        current_amount = float(piggy["current_amount"] if isinstance(piggy, sqlite3.Row) else piggy[2])

        # 2) Sprawdź konto źródłowe/docelowe
        cursor.execute("SELECT balance FROM accounts WHERE name = ?", (selected_account,))
        acc_row = cursor.fetchone()
        if not acc_row:
            raise Exception(f"Nie znaleziono konta: {selected_account}")

        account_balance = float(acc_row["balance"] if isinstance(acc_row, sqlite3.Row) else acc_row[0])

        amount_change = float(amount_change or 0.0)
        if amount_change == 0:
            raise Exception("Kwota operacji nie może być równa zero")

        # 3) Walidacje biznesowe
        # Wpłata na skarbonkę: konto musi mieć środki
        if amount_change > 0 and account_balance < amount_change:
            raise Exception("Brak środków na wybranym koncie")

        # Wypłata ze skarbonki: skarbonka musi mieć środki
        if amount_change < 0 and current_amount < abs(amount_change):
            raise Exception("Brak środków w skarbonce")

        # 4) Zadbaj o techniczną kategorię dla operacji skarbonki
        savings_category = ensure_internal_category(conn, "Oszczędności", 0.0)

        # 5) Aktualizacja sald
        # skarbonka rośnie przy wpłacie, maleje przy wypłacie
        cursor.execute(
            "UPDATE piggy_banks SET current_amount = current_amount + ? WHERE id = ?",
            (amount_change, p_id)
        )

        # konto maleje przy wpłacie, rośnie przy wypłacie
        cursor.execute(
            "UPDATE accounts SET balance = balance - ? WHERE name = ?",
            (amount_change, selected_account)
        )

        # 6) Rejestracja w historii (legacy-compatible)
        if is_registered:
            today = datetime.now().strftime("%Y-%m-%d")

            if amount_change > 0:
                tx_type = "Wydatek"
                tx_desc = f"Wpłata na skarbonkę: {piggy_name}"
            else:
                tx_type = "Dochód"
                tx_desc = f"Wypłata ze skarbonki: {piggy_name}"

            _insert_transaction_row(
                conn=conn,
                date=today,
                t_type=tx_type,
                category=savings_category,
                account=selected_account,
                shop=piggy_name,
                amount=abs(amount_change),
                desc=tx_desc,
                is_reg=1,
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ==============================================================================
# CYKLICZNE
# ==============================================================================

def get_all_recurring():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recurring_payments ORDER BY start_date ASC")
        return cursor.fetchall()
    finally:
        conn.close()


def get_recurring_by_id(r_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recurring_payments WHERE id = ?", (r_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def add_recurring(name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO recurring_payments (name, amount, type, category, account_type, cycle, start_date, is_registered, piggy_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id),
        )
        new_id = cursor.lastrowid
        cursor.execute("UPDATE recurring_payments SET rr_code=? WHERE id=?", (_code("RR", int(new_id)), int(new_id)))
        conn.commit()
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def update_recurring(r_id, name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recurring_payments SET name=?, amount=?, type=?, category=?, account_type=?, cycle=?, start_date=?, is_registered=?, piggy_id=? WHERE id=?",
            (name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id, r_id),
        )
        conn.commit()
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def delete_recurring(r_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recurring_payments WHERE id=?", (r_id,))
        conn.commit()
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def toggle_recurring_pause(r_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT is_registered FROM recurring_payments WHERE id=?", (r_id,))
        row = cursor.fetchone()
        if not row: return False
        new_status = 0 if int(row["is_registered"] or 0) == 1 else 1
        cursor.execute("UPDATE recurring_payments SET is_registered=? WHERE id=?", (new_status, r_id))
        conn.commit()
        return new_status == 1
    finally:
        conn.close()


# ==============================================================================
# RAPORTY / ARCHIWIZACJA
# ==============================================================================

def get_monthly_balance(month_str: str) -> Tuple[float, float]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Dochód' AND date LIKE ?", (f"{month_str}%",))
        inc = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Wydatek' AND date LIKE ?", (f"{month_str}%",))
        exp = cursor.fetchone()[0] or 0.0
        return float(inc), float(exp)
    finally:
        conn.close()


def get_monthly_summary(year_month: str) -> Tuple[float, float]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT type, SUM(amount) as total FROM transactions WHERE date LIKE ? GROUP BY type UNION ALL SELECT type, SUM(amount) as total FROM archive WHERE date LIKE ? GROUP BY type"
        cursor.execute(query, (f"{year_month}%", f"{year_month}%"))
        rows = cursor.fetchall()
        income, expense = 0.0, 0.0
        for row in rows:
            if row["type"] == "Dochód":
                income += row["total"]
            elif row["type"] == "Wydatek":
                expense += row["total"]
        return float(income), float(expense)
    finally:
        conn.close()


def archive_month(year_month: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        param = f"{year_month}%"
        cursor.execute(
            "INSERT INTO archive (id, date, type, category, account_type, shop, amount, description, archived_at) SELECT id, date, type, category, account_type, shop, amount, description, date('now') FROM transactions WHERE date LIKE ?",
            (param,))
        copied_count = cursor.rowcount
        if copied_count > 0:
            cursor.execute("DELETE FROM transactions WHERE date LIKE ?", (param,))
            conn.commit()
        return int(copied_count)
    finally:
        conn.close()


def get_daily_spending_map(year_month: str) -> Dict[int, float]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strftime('%d', date) as day, SUM(amount) as total FROM transactions WHERE type = 'Wydatek' AND date LIKE ? GROUP BY day",
            (f"{year_month}%",))
        return {int(row["day"]): float(row["total"] or 0.0) for row in cursor.fetchall() if row["day"]}
    finally:
        conn.close()


def get_recurring_sum() -> float:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(amount) FROM recurring_payments WHERE is_registered = 1 AND (type = 'Wydatek' OR type = 'Na Skarbonkę')")
        res = cursor.fetchone()[0]
        return float(res) if res else 0.0
    finally:
        conn.close()


# ==============================================================================
# CYKLICZNE - AUTOMAT
# ==============================================================================

def replace_safe(date_obj: datetime.date, day: int):
    try:
        return date_obj.replace(day=day)
    except ValueError:
        return date_obj.replace(day=calendar.monthrange(date_obj.year, date_obj.month)[1])


def check_due_payments_count() -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        today = datetime.now().date()
        count = 0
        cursor.execute("SELECT * FROM recurring_payments WHERE is_registered=1")
        for row in cursor.fetchall():
            try:
                start_date = datetime.strptime(row["start_date"], "%Y-%m-%d").date()
                if row["last_payment_date"]:
                    last_pay = datetime.strptime(row["last_payment_date"], "%Y-%m-%d").date()
                    if row["cycle"] == "Miesięcznie":
                        if today >= replace_safe(today, day=start_date.day) > last_pay: count += 1
                elif today >= start_date:
                    count += 1
            except Exception:
                pass
        return count
    finally:
        conn.close()


def process_due_payments() -> int:
    return check_and_process_recurring()


def check_and_process_recurring() -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        today = datetime.now().date()
        cursor.execute("SELECT * FROM recurring_payments")
        processed_count = 0

        for row in cursor.fetchall():
            # FIX BŁĄD 3 - Całkowite ignorowanie płatności "zombie" (spauzowanych)
            is_reg = int(row["is_registered"] or 0)
            if is_reg == 0:
                continue

            start_date = datetime.strptime(row["start_date"], "%Y-%m-%d").date()
            base_date = start_date

            if row["last_payment_date"]:
                last_pay_date = datetime.strptime(row["last_payment_date"], "%Y-%m-%d").date()
                if last_pay_date > base_date:
                    base_date = last_pay_date

            next_due = base_date
            if not row["last_payment_date"]:
                if today < start_date: continue
            else:
                cycle = row["cycle"]
                if cycle == "Dziennie":
                    next_due = base_date + timedelta(days=1)
                elif cycle == "Tygodniowo":
                    next_due = base_date + timedelta(weeks=1)
                elif cycle == "Miesięcznie":
                    y, m = base_date.year + (base_date.month // 12), (base_date.month % 12) + 1
                    try:
                        next_due = base_date.replace(year=y, month=m, day=start_date.day)
                    except ValueError:
                        next_due = base_date.replace(year=y, month=m, day=calendar.monthrange(y, m)[1])
                elif cycle == "Rocznie":
                    try:
                        next_due = base_date.replace(year=base_date.year + 1)
                    except ValueError:
                        next_due = base_date.replace(year=base_date.year + 1, month=2, day=28)

            if today < next_due: continue

            date_str = next_due.strftime("%Y-%m-%d")
            amount = float(row["amount"] or 0.0)
            hist_type, final_cat = row["type"], row["category"]

            if row["type"] == "Na Skarbonkę":
                hist_type, final_cat = "Wydatek", "Oszczędności"

            _insert_transaction_row(conn, date_str, hist_type, final_cat or "---", row["account_type"], row["name"],
                                    amount, f"[CYKLICZNE] {row['name']}", is_reg)

            change = amount if row["type"] == "Dochód" else -amount
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (change, row["account_type"]))

            if row["type"] == "Na Skarbonkę" and row["piggy_id"]:
                cursor.execute("UPDATE piggy_banks SET current_amount = current_amount + ? WHERE id = ?",
                               (amount, row["piggy_id"]))

            cursor.execute("UPDATE recurring_payments SET last_payment_date = ? WHERE id = ?", (date_str, row["id"]))
            processed_count += 1

        conn.commit()
        return processed_count
    except Exception as e:
        print(f"Błąd przetwarzania cyklicznych: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def sync_active_month() -> None:
    db_month = get_active_month_str()
    now_month = datetime.now().strftime("%Y-%m")
    if db_month != now_month:
        set_active_month_str(now_month)