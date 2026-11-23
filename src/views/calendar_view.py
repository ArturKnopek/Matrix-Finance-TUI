"""Kalendarz: miesiąc z intensywnością wydatków, zleceniami i terminami lokat + szczegóły dnia."""

from __future__ import annotations

from datetime import date
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.finance.analytics import get_calendar_data
from src.finance.ledger import TRANSFER, describe_entry, get_transactions_for_day
from src.finance.storage import get_active_month_str
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import MonthCalendar, WidthClassesMixin, money
from src.views.base import ViewAction, ViewMixin

MONTHS_PL = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
             "październik", "listopad", "grudzień"]


class CalendarView(WidthClassesMixin, ViewMixin, Horizontal):
    TITLE = "KALENDARZ"
    NARROW_AT = 100
    COLUMNS = [
        Col("shop", "Opis", 8, max_width=30, flex=1),
        Col("category", "Koperta", 6, max_width=16, hide_priority=1),
        Col("amount", "Kwota", 9, align="right"),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWA W TYM DNIU", "NOWA"),
        ViewAction("prev_month", "[", "POPRZ. MIESIĄC", "◀"),
        ViewAction("next_month", "]", "NAST. MIESIĄC", "▶"),
        ViewAction("today", "D", "DZIŚ", "DZIŚ"),
    ]
    BINDINGS = [("d", "go_today", "Dziś")]

    def compose(self) -> ComposeResult:
        with Vertical(id="cal-left"):
            yield Label("", id="cal-title", classes="view-header")
            yield MonthCalendar(interactive=True, id="cal-main")
            yield Label("← → ↑ ↓ dzień · Enter / 2× klik — nowa transakcja · [ ] miesiąc · D dziś",
                        classes="view-hint")
        with Vertical(id="cal-right"):
            yield Label("", id="cal-day-title", classes="view-header")
            yield Label("", id="cal-day-summary", classes="cal-summary")
            yield SmartTable(self.COLUMNS, id="cal-day-table", empty_text="brak wpisów tego dnia")
            yield Label("", id="cal-day-planned", classes="cal-planned")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_primary)

    def focus_primary(self) -> None:
        self.query_one("#cal-main", MonthCalendar).focus()

    # ------------------------------------------------------------- akcje

    def do_new(self) -> None:
        from src.ui.forms import TransactionDialog

        day = self.query_one("#cal-main", MonthCalendar).selected_date
        self.open_dialog(TransactionDialog(preset_date=day.isoformat()))

    def do_prev_month(self) -> None:
        self.app.screen.action_shift_month(-1)  # type: ignore[attr-defined]

    def do_next_month(self) -> None:
        self.app.screen.action_shift_month(1)  # type: ignore[attr-defined]

    def do_today(self) -> None:
        self.action_go_today()

    def action_go_today(self) -> None:
        today = date.today()
        screen = self.app.screen
        if today.strftime("%Y-%m") != get_active_month_str():
            screen.action_set_month(today.strftime("%Y-%m"))  # type: ignore[attr-defined]
        cal = self.query_one("#cal-main", MonthCalendar)
        cal.selected = today.day
        self._show_day(today)

    def on_month_calendar_day_selected(self, event: MonthCalendar.DaySelected) -> None:
        self._show_day(event.day)

    def on_month_calendar_day_activated(self, event: MonthCalendar.DayActivated) -> None:
        self.do_new()

    def on_month_calendar_month_shift(self, event: MonthCalendar.MonthShift) -> None:
        self.app.screen.action_shift_month(event.delta)  # type: ignore[attr-defined]

    # ------------------------------------------------------------- dane

    def load_data(self) -> None:
        month = get_active_month_str()
        y, m = map(int, month.split("-"))
        self._data = get_calendar_data(month)
        cal = self.query_one("#cal-main", MonthCalendar)
        keep = cal.selected if (cal.year, cal.month) == (y, m) else None
        cal.set_month(month, self._data, keep)
        spent = sum(d.spent for d in self._data.values())
        income = sum(d.income for d in self._data.values())
        p = palette()
        title = Text(f"{MONTHS_PL[m - 1].upper()} {y}", style=f"bold {p.accent}")
        title.append(f"   wydano {money(spent)} · wpłynęło {money(income)}", style=p.muted)
        self.query_one("#cal-title", Label).update(title)
        self._show_day(cal.selected_date)

    def _show_day(self, day: date) -> None:
        p = palette()
        info = getattr(self, "_data", {}).get(day.day)
        self.query_one("#cal-day-title", Label).update(Text(f"{day:%d.%m.%Y}", style=f"bold {p.accent}"))
        rows = []
        for row in get_transactions_for_day(day.isoformat()):
            e = describe_entry(row)
            color = p.transfer if e["type"] == TRANSFER else p.negative if e["signed_amount"] < 0 else p.positive
            amount = money(e["signed_amount"], "", signed=True)
            rows.append({"id": str(e["id"]), "shop": e.get("shop") or e.get("description") or "—",
                         "category": e.get("category") or e["kind_label"],
                         "amount": Text(amount, style=color), "clean_amount": amount})
        self.query_one("#cal-day-table", SmartTable).set_data(rows)
        summary = Text()
        if info:
            summary.append("wydatki ", style=p.muted)
            summary.append(money(info.spent), style=f"bold {p.negative if info.spent else p.text}")
            summary.append("  wpływy ", style=p.muted)
            summary.append(money(info.income), style=f"bold {p.positive if info.income else p.text}")
        self.query_one("#cal-day-summary", Label).update(summary)
        planned = Text()
        if info and (info.planned or info.events):
            for item in info.planned:
                planned.append("• ", style=p.warning)
                planned.append(f"{item}\n", style=p.text)
            for item in info.events:
                planned.append("◆ ", style=p.info)
                planned.append(f"{item}\n", style=p.text)
        self.query_one("#cal-day-planned", Label).update(planned)

    def select_ref(self, ref: Any) -> None:
        pass
