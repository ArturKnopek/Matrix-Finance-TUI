from __future__ import annotations

from datetime import date

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.database import get_all_piggy_banks, get_all_recurring, get_recurring_next_due
from src.utils.smart_table import Col, SmartTable
from src.utils.ui_tools import GREEN, RED, YELLOW, money

CYCLE_SHORT = {
    "Dziennie": "co dzień",
    "Tygodniowo": "co tydz.",
    "Miesięcznie": "co m-c",
    "Rocznie": "co rok",
}
# ile razy w miesiącu (średnio) wypada płatność danego cyklu
CYCLE_PER_MONTH = {"Dziennie": 30.44, "Tygodniowo": 4.345, "Miesięcznie": 1.0, "Rocznie": 1 / 12}


def describe_days(days: int) -> str:
    if days < 0:
        return "ZALEGŁE"
    if days == 0:
        return "DZIŚ"
    if days == 1:
        return "JUTRO"
    return f"za {days} dni"


class RecurringView(Vertical):
    """Lista płatności cyklicznych z datą najbliższej płatności liczoną przez silnik."""

    COLUMNS = [
        Col("rr_code", "Kod", 8, hide_priority=4),
        Col("name", "Nazwa", 12, max_width=28, flex=1),
        Col("amount", "Kwota", 9, align="right"),
        Col("type", "Typ", 7, max_width=12, hide_priority=2),
        Col("details", "Kategoria / cel", 10, max_width=24, hide_priority=3),
        Col("cycle", "Cykl", 6, hide_priority=1),
        Col("next", "Następna", 10),
        Col("status", "Status", 7),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="rec-header-panel", classes="view-header"):
            yield Label("PŁATNOŚCI CYKLICZNE", classes="view-header-title")
            with Horizontal(classes="view-header-stats"):
                yield Label("KOSZT / M-C:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-rec-monthly", classes="stat-value expense")
                yield Label("WPŁYWY / M-C:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-rec-income", classes="stat-value income")
        yield SmartTable(self.COLUMNS, id="rec-smart-table", empty_text="brak zleceń — ^N dodaje nowe")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#rec-smart-table", SmartTable).focus_table()

    def load_data(self) -> None:
        rows = get_all_recurring() or []
        piggy_codes = {
            int(p["id"]): (p["pb_code"] or f"PB{int(p['id']):06d}", p["name"]) for p in get_all_piggy_banks() or []
        }
        today = date.today()
        monthly_cost = 0.0
        monthly_income = 0.0
        processed = []

        for row in rows:
            r = dict(row)
            r_id = r.get("id")
            r_type = r.get("type") or ""
            amount = float(r.get("amount") or 0.0)
            cycle = r.get("cycle") or "Miesięcznie"
            active = int(r.get("is_registered") or 0) == 1

            if active:
                per_month = amount * CYCLE_PER_MONTH.get(cycle, 1.0)
                if r_type == "Dochód":
                    monthly_income += per_month
                else:
                    monthly_cost += per_month

            if r_type == "Na Skarbonkę":
                pig = piggy_codes.get(int(r.get("piggy_id") or 0))
                details = f"{pig[1]} ({pig[0]})" if pig else "cel: ---"
            else:
                details = r.get("category") or "---"

            nxt = get_recurring_next_due(r)
            days = (nxt - today).days if nxt else None
            if not active:
                status = Text("PAUZA", style="#777777")
            elif days is not None and days < 0:
                status = Text("ZALEGŁE", style=f"bold {RED}")
            else:
                status = Text("AKTYWNA", style=GREEN)

            color = RED if r_type == "Wydatek" else GREEN if r_type == "Dochód" else YELLOW
            amount_txt = money(amount, "")
            processed.append({
                "id": str(r_id),
                "rr_code": r.get("rr_code") or (f"RR{int(r_id):06d}" if r_id is not None else ""),
                "name": r.get("name") or "",
                "amount": Text(amount_txt, style=color),
                "clean_amount": amount_txt,
                "type": r_type,
                "details": details,
                "cycle": CYCLE_SHORT.get(cycle, cycle.lower()),
                "next": nxt.strftime("%Y-%m-%d") if nxt else "---",
                "status": status,
                "clean_status": status.plain,
            })

        self.query_one("#lbl-rec-monthly", Label).update(money(monthly_cost))
        self.query_one("#lbl-rec-income", Label).update(money(monthly_income))
        self.query_one("#rec-smart-table", SmartTable).set_data(processed)

    refresh_table = load_data

    def get_selected_recurring_id(self):
        return self.query_one("#rec-smart-table", SmartTable).get_selected_id()
