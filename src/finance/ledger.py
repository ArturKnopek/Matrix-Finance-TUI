"""
Księga transakcji (ledger).

Typy wpisów (kolumna `type`):
    "Wydatek"  – zmniejsza saldo, liczy się do wydatków i kopert,
    "Dochód"   – zwiększa saldo, liczy się do przychodów,
    "Transfer" – ruch pieniędzy między własnymi kontami/celami/inwestycjami.
                 NIE jest ani wydatkiem, ani przychodem. Kierunek określa
                 `entry_subtype` (sufiks "_in"/"_up" = +, pozostałe = -).

Podtypy (entry_subtype) dla "Transfer":
    transfer_out / transfer_in   – przelew między kontami (2 wpisy z tym samym linked_group_id)
    goal_out / goal_in           – wpłata na cel / wypłata z celu (goal_id)
    valuation_up / valuation_down – zmiana wyceny inwestycji
    external_in                  – wpłata spoza budżetu (np. pracodawca do PPK)
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from src.finance.storage import make_code, open_user_db

EXPENSE = "Wydatek"
INCOME = "Dochód"
TRANSFER = "Transfer"
ENTRY_TYPES = (EXPENSE, INCOME, TRANSFER)

SUBTYPE_LABELS = {
    "transfer_out": "Przelew wychodzący",
    "transfer_in": "Przelew przychodzący",
    "goal_out": "Wpłata na cel",
    "goal_in": "Wypłata z celu",
    "valuation_up": "Wzrost wyceny",
    "valuation_down": "Spadek wyceny",
    "external_in": "Wpłata zewnętrzna",
    "correction_up": "Korekta salda (+)",
    "correction_down": "Korekta salda (−)",
}

_EMPTY_CATEGORY_VALUES = {"", "---", "CLEAR", "Select.BLANK", "None"}


# =============================================================================
# Saldo
# =============================================================================

def is_inflow(t_type: str, subtype: Optional[str] = None) -> bool:
    if t_type == INCOME:
        return True
    if t_type == EXPENSE:
        return False
    sub = subtype or ""
    return sub.endswith("_in") or sub.endswith("_up")


def balance_delta(t_type: str, amount: float, subtype: Optional[str] = None) -> float:
    """O ile zmienia się saldo konta przy danym wpisie."""
    amt = abs(float(amount or 0.0))
    return amt if is_inflow(t_type, subtype) else -amt


_balance_delta = balance_delta  # zgodność wsteczna


def require_account(conn: sqlite3.Connection, account: str) -> str:
    name = (account or "").strip()
    if not conn.execute("SELECT 1 FROM accounts WHERE name = ?", (name,)).fetchone():
        raise ValueError(f"Nie znaleziono konta: {name or '(puste)'}")
    return name


def account_balance_in(conn: sqlite3.Connection, account: str) -> float:
    row = conn.execute("SELECT balance FROM accounts WHERE name = ?", (account,)).fetchone()
    return float(row[0] or 0.0) if row else 0.0


def change_balance(conn: sqlite3.Connection, account: str, delta: float) -> None:
    conn.execute("UPDATE accounts SET balance = balance + ?, updated_at = datetime('now') WHERE name = ?",
                 (float(delta), account))


# =============================================================================
# Kategorie (klucz obcy)
# =============================================================================

def normalize_category(conn: sqlite3.Connection, category: Any) -> Optional[str]:
    """
    Kategoria bezpieczna dla klucza obcego: puste -> NULL,
    nieistniejąca -> tworzona automatycznie (np. usunięta, a używana przez zlecenie).
    """
    from src.finance.envelopes import ensure_category

    if category is None:
        return None
    name = str(category).strip()
    if name in _EMPTY_CATEGORY_VALUES or "NoSelection" in name:
        return None
    return ensure_category(conn, name)


_normalize_category = normalize_category


# =============================================================================
# Zapis wpisów
# =============================================================================

def insert_entry(
    conn: sqlite3.Connection,
    date: str,
    t_type: str,
    category: Optional[str],
    account: str,
    shop: str,
    amount: float,
    desc: str,
    is_reg: int = 1,
    subtype: str = "regular",
    group_id: Optional[str] = None,
    goal_id: Optional[int] = None,
    tx_uid: Optional[str] = None,
) -> int:
    """Wstawia wiersz transakcji (bez zmiany salda) i nadaje kod TX000001.
    tx_uid — stały identyfikator (synchronizacja telefon ↔ PC); domyślnie losowy."""
    cur = conn.execute(
        """
        INSERT INTO transactions
            (date, type, category, account_type, shop, amount, description, is_registered,
             entry_subtype, linked_group_id, goal_id, tx_uid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (date, t_type, category, account, shop, abs(float(amount)), desc, int(is_reg),
         subtype, group_id, goal_id, tx_uid or uuid.uuid4().hex),
    )
    new_id = int(cur.lastrowid)
    conn.execute("UPDATE transactions SET human_code = ? WHERE id = ?", (make_code("TX", new_id), new_id))
    return new_id


def _insert_transaction_row(conn, date, t_type, category, account, shop, amount, desc, is_reg) -> int:
    """(Zgodność wsteczna)"""
    return insert_entry(conn, date, t_type, category, account, shop, amount, desc, is_reg)


def post_entry(conn: sqlite3.Connection, date: str, t_type: str, category: Optional[str], account: str,
               shop: str, amount: float, desc: str, subtype: str = "regular",
               group_id: Optional[str] = None, goal_id: Optional[int] = None, tx_uid: Optional[str] = None) -> int:
    """Wpis + zmiana salda w jednym kroku (w ramach przekazanej transakcji SQL)."""
    t_id = insert_entry(conn, date, t_type, category, account, shop, amount, desc, 1, subtype, group_id, goal_id,
                        tx_uid)
    change_balance(conn, account, balance_delta(t_type, amount, subtype))
    return t_id


def new_group_id(prefix: str = "grp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# =============================================================================
# API transakcji (wydatki / dochody)
# =============================================================================

def add_transaction(date: str, t_type: str, category: str, account: str, shop: str, amount: float, desc: str,
                    is_reg: bool, apply_autosave: bool = True, tx_uid: Optional[str] = None) -> int:
    """
    Dodaje wydatek lub dochód.
    is_reg=True  -> wpis w historii + zmiana salda (+ reguły auto-oszczędzania),
    is_reg=False -> tylko korekta salda, bez wpisu w historii.
    Zwraca id transakcji (0, gdy nie zapisano w historii).
    """
    if t_type not in (EXPENSE, INCOME):
        raise ValueError("Transakcja musi być wydatkiem albo dochodem (przelewy: transfer_between_accounts).")
    amount = abs(float(amount or 0.0))
    with open_user_db(write=True) as conn:
        account = require_account(conn, account)
        if not is_reg:
            change_balance(conn, account, balance_delta(t_type, amount))
            return 0
        t_id = post_entry(conn, date, t_type, normalize_category(conn, category), account, shop, amount, desc,
                          tx_uid=tx_uid)
        if apply_autosave:
            from src.finance.autosave import apply_autosave_rules

            apply_autosave_rules(conn, account, t_type, amount, date, shop or desc)
        return t_id


def get_transaction_by_uid(tx_uid: str):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM transactions WHERE tx_uid = ?", (tx_uid,)).fetchone()


def get_transaction_by_id(t_id: int):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM transactions WHERE id = ?", (t_id,)).fetchone()


def is_transfer_row(row: Any) -> bool:
    return (row["type"] if row else None) == TRANSFER


def _revert_row(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Cofa wpływ wpisu na saldo konta (i na cel, jeśli dotyczy)."""
    if int(row["is_registered"] or 0) == 1:
        change_balance(conn, row["account_type"],
                       -balance_delta(row["type"], row["amount"], row["entry_subtype"]))
    goal_id = row["goal_id"]
    subtype = row["entry_subtype"] or ""
    if goal_id and subtype in ("goal_out", "goal_in"):
        # goal_out = pieniądze poszły na cel -> cofnięcie zmniejsza cel
        sign = -1 if subtype == "goal_out" else 1
        conn.execute("UPDATE piggy_banks SET current_amount = current_amount + ? WHERE id = ?",
                     (sign * abs(float(row["amount"] or 0.0)), goal_id))


def delete_transaction(t_id: int) -> int:
    """Usuwa wpis; przelew usuwany jest razem z drugą „nogą”. Zwraca liczbę usuniętych wpisów."""
    with open_user_db(write=True) as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (t_id,)).fetchone()
        if not row:
            return 0
        group = row["linked_group_id"]
        if group and row["type"] == TRANSFER:
            rows = conn.execute("SELECT * FROM transactions WHERE linked_group_id = ?", (group,)).fetchall()
        else:
            rows = [row]
        for r in rows:
            _revert_row(conn, r)
            conn.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
        return len(rows)


def update_transaction(t_id: int, date: str, t_type: str, category: str, account: str, shop: str, amount: float,
                       desc: str, is_reg: bool) -> None:
    if t_type not in (EXPENSE, INCOME):
        raise ValueError("Niepoprawny rodzaj transakcji.")
    with open_user_db(write=True) as conn:
        old = conn.execute("SELECT * FROM transactions WHERE id = ?", (t_id,)).fetchone()
        if not old:
            return
        if old["type"] == TRANSFER:
            raise ValueError("Przelewów i operacji na celach nie edytuje się — usuń wpis i utwórz go ponownie.")
        account = require_account(conn, account)
        category = normalize_category(conn, category)
        new_amount = abs(float(amount or 0.0))
        new_is_reg = 1 if is_reg else 0

        _revert_row(conn, old)
        conn.execute(
            "UPDATE transactions SET date=?, type=?, category=?, account_type=?, shop=?, amount=?, description=?, "
            "is_registered=? WHERE id=?",
            (date, t_type, category, account, shop, new_amount, desc, new_is_reg, t_id),
        )
        if new_is_reg:
            change_balance(conn, account, balance_delta(t_type, new_amount))


# =============================================================================
# Odczyt
# =============================================================================

def fetch_transactions(search_text: Optional[str] = None, category_filter: Optional[str] = None,
                       month_filter: Optional[str] = None, account_filter: Optional[str] = None,
                       type_filter: Optional[str] = None, limit: Optional[int] = None) -> List[sqlite3.Row]:
    query = "SELECT * FROM transactions WHERE 1=1"
    params: List[Any] = []
    if month_filter:
        query += " AND date LIKE ?"
        params.append(f"{month_filter}%")
    if category_filter and str(category_filter) not in ("CLEAR", "Select.BLANK") \
            and "NoSelection" not in str(category_filter):
        query += " AND category = ?"
        params.append(category_filter)
    if account_filter:
        query += " AND account_type = ?"
        params.append(account_filter)
    if type_filter:
        query += " AND type = ?"
        params.append(type_filter)
    if search_text:
        query += (" AND (py_lower(shop) LIKE ? OR py_lower(description) LIKE ? OR py_lower(category) LIKE ?"
                  " OR py_lower(human_code) LIKE ? OR py_lower(account_type) LIKE ? OR CAST(amount AS TEXT) LIKE ?)")
        params.extend([f"%{search_text.lower()}%"] * 6)
    query += " ORDER BY date DESC, id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    with open_user_db() as conn:
        return conn.execute(query, params).fetchall()


def get_transactions_by_month(ym_str: str, include_archive: bool = False):
    with open_user_db() as conn:
        if include_archive:
            return conn.execute(
                """
                SELECT id, date, type, category, account_type, shop, amount, description, is_registered,
                       entry_subtype
                FROM transactions WHERE date LIKE ?
                UNION ALL
                SELECT id, date, type, category, account_type, shop, amount, description, 1, entry_subtype
                FROM archive WHERE date LIKE ?
                ORDER BY date ASC
                """,
                (f"{ym_str}-%", f"{ym_str}-%"),
            ).fetchall()
        return conn.execute("SELECT * FROM transactions WHERE date LIKE ?", (f"{ym_str}-%",)).fetchall()


def get_transactions_for_day(day_iso: str) -> List[sqlite3.Row]:
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM transactions WHERE date = ? ORDER BY id DESC", (day_iso,)).fetchall()


def get_transaction_year_range():
    from datetime import datetime

    now_year = datetime.now().year
    with open_user_db() as conn:
        row = conn.execute(
            "SELECT MIN(y), MAX(y) FROM (SELECT CAST(substr(date,1,4) AS INTEGER) y FROM transactions "
            "UNION ALL SELECT CAST(substr(date,1,4) AS INTEGER) y FROM archive)"
        ).fetchone()
    lo = int(row[0]) if row and row[0] else now_year
    hi = int(row[1]) if row and row[1] else now_year
    return min(lo, now_year), max(hi, now_year)


def describe_entry(row: Any) -> Dict[str, Any]:
    """Przyjazny opis wpisu do list: etykieta rodzaju, znak kwoty."""
    r = dict(row)
    t_type = r.get("type")
    subtype = r.get("entry_subtype") or "regular"
    signed = balance_delta(t_type, r.get("amount") or 0.0, subtype)
    if t_type == TRANSFER:
        kind = SUBTYPE_LABELS.get(subtype, "Transfer")
    else:
        kind = t_type
    r["signed_amount"] = signed
    r["kind_label"] = kind
    return r
