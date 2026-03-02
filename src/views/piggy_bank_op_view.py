from __future__ import annotations

from typing import Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Input, Select, Label, Checkbox


class PiggyBankOperationView(VerticalScroll):
    """Widok wpłaty / wypłaty ze skarbonki."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_piggy_id: Optional[str] = None
        self.target_piggy_name: str = ""
        self.operation_type: str = "deposit"  # "deposit" lub "withdraw"

        # Jeśli setup_operation zostanie wywołane przed renderem UI, trzymamy dane tutaj
        self._pending_setup: Optional[tuple[str, str, str]] = None

    def compose(self) -> ComposeResult:
        yield Label("OPERACJA FINANSOWA", id="pig-op-header", classes="form-header")

        # Cel (tylko do odczytu)
        with Horizontal(classes="form-row"):
            yield Label("Cel:", classes="row-label")
            yield Input(value="...", id="pig-op-target", classes="row-input", disabled=True)

        # Kwota
        with Horizontal(classes="form-row"):
            yield Label("Kwota (PLN):", classes="row-label")
            yield Input(
                placeholder="0.00",
                id="pig-op-amount",
                classes="row-input",
                restrict=r"^[0-9.,]*$",
            )

        # Konto źródłowe
        with Horizontal(classes="form-row"):
            yield Label("Konto:", classes="row-label")
            yield Select(
                [("Karta", "Karta"), ("Gotówka", "Gotówka")],
                value="Karta",
                id="pig-op-account",
                allow_blank=False,
                classes="row-select",
            )

        # Opcje (checkbox w szarym pasku)
        with Horizontal(classes="form-row"):
            yield Label("Opcje:", classes="row-label")
            with Container(classes="row-input", id="pig-chk-container"):
                yield Checkbox(
                    "Rejestruj w historii i saldzie",
                    value=True,
                    id="pig-op-registered",
                )

        yield Label("", classes="menu-spacer")

    def on_mount(self) -> None:
        # Fokus na kwotę
        try:
            self.query_one("#pig-op-amount", Input).focus()
        except Exception:
            pass

        # Jeśli setup_operation poszło zanim UI się narysował, zastosuj teraz
        if self._pending_setup:
            p_id, p_name, op_type = self._pending_setup
            self._pending_setup = None
            self._apply_setup(p_id, p_name, op_type)

    # ------------------------------------------------------------------
    # Public API (wywoływane z MainDashboard)
    # ------------------------------------------------------------------

    def setup_operation(self, p_id: str, p_name: str, op_type: str) -> None:
        """
        Ustawia kontekst operacji.
        Bezpieczne nawet jeśli zostanie wywołane przed renderem UI.
        """
        self.target_piggy_id = p_id
        self.target_piggy_name = p_name
        self.operation_type = op_type

        # jeśli UI już istnieje, zastosuj; jeśli nie, zapamiętaj
        self._pending_setup = (p_id, p_name, op_type)
        self.call_after_refresh(self._apply_setup, p_id, p_name, op_type)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_setup(self, p_id: str, p_name: str, op_type: str) -> None:
        """Ustawia tytuł, nazwę celu i resetuje pola."""
        title = "WPŁATA NA CEL" if op_type == "deposit" else "WYPŁATA Z CELU"

        try:
            self.query_one("#pig-op-header", Label).update(title)
            self.query_one("#pig-op-target", Input).value = p_name
            self.query_one("#pig-op-amount", Input).value = ""
            self.query_one("#pig-op-registered", Checkbox).value = True
            self.query_one("#pig-op-amount", Input).focus()
        except Exception:
            # jeśli UI jeszcze się nie zmontował, _pending_setup załatwi to w on_mount
            pass

    # ------------------------------------------------------------------
    # Data extraction / validation
    # ------------------------------------------------------------------

    def get_data(self) -> Tuple[Optional[float], Optional[str], Optional[bool]]:
        """Zwraca (kwota, konto, czy_rejestrować). Jeśli błąd, zwraca (None, None, None)."""
        try:
            raw_amt = self.query_one("#pig-op-amount", Input).value.strip().replace(",", ".")
            acc = self.query_one("#pig-op-account", Select).value
            is_reg = self.query_one("#pig-op-registered", Checkbox).value
        except Exception:
            return None, None, None

        if raw_amt == "":
            return None, None, None

        try:
            amount = float(raw_amt)
        except ValueError:
            return None, None, None

        # Kwota musi być dodatnia
        if amount <= 0:
            return None, None, None

        return amount, acc, is_reg