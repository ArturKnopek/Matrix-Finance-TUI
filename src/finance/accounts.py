"""
Konta i produkty finansowe.

Rodzaje kont (ACCOUNT_KINDS) dzielą się na grupy:
    Codzienne   – konto osobiste, gotówka, portfel fintech (Revolut, PayPal…)
    Oszczędności – konto oszczędnościowe, lokata
    Inwestycje  – obligacje skarbowe, konto maklerskie, robodoradca
    Emerytalne  – IKE, IKZE, PPK

Operacje:
    transfer_between_accounts – przelew między dowolnymi kontami (2 wpisy typu Transfer),
    open_term_deposit         – założenie lokaty/obligacji z konta źródłowego,
    settle_matured_deposits   – rozliczenie lokat po terminie (odsetki netto, odnowienie lub zwrot),
    break_term_deposit        – zerwanie lokaty (zwrot kapitału bez odsetek),
    update_valuation          – aktualizacja wyceny inwestycji (zysk/strata),
    external_contribution     – wpłata spoza budżetu (np. pracodawca do PPK),
    record_interest           – dopisanie odsetek (dochód).
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.finance.ledger import (
    INCOME,
    TRANSFER,
    account_balance_in,
    change_balance,
    new_group_id,
    normalize_category,
    post_entry,
    require_account,
)
from src.finance.storage import INTEREST_CATEGORY, now_iso, open_user_db


@dataclass(frozen=True)
class AccountKind:
    code: str
    label: str
    group: str
    liquid: bool = True  # czy środki są „pod ręką” (dostępne)
    has_rate: bool = False  # oprocentowanie
    has_term: bool = False  # termin zapadalności (lokata, obligacje)
    valuation: bool = False  # wartość zmienia się wyceną (inwestycje)
    retirement: bool = False  # limity roczne wpłat (IKE/IKZE)


ACCOUNT_KINDS: Dict[str, AccountKind] = {
    k.code: k for k in (
        AccountKind("checking", "Konto osobiste", "Codzienne"),
        AccountKind("cash", "Gotówka", "Codzienne"),
        AccountKind("ewallet", "Fintech / portfel (Revolut…)", "Codzienne", has_rate=True),
        AccountKind("savings", "Konto oszczędnościowe", "Oszczędności", has_rate=True),
        AccountKind("deposit", "Lokata", "Oszczędności", liquid=False, has_rate=True, has_term=True),
        AccountKind("bonds", "Obligacje skarbowe", "Inwestycje", liquid=False, has_rate=True, has_term=True),
        AccountKind("investment", "Konto maklerskie", "Inwestycje", liquid=False, valuation=True),
        AccountKind("robo", "Robodoradca", "Inwestycje", liquid=False, valuation=True),
        AccountKind("ike", "IKE", "Emerytalne", liquid=False, valuation=True, retirement=True),
        AccountKind("ikze", "IKZE", "Emerytalne", liquid=False, valuation=True, retirement=True),
        AccountKind("ppk", "PPK", "Emerytalne", liquid=False, valuation=True, retirement=True),
    )
}
KIND_GROUPS = ["Codzienne", "Oszczędności", "Inwestycje", "Emerytalne"]
INSTITUTIONS = ["Revolut", "PKO BP", "mBank", "ING", "Santander", "Pekao", "Millennium", "Alior", "BNP Paribas",
                "Credit Agricole", "VeloBank", "Nest Bank", "XTB", "Finax", "inPZU", "Obligacje skarbowe (PKO)"]
DEFAULT_TAX_RATE = 19.0  # podatek od zysków kapitałowych („podatek Belki”)


def kind_info(code: Optional[str]) -> AccountKind:
    return ACCOUNT_KINDS.get(code or "checking", ACCOUNT_KINDS["checking"])


def kind_options() -> List[Tuple[str, str]]:
    return [(f"{k.group} · {k.label}", k.code) for k in ACCOUNT_KINDS.values()]


# =============================================================================
# Odczyt
# =============================================================================

def get_all_accounts_data(active_only: bool = False):
    query = "SELECT * FROM accounts"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY sort_order ASC, name ASC"
    with open_user_db() as conn:
        return conn.execute(query).fetchall()


def get_account(name: str):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM accounts WHERE name = ?", (name,)).fetchone()


def get_account_names(active_only: bool = True, liquid_only: bool = False) -> List[str]:
    rows = get_all_accounts_data(active_only=active_only)
    return [r["name"] for r in rows if not liquid_only or kind_info(r["account_kind"]).liquid]


def get_account_options(active_only: bool = True, liquid_only: bool = False,
                        with_balance: bool = False) -> List[Tuple[str, str]]:
    rows = get_all_accounts_data(active_only=active_only)
    out: List[Tuple[str, str]] = []
    for r in rows:
        if liquid_only and not kind_info(r["account_kind"]).liquid:
            continue
        label = r["name"]
        if r["currency"] and r["currency"] != "PLN":
            label += f" ({r['currency']})"
        if with_balance:
            label += f" · {float(r['balance'] or 0):,.2f}".replace(",", " ")
        out.append((label, r["name"]))
    return out or [("Karta", "Karta")]


def get_account_balance(account_name: str) -> float:
    with open_user_db() as conn:
        return account_balance_in(conn, account_name)


def update_account_balance(account_name: str, amount_change: float) -> None:
    with open_user_db(write=True) as conn:
        change_balance(conn, account_name, amount_change)


def set_account_balance(account_name: str, new_balance: float, note: str = "Korekta salda",
                        day: Optional[str] = None, tx_uid: Optional[str] = None) -> float:
    """
    Korekta salda: ustawia rzeczywiste saldo konta, zapisując różnicę jako wpis
    „Korekta salda (+/−)” (Transfer — nie jest wydatkiem ani dochodem, nie zmienia budżetu).
    Zwraca różnicę.
    """
    with open_user_db(write=True) as conn:
        require_account(conn, account_name)
        diff = round(float(new_balance) - account_balance_in(conn, account_name), 2)
        if diff:
            post_entry(conn, day or date.today().isoformat(), TRANSFER, None, account_name,
                       note or "Korekta salda", abs(diff), "[KOREKTA] ręczna zmiana salda",
                       subtype="correction_up" if diff > 0 else "correction_down", tx_uid=tx_uid)
        return diff


# =============================================================================
# Zakładanie / edycja / zamykanie
# =============================================================================

def add_account(
    name: str,
    opening_balance: float = 0.0,
    currency: str = "PLN",
    account_kind: str = "checking",
    include_in_reports: bool = True,
    include_in_net_worth: bool = True,
    institution: Optional[str] = None,
    interest_rate: float = 0.0,
    tax_rate: float = DEFAULT_TAX_RATE,
    yearly_limit: float = 0.0,
    notes: Optional[str] = None,
    opened_at: Optional[str] = None,
    maturity_date: Optional[str] = None,
    term_months: Optional[int] = None,
    linked_account: Optional[str] = None,
    auto_renew: bool = False,
) -> Tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "Podaj nazwę konta."
    if account_kind not in ACCOUNT_KINDS:
        return False, "Nieznany rodzaj konta."
    try:
        with open_user_db(write=True) as conn:
            next_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 FROM accounts").fetchone()[0] or 10
            stamp = now_iso()
            conn.execute(
                """
                INSERT INTO accounts
                    (name, balance, currency, account_kind, sort_order, is_active, include_in_reports,
                     include_in_net_worth, created_at, updated_at, institution, interest_rate, tax_rate,
                     yearly_limit, notes, opened_at, maturity_date, term_months, principal, linked_account,
                     auto_renew)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, float(opening_balance or 0.0), (currency or "PLN").upper(), account_kind, int(next_order),
                 1 if include_in_reports else 0, 1 if include_in_net_worth else 0, stamp, stamp,
                 (institution or "").strip() or None, float(interest_rate or 0.0), float(tax_rate),
                 float(yearly_limit or 0.0), notes, opened_at, maturity_date, term_months,
                 float(opening_balance or 0.0), linked_account, 1 if auto_renew else 0),
            )
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Konto o tej nazwie już istnieje."
    except Exception as e:
        return False, str(e)


_EDITABLE = {"account_kind", "institution", "interest_rate", "tax_rate", "yearly_limit", "notes", "linked_account",
             "auto_renew", "include_in_net_worth", "include_in_reports", "maturity_date", "currency"}


def update_account(name: str, new_name: Optional[str] = None, **fields: Any) -> Tuple[bool, str]:
    bad = set(fields) - _EDITABLE
    if bad:
        return False, f"Niedozwolone pola: {', '.join(sorted(bad))}"
    if new_name and new_name.strip() != name:
        ok, msg = update_account_name_everywhere(name, new_name.strip())
        if not ok:
            return ok, msg
        name = new_name.strip()
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
        with open_user_db(write=True) as conn:
            conn.execute(f"UPDATE accounts SET {sets} WHERE name = ?", (*fields.values(), now_iso(), name))
    return True, ""


def update_account_name_everywhere(old_name: str, new_name: str) -> Tuple[bool, str]:
    old_name, new_name = (old_name or "").strip(), (new_name or "").strip()
    if not old_name or not new_name:
        return False, "Niepoprawna nazwa konta."
    try:
        with open_user_db(write=True) as conn:
            conn.execute("UPDATE accounts SET name=?, updated_at=? WHERE name=?", (new_name, now_iso(), old_name))
            for table, column in (("transactions", "account_type"), ("archive", "account_type"),
                                  ("piggy_banks", "account_type"), ("recurring_payments", "account_type"),
                                  ("recurring_payments", "target_account"), ("accounts", "linked_account"),
                                  ("autosave_rules", "source_account")):
                conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new_name, old_name))
            conn.execute("UPDATE autosave_rules SET target=? WHERE target_kind='account' AND target=?",
                         (new_name, old_name))
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Konto o tej nazwie już istnieje."


def close_account(name: str, transfer_to: Optional[str] = None) -> Tuple[bool, str]:
    """Zamyka konto. Pozostałe saldo przelewa na `transfer_to` (wymagane, gdy saldo ≠ 0)."""
    with open_user_db(write=True) as conn:
        require_account(conn, name)
        balance = account_balance_in(conn, name)
        if abs(balance) >= 0.005:
            if not transfer_to:
                return False, "Konto ma saldo — wskaż konto, na które przelać środki."
            if balance < 0:
                return False, "Konto ma ujemne saldo — wyrównaj je przed zamknięciem."
            _transfer(conn, name, transfer_to, balance, date.today().isoformat(), f"Zamknięcie konta {name}")
        conn.execute("UPDATE accounts SET is_active = 0, closed_at = ?, updated_at = ? WHERE name = ?",
                     (now_iso(), now_iso(), name))
    return True, ""


# =============================================================================
# Przelewy i operacje
# =============================================================================

def _transfer(conn: sqlite3.Connection, source: str, target: str, amount: float, day: str, note: str,
              check_funds: bool = True, group_prefix: str = "trf", group_id: Optional[str] = None) -> str:
    source = require_account(conn, source)
    target = require_account(conn, target)
    amount = round(abs(float(amount)), 2)
    if source == target:
        raise ValueError("Konto źródłowe i docelowe muszą być różne.")
    if amount <= 0:
        raise ValueError("Kwota przelewu musi być większa od zera.")
    if check_funds and account_balance_in(conn, source) + 1e-9 < amount:
        raise ValueError(f"Brak środków na koncie {source}.")
    group = group_id or new_group_id(group_prefix)
    desc = note or f"Przelew {source} → {target}"
    # stały group_id (np. z telefonu) => stałe identyfikatory obu „nóg” przelewu
    uid_out, uid_in = (f"{group}:out", f"{group}:in") if group_id else (None, None)
    post_entry(conn, day, TRANSFER, None, source, f"→ {target}", amount, desc, subtype="transfer_out", group_id=group,
               tx_uid=uid_out)
    post_entry(conn, day, TRANSFER, None, target, f"← {source}", amount, desc, subtype="transfer_in", group_id=group,
               tx_uid=uid_in)
    return group


def transfer_between_accounts(source: str, target: str, amount: float, day: Optional[str] = None,
                              note: str = "", check_funds: bool = True, group_id: Optional[str] = None) -> str:
    with open_user_db(write=True) as conn:
        return _transfer(conn, source, target, amount, day or date.today().isoformat(), note, check_funds,
                         group_id=group_id)


def external_contribution(account: str, amount: float, day: Optional[str] = None, note: str = "") -> int:
    """Wpłata spoza budżetu (np. pracodawca/państwo do PPK) — zwiększa saldo, nie jest dochodem."""
    with open_user_db(write=True) as conn:
        account = require_account(conn, account)
        return post_entry(conn, day or date.today().isoformat(), TRANSFER, None, account,
                          note or "Wpłata zewnętrzna", abs(float(amount)), note or "Wpłata zewnętrzna",
                          subtype="external_in")


def record_interest(account: str, amount: float, day: Optional[str] = None, note: str = "") -> int:
    """Odsetki / zysk zrealizowany — dochód w kategorii „Odsetki i zyski”."""
    with open_user_db(write=True) as conn:
        account = require_account(conn, account)
        cat = normalize_category(conn, INTEREST_CATEGORY)
        return post_entry(conn, day or date.today().isoformat(), INCOME, cat, account, note or "Odsetki",
                          abs(float(amount)), note or f"Odsetki: {account}")


def update_valuation(account: str, new_value: float, day: Optional[str] = None, note: str = "") -> float:
    """Aktualizuje wycenę inwestycji; różnica zapisana jako wzrost/spadek wyceny. Zwraca różnicę."""
    with open_user_db(write=True) as conn:
        account = require_account(conn, account)
        diff = round(float(new_value) - account_balance_in(conn, account), 2)
        if diff:
            post_entry(conn, day or date.today().isoformat(), TRANSFER, None, account, "Wycena",
                       abs(diff), note or "Aktualizacja wyceny",
                       subtype="valuation_up" if diff > 0 else "valuation_down")
        return diff


def contributions_in_year(account: str, year: Optional[int] = None) -> float:
    """Suma wpłat na konto w roku (przelewy przychodzące + wpłaty zewnętrzne) — do limitów IKE/IKZE."""
    year = year or date.today().year
    with open_user_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_type = ? AND date LIKE ? "
            "AND entry_subtype IN ('transfer_in', 'external_in')",
            (account, f"{year}-%"),
        ).fetchone()
    return float(row[0] or 0.0)


# =============================================================================
# Lokaty i obligacje
# =============================================================================

def add_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _parse(d: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date() if d else None
    except ValueError:
        return None


def interest_for_period(principal: float, rate_pct: float, start: date, end: date,
                        tax_rate: float = DEFAULT_TAX_RATE) -> Tuple[float, float, float]:
    """Odsetki proste za okres: (brutto, podatek, netto), zaokrąglone do groszy."""
    days = max(0, (end - start).days)
    gross = round(principal * (rate_pct / 100.0) * days / 365.0, 2)
    tax = round(gross * tax_rate / 100.0, 2)
    return gross, tax, round(gross - tax, 2)


def open_term_deposit(name: str, source_account: str, amount: float, interest_rate: float, term_months: int,
                      start_date: Optional[str] = None, institution: Optional[str] = None,
                      kind: str = "deposit", auto_renew: bool = False,
                      tax_rate: float = DEFAULT_TAX_RATE) -> Tuple[bool, str]:
    """Zakłada lokatę/obligacje: nowe konto + przelew z konta źródłowego."""
    if kind not in ("deposit", "bonds"):
        return False, "Rodzaj musi być lokatą albo obligacjami."
    if amount <= 0 or term_months <= 0:
        return False, "Kwota i okres muszą być większe od zera."
    start = _parse(start_date) or date.today()
    maturity = add_months(start, int(term_months))
    ok, msg = add_account(name, 0.0, account_kind=kind, institution=institution, interest_rate=interest_rate,
                          tax_rate=tax_rate, opened_at=start.isoformat(), maturity_date=maturity.isoformat(),
                          term_months=int(term_months), linked_account=source_account, auto_renew=auto_renew)
    if not ok:
        return ok, msg
    try:
        with open_user_db(write=True) as conn:
            _transfer(conn, source_account, name, amount, start.isoformat(),
                      f"Założenie: {name} ({interest_rate:.2f}% / {term_months} m-cy)", group_prefix="dep")
            conn.execute("UPDATE accounts SET principal = ? WHERE name = ?", (round(float(amount), 2), name))
    except Exception as e:
        with open_user_db(write=True) as conn:
            conn.execute("DELETE FROM accounts WHERE name = ?", (name,))
        return False, str(e)
    return True, ""


def deposit_projection(acc: Any, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Prognoza dla lokaty/obligacji: postęp okresu, odsetki narosłe i na koniec okresu (netto)."""
    a = dict(acc)
    if not kind_info(a.get("account_kind")).has_term:
        return None
    start, end = _parse(a.get("opened_at")), _parse(a.get("maturity_date"))
    if not start or not end:
        return None
    today = today or date.today()
    principal = float(a.get("principal") or a.get("balance") or 0.0)
    rate = float(a.get("interest_rate") or 0.0)
    tax = float(a.get("tax_rate") if a.get("tax_rate") is not None else DEFAULT_TAX_RATE)
    total_days = max(1, (end - start).days)
    elapsed = min(total_days, max(0, (today - start).days))
    gross, tax_amt, net = interest_for_period(principal, rate, start, end, tax)
    _, _, accrued = interest_for_period(principal, rate, start, start + timedelta(days=elapsed), tax)
    return {
        "principal": principal,
        "rate": rate,
        "start": start,
        "end": end,
        "days_total": total_days,
        "days_left": max(0, (end - today).days),
        "progress": elapsed / total_days * 100.0,
        "gross_interest": gross,
        "tax": tax_amt,
        "net_interest": net,
        "accrued_net": accrued,
        "final_value": round(principal + net, 2),
        "matured": today >= end,
    }


def get_matured_deposits(today: Optional[date] = None) -> List[sqlite3.Row]:
    today = today or date.today()
    with open_user_db() as conn:
        rows = conn.execute("SELECT * FROM accounts WHERE is_active = 1 AND account_kind IN ('deposit', 'bonds') "
                            "AND maturity_date IS NOT NULL").fetchall()
    return [r for r in rows if (_parse(r["maturity_date"]) or date.max) <= today]


def settle_matured_deposits(today: Optional[date] = None) -> List[str]:
    """
    Rozlicza lokaty/obligacje po terminie: dopisuje odsetki netto (dochód) i
    odnawia lokatę (auto_renew) albo przelewa całość na konto powiązane i zamyka.
    Zwraca opisy wykonanych operacji.
    """
    today = today or date.today()
    messages: List[str] = []
    for acc in get_matured_deposits(today):
        name = acc["name"]
        with open_user_db(write=True) as conn:
            cat = normalize_category(conn, INTEREST_CATEGORY)
            start, end = _parse(acc["opened_at"]) or today, _parse(acc["maturity_date"]) or today
            principal = float(acc["principal"] or account_balance_in(conn, name))
            rate, tax = float(acc["interest_rate"] or 0.0), float(acc["tax_rate"] or 0.0)
            term = int(acc["term_months"] or 0)
            renewals = 0
            while True:
                gross, tax_amt, net = interest_for_period(principal, rate, start, end, tax)
                if net > 0:
                    post_entry(conn, end.isoformat(), INCOME, cat, name, f"Odsetki: {name}", net,
                               f"Odsetki {start:%d.%m.%Y}–{end:%d.%m.%Y}: brutto {gross:.2f}, podatek {tax_amt:.2f}")
                if not int(acc["auto_renew"] or 0) or term <= 0:
                    break
                renewals += 1
                start, end = end, add_months(end, term)
                principal = account_balance_in(conn, name)
                if end > today:
                    conn.execute("UPDATE accounts SET opened_at=?, maturity_date=?, principal=?, updated_at=? "
                                 "WHERE name=?", (start.isoformat(), end.isoformat(), principal, now_iso(), name))
                    break
            if int(acc["auto_renew"] or 0) and term > 0:
                messages.append(f"{name}: dopisano odsetki i odnowiono ({renewals}×) do {end:%d.%m.%Y}.")
                continue
            balance = account_balance_in(conn, name)
            target = acc["linked_account"]
            if target and conn.execute("SELECT 1 FROM accounts WHERE name=? AND is_active=1", (target,)).fetchone() \
                    and balance > 0:
                _transfer(conn, name, target, balance, end.isoformat(), f"Zakończenie: {name}", group_prefix="dep")
                conn.execute("UPDATE accounts SET is_active=0, closed_at=? WHERE name=?", (now_iso(), name))
                messages.append(f"{name}: zakończona, {balance:.2f} wróciło na {target}.")
            else:
                messages.append(f"{name}: zakończona, środki czekają na koncie lokaty.")
    return messages


def break_term_deposit(name: str, today: Optional[date] = None) -> Tuple[bool, str]:
    """Zerwanie lokaty przed terminem: kapitał wraca na konto powiązane bez odsetek."""
    today = today or date.today()
    acc = get_account(name)
    if not acc or not kind_info(acc["account_kind"]).has_term:
        return False, "To nie jest lokata ani obligacje."
    target = acc["linked_account"]
    if not target:
        return False, "Lokata nie ma konta powiązanego."
    with open_user_db(write=True) as conn:
        balance = account_balance_in(conn, name)
        if balance > 0:
            _transfer(conn, name, target, balance, today.isoformat(), f"Zerwanie: {name}", group_prefix="dep")
        conn.execute("UPDATE accounts SET is_active=0, closed_at=? WHERE name=?", (now_iso(), name))
    return True, f"Zerwano {name}: {balance:.2f} wróciło na {target} (bez odsetek)."


# =============================================================================
# Przegląd
# =============================================================================

def get_accounts_overview(active_only: bool = True) -> List[Dict[str, Any]]:
    out = []
    today = date.today()
    for row in get_all_accounts_data(active_only=active_only):
        r = dict(row)
        info = kind_info(r.get("account_kind"))
        r["balance"] = float(r.get("balance") or 0.0)
        r["kind"] = info
        r["kind_label"] = info.label
        r["group"] = info.group
        r["liquid"] = info.liquid
        r["include_in_net_worth"] = int(r.get("include_in_net_worth") or 0) == 1
        r["currency"] = r.get("currency") or "PLN"
        r["projection"] = deposit_projection(r, today)
        if info.retirement:
            r["contributed_this_year"] = contributions_in_year(r["name"], today.year)
        if info.has_rate and not info.has_term and r.get("interest_rate") and r["balance"] > 0:
            rate, tax = float(r["interest_rate"]), float(r.get("tax_rate") or 0.0)
            r["monthly_interest_net"] = round(r["balance"] * rate / 100 / 12 * (1 - tax / 100), 2)
        out.append(r)
    return out


def get_net_worth() -> Dict[str, float]:
    """Majątek wg grup + cele + suma."""
    from src.finance.goals import get_piggy_total

    groups = {g: 0.0 for g in KIND_GROUPS}
    liquid = 0.0
    for acc in get_accounts_overview(active_only=True):
        if not acc["include_in_net_worth"]:
            continue
        groups[acc["group"]] = groups.get(acc["group"], 0.0) + acc["balance"]
        if acc["liquid"]:
            liquid += acc["balance"]
    goals = get_piggy_total()
    return {**groups, "liquid": liquid, "goals": goals, "total": sum(groups.values()) + goals}
