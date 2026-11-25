"""
Kredyty, pożyczki i zakupy na raty (grupa kont „Zobowiązania”).

Konto zobowiązania ma saldo UJEMNE = dług do spłaty (np. −1 500 zł za ekspres na raty).

Rata (księgowana automatycznie w dniu płatności, także zaległe — jak zlecenia stałe):
    * WYDATEK z konta spłaty w kopercie rat (np. „Raty”) — budżet widzi miesięczną ratę,
    * SPŁATA na koncie kredytu („Spłata raty”) — dług maleje o część kapitałową,
    * odsetki = pozostały dług × oprocentowanie / 12 (raty 0% — bez odsetek).
  Oba wpisy mają wspólny identyfikator grupy (usunięcie jednego usuwa oba).
Majątek: przy zaciągnięciu kredytu / zakupie na raty spada o kwotę długu; spłata kapitału
majątku nie zmienia (gotówka ↓, dług ↓), odsetki go zmniejszają.

Harmonogram: rata nr k ma termin = pierwsza rata + (k−1) miesięcy; liczba zapłaconych rat
wynika z wpisów „Spłata raty”, więc spłaty zawsze zgadzają się z historią.
Spłata kończy się sama, gdy dług wynosi 0 (np. po nadpłacie — wcześniej).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.finance.ledger import EXPENSE, TRANSFER, account_balance_in, new_group_id, normalize_category, post_entry
from src.finance.storage import now_iso, open_user_db

REPAY = "loan_repay_in"  # spłata raty (dług maleje)
OPEN_DEBT = "loan_open_out"  # zaciągnięcie kredytu / zakup na raty (dług rośnie)
FUNDS_IN = "loan_funds_in"  # wypłata kredytu na konto
DEFAULT_CATEGORY = "Raty i kredyty"


def annuity_payment(principal: float, rate_pct: float, months: int) -> float:
    """Rata równa (annuitetowa); dla 0% — kwota / liczba rat."""
    principal, months = float(principal), max(1, int(months))
    r = float(rate_pct or 0) / 1200.0
    if r <= 0:
        return round(principal / months, 2)
    return round(principal * r / (1 - (1 + r) ** -months), 2)


def _add_months(d: date, months: int) -> date:
    from src.finance.accounts import add_months

    return add_months(d, months)


def _parse(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def paid_count(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM transactions WHERE account_type = ? AND entry_subtype = ?",
                            (name, REPAY)).fetchone()[0])


def interest_paid(conn: sqlite3.Connection, name: str) -> float:
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE linked_group_id IN "
                       "(SELECT linked_group_id FROM transactions WHERE account_type = ? AND entry_subtype = ?) "
                       "AND type = ?", (name, REPAY, EXPENSE)).fetchone()
    repaid = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_type = ? AND "
                          "entry_subtype = ?", (name, REPAY)).fetchone()
    return round(float(row[0] or 0) - float(repaid[0] or 0), 2)


def loan_status(acc: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Stan zobowiązania: dług, raty zapłacone/wszystkie, następny termin, postęp spłaty."""
    a = dict(acc)
    today = today or date.today()
    name = a["name"]
    with open_user_db() as conn:
        paid = paid_count(conn, name)
        interest = interest_paid(conn, name)
    remaining = max(0.0, -float(a.get("balance") or 0.0))
    total = float(a.get("principal") or 0.0) or remaining
    installments = int(a.get("term_months") or 0)
    payment = float(a.get("loan_installment") or 0.0)
    first = _parse(a.get("loan_first_due"))
    finished = remaining < 0.005
    next_due = None if finished or not first else _add_months(first, paid)
    left = max(0, installments - paid) if installments else None
    end = _add_months(first, installments - 1) if first and installments else None
    return {
        "remaining": round(remaining, 2),
        "total": round(total, 2),
        "paid": paid,
        "installments": installments,
        "left": left,
        "payment": payment,
        "rate": float(a.get("interest_rate") or 0.0),
        "next_due": next_due,
        "days": (next_due - today).days if next_due else None,
        "end": end,
        "finished": finished,
        "progress": (1 - remaining / total) * 100.0 if total > 0 else 100.0,
        "interest_paid": interest,
        "pay_from": a.get("linked_account"),
        "category": a.get("loan_category"),
    }


def open_loan(name: str, amount: float, installments: int, first_due: str, pay_from: str,
              rate_pct: float = 0.0, payment: Optional[float] = None, kind: str = "installments",
              category: Optional[str] = None, disburse_to: Optional[str] = None, institution: Optional[str] = None,
              record_history: bool = True, day: Optional[str] = None) -> Tuple[bool, str]:
    """
    Zakłada kredyt / zakup na raty.
      amount       — kwota do spłaty (kapitał; dla trwającego kredytu: ile jeszcze zostało),
      installments — liczba (pozostałych) rat, first_due — termin najbliższej raty,
      payment      — rata miesięczna (domyślnie wyliczona: równa / annuitetowa),
      disburse_to  — konto, na które wpłynęły pieniądze (kredyt gotówkowy); None = zakup na raty,
      record_history=False — stan początkowy: tylko saldo, bez wpisów (np. kredyt spłacany od dawna).
    """
    from src.finance.accounts import add_account

    amount = round(abs(float(amount)), 2)
    if amount <= 0 or int(installments) <= 0:
        return False, "Kwota i liczba rat muszą być większe od zera."
    if kind not in ("loan", "installments"):
        return False, "Nieznany rodzaj zobowiązania."
    if not _parse(first_due):
        return False, "Podaj datę najbliższej raty."
    payment = round(float(payment), 2) if payment else annuity_payment(amount, rate_pct, installments)
    with open_user_db() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE name = ?", (pay_from,)).fetchone():
            return False, f"Nie ma konta spłaty: {pay_from}"
    ok, msg = add_account(name, 0.0, account_kind=kind, institution=institution, interest_rate=rate_pct,
                          term_months=int(installments), linked_account=pay_from, opened_at=day or now_iso()[:10])
    if not ok:
        return ok, msg
    with open_user_db(write=True) as conn:
        cat = _ensure_loan_category(conn, category or DEFAULT_CATEGORY, payment)
        conn.execute("UPDATE accounts SET principal = ?, loan_installment = ?, loan_category = ?, loan_first_due = ? "
                     "WHERE name = ?", (amount, payment, cat, _parse(first_due).isoformat(), name))
        when = day or date.today().isoformat()
        if not record_history:
            conn.execute("UPDATE accounts SET balance = ? WHERE name = ?", (-amount, name))
        elif disburse_to:
            group = new_group_id("loan")
            post_entry(conn, when, TRANSFER, None, name, f"→ {disburse_to}", amount, f"Kredyt: {name}",
                       subtype=OPEN_DEBT, group_id=group)
            post_entry(conn, when, TRANSFER, None, disburse_to, f"← {name}", amount, f"Wypłata kredytu: {name}",
                       subtype=FUNDS_IN, group_id=group)
        else:
            post_entry(conn, when, TRANSFER, None, name, name, amount, f"Zakup na raty: {name}", subtype=OPEN_DEBT)
    return True, ""


def _ensure_loan_category(conn: sqlite3.Connection, name: str, payment: float) -> str:
    """Koperta na raty: nowa dostaje budżet równy racie; budżetu istniejącej koperty nie zmieniamy."""
    name = (name or DEFAULT_CATEGORY).strip()
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone() is None:
        normalize_category(conn, name)
        conn.execute("UPDATE categories SET limit_amount = ? WHERE name = ?", (round(payment, 2), name))
    return name


def _due_dates(acc: Any, today: date) -> List[date]:
    """Terminy rat do zaksięgowania (zaległe i dzisiejsza)."""
    st = loan_status(acc, today)
    if st["finished"] or not st["next_due"] or not st["pay_from"]:
        return []
    out, k = [], 0
    first = _parse(acc["loan_first_due"])
    while len(out) < 600:  # zabezpieczenie (50 lat rat)
        due = _add_months(first, st["paid"] + k)
        if due > today:
            break
        out.append(due)
        k += 1
    return out


def pay_installment(conn: sqlite3.Connection, acc: Any, due: date) -> Optional[float]:
    """Księguje jedną ratę. Zwraca kwotę raty (None, gdy dług już spłacony)."""
    name = acc["name"]
    remaining = -account_balance_in(conn, name)
    if remaining < 0.005:
        return None
    rate = float(acc["interest_rate"] or 0.0)
    interest = round(remaining * rate / 1200.0, 2)
    payment = min(float(acc["loan_installment"] or 0.0) or remaining + interest, round(remaining + interest, 2))
    principal_part = round(min(remaining, payment - interest), 2)
    if principal_part <= 0:  # rata nie pokrywa odsetek — spłacamy co najmniej grosz kapitału, żeby skończyć
        principal_part = min(remaining, 0.01)
        payment = round(interest + principal_part, 2)
    k = paid_count(conn, name) + 1
    n = int(acc["term_months"] or 0)
    label = f"Rata {k}/{n}" if n else f"Rata {k}"
    group = new_group_id("loan")
    category = normalize_category(conn, acc["loan_category"] or DEFAULT_CATEGORY)
    post_entry(conn, due.isoformat(), EXPENSE, category, acc["linked_account"], name, payment,
               f"{label}: {name}" + (f" (odsetki {interest:.2f})" if interest else ""), group_id=group)
    post_entry(conn, due.isoformat(), TRANSFER, None, name, f"← {acc['linked_account']}", principal_part,
               f"{label}: spłata kapitału", subtype=REPAY, group_id=group)
    return payment


def due_installments_count(today: Optional[date] = None) -> int:
    today = today or date.today()
    return sum(len(_due_dates(acc, today)) for acc in _active_loans())


def process_due_installments(today: Optional[date] = None) -> int:
    """Księguje wszystkie zaległe raty aktywnych zobowiązań. Zwraca liczbę zaksięgowanych rat."""
    today = today or date.today()
    count = 0
    for acc in _active_loans():
        dues = _due_dates(acc, today)
        if not dues:
            continue
        with open_user_db(write=True) as conn:
            if not conn.execute("SELECT 1 FROM accounts WHERE name = ?", (acc["linked_account"],)).fetchone():
                continue
            for due in dues:
                if pay_installment(conn, acc, due) is None:
                    break
                count += 1
    return count


def upcoming_installments(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Najbliższe raty (do listy „Nadchodzące płatności”)."""
    today = today or date.today()
    out = []
    for acc in _active_loans():
        st = loan_status(acc, today)
        if st["finished"] or not st["next_due"]:
            continue
        interest = round(st["remaining"] * st["rate"] / 1200.0, 2)
        amount = min(st["payment"] or st["remaining"], round(st["remaining"] + interest, 2))
        out.append({"name": f"Rata: {acc['name']}", "amount": amount, "type": "Rata", "next_due": st["next_due"],
                    "days": (st["next_due"] - today).days, "category": st["category"],
                    "account_type": st["pay_from"], "cycle": "Miesięcznie", "loan": acc["name"]})
    return out


def _active_loans() -> List[sqlite3.Row]:
    with open_user_db() as conn:
        rows = conn.execute("SELECT * FROM accounts WHERE is_active = 1").fetchall()
    from src.finance.accounts import account_info

    return [r for r in rows if account_info(r).liability and r["loan_first_due"]]
