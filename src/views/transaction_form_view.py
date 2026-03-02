from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Input, Select, Label, Checkbox

from src.database import get_unique_categories


class TransactionFormView(Container):
    """Formularz dodawania/edycji transakcji (Wydatek/Dochód) z kontem Karta/Gotówka."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.editing_id: Optional[int] = None

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form-scroll-container"):
            yield Label("NOWA TRANSAKCJA", id="form-title-label", classes="form-header")

            # --- 1) DATA ---
            with Horizontal(classes="form-row"):
                yield Label("Data:", classes="row-label")
                yield Input(placeholder="Puste = Dzisiaj", id="input-date", classes="row-input")

            # --- 2) RODZAJ ---
            with Horizontal(classes="form-row"):
                yield Label("Rodzaj:", classes="row-label")
                yield Select(
                    [("Wydatek", "Wydatek"), ("Dochód", "Dochód")],
                    value="Wydatek",
                    id="input-type",
                    allow_blank=False,
                    classes="row-select",
                )

            # --- 3) KONTO ---
            with Horizontal(classes="form-row"):
                yield Label("Konto:", classes="row-label")
                yield Select(
                    [("Karta", "Karta"), ("Gotówka", "Gotówka")],
                    value="Karta",
                    id="input-account",
                    allow_blank=False,
                    classes="row-select",
                )

            # --- 4) KWOTA ---
            with Horizontal(classes="form-row"):
                yield Label("Kwota (PLN):", classes="row-label")
                yield Input(
                    placeholder="0.00",
                    id="input-amount",
                    classes="row-input",
                    restrict=r"^[0-9.,]*$",
                )

            # --- 5) KATEGORIA ---
            with Horizontal(classes="form-row"):
                yield Label("Kategoria:", classes="row-label")
                # allow_blank=True -> możemy ustawić Select.BLANK bez błędów
                yield Select([], prompt="Wybierz...", id="input-category", classes="row-select", allow_blank=True)

            # --- 6) SKLEP/OPIS ---
            with Horizontal(classes="form-row"):
                yield Label("Sklep/Opis:", classes="row-label")
                yield Input(placeholder="...", id="input-shop", classes="row-input")

            # --- 7) NOTATKA (opis dodatkowy) ---
            with Horizontal(classes="form-row"):
                yield Label("Notatka:", classes="row-label")
                yield Input(placeholder="...", id="input-desc", classes="row-input")

            # --- 8) CHECKBOX ---
            with Horizontal(classes="form-row checkbox-row"):
                yield Label("", classes="row-label")
                yield Checkbox("Rejestrowana", id="input-registered", value=True)

    def on_mount(self) -> None:
        self._load_categories()

        # Fokus na dacie (lub kwocie, jeśli wolisz)
        try:
            self.query_one("#input-date", Input).focus()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def _load_categories(self) -> None:
        """Ładuje opcje kategorii do Select."""
        cats = get_unique_categories() or []
        if not cats:
            cats = ["Spożywcze", "Transport", "Opłaty", "Inne"]

        sel = self.query_one("#input-category", Select)
        sel.set_options([(c, c) for c in cats])

        # jeśli jeszcze nic nie wybrane, ustaw BLANK
        if sel.value in (None, Select.BLANK):
            sel.value = Select.BLANK

    def _ensure_category_exists(self, cat_value: str) -> None:
        """
        Jeśli w edycji transakcji kategoria z bazy nie istnieje już na liście,
        dodajemy ją tymczasowo do Selecta, żeby uniknąć "Illegal select value".
        """
        if not cat_value:
            return

        sel = self.query_one("#input-category", Select)
        # options to lista (label, value); nie zawsze jest łatwo odczytać,
        # więc najprościej spróbować ustawić wartość; jeśli się nie da -> dodaj opcję.
        try:
            sel.value = cat_value
        except Exception:
            # dodaj brakującą kategorię i ustaw
            try:
                current = [(opt[0], opt[1]) for opt in sel.options]  # type: ignore[attr-defined]
            except Exception:
                current = []
            current.append((cat_value, cat_value))
            sel.set_options(current)
            sel.value = cat_value

    # ---------------------------------------------------------------------
    # API używane przez MainDashboard
    # ---------------------------------------------------------------------

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#form-title-label", Label).update("NOWA TRANSAKCJA")

        self.query_one("#input-date", Input).value = ""
        self.query_one("#input-type", Select).value = "Wydatek"
        self.query_one("#input-account", Select).value = "Karta"
        self.query_one("#input-amount", Input).value = ""
        self.query_one("#input-shop", Input).value = ""
        self.query_one("#input-desc", Input).value = ""
        self.query_one("#input-registered", Checkbox).value = True

        # kategoria: wróć do BLANK
        try:
            self.query_one("#input-category", Select).value = Select.BLANK
        except Exception:
            pass

        # odśwież listę kategorii (na wypadek zmian w DB)
        self._load_categories()

    def load_existing_data(self, data) -> None:
        """Ładuje dane z bazy do formularza (edycja)."""
        data = dict(data)
        # ---------------------------------------------------

        self.editing_id = int(data["id"])
        self.query_one("#form-title-label", Label).update(f"EDYCJA TRANSAKCJI (ID: {data['id']})")

        self.query_one("#input-date", Input).value = str(data["date"])
        self.query_one("#input-type", Select).value = data["type"]

        # Konto (account_type) - teraz .get() zadziała poprawnie
        acc = data["account_type"] if data.get("account_type") else "Karta"
        self.query_one("#input-account", Select).value = acc

        # Kwota
        self.query_one("#input-amount", Input).value = f"{float(data['amount']):.2f}"

        # Kategorie: dla Dochodu może być pusta
        cat_val = data["category"] or ""
        self._load_categories()
        if cat_val:
            self._ensure_category_exists(cat_val)
        else:
            self.query_one("#input-category", Select).value = Select.BLANK

        self.query_one("#input-shop", Input).value = data["shop"] or ""
        # W bazie kolumna to "description"
        self.query_one("#input-desc", Input).value = data["description"] or ""
        self.query_one("#input-registered", Checkbox).value = True if data["is_registered"] else False

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Zwraca (data_dict, error_msg). Jeśli error_msg != None, to walidacja nie przeszła."""

        # 1) Data
        raw_date = self.query_one("#input-date", Input).value.strip()
        final_date = raw_date if raw_date else datetime.now().strftime("%Y-%m-%d")

        # Smart date: wpisanie tylko dnia ("12")
        if raw_date.isdigit() and len(raw_date) <= 2:
            now = datetime.now()
            try:
                day = int(raw_date)
                final_date = f"{now.year}-{now.month:02d}-{day:02d}"
            except Exception:
                pass

        # Minimalna walidacja formatu YYYY-MM-DD (żeby nie wpuścić śmieci)
        try:
            datetime.strptime(final_date, "%Y-%m-%d")
        except Exception:
            return None, "Błąd: Niepoprawna data! (format: YYYY-MM-DD lub sam dzień np. 12)"

        # 2) Kwota
        raw_amount = self.query_one("#input-amount", Input).value.strip().replace(",", ".")
        if raw_amount == "":
            return None, "Błąd: Podaj kwotę!"

        try:
            amount_float = float(raw_amount)
        except ValueError:
            return None, "Błąd: Niepoprawna kwota!"

        if amount_float <= 0:
            return None, "Błąd: Kwota musi być większa od zera!"

        # 3) Reszta pól
        t_type = self.query_one("#input-type", Select).value
        category_val = self.query_one("#input-category", Select).value
        shop = self.query_one("#input-shop", Input).value.strip()
        desc = self.query_one("#input-desc", Input).value.strip()
        account = self.query_one("#input-account", Select).value
        is_reg = self.query_one("#input-registered", Checkbox).value

        # 4) Kategoria
        final_category = category_val
        if t_type == "Wydatek":
            if category_val in (None, Select.BLANK):
                return None, "Wybierz Kategorię dla wydatku!"
        else:
            # Dochód -> kategoria opcjonalna
            if category_val in (None, Select.BLANK):
                final_category = ""

        # 5) Sklep/Opis wymagany (u Ciebie to ważne — zostawiam)
        if not shop:
            return None, "Wpisz sklep lub opis!"

        # OK
        return {
            "date": final_date,
            "type": t_type,
            "account": account,
            "category": final_category,
            "shop": shop,
            "amount": amount_float,
            "desc": desc,       # ważne: MainDashboard przekazuje to do database.add_transaction -> description
            "is_reg": is_reg,   # ważne: klucz oczekiwany w MainDashboard
        }, None