from __future__ import annotations

from typing import Optional, Tuple

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Checkbox, Input, Label, Select

from src.database import get_account_balance, get_account_options, get_piggy_bank_by_id
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount
from src.utils.ui_tools import money
from src.views.transaction_form_view import FORM_HINT, form_row


class PiggyBankOperationView(VerticalScroll):
    """Wpłata na cel / wypłata z celu."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self.target_piggy_id: Optional[str] = None
        self.target_piggy_name: str = ""
        self.operation_type: str = "deposit"  # "deposit" | "withdraw"

    def compose(self) -> ComposeResult:
        yield Label("OPERACJA FINANSOWA", id="pig-op-header", classes="form-header")
        yield form_row("Cel:", Label("...", id="pig-op-target", classes="row-value"))
        yield form_row("Stan celu:", Label("...", id="pig-op-state", classes="row-value"))
        yield form_row("Kwota (PLN):", Input(placeholder="0.00", id="pig-op-amount", classes="row-input",
                                             restrict=AMOUNT_RESTRICT))
        yield form_row("Konto:", Select([], prompt="Wybierz konto...", id="pig-op-account", allow_blank=True,
                                        classes="row-select"))
        yield form_row("Saldo konta:", Label("...", id="pig-op-balance", classes="row-value"))
        yield form_row("", Checkbox("Zapisz w historii transakcji", value=True, id="pig-op-registered"),
                       classes="checkbox-row")
        yield Label(FORM_HINT, classes="form-hint")

    def on_mount(self) -> None:
        self._load_accounts()

    def setup_operation(self, p_id: str, p_name: str, op_type: str) -> None:
        self.target_piggy_id = p_id
        self.target_piggy_name = p_name
        self.operation_type = op_type

        piggy = get_piggy_bank_by_id(int(p_id)) if p_id else None
        self.query_one("#pig-op-header", Label).update("WPŁATA NA CEL" if op_type == "deposit" else "WYPŁATA Z CELU")
        self.query_one("#pig-op-target", Label).update(p_name)
        if piggy:
            cur = float(piggy["current_amount"] or 0.0)
            tgt = float(piggy["target_amount"] or 0.0)
            self.query_one("#pig-op-state", Label).update(f"{money(cur)} / {money(tgt)}")
        self.query_one("#pig-op-amount", Input).value = ""
        self.query_one("#pig-op-registered", Checkbox).value = True
        self._load_accounts(prefer=piggy["account_type"] if piggy else None)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "pig-op-account":
            self._update_balance_label()

    def _update_balance_label(self) -> None:
        acc = self.query_one("#pig-op-account", Select).value
        text = money(get_account_balance(acc)) if acc not in (None, Select.BLANK) else "—"
        self.query_one("#pig-op-balance", Label).update(text)

    def get_data(self) -> Tuple[Optional[float], Optional[str], Optional[bool]]:
        amount = parse_amount(self.query_one("#pig-op-amount", Input).value)
        acc = self.query_one("#pig-op-account", Select).value
        is_reg = self.query_one("#pig-op-registered", Checkbox).value
        if amount is None or amount <= 0 or acc in (None, Select.BLANK):
            return None, None, None
        return amount, acc, is_reg

    def _load_accounts(self, prefer: Optional[str] = None) -> None:
        sel = self.query_one("#pig-op-account", Select)
        options = list(get_account_options() or [("Karta", "Karta"), ("Gotówka", "Gotówka")])
        sel.set_options(options)
        values = [v for _, v in options]
        sel.value = prefer if prefer in values else values[0]
        self._update_balance_label()
