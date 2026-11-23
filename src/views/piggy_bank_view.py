from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.database import get_all_piggy_banks
from src.utils.smart_table import Col, SmartTable
from src.utils.ui_tools import money, progress_text


def _progress_cell(item, width: int):
    return progress_text(item.get("pct"), width, is_savings=True)


class PiggyBankView(Vertical):
    """Widok celów oszczędnościowych (skarbonek) z samoskalującym się paskiem postępu."""

    COLUMNS = [
        Col("pb_code", "Kod", 8, hide_priority=3),
        Col("name", "Cel", 6, max_width=24),
        Col("account", "Konto", 5, max_width=14, hide_priority=2),
        Col("collected", "Uzbierano", 9, align="right"),
        Col("target", "Cel (PLN)", 9, align="right", hide_priority=4),
        Col("remaining", "Brakuje", 8, align="right", hide_priority=1),
        Col("progress", "Postęp", 12, flex=1, render=_progress_cell),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="piggy-header-panel", classes="view-header"):
            yield Label("STATUS OSZCZĘDZANIA", classes="view-header-title")
            with Horizontal(classes="view-header-stats"):
                yield Label("UZBIERANO:", classes="stat-label")
                yield Label("0.00 / 0.00 PLN", id="lbl-piggy-total", classes="stat-value savings")
        yield SmartTable(self.COLUMNS, id="piggy-smart-table", empty_text="brak celów — ^N dodaje nowy")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#piggy-smart-table", SmartTable).focus_table()

    def load_data(self) -> None:
        data = get_all_piggy_banks() or []
        total_collected = sum(float(d["current_amount"] or 0.0) for d in data)
        total_target = sum(float(d["target_amount"] or 0.0) for d in data)
        self.query_one("#lbl-piggy-total", Label).update(
            f"{money(total_collected, '')} / {money(total_target)}"
        )

        processed = []
        for pig in data:
            p = dict(pig)
            p_id = p.get("id")
            target = float(p.get("target_amount") or 0.0)
            current = float(p.get("current_amount") or 0.0)
            processed.append({
                "id": str(p_id),
                "pb_code": p.get("pb_code") or (f"PB{int(p_id):06d}" if p_id is not None else ""),
                "name": p.get("name") or "",
                "account": p.get("account_type") or "Karta",
                "collected": money(current, ""),
                "target": money(target, ""),
                "remaining": money(max(0.0, target - current), ""),
                "pct": (current / target) * 100.0 if target > 0 else 0.0,
            })

        self.query_one("#piggy-smart-table", SmartTable).set_data(processed)

    refresh_table = load_data

    def get_selected_piggy_id(self):
        return self.query_one("#piggy-smart-table", SmartTable).get_selected_id()
