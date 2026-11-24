"""
Cele oszczędnościowe („skarbonki”, koperty oszczędnościowe).

Cel to wirtualna część majątku: wpłata przenosi pieniądze z konta do celu
(wpis typu Transfer / goal_out), wypłata – z celu na konto (goal_in).
Nie są to wydatki ani dochody, więc nie zaburzają budżetu.
Opcjonalny termin (`target_date`) pozwala policzyć, ile odkładać miesięcznie.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from src.finance.ledger import TRANSFER, account_balance_in, post_entry, require_account
from src.finance.storage import make_code, open_user_db


def get_all_piggy_banks():
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM piggy_banks ORDER BY name ASC").fetchall()


def get_piggy_bank_by_id(p_id: int):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM piggy_banks WHERE id = ?", (p_id,)).fetchone()


def get_piggy_total() -> float:
    with open_user_db() as conn:
        return float(conn.execute("SELECT COALESCE(SUM(current_amount), 0) FROM piggy_banks").fetchone()[0] or 0.0)


def add_piggy_bank(name: str, target: float, account_type: str, target_date: Optional[str] = None
                   ) -> Tuple[bool, str]:
    try:
        with open_user_db(write=True) as conn:
            cur = conn.execute(
                "INSERT INTO piggy_banks (name, target_amount, current_amount, account_type, target_date) "
                "VALUES (?, ?, 0, ?, ?)", (name, float(target), account_type, target_date or None))
            conn.execute("UPDATE piggy_banks SET pb_code=? WHERE id=?", (make_code("PB", cur.lastrowid), cur.lastrowid))
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Cel o tej nazwie już istnieje!"


def update_piggy_bank(p_id: int, name: str, target: float, account_type: str,
                      target_date: Optional[str] = None) -> Tuple[bool, str]:
    try:
        with open_user_db(write=True) as conn:
            conn.execute("UPDATE piggy_banks SET name=?, target_amount=?, account_type=?, target_date=? WHERE id=?",
                         (name, float(target), account_type, target_date or None, p_id))
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Cel o tej nazwie już istnieje!"
    except Exception as e:
        return False, f"Błąd zapisu celu: {e}"


def move_goal_funds(conn: sqlite3.Connection, p_id: int, amount_change: float, account: str, day: str,
                    note: str = "", check_funds: bool = True, tx_uid: Optional[str] = None) -> None:
    """
    amount_change > 0: konto -> cel, < 0: cel -> konto. Wykonywane w przekazanej transakcji SQL.
    """
    piggy = conn.execute("SELECT * FROM piggy_banks WHERE id = ?", (p_id,)).fetchone()
    if not piggy:
        raise ValueError("Nie znaleziono celu.")
    account = require_account(conn, account)
    amount_change = round(float(amount_change or 0.0), 2)
    if amount_change == 0:
        raise ValueError("Kwota operacji nie może być równa zero.")
    current = float(piggy["current_amount"] or 0.0)
    if amount_change > 0 and check_funds and account_balance_in(conn, account) + 1e-9 < amount_change:
        raise ValueError(f"Brak środków na koncie {account}.")
    if amount_change < 0 and current + 1e-9 < abs(amount_change):
        raise ValueError("Brak środków w celu.")

    conn.execute("UPDATE piggy_banks SET current_amount = current_amount + ? WHERE id = ?", (amount_change, p_id))
    if amount_change > 0:
        post_entry(conn, day, TRANSFER, None, account, piggy["name"], amount_change,
                   note or f"Wpłata na cel: {piggy['name']}", subtype="goal_out", goal_id=p_id, tx_uid=tx_uid)
    else:
        post_entry(conn, day, TRANSFER, None, account, piggy["name"], abs(amount_change),
                   note or f"Wypłata z celu: {piggy['name']}", subtype="goal_in", goal_id=p_id, tx_uid=tx_uid)


def update_piggy_bank_balance(p_id: int, amount_change: float, selected_account: str,
                              is_registered: bool = True) -> None:
    """Wpłata (>0) / wypłata (<0) na cel. is_registered=False: tylko zmiana stanu celu i konta bez wpisu."""
    with open_user_db(write=True) as conn:
        if is_registered:
            move_goal_funds(conn, p_id, amount_change, selected_account, date.today().isoformat())
            return
        piggy = conn.execute("SELECT current_amount FROM piggy_banks WHERE id = ?", (p_id,)).fetchone()
        if not piggy:
            raise ValueError("Nie znaleziono celu.")
        if amount_change < 0 and float(piggy[0] or 0) < abs(amount_change):
            raise ValueError("Brak środków w celu.")
        conn.execute("UPDATE piggy_banks SET current_amount = current_amount + ? WHERE id = ?", (amount_change, p_id))
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (amount_change, selected_account))


def set_goal_amount(p_id: int, new_amount: float) -> float:
    """
    Korekta stanu celu: ustawia zgromadzoną kwotę bez ruchu pieniędzy na kontach
    (np. gdy stan celu rozjechał się z rzeczywistością). Zwraca różnicę.
    """
    new_amount = round(float(new_amount), 2)
    if new_amount < 0:
        raise ValueError("Stan celu nie może być ujemny.")
    with open_user_db(write=True) as conn:
        piggy = conn.execute("SELECT current_amount FROM piggy_banks WHERE id = ?", (p_id,)).fetchone()
        if not piggy:
            raise ValueError("Nie znaleziono celu.")
        diff = round(new_amount - float(piggy[0] or 0.0), 2)
        if diff:
            conn.execute("UPDATE piggy_banks SET current_amount = ? WHERE id = ?", (new_amount, p_id))
        return diff


def delete_piggy_bank(p_id: int, refund: bool = True) -> float:
    """Usuwa cel; zgromadzone środki (refund=True) wracają na konto celu. Zwraca zwróconą kwotę."""
    refunded = 0.0
    with open_user_db(write=True) as conn:
        piggy = conn.execute("SELECT * FROM piggy_banks WHERE id = ?", (p_id,)).fetchone()
        if not piggy:
            return 0.0
        current = float(piggy["current_amount"] or 0.0)
        account = piggy["account_type"] or "Karta"
        if refund and current > 0 and conn.execute("SELECT 1 FROM accounts WHERE name=?", (account,)).fetchone():
            move_goal_funds(conn, p_id, -current, account, date.today().isoformat(),
                            f"Zamknięcie celu: {piggy['name']}")
            refunded = current
        conn.execute("UPDATE transactions SET goal_id = NULL WHERE goal_id = ?", (p_id,))
        conn.execute("DELETE FROM recurring_payments WHERE piggy_id = ?", (p_id,))
        conn.execute("DELETE FROM autosave_rules WHERE target_kind = 'goal' AND target = ?", (str(p_id),))
        conn.execute("DELETE FROM piggy_banks WHERE id = ?", (p_id,))
    return refunded


def goal_plan(row: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Postęp celu i — jeśli ma termin — wymagana miesięczna wpłata."""
    p = dict(row)
    today = today or date.today()
    target = float(p.get("target_amount") or 0.0)
    current = float(p.get("current_amount") or 0.0)
    missing = max(0.0, target - current)
    plan: Dict[str, Any] = {
        "pct": (current / target * 100.0) if target > 0 else 0.0,
        "missing": missing,
        "months_left": None,
        "monthly_needed": None,
        "overdue": False,
    }
    deadline = None
    try:
        deadline = datetime.strptime(str(p.get("target_date"))[:10], "%Y-%m-%d").date() if p.get("target_date") else None
    except ValueError:
        deadline = None
    if deadline:
        months = (deadline.year - today.year) * 12 + (deadline.month - today.month)
        if deadline.day < today.day:
            months -= 1  # niepełny ostatni miesiąc się nie liczy
        plan["months_left"] = max(0, months)
        plan["overdue"] = deadline < today and missing > 0
        plan["monthly_needed"] = round(missing / max(1, months), 2) if missing > 0 else 0.0
        plan["deadline"] = deadline
    return plan


def goals_overview() -> List[Dict[str, Any]]:
    out = []
    for row in get_all_piggy_banks():
        d = dict(row)
        d.update(goal_plan(row))
        d["code"] = d.get("pb_code") or make_code("PB", d["id"])
        out.append(d)
    return out


def months_to_goal(missing: float, monthly: float) -> Optional[int]:
    return int(ceil(missing / monthly)) if monthly > 0 else None
