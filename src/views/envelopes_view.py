"""Koperty — budżet miesięczny (metoda kopertowa) z kopertami elastycznymi (przenoszenie reszty)."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.finance.envelopes import delete_category, get_budget_summary, get_category_by_id, get_envelope_overview
from src.finance.storage import get_active_month_str
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import meter_text, money
from src.views.base import ViewAction, ViewMixin


def _usage_cell(item: Any, width: int) -> Text:
    return meter_text(item.get("pct"), width, "budget")


class EnvelopesView(ViewMixin, Vertical):
    TITLE = "KOPERTY — BUDŻET MIESIĄCA"
    COLUMNS = [
        Col("name", "Koperta", 8, max_width=24),
        Col("budget", "Budżet", 8, align="right", hide_priority=2),
        Col("carried", "Z poprz. m-ca", 8, align="right", hide_priority=3),
        Col("adjustment", "Korekty", 8, align="right", hide_priority=4),
        Col("available", "Dostępne", 9, align="right", hide_priority=1),
        Col("spent", "Wydano", 8, align="right"),
        Col("remaining", "Zostało", 9, align="right"),
        Col("usage", "Wykorzystanie", 12, flex=1, render=_usage_cell),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWA KOPERTA", "NOWA"),
        ViewAction("edit", "^E", "EDYTUJ", "EDYT."),
        ViewAction("delete", "^D", "USUŃ", "USUŃ"),
        ViewAction("spend", "+", "WYDATEK Z KOPERTY", "WYDATEK"),
        ViewAction("adjust", "K", "KOREKTA", "KOREKTA"),
        ViewAction("move", "M", "PRZESUŃ ŚRODKI", "PRZES."),
    ]
    BINDINGS = [("k", "view_action('adjust')", "Korekta"), ("m", "view_action('move')", "Przesuń")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="env-header", classes="view-header"):
            yield Label("", id="env-title", classes="view-header-title")
            yield Label("", id="env-stats", classes="view-header-stats")
        yield SmartTable(self.COLUMNS, id="env-table", empty_text="brak kopert — ^N dodaje nową")
        yield Label("↻ = koperta elastyczna (reszta przechodzi na kolejny miesiąc) · K — korekta stanu · "
                    "M — przesuń środki do innej koperty", classes="view-hint")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#env-table", SmartTable).focus_table()

    def select_ref(self, ref: Any) -> None:
        self.query_one("#env-table", SmartTable).select_id(ref)

    def _selected(self):
        c_id = self.query_one("#env-table", SmartTable).get_selected_id()
        return get_category_by_id(int(c_id)) if c_id else None

    def do_new(self) -> None:
        from src.ui.forms import EnvelopeDialog

        self.open_dialog(EnvelopeDialog())

    def do_edit(self) -> None:
        from src.ui.forms import EnvelopeDialog

        row = self._selected()
        self.open_dialog(EnvelopeDialog(row)) if row else self.warn_select("kopertę")

    def do_delete(self) -> None:
        row = self._selected()
        if not row:
            return self.warn_select("kopertę")
        self.confirm(f"Usunąć kopertę „{row['name']}”?\nTransakcje zostaną bez koperty.",
                     lambda: (delete_category(int(row["id"])), f"Usunięto kopertę {row['name']}.")[1])

    def _adjust(self, mode: str) -> None:
        from src.ui.forms import EnvelopeAdjustDialog

        row = self._selected()
        if not row:
            return self.warn_select("kopertę")
        self.open_dialog(EnvelopeAdjustDialog(int(row["id"]), mode))

    def do_adjust(self) -> None:
        self._adjust("set")

    def do_move(self) -> None:
        self._adjust("move")

    def do_spend(self) -> None:
        from src.ui.forms import TransactionDialog

        row = self._selected()
        self.open_dialog(TransactionDialog(preset_category=row["name"] if row else None))

    def load_data(self) -> None:
        p = palette()
        month = get_active_month_str()
        summary = get_budget_summary(month)
        rows = []
        for e in get_envelope_overview(month):
            remaining_style = p.negative if e["remaining"] < 0 else p.positive if e["available"] > 0 else p.muted
            rows.append({
                "id": str(e["id"]),
                "name": ("↻ " if e["rollover"] else "") + e["name"],
                "budget": money(e["budget"], "") if e["budget"] else "—",
                "carried": money(e["carried"], "") if e["carried"] else "—",
                "adjustment": money(e["adjustment"], "", signed=True) if e["adjustment"] else "—",
                "available": money(e["available"], "") if e["available"] else "—",
                "spent": money(e["spent"], ""),
                "remaining": Text(money(e["remaining"], ""), style=remaining_style),
                "clean_remaining": money(e["remaining"], ""),
                "pct": e["pct"],
            })
        self.query_one("#env-table", SmartTable).set_data(rows)
        self.query_one("#env-title", Label).update(f"BUDŻET {month}")
        stats = Text()
        stats.append("przychody ", style=p.muted)
        stats.append(money(summary["income"], ""), style=f"bold {p.positive}")
        stats.append("  przydzielono ", style=p.muted)
        stats.append(money(summary["budgeted"], ""), style=f"bold {p.text}")
        stats.append("  do rozdysponowania ", style=p.muted)
        stats.append(money(summary["unallocated"], ""),
                     style=f"bold {p.positive if summary['unallocated'] >= 0 else p.negative}")
        self.query_one("#env-stats", Label).update(stats)
