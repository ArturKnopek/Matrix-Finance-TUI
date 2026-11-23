"""
Koperty budżetowe (metoda kopertowa).

Każda kategoria wydatków to koperta z miesięcznym budżetem (`limit_amount`).
Koperta „elastyczna” (`rollover = 1`) przenosi NIEWYDANE środki na kolejny
miesiąc: dostępne = budżet + przeniesione z poprzedniego miesiąca.

    przeniesione(m) = max(0, dostępne(m-1) - wydane(m-1))     liczone od `rollover_since`

Wydane w kopercie = wydatki - zwroty (dochody przypisane do tej kategorii).
Przelewy i operacje na celach nie obciążają kopert.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.finance.storage import make_code, now_iso, open_user_db

MAX_ROLLOVER_MONTHS = 120


def month_add(ym: str, delta: int) -> str:
    y, m = map(int, ym.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def months_between(start_ym: str, end_ym: str) -> int:
    y1, m1 = map(int, start_ym.split("-"))
    y2, m2 = map(int, end_ym.split("-"))
    return (y2 * 12 + m2) - (y1 * 12 + m1)


# =============================================================================
# CRUD
# =============================================================================

def ensure_category(conn: sqlite3.Connection, name: str, limit_amount: float = 0.0) -> str:
    row = conn.execute("SELECT name FROM categories WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO categories (name, limit_amount, created_at) VALUES (?, ?, ?)",
                       (name, float(limit_amount or 0.0), now_iso()))
    conn.execute("UPDATE categories SET ct_code = ? WHERE id = ?", (make_code("CT", cur.lastrowid), cur.lastrowid))
    return name


ensure_internal_category = ensure_category  # zgodność wsteczna


def get_unique_categories() -> List[str]:
    with open_user_db() as conn:
        return [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name ASC").fetchall()]


def get_all_categories_data():
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM categories ORDER BY name ASC").fetchall()


def get_category_by_id(c_id: int):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM categories WHERE id = ?", (c_id,)).fetchone()


def add_category(name: str, limit_amount: float, rollover: bool = False) -> Tuple[bool, str]:
    try:
        with open_user_db(write=True) as conn:
            cur = conn.execute(
                "INSERT INTO categories (name, limit_amount, rollover, rollover_since, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, float(limit_amount or 0.0), 1 if rollover else 0,
                 datetime.now().strftime("%Y-%m") if rollover else None, now_iso()),
            )
            conn.execute("UPDATE categories SET ct_code=? WHERE id=?", (make_code("CT", cur.lastrowid), cur.lastrowid))
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Koperta o tej nazwie już istnieje!"


def update_category(c_id: int, name: str, limit_amount: float, rollover: Optional[bool] = None) -> Tuple[bool, str]:
    try:
        with open_user_db(write=True) as conn:
            old = conn.execute("SELECT * FROM categories WHERE id = ?", (c_id,)).fetchone()
            if not old:
                return False, "Nie ma takiej koperty"
            new_rollover = int(old["rollover"] or 0) if rollover is None else (1 if rollover else 0)
            since = old["rollover_since"]
            if new_rollover and not int(old["rollover"] or 0):
                since = datetime.now().strftime("%Y-%m")  # przenoszenie liczone od teraz
            conn.execute("UPDATE categories SET name=?, limit_amount=?, rollover=?, rollover_since=? WHERE id=?",
                         (name, float(limit_amount or 0.0), new_rollover, since, c_id))
            if old["name"] != name:
                conn.execute("UPDATE transactions SET category=? WHERE category=?", (name, old["name"]))
                conn.execute("UPDATE recurring_payments SET category=? WHERE category=?", (name, old["name"]))
                conn.execute("UPDATE archive SET category=? WHERE category=?", (name, old["name"]))
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Koperta o tej nazwie już istnieje!"


def delete_category(c_id: int) -> None:
    with open_user_db(write=True) as conn:
        row = conn.execute("SELECT name FROM categories WHERE id = ?", (c_id,)).fetchone()
        if row:
            conn.execute("UPDATE recurring_payments SET category = NULL WHERE category = ?", (row[0],))
        conn.execute("DELETE FROM categories WHERE id = ?", (c_id,))


# =============================================================================
# Wydatki w kopertach
# =============================================================================

_SPENT_SQL = """
    SELECT category, substr(date, 1, 7) AS ym,
           SUM(CASE WHEN type = 'Wydatek' THEN amount ELSE 0 END) -
           SUM(CASE WHEN type = 'Dochód' THEN amount ELSE 0 END) AS spent
    FROM {table}
    WHERE category IS NOT NULL AND substr(date, 1, 7) BETWEEN ? AND ?
    GROUP BY category, ym
"""


def _spending_by_month(conn: sqlite3.Connection, start_ym: str, end_ym: str) -> Dict[Tuple[str, str], float]:
    out: Dict[Tuple[str, str], float] = defaultdict(float)
    for table in ("transactions", "archive"):
        for row in conn.execute(_SPENT_SQL.format(table=table), (start_ym, end_ym)).fetchall():
            out[(row["category"], row["ym"])] += float(row["spent"] or 0.0)
    return out


def get_category_spending_map(month_str: str) -> Dict[str, float]:
    with open_user_db() as conn:
        data = _spending_by_month(conn, month_str, month_str)
    return {cat: value for (cat, _), value in data.items()}


def get_category_spent(category_name: str, month_str: str) -> float:
    return float(get_category_spending_map(month_str).get(category_name, 0.0))


def get_envelope_overview(month: str) -> List[Dict[str, Any]]:
    """
    Stan kopert w miesiącu: budżet, przeniesione z poprzednich miesięcy, dostępne,
    wydane, pozostało, procent wykorzystania.
    """
    with open_user_db() as conn:
        cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
        starts = [c["rollover_since"] for c in cats if int(c["rollover"] or 0) and c["rollover_since"]]
        first = min(starts + [month]) if starts else month
        if months_between(first, month) > MAX_ROLLOVER_MONTHS:
            first = month_add(month, -MAX_ROLLOVER_MONTHS)
        spending = _spending_by_month(conn, first, month)

    out = []
    for cat in cats:
        name = cat["name"]
        budget = float(cat["limit_amount"] or 0.0)
        rollover = int(cat["rollover"] or 0) == 1
        carried = 0.0
        since = cat["rollover_since"]
        if rollover and since and since < month:
            m = max(since, first)
            while m < month:
                available = budget + carried
                carried = max(0.0, available - max(0.0, spending.get((name, m), 0.0)))
                m = month_add(m, 1)
        spent = max(0.0, spending.get((name, month), 0.0))  # kategorie dochodowe nie „wydają”
        available = budget + carried
        remaining = available - spent
        pct = (spent / available * 100.0) if available > 0 else None
        out.append({
            "id": cat["id"],
            "code": cat["ct_code"] or make_code("CT", cat["id"]),
            "name": name,
            "budget": budget,
            "rollover": rollover,
            "carried": carried,
            "available": available,
            "spent": spent,
            "remaining": remaining,
            "pct": pct,
            "over": available > 0 and spent > available,
        })
    return out


def get_budget_summary(month: str) -> Dict[str, float]:
    """Podsumowanie budżetu kopertowego: przydzielono / dostępne / wydano / do rozdysponowania."""
    from src.finance.analytics import get_monthly_balance

    envelopes = get_envelope_overview(month)
    income, expense = get_monthly_balance(month)
    budgeted = sum(e["budget"] for e in envelopes)
    available = sum(e["available"] for e in envelopes)
    spent_in_envelopes = sum(max(0.0, e["spent"]) for e in envelopes if e["available"] > 0)
    remaining = sum(max(0.0, e["remaining"]) for e in envelopes if e["available"] > 0)
    return {
        "income": income,
        "expense": expense,
        "budgeted": budgeted,
        "carried": sum(e["carried"] for e in envelopes),
        "available": available,
        "spent": spent_in_envelopes,
        "remaining": remaining,
        "unallocated": income - budgeted,
        "over_count": sum(1 for e in envelopes if e["over"]),
    }
