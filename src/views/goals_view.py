"""Cele oszczędnościowe (koperty oszczędnościowe) z terminem i planem miesięcznym."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.finance.goals import delete_piggy_bank, get_piggy_bank_by_id, get_piggy_total, goals_overview
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import meter_text, money
from src.views.base import ViewAction, ViewMixin


def _progress_cell(item: Any, width: int) -> Text:
    return meter_text(item.get("pct"), width, "goal")


class GoalsView(ViewMixin, Vertical):
    TITLE = "CELE OSZCZĘDNOŚCIOWE"
    COLUMNS = [
        Col("name", "Cel", 8, max_width=24),
        Col("account", "Konto", 5, max_width=14, hide_priority=3),
        Col("current", "Uzbierano", 9, align="right"),
        Col("target", "Cel", 9, align="right", hide_priority=2),
        Col("deadline", "Termin", 7, hide_priority=4),
        Col("plan", "Plan", 10, max_width=22, hide_priority=1),
        Col("progress", "Postęp", 12, flex=1, render=_progress_cell),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWY CEL", "NOWY"),
        ViewAction("edit", "^E", "EDYTUJ", "EDYT."),
        ViewAction("deposit", "+", "WPŁAĆ", "WPŁ."),
        ViewAction("withdraw", "-", "WYPŁAĆ", "WYP."),
        ViewAction("delete", "^D", "USUŃ", "USUŃ"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="goals-header", classes="view-header"):
            yield Label("OSZCZĘDZANIE NA CELE", classes="view-header-title")
            yield Label("", id="goals-stats", classes="view-header-stats")
        yield SmartTable(self.COLUMNS, id="goals-table", empty_text="brak celów — ^N dodaje nowy")
        yield Label("Wpłaty na cel to przeniesienie pieniędzy (nie wydatek). Auto-oszczędzanie: zakładka 4 → A.",
                    classes="view-hint")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#goals-table", SmartTable).focus_table()

    def select_ref(self, ref: Any) -> None:
        self.query_one("#goals-table", SmartTable).select_id(ref)

    def _selected(self):
        g_id = self.query_one("#goals-table", SmartTable).get_selected_id()
        return get_piggy_bank_by_id(int(g_id)) if g_id else None

    def do_new(self) -> None:
        from src.ui.forms import GoalDialog

        self.open_dialog(GoalDialog())

    def do_edit(self) -> None:
        from src.ui.forms import GoalDialog

        row = self._selected()
        self.open_dialog(GoalDialog(row)) if row else self.warn_select("cel")

    def _operation(self, op: str) -> None:
        from src.ui.forms import GoalOperationDialog

        row = self._selected()
        self.open_dialog(GoalOperationDialog(int(row["id"]), op)) if row else self.warn_select("cel")

    def do_deposit(self) -> None:
        self._operation("deposit")

    def do_withdraw(self) -> None:
        self._operation("withdraw")

    def do_delete(self) -> None:
        row = self._selected()
        if not row:
            return self.warn_select("cel")
        current = float(row["current_amount"] or 0)
        extra = f"\n{money(current)} wróci na konto {row['account_type']}." if current > 0 else ""

        def delete() -> str:
            refunded = delete_piggy_bank(int(row["id"]))
            return f"Usunięto cel {row['name']}." + (f" Zwrócono {money(refunded)}." if refunded else "")

        self.confirm(f"Usunąć cel „{row['name']}”?{extra}", delete)

    def load_data(self) -> None:
        p = palette()
        rows = []
        target_total = 0.0
        for g in goals_overview():
            target = float(g.get("target_amount") or 0.0)
            target_total += target
            plan = ""
            if g.get("monthly_needed"):
                plan = f"{money(g['monthly_needed'], '')} / mies."
            elif g["pct"] >= 100:
                plan = "osiągnięty ✔"
            deadline = g.get("deadline")
            rows.append({
                "id": str(g["id"]),
                "name": g["name"],
                "account": g.get("account_type") or "",
                "current": Text(money(float(g.get("current_amount") or 0), ""), style=f"bold {p.info}"),
                "clean_current": money(float(g.get("current_amount") or 0), ""),
                "target": money(target, ""),
                "deadline": Text(deadline.strftime("%m.%Y"), style=p.negative if g.get("overdue") else p.text)
                if deadline else "—",
                "clean_deadline": deadline.strftime("%m.%Y") if deadline else "—",
                "plan": plan,
                "pct": g["pct"],
            })
        self.query_one("#goals-table", SmartTable).set_data(rows)
        stats = Text()
        stats.append("uzbierano ", style=p.muted)
        stats.append(money(get_piggy_total(), ""), style=f"bold {p.info}")
        stats.append(f" / {money(target_total)}", style=p.muted)
        self.query_one("#goals-stats", Label).update(stats)
