from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label


class CategoryFormView(VerticalScroll):
    """Formularz dodawania/edycji kategorii (nazwa + limit)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.editing_id: int | None = None

    def compose(self) -> ComposeResult:
        # Uwaga: ten widok jest w ContentSwitcher, więc VerticalScroll jako root
        # ułatwia przewijanie na małych terminalach.
        yield Label("NOWA KATEGORIA", id="cat-form-title", classes="form-header")

        # --- WIERSZ 1: NAZWA ---
        with Horizontal(classes="form-row"):
            yield Label("Nazwa:", classes="row-label")
            yield Input(placeholder="np. Jedzenie", id="cat-input-name", classes="row-input")

        # --- WIERSZ 2: LIMIT ---
        with Horizontal(classes="form-row"):
            yield Label("Limit (PLN):", classes="row-label")
            yield Input(
                placeholder="0.00",
                id="cat-input-limit",
                classes="row-input",
                restrict=r"^[0-9.,]*$",
            )

    def on_mount(self) -> None:
        """Ustaw focus na nazwie, żeby nie trzeba było klikać myszą."""
        try:
            self.query_one("#cat-input-name", Input).focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API używane przez MainDashboard
    # ------------------------------------------------------------------

    def reset_form(self) -> None:
        """Czyści formularz (tryb: nowa kategoria)."""
        self.editing_id = None
        self.query_one("#cat-form-title", Label).update("NOWA KATEGORIA")
        self.query_one("#cat-input-name", Input).value = ""
        self.query_one("#cat-input-limit", Input).value = ""

        # Fokus na nazwie
        try:
            self.query_one("#cat-input-name", Input).focus()
        except Exception:
            pass

    def load_existing_data(self, data) -> None:
        """Ładuje dane do edycji."""
        data = dict(data)
        self.editing_id = int(data["id"])
        self.query_one("#cat-form-title", Label).update(f"EDYCJA KATEGORII (ID: {data['id']})")

        self.query_one("#cat-input-name", Input).value = data["name"] or ""
        self.query_one("#cat-input-limit", Input).value = f"{float(data['limit_amount'] or 0.0):.2f}"

        # Fokus na nazwie (albo na limicie – jak wolisz)
        try:
            self.query_one("#cat-input-name", Input).focus()
        except Exception:
            pass

    def get_data_and_validate(self):
        """Zwraca (data_dict, error)."""
        name = self.query_one("#cat-input-name", Input).value.strip()
        raw_limit = self.query_one("#cat-input-limit", Input).value.strip().replace(",", ".")

        if not name:
            return None, "Podaj nazwę kategorii!"

        # limit może być pusty -> 0.0
        if raw_limit == "":
            limit = 0.0
        else:
            try:
                limit = float(raw_limit)
            except ValueError:
                return None, "Błędny format limitu!"

        # dodatkowa walidacja: limit nie może być ujemny
        if limit < 0:
            return None, "Limit nie może być ujemny!"

        return {"name": name, "limit": limit}, None