from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll, Container
from textual.widgets import Input, Select, Label, Checkbox

from src.database import get_unique_categories, get_all_piggy_banks


class RecurringFormView(VerticalScroll):
    """Formularz definicji płatności cyklicznej (Wydatek / Dochód / Na Skarbonkę)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.editing_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label("NOWA PŁATNOŚĆ CYKLICZNA", id="rec-form-title", classes="form-header")

        # 1) RODZAJ
        with Horizontal(classes="form-row"):
            yield Label("Rodzaj:", classes="row-label")
            yield Select(
                [
                    ("Wydatek", "Wydatek"),
                    ("Dochód", "Dochód"),
                    ("Na Skarbonkę", "Na Skarbonkę"),
                ],
                value="Wydatek",
                id="rec-input-type",
                allow_blank=False,
                classes="row-select",
            )

        # 2) NAZWA
        with Horizontal(classes="form-row"):
            yield Label("Nazwa:", classes="row-label")
            yield Input(placeholder="np. Netflix", id="rec-input-name", classes="row-input")

        # 3) KWOTA
        with Horizontal(classes="form-row"):
            yield Label("Kwota (PLN):", classes="row-label")
            yield Input(
                placeholder="0.00",
                id="rec-input-amount",
                classes="row-input",
                restrict=r"^[0-9.,]*$",
            )

        # 4) KATEGORIA (dla Wydatek/Dochód)
        with Horizontal(classes="form-row", id="row-category"):
            yield Label("Kategoria:", classes="row-label")
            yield Select(
                [],
                prompt="Wybierz...",
                id="rec-input-category",
                classes="row-select",
                allow_blank=True,
            )

        # 5) SKARBONKA (dla Na Skarbonkę)
        with Horizontal(classes="form-row", id="row-piggy"):
            yield Label("Cel:", classes="row-label")
            yield Select(
                [],
                prompt="Wybierz cel...",
                id="rec-input-piggy",
                classes="row-select",
                allow_blank=True,
            )

        # 6) KONTO
        with Horizontal(classes="form-row"):
            yield Label("Z konta:", classes="row-label")
            yield Select(
                [("Karta", "Karta"), ("Gotówka", "Gotówka")],
                value="Karta",
                id="rec-input-account",
                allow_blank=False,
                classes="row-select",
            )

        # 7) CYKL
        with Horizontal(classes="form-row"):
            yield Label("Cykl:", classes="row-label")
            yield Select(
                [
                    ("Dziennie", "Dziennie"),
                    ("Tygodniowo", "Tygodniowo"),
                    ("Miesięcznie", "Miesięcznie"),
                    ("Rocznie", "Rocznie"),
                ],
                value="Miesięcznie",
                id="rec-input-cycle",
                classes="row-select",
                allow_blank=False,
            )

        # 8) DATA STARTU
        with Horizontal(classes="form-row"):
            yield Label("Pierwsza płatność:", classes="row-label")
            yield Input(
                value=datetime.now().strftime("%Y-%m-%d"),
                id="rec-input-date",
                classes="row-input",
            )

        # 9) REJESTROWANA (szary pasek)
        with Horizontal(classes="form-row"):
            yield Label("Opcje:", classes="row-label")
            with Container(classes="row-input", id="rec-chk-container"):
                yield Checkbox("Rejestrowana", value=True, id="rec-input-registered")

    def on_mount(self) -> None:
        # Układ startowy: domyślnie kategoria widoczna, skarbonka ukryta
        self._set_type_visibility("Wydatek")

        # Załaduj opcje (kategorie i skarbonki) po renderze
        self.refresh_options()

        # Fokus na nazwie
        try:
            self.query_one("#rec-input-name", Input).focus()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Widoczność pól zależnie od rodzaju
    # ---------------------------------------------------------------------

    def _set_type_visibility(self, r_type: str) -> None:
        """Pokazuje/ukrywa wiersze kategorii i skarbonki."""
        show_piggy = (r_type == "Na Skarbonkę")

        try:
            self.query_one("#row-category").styles.display = "none" if show_piggy else "block"
            self.query_one("#row-piggy").styles.display = "block" if show_piggy else "none"
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "rec-input-type":
            r_type = event.value
            self._set_type_visibility(r_type)

            # Drobny UX: czyścimy nieużywane pole
            try:
                if r_type == "Na Skarbonkę":
                    self.query_one("#rec-input-category", Select).value = Select.BLANK
                else:
                    self.query_one("#rec-input-piggy", Select).value = Select.BLANK
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # API używane przez MainDashboard
    # ---------------------------------------------------------------------

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#rec-form-title", Label).update("NOWA PŁATNOŚĆ CYKLICZNA")

        self.query_one("#rec-input-type", Select).value = "Wydatek"
        self.query_one("#rec-input-name", Input).value = ""
        self.query_one("#rec-input-amount", Input).value = ""
        self.query_one("#rec-input-account", Select).value = "Karta"
        self.query_one("#rec-input-cycle", Select).value = "Miesięcznie"
        self.query_one("#rec-input-date", Input).value = datetime.now().strftime("%Y-%m-%d")
        self.query_one("#rec-input-registered", Checkbox).value = True

        # reset pól wyboru
        try:
            self.query_one("#rec-input-category", Select).value = Select.BLANK
            self.query_one("#rec-input-piggy", Select).value = Select.BLANK
        except Exception:
            pass

        # widoczność zgodna z typem
        self._set_type_visibility("Wydatek")

        # odśwież opcje (na wypadek zmian w DB)
        self.refresh_options()

        try:
            self.query_one("#rec-input-name", Input).focus()
        except Exception:
            pass

    def refresh_options(self) -> None:
        """Odświeża listy kategorii i skarbonek."""
        # Kategorie
        cats = get_unique_categories() or []
        c_sel = self.query_one("#rec-input-category", Select)
        c_sel.set_options([(c, c) for c in cats])

        # Skarbonki
        pigs = get_all_piggy_banks() or []
        p_sel = self.query_one("#rec-input-piggy", Select)
        p_sel.set_options([(p["name"], str(p["id"])) for p in pigs])

        # Jeśli nic nie wybrane, ustaw BLANK
        if c_sel.value in (None, Select.BLANK):
            c_sel.value = Select.BLANK
        if p_sel.value in (None, Select.BLANK):
            p_sel.value = Select.BLANK

    def load_existing_data(self, data) -> None:
        """Ładuje dane do edycji."""
        self.refresh_options()

        d = dict(data)  # sqlite3.Row -> dict
        self.editing_id = int(d["id"])
        self.query_one("#rec-form-title", Label).update(f"EDYCJA (ID: {d['id']})")

        r_type = d.get("type", "Wydatek")
        self.query_one("#rec-input-type", Select).value = r_type
        self._set_type_visibility(r_type)

        self.query_one("#rec-input-name", Input).value = d.get("name", "") or ""
        self.query_one("#rec-input-amount", Input).value = f"{float(d.get('amount', 0.0) or 0.0):.2f}"

        # Konto
        acc = d.get("account_type") or "Karta"
        self.query_one("#rec-input-account", Select).value = acc

        # Cykl + data
        self.query_one("#rec-input-cycle", Select).value = d.get("cycle") or "Miesięcznie"
        self.query_one("#rec-input-date", Input).value = d.get("start_date") or datetime.now().strftime("%Y-%m-%d")

        # Rejestrowana
        self.query_one("#rec-input-registered", Checkbox).value = True if d.get("is_registered") else False

        # Pola zależne od typu
        if r_type == "Na Skarbonkę":
            piggy_id = d.get("piggy_id")
            self.query_one("#rec-input-piggy", Select).value = str(piggy_id) if piggy_id else Select.BLANK
            self.query_one("#rec-input-category", Select).value = Select.BLANK
        else:
            cat = d.get("category") or ""
            self.query_one("#rec-input-category", Select).value = cat if cat else Select.BLANK
            self.query_one("#rec-input-piggy", Select).value = Select.BLANK

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Zwraca (data, error)."""
        name = self.query_one("#rec-input-name", Input).value.strip()
        raw_amt = self.query_one("#rec-input-amount", Input).value.strip().replace(",", ".")
        r_type = self.query_one("#rec-input-type", Select).value
        date_str = self.query_one("#rec-input-date", Input).value.strip()

        if not name:
            return None, "Podaj nazwę!"

        if raw_amt == "":
            return None, "Podaj kwotę!"

        try:
            amount = float(raw_amt)
        except ValueError:
            return None, "Błędna kwota!"

        if amount <= 0:
            return None, "Kwota musi być większa od zera!"

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return None, "Format daty: YYYY-MM-DD"

        cat: Optional[str] = None
        piggy_id: Optional[int] = None

        if r_type == "Na Skarbonkę":
            raw_pig = self.query_one("#rec-input-piggy", Select).value
            if not raw_pig or raw_pig == Select.BLANK:
                return None, "Wybierz skarbonkę docelową!"
            piggy_id = int(raw_pig)
            cat = "Oszczędności"
        else:
            raw_cat = self.query_one("#rec-input-category", Select).value
            if r_type == "Wydatek" and (not raw_cat or raw_cat == Select.BLANK):
                return None, "Wybierz kategorię!"
            cat = "" if raw_cat == Select.BLANK else raw_cat

        return {
            "name": name,
            "amount": amount,
            "type": r_type,
            "category": cat,
            "account": self.query_one("#rec-input-account", Select).value,
            "cycle": self.query_one("#rec-input-cycle", Select).value,
            "start_date": date_str,
            "is_registered": self.query_one("#rec-input-registered", Checkbox).value,
            "piggy_id": piggy_id,
        }, None