from __future__ import annotations

from typing import Optional, Tuple, Dict, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label, Select


class PiggyBankFormView(VerticalScroll):
    """Formularz Skarbonki (Nazwa, Kwota celu, Konto domyślne)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.editing_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label("NOWY CEL", id="piggy-form-title", classes="form-header")

        with Horizontal(classes="form-row"):
            yield Label("Nazwa celu:", classes="row-label")
            yield Input(placeholder="np. Wakacje", id="piggy-input-name", classes="row-input")

        with Horizontal(classes="form-row"):
            yield Label("Kwota celu (PLN):", classes="row-label")
            yield Input(
                placeholder="0.00",
                id="piggy-input-target",
                classes="row-input",
                restrict=r"^[0-9.,]*$",
            )

        with Horizontal(classes="form-row"):
            yield Label("Konto domyślne:", classes="row-label")
            yield Select(
                [("Karta", "Karta"), ("Gotówka", "Gotówka")],
                value="Karta",
                id="piggy-input-account",
                allow_blank=False,
                classes="row-select",
            )

    def on_mount(self) -> None:
        """Focus od razu na nazwie."""
        try:
            self.query_one("#piggy-input-name", Input).focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API używane przez MainDashboard
    # ------------------------------------------------------------------

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#piggy-form-title", Label).update("NOWY CEL")

        self.query_one("#piggy-input-name", Input).value = ""
        self.query_one("#piggy-input-target", Input).value = ""
        self.query_one("#piggy-input-account", Select).value = "Karta"

        try:
            self.query_one("#piggy-input-name", Input).focus()
        except Exception:
            pass

    def load_existing_data(self, data) -> None:
        """Ładuje dane skarbonki do edycji (obsługuje sqlite3.Row i dict)."""
        d = dict(data)  # <<< KLUCZ: sqlite3.Row -> dict

        self.editing_id = int(d["id"])
        self.query_one("#piggy-form-title", Label).update(f"EDYCJA CELU (ID: {d['id']})")

        self.query_one("#piggy-input-name", Input).value = d.get("name", "") or ""
        self.query_one("#piggy-input-target", Input).value = f"{float(d.get('target_amount', 0.0) or 0.0):.2f}"

        acc = d.get("account_type") or "Karta"
        self.query_one("#piggy-input-account", Select).value = acc

        try:
            self.query_one("#piggy-input-name", Input).focus()
        except Exception:
            pass

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Zwraca (data, error)."""
        name = self.query_one("#piggy-input-name", Input).value.strip()
        raw_target = self.query_one("#piggy-input-target", Input).value.strip().replace(",", ".")

        if not name:
            return None, "Podaj nazwę celu!"

        if raw_target == "":
            return None, "Podaj kwotę celu!"

        try:
            target = float(raw_target)
        except ValueError:
            return None, "Błędna kwota!"

        # Jeśli chcesz dopuszczać 0.0 jako cel, usuń ten warunek
        if target <= 0:
            return None, "Kwota celu musi być większa od zera!"

        account = self.query_one("#piggy-input-account", Select).value

        return {"name": name, "target": target, "account": account}, None