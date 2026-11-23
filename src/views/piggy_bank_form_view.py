from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Label, Select

from src.database import get_account_options
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount
from src.views.transaction_form_view import FORM_HINT, form_row


class PiggyBankFormView(VerticalScroll):
    """Formularz celu oszczędnościowego (nazwa, kwota celu, konto domyślne)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self.editing_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label("NOWY CEL", id="piggy-form-title", classes="form-header")
        yield form_row("Nazwa celu:", Input(placeholder="np. Wakacje", id="piggy-input-name", classes="row-input"))
        yield form_row("Kwota celu (PLN):", Input(placeholder="0.00", id="piggy-input-target", classes="row-input",
                                                  restrict=AMOUNT_RESTRICT))
        yield form_row("Konto domyślne:", Select([], prompt="Wybierz konto...", id="piggy-input-account",
                                                 allow_blank=True, classes="row-select"))
        yield Label(FORM_HINT, classes="form-hint")

    def on_mount(self) -> None:
        self._load_accounts()

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#piggy-form-title", Label).update("NOWY CEL")
        self.query_one("#piggy-input-name", Input).value = ""
        self.query_one("#piggy-input-target", Input).value = ""
        self._load_accounts()

    def load_existing_data(self, data) -> None:
        d = dict(data)
        self.editing_id = int(d["id"])
        code = d.get("pb_code") or f"PB{self.editing_id:06d}"
        self.query_one("#piggy-form-title", Label).update(f"EDYCJA CELU {code}")
        self.query_one("#piggy-input-name", Input).value = d.get("name") or ""
        self.query_one("#piggy-input-target", Input).value = f"{float(d.get('target_amount') or 0.0):.2f}"
        self._load_accounts(keep=d.get("account_type") or "Karta")

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        name = self.query_one("#piggy-input-name", Input).value.strip()
        if not name:
            return None, "Podaj nazwę celu!"
        target = parse_amount(self.query_one("#piggy-input-target", Input).value)
        if target is None:
            return None, "Podaj poprawną kwotę celu!"
        if target <= 0:
            return None, "Kwota celu musi być większa od zera!"
        account = self.query_one("#piggy-input-account", Select).value
        if account in (None, Select.BLANK):
            return None, "Wybierz konto!"
        return {"name": name, "target": target, "account": account}, None

    def _load_accounts(self, keep: Optional[str] = None) -> None:
        sel = self.query_one("#piggy-input-account", Select)
        options = list(get_account_options() or [("Karta", "Karta"), ("Gotówka", "Gotówka")])
        if keep and keep not in {v for _, v in options}:
            options.append((keep, keep))
        sel.set_options(options)
        sel.value = keep or options[0][1]
