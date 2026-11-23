from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.database import (
    get_active_month_str,
    get_all_categories_data,
    get_category_spending_map,
    get_monthly_balance,
)
from src.utils.smart_table import Col, SmartTable
from src.utils.ui_tools import GREEN, RED, money, progress_text


def _progress_cell(item, width: int) -> Text:
    return progress_text(item.get("pct"), width, is_savings=False)


class CategoriesView(Vertical):
    """
    Widok kategorii z budżetem na miesiąc roboczy.
    Pasek „Realizacja” rysuje się dokładnie w szerokości swojej kolumny,
    więc sam rośnie/maleje razem z oknem.
    """

    COLUMNS = [
        Col("ct_code", "Kod", 8, hide_priority=3),
        Col("name", "Kategoria", 8, max_width=24),
        Col("limit", "Limit", 8, align="right", hide_priority=2),
        Col("spent", "Wydano", 8, align="right"),
        Col("remaining", "Pozostało", 9, align="right", hide_priority=1),
        Col("progress", "Realizacja", 12, flex=1, render=_progress_cell),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="cat-header-panel", classes="view-header"):
            yield Label("BILANS MIESIĄCA", id="cat-header-title", classes="view-header-title")
            with Horizontal(classes="view-header-stats"):
                yield Label("PRZYCHODY:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-income", classes="stat-value income")
                yield Label("WYDATKI:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-expenses", classes="stat-value expense")
        yield SmartTable(self.COLUMNS, id="cat-smart-table", empty_text="brak kategorii — ^N dodaje nową")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#cat-smart-table", SmartTable).focus_table()

    def load_data(self) -> None:
        month = get_active_month_str()
        try:
            income, expenses = get_monthly_balance(month)
            self.query_one("#cat-header-title", Label).update(f"BILANS {month}")
            self.query_one("#lbl-income", Label).update(money(income))
            self.query_one("#lbl-expenses", Label).update(money(expenses))
        except Exception:
            pass

        spending = get_category_spending_map(month)
        processed = []
        for row in get_all_categories_data() or []:
            cat = dict(row)
            c_id = cat.get("id")
            name = cat.get("name") or ""
            limit = float(cat.get("limit_amount") or 0.0)
            spent = float(spending.get(name, 0.0))
            remaining = limit - spent
            pct = (spent / limit) * 100.0 if limit > 0 else None

            processed.append({
                "id": str(c_id),
                "ct_code": cat.get("ct_code") or (f"CT{int(c_id):06d}" if c_id is not None else ""),
                "name": name,
                "limit": money(limit, "") if limit > 0 else "—",
                "spent": money(spent, ""),
                "remaining": Text(money(remaining, ""), style=RED if remaining < 0 else GREEN)
                if limit > 0 else Text("—"),
                "clean_remaining": money(remaining, "") if limit > 0 else "—",
                "pct": pct,
            })

        self.query_one("#cat-smart-table", SmartTable).set_data(processed)

    refresh_table = load_data

    def get_selected_category_id(self):
        return self.query_one("#cat-smart-table", SmartTable).get_selected_id()
