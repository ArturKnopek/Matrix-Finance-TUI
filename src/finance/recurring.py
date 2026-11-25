"""
Zlecenia cykliczne (rachunki, subskrypcje, pensja, stałe odkładanie).

Rodzaje zleceń:
    "Wydatek"       – wydatek z konta w wybranej kopercie,
    "Dochód"        – wpływ na konto (uruchamia reguły auto-oszczędzania),
    "Na Skarbonkę"  – wpłata z konta na cel oszczędnościowy,
    "Przelew"       – przelew na inne konto (np. lokata, IKE, konto oszczędnościowe).

Terminy liczone są od daty startu (bez dryfu): 31.01 + miesiąc -> 28/29.02, 31.03...
Silnik księguje wszystkie zaległe terminy naraz (np. 3 pominięte miesiące = 3 wpisy).
"""

from __future__ import annotations

import calendar
import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.finance.ledger import normalize_category, post_entry
from src.finance.storage import make_code, open_user_db

RECURRING_TYPES: Tuple[str, ...] = ("Wydatek", "Dochód", "Na Skarbonkę", "Przelew")
RECURRING_CYCLES: Tuple[str, ...] = ("Dziennie", "Tygodniowo", "Miesięcznie", "Kwartalnie", "Rocznie")
CYCLE_PER_MONTH = {"Dziennie": 30.44, "Tygodniowo": 4.345, "Miesięcznie": 1.0, "Kwartalnie": 1 / 3,
                   "Rocznie": 1 / 12}
MAX_CATCHUP_OCCURRENCES = 1000
log = logging.getLogger(__name__)


# =============================================================================
# CRUD
# =============================================================================

def get_all_recurring():
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM recurring_payments ORDER BY start_date ASC").fetchall()


def get_recurring_by_id(r_id: int):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM recurring_payments WHERE id = ?", (r_id,)).fetchone()


def _clean_category(category: Any) -> Optional[str]:
    if category is None:
        return None
    name = str(category).strip()
    return None if name in ("", "---", "None", "Select.BLANK") or "NoSelection" in name else name


def add_recurring(name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id=None,
                  target_account=None):
    try:
        with open_user_db(write=True) as conn:
            cur = conn.execute(
                "INSERT INTO recurring_payments (name, amount, type, category, account_type, cycle, start_date, "
                "is_registered, piggy_id, target_account) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, amount, r_type, _clean_category(category), account, cycle, start_date, int(bool(is_reg)),
                 piggy_id, target_account),
            )
            conn.execute("UPDATE recurring_payments SET rr_code=? WHERE id=?",
                         (make_code("RR", cur.lastrowid), cur.lastrowid))
        return True, ""
    except Exception as e:
        return False, str(e)


def update_recurring(r_id, name, amount, r_type, category, account, cycle, start_date, is_reg, piggy_id=None,
                     target_account=None):
    try:
        with open_user_db(write=True) as conn:
            conn.execute(
                "UPDATE recurring_payments SET name=?, amount=?, type=?, category=?, account_type=?, cycle=?, "
                "start_date=?, is_registered=?, piggy_id=?, target_account=? WHERE id=?",
                (name, amount, r_type, _clean_category(category), account, cycle, start_date, int(bool(is_reg)),
                 piggy_id, target_account, r_id),
            )
        return True, ""
    except Exception as e:
        return False, str(e)


def delete_recurring(r_id: int):
    try:
        with open_user_db(write=True) as conn:
            conn.execute("DELETE FROM recurring_payments WHERE id=?", (r_id,))
        return True, ""
    except Exception as e:
        return False, str(e)


def toggle_recurring_pause(r_id: int) -> bool:
    """Przełącza aktywne/wstrzymane. Zwraca True, gdy zlecenie jest teraz aktywne."""
    with open_user_db(write=True) as conn:
        row = conn.execute("SELECT is_registered FROM recurring_payments WHERE id=?", (r_id,)).fetchone()
        if not row:
            return False
        new_status = 0 if int(row[0] or 0) == 1 else 1
        conn.execute("UPDATE recurring_payments SET is_registered=? WHERE id=?", (new_status, r_id))
        return new_status == 1


# =============================================================================
# Harmonogram
# =============================================================================

def replace_safe(date_obj: date, day: int) -> date:
    try:
        return date_obj.replace(day=day)
    except ValueError:
        return date_obj.replace(day=calendar.monthrange(date_obj.year, date_obj.month)[1])


def _parse_iso_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def _add_months(base: date, months: int, anchor_day: int) -> date:
    idx = base.year * 12 + (base.month - 1) + months
    year, month = idx // 12, idx % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def recurring_occurrence(start: date, cycle: str, n: int) -> date:
    """n-te wystąpienie liczone od daty startu."""
    if cycle == "Dziennie":
        return start + timedelta(days=n)
    if cycle == "Tygodniowo":
        return start + timedelta(weeks=n)
    if cycle == "Kwartalnie":
        return _add_months(start, 3 * n, start.day)
    if cycle == "Rocznie":
        return _add_months(start, 12 * n, start.day)
    return _add_months(start, n, start.day)


def _first_occurrence_index_after(start: date, cycle: str, after: Optional[date]) -> int:
    if after is None or after < start:
        return 0
    if cycle == "Dziennie":
        n = (after - start).days + 1
    elif cycle == "Tygodniowo":
        n = (after - start).days // 7 + 1
    elif cycle == "Rocznie":
        n = after.year - start.year
    elif cycle == "Kwartalnie":
        n = ((after.year - start.year) * 12 + (after.month - start.month)) // 3
    else:
        n = (after.year - start.year) * 12 + (after.month - start.month)
    n = max(0, n - 1)
    while recurring_occurrence(start, cycle, n) <= after:
        n += 1
    return n


def get_recurring_next_due(row: Any) -> Optional[date]:
    """Najbliższy nieopłacony termin (może być w przeszłości = zaległość)."""
    r = dict(row)
    start = _parse_iso_date(r.get("start_date"))
    if not start:
        return None
    cycle = r.get("cycle") or "Miesięcznie"
    n = _first_occurrence_index_after(start, cycle, _parse_iso_date(r.get("last_payment_date")))
    return recurring_occurrence(start, cycle, n)


def get_recurring_due_dates(row: Any, today: Optional[date] = None) -> List[date]:
    r = dict(row)
    if int(r.get("is_registered") or 0) != 1:
        return []
    start = _parse_iso_date(r.get("start_date"))
    if not start:
        return []
    today = today or date.today()
    cycle = r.get("cycle") or "Miesięcznie"
    out: List[date] = []
    n = _first_occurrence_index_after(start, cycle, _parse_iso_date(r.get("last_payment_date")))
    while len(out) < MAX_CATCHUP_OCCURRENCES:
        occ = recurring_occurrence(start, cycle, n)
        if occ > today:
            break
        out.append(occ)
        n += 1
    return out


def occurrences_in_month(row: Any, ym: str) -> List[date]:
    """Terminy zlecenia przypadające w danym miesiącu (do kalendarza)."""
    r = dict(row)
    start = _parse_iso_date(r.get("start_date"))
    if not start or int(r.get("is_registered") or 0) != 1:
        return []
    y, m = map(int, ym.split("-"))
    first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    cycle = r.get("cycle") or "Miesięcznie"
    out: List[date] = []
    n = _first_occurrence_index_after(start, cycle, first - timedelta(days=1))
    while len(out) < 40:
        occ = recurring_occurrence(start, cycle, n)
        if occ > last:
            break
        out.append(occ)
        n += 1
    return out


def check_due_payments_count(today: Optional[date] = None) -> int:
    """Zaległe terminy: zlecenia stałe + raty kredytów/zakupów na raty."""
    from src.finance.loans import due_installments_count

    with open_user_db() as conn:
        rows = conn.execute("SELECT * FROM recurring_payments WHERE is_registered = 1").fetchall()
    return sum(len(get_recurring_due_dates(row, today)) for row in rows) + due_installments_count(today)


def get_upcoming_recurring(limit: int = 20, today: Optional[date] = None) -> List[Dict[str, Any]]:
    today = today or date.today()
    out: List[Dict[str, Any]] = []
    for row in get_all_recurring():
        r = dict(row)
        if int(r.get("is_registered") or 0) != 1:
            continue
        nxt = get_recurring_next_due(r)
        if nxt is None:
            continue
        r["next_due"] = nxt
        r["days"] = (nxt - today).days
        out.append(r)
    from src.finance.loans import upcoming_installments

    out += upcoming_installments(today)  # raty kredytów i zakupów na raty
    out.sort(key=lambda x: (x["days"], x.get("name") or ""))
    return out[:limit]


def monthly_cost_summary() -> Dict[str, float]:
    """Średni miesięczny koszt / wpływ / odkładanie ze zleceń aktywnych."""
    cost = income = saving = 0.0
    for row in get_all_recurring():
        if int(row["is_registered"] or 0) != 1:
            continue
        value = float(row["amount"] or 0.0) * CYCLE_PER_MONTH.get(row["cycle"], 1.0)
        if row["type"] == "Dochód":
            income += value
        elif row["type"] in ("Na Skarbonkę", "Przelew"):
            saving += value
        else:
            cost += value
    return {"cost": cost, "income": income, "saving": saving}


# =============================================================================
# Księgowanie
# =============================================================================

def _post_occurrence(conn: sqlite3.Connection, row: sqlite3.Row, due: date) -> None:
    from src.finance.accounts import _transfer
    from src.finance.autosave import apply_autosave_rules
    from src.finance.goals import move_goal_funds

    day = due.isoformat()
    amount = abs(float(row["amount"] or 0.0))
    account = row["account_type"]
    r_type = row["type"]
    note = f"[CYKLICZNE] {row['name']}"

    if r_type == "Na Skarbonkę":
        if row["piggy_id"]:
            move_goal_funds(conn, row["piggy_id"], amount, account, day, note, check_funds=False)
        return
    if r_type == "Przelew":
        target = row["target_account"]
        if target:
            _transfer(conn, account, target, amount, day, note, check_funds=False, group_prefix="rec")
        return
    category = normalize_category(conn, row["category"])
    post_entry(conn, day, r_type, category, account, row["name"], amount, note)
    if r_type == "Dochód":
        apply_autosave_rules(conn, account, r_type, amount, day, row["name"])


def check_and_process_recurring(today: Optional[date] = None) -> int:
    """Księguje wszystkie zaległe terminy aktywnych zleceń. Zwraca liczbę operacji."""
    today = today or date.today()
    processed = 0
    try:
        with open_user_db(write=True) as conn:
            rows = conn.execute("SELECT * FROM recurring_payments WHERE is_registered = 1").fetchall()
            for row in rows:
                due_dates = get_recurring_due_dates(row, today)
                if not due_dates:
                    continue
                if not conn.execute("SELECT 1 FROM accounts WHERE name = ?", (row["account_type"],)).fetchone():
                    log.warning("Zlecenie %s pominięte: brak konta %s", row["name"], row["account_type"])
                    continue
                for due in due_dates:
                    _post_occurrence(conn, row, due)
                    processed += 1
                conn.execute("UPDATE recurring_payments SET last_payment_date = ? WHERE id = ?",
                             (due_dates[-1].isoformat(), row["id"]))
    except Exception as e:
        log.error("Błąd przetwarzania zleceń cyklicznych: %s", e)
    try:
        from src.finance.loans import process_due_installments

        processed += process_due_installments(today)
    except Exception as e:
        log.error("Błąd księgowania rat: %s", e)
    return processed


process_due_payments = check_and_process_recurring


def get_recurring_sum() -> float:
    return monthly_cost_summary()["cost"]
