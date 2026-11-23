from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Label

from src.utils.parsing import AMOUNT_RESTRICT, parse_amount
from src.views.transaction_form_view import FORM_HINT, form_row


class CategoryFormView(VerticalScroll):
    """Formularz dodawania/edycji kategorii (nazwa + miesięczny limit)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self.editing_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Label("NOWA KATEGORIA", id="cat-form-title", classes="form-header")
        yield form_row("Nazwa:", Input(placeholder="np. Jedzenie", id="cat-input-name", classes="row-input"))
        yield form_row("Limit / m-c (PLN):", Input(placeholder="0 = bez limitu", id="cat-input-limit",
                                                   classes="row-input", restrict=AMOUNT_RESTRICT))
        yield Label(FORM_HINT, classes="form-hint")

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#cat-form-title", Label).update("NOWA KATEGORIA")
        self.query_one("#cat-input-name", Input).value = ""
        self.query_one("#cat-input-limit", Input).value = ""

    def load_existing_data(self, data) -> None:
        data = dict(data)
        self.editing_id = int(data["id"])
        code = data.get("ct_code") or f"CT{self.editing_id:06d}"
        self.query_one("#cat-form-title", Label).update(f"EDYCJA KATEGORII {code}")
        self.query_one("#cat-input-name", Input).value = data.get("name") or ""
        self.query_one("#cat-input-limit", Input).value = f"{float(data.get('limit_amount') or 0.0):.2f}"

    def get_data_and_validate(self):
        name = self.query_one("#cat-input-name", Input).value.strip()
        raw_limit = self.query_one("#cat-input-limit", Input).value.strip()
        if not name:
            return None, "Podaj nazwę kategorii!"
        limit = 0.0 if raw_limit == "" else parse_amount(raw_limit)
        if limit is None:
            return None, "Błędny format limitu!"
        if limit < 0:
            return None, "Limit nie może być ujemny!"
        return {"name": name, "limit": limit}, None
