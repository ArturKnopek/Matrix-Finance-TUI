"""
Analityka: podsumowania miesięcy, trendy, dane do kalendarza, wskazówki „Doradcy”
oraz wyszukiwanie globalne.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.finance.envelopes import month_add
from src.finance.storage import open_user_db


# =============================================================================
# Podsumowania
# =============================================================================

def get_monthly_balance(month_str: str) -> Tuple[float, float]:
    """(przychody, wydatki) z bieżących transakcji (bez archiwum, bez przelewów)."""
    with open_user_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='Dochód' THEN amount END), 0), "
            "COALESCE(SUM(CASE WHEN type='Wydatek' THEN amount END), 0) FROM transactions WHERE date LIKE ?",
            (f"{month_str}%",)).fetchone()
    return float(row[0]), float(row[1])


def get_monthly_summary(year_month: str) -> Tuple[float, float]:
    """(przychody, wydatki) łącznie z archiwum."""
    income = expense = 0.0
    with open_user_db() as conn:
        for table in ("transactions", "archive"):
            row = conn.execute(
                f"SELECT COALESCE(SUM(CASE WHEN type='Dochód' THEN amount END), 0), "
                f"COALESCE(SUM(CASE WHEN type='Wydatek' THEN amount END), 0) FROM {table} WHERE date LIKE ?",
                (f"{year_month}%",)).fetchone()
            income += float(row[0])
            expense += float(row[1])
    return income, expense


def get_daily_spending_map(year_month: str) -> Dict[int, float]:
    with open_user_db() as conn:
        rows = conn.execute(
            "SELECT CAST(strftime('%d', date) AS INTEGER) AS day, SUM(amount) AS total FROM transactions "
            "WHERE type = 'Wydatek' AND date LIKE ? GROUP BY day", (f"{year_month}%",)).fetchall()
    return {int(r["day"]): float(r["total"] or 0.0) for r in rows if r["day"]}


def get_trend(months: int = 6, end_ym: Optional[str] = None) -> List[Dict[str, Any]]:
    """Przychody/wydatki/oszczędności dla ostatnich `months` miesięcy (rosnąco)."""
    end_ym = end_ym or date.today().strftime("%Y-%m")
    out = []
    for i in range(months - 1, -1, -1):
        ym = month_add(end_ym, -i)
        inc, exp = get_monthly_summary(ym)
        out.append({"ym": ym, "income": inc, "expense": exp, "saved": inc - exp})
    return out


def savings_rate(income: float, expense: float) -> Optional[float]:
    return (income - expense) / income * 100.0 if income > 0 else None


def archive_month(year_month: str) -> int:
    """Przenosi transakcje miesiąca do archiwum (salda bez zmian, podsumowania zostają)."""
    with open_user_db(write=True) as conn:
        cur = conn.execute(
            "INSERT OR REPLACE INTO archive (id, date, type, category, account_type, shop, amount, description, "
            "archived_at, entry_subtype, linked_group_id, goal_id) "
            "SELECT id, date, type, category, account_type, shop, amount, description, date('now'), "
            "entry_subtype, linked_group_id, goal_id FROM transactions WHERE date LIKE ?", (f"{year_month}%",))
        count = max(0, cur.rowcount)
        if count:
            conn.execute("DELETE FROM transactions WHERE date LIKE ?", (f"{year_month}%",))
        return count


# =============================================================================
# Kalendarz
# =============================================================================

@dataclass
class DayInfo:
    day: int
    spent: float = 0.0
    income: float = 0.0
    count: int = 0
    planned: List[str] = None  # type: ignore[assignment]
    events: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.planned = self.planned or []
        self.events = self.events or []


def get_calendar_data(ym: str) -> Dict[int, DayInfo]:
    """Dane dla każdego dnia miesiąca: wydano, wpłynęło, liczba wpisów, planowane zlecenia, terminy lokat."""
    from src.finance.accounts import get_all_accounts_data
    from src.finance.recurring import get_all_recurring, occurrences_in_month

    y, m = map(int, ym.split("-"))
    days = {d: DayInfo(d) for d in range(1, calendar.monthrange(y, m)[1] + 1)}
    with open_user_db() as conn:
        for r in conn.execute(
            "SELECT CAST(strftime('%d', date) AS INTEGER) AS day, type, SUM(amount) AS total, COUNT(*) AS n "
            "FROM transactions WHERE date LIKE ? GROUP BY day, type", (f"{ym}%",)).fetchall():
            info = days.get(int(r["day"] or 0))
            if not info:
                continue
            info.count += int(r["n"])
            if r["type"] == "Wydatek":
                info.spent += float(r["total"] or 0.0)
            elif r["type"] == "Dochód":
                info.income += float(r["total"] or 0.0)
    for row in get_all_recurring():
        for occ in occurrences_in_month(row, ym):
            days[occ.day].planned.append(f"{row['name']} ({float(row['amount']):.2f})")
    for acc in get_all_accounts_data(active_only=True):
        maturity = acc["maturity_date"]
        if maturity and str(maturity).startswith(ym):
            days[int(str(maturity)[8:10])].events.append(f"Koniec: {acc['name']}")
    return days


# =============================================================================
# Doradca
# =============================================================================

@dataclass
class Insight:
    level: str  # "ok" | "info" | "warn" | "alert"
    text: str


def get_insights(month: Optional[str] = None) -> List[Insight]:
    """Proste, regułowe wskazówki finansowe na podstawie danych użytkownika."""
    from src.finance.accounts import get_accounts_overview, get_matured_deposits
    from src.finance.envelopes import get_envelope_overview
    from src.finance.goals import goals_overview
    from src.finance.recurring import check_due_payments_count

    month = month or date.today().strftime("%Y-%m")
    tips: List[Insight] = []

    income, expense = get_monthly_summary(month)
    rate = savings_rate(income, expense)
    if rate is not None:
        if rate >= 20:
            tips.append(Insight("ok", f"Stopa oszczędności {rate:.0f}% — świetnie (cel: min. 20%)."))
        elif rate >= 0:
            tips.append(Insight("info", f"Stopa oszczędności {rate:.0f}%. Spróbuj dojść do 20% przychodów."))
        else:
            tips.append(Insight("alert", f"Wydatki przekraczają przychody o {expense - income:,.2f} zł.".replace(",", " ")))

    trend = get_trend(3, month_add(month, -1))
    past_expenses = [t["expense"] for t in trend if t["expense"] > 0] or ([expense] if expense > 0 else [])
    avg_expense = sum(past_expenses) / len(past_expenses) if past_expenses else 0.0
    accounts = get_accounts_overview(active_only=True)
    liquid = sum(a["balance"] for a in accounts if a["liquid"])
    savings_like = sum(a["balance"] for a in accounts if a["group"] in ("Oszczędności",))
    if avg_expense > 0:
        months_cover = (liquid + savings_like) / avg_expense
        if months_cover < 3:
            tips.append(Insight("warn", f"Poduszka finansowa: {months_cover:.1f} mies. wydatków (zalecane 3–6)."))
        else:
            tips.append(Insight("ok", f"Poduszka finansowa: {months_cover:.1f} mies. wydatków."))
        idle = sum(a["balance"] for a in accounts if a["kind"].code in ("checking", "ewallet", "cash"))
        has_rate = any(a["kind"].has_rate and float(a.get("interest_rate") or 0) > 0 for a in accounts)
        if idle > 3 * avg_expense and not has_rate:
            tips.append(Insight("info", "Dużo środków na nieoprocentowanych kontach — rozważ konto "
                                        "oszczędnościowe lub lokatę."))

    over = [e["name"] for e in get_envelope_overview(month) if e["over"]]
    if over:
        tips.append(Insight("warn", f"Przekroczone koperty: {', '.join(over[:4])}{'…' if len(over) > 4 else ''}."))

    for acc in accounts:
        proj = acc.get("projection")
        if proj and 0 <= proj["days_left"] <= 7 and not proj["matured"]:
            tips.append(Insight("info", f"{acc['name']} kończy się za {proj['days_left']} dni "
                                        f"(+{proj['net_interest']:.2f} zł netto)."))
        limit = float(acc.get("yearly_limit") or 0)
        if acc["kind"].retirement and limit > 0:
            used = acc.get("contributed_this_year", 0.0)
            if used < limit and date.today().month >= 10:
                tips.append(Insight("info", f"{acc['name']}: wykorzystano {used / limit * 100:.0f}% rocznego limitu."))

    if get_matured_deposits():
        tips.append(Insight("warn", "Są lokaty po terminie — odśwież (Ctrl+R), aby je rozliczyć."))
    due = check_due_payments_count()
    if due:
        tips.append(Insight("warn", f"Zaległe płatności cykliczne: {due}."))
    for g in goals_overview():
        if g.get("overdue"):
            tips.append(Insight("warn", f"Cel „{g['name']}” po terminie — brakuje {g['missing']:.2f} zł."))
        elif g.get("monthly_needed"):
            tips.append(Insight("info", f"Cel „{g['name']}”: odkładaj {g['monthly_needed']:.2f} zł/mies., "
                                        f"by zdążyć na czas."))
    if not tips:
        tips.append(Insight("info", "Dodaj transakcje i koperty, a doradca podpowie, co poprawić."))
    order = {"alert": 0, "warn": 1, "info": 2, "ok": 3}
    tips.sort(key=lambda t: order.get(t.level, 9))
    return tips


# =============================================================================
# Wyszukiwanie globalne
# =============================================================================

@dataclass
class SearchHit:
    kind: str  # transaction | account | envelope | goal | recurring
    ref: Any
    title: str
    detail: str


def search_everything(query: str, limit: int = 40) -> List[SearchHit]:
    from src.finance.accounts import get_all_accounts_data, kind_info
    from src.finance.envelopes import get_all_categories_data
    from src.finance.goals import get_all_piggy_banks
    from src.finance.ledger import describe_entry, fetch_transactions
    from src.finance.recurring import get_all_recurring

    q = (query or "").strip().lower()
    if not q:
        return []
    hits: List[SearchHit] = []

    def match(*values: Any) -> bool:
        return any(q in str(v or "").lower() for v in values)

    for acc in get_all_accounts_data():
        if match(acc["name"], acc["institution"], kind_info(acc["account_kind"]).label):
            hits.append(SearchHit("account", acc["name"], acc["name"],
                                  f"{kind_info(acc['account_kind']).label} · {float(acc['balance']):,.2f} zł"
                                  .replace(",", " ")))
    for cat in get_all_categories_data():
        if match(cat["name"], cat["ct_code"]):
            hits.append(SearchHit("envelope", cat["id"], cat["name"], f"Koperta · budżet {float(cat['limit_amount']):.2f}"))
    for goal in get_all_piggy_banks():
        if match(goal["name"], goal["pb_code"]):
            hits.append(SearchHit("goal", goal["id"], goal["name"],
                                  f"Cel · {float(goal['current_amount']):.2f} / {float(goal['target_amount']):.2f}"))
    for rec in get_all_recurring():
        if match(rec["name"], rec["rr_code"], rec["category"]):
            hits.append(SearchHit("recurring", rec["id"], rec["name"],
                                  f"Zlecenie · {rec['cycle']} · {float(rec['amount']):.2f}"))
    for row in fetch_transactions(search_text=q, limit=limit):
        e = describe_entry(row)
        hits.append(SearchHit("transaction", e["id"], e.get("shop") or e.get("description") or "—",
                              f"{e['date']} · {e['kind_label']} · {e['signed_amount']:+.2f} · {e['account_type']}"))
    return hits[:limit]


def group_by(items: List[Dict[str, Any]], key: str) -> Dict[Any, List[Dict[str, Any]]]:
    out: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        out[item.get(key)].append(item)
    return out
