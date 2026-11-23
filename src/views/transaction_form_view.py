from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Checkbox, Input, Label, Select

from src.database import get_account_options, get_active_month_str, get_unique_categories
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount, parse_user_date

FORM_HINT = "Enter / ^S — zapisz   ·   ESC — anuluj   ·   ↑ ↓ — poprzednie / następne pole"


def form_row(label: str, *widgets, row_id: Optional[str] = None, classes: str = "") -> Horizontal:
    """Wiersz formularza: etykieta o stałej szerokości + pole wypełniające resztę."""
    return Horizontal(Label(label, classes="row-label"), *widgets, id=row_id, classes=f"form-row {classes}".strip())


class TransactionFormView(VerticalScroll):
    """Formularz dodawania/edycji transakcji."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self.editing_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label("NOWA TRANSAKCJA", id="form-title-label", classes="form-header")
        yield form_row("Data:", Input(placeholder="puste = dziś · 12 · 12.05 · wczoraj", id="input-date",
                                      classes="row-input"))
        yield form_row("Rodzaj:", Select([("Wydatek", "Wydatek"), ("Dochód", "Dochód")], value="Wydatek",
                                         id="input-type", allow_blank=False, classes="row-select"))
        yield form_row("Konto:", Select([], prompt="Wybierz konto...", id="input-account", allow_blank=True,
                                        classes="row-select"))
        yield form_row("Kwota (PLN):", Input(placeholder="0.00  (można liczyć: 12.5+3)", id="input-amount",
                                             classes="row-input", restrict=AMOUNT_RESTRICT))
        yield form_row("Kategoria:", Select([], prompt="Wybierz...", id="input-category", allow_blank=True,
                                            classes="row-select"))
        yield form_row("Sklep / opis:", Input(placeholder="np. Biedronka", id="input-shop", classes="row-input"))
        yield form_row("Notatka:", Input(placeholder="opcjonalnie", id="input-desc", classes="row-input"))
        yield form_row("", Checkbox("Zapisz w historii (odznacz = tylko korekta salda)", id="input-registered",
                                    value=True), classes="checkbox-row")
        yield Label(FORM_HINT, classes="form-hint")

    def on_mount(self) -> None:
        self._load_categories()
        self._load_accounts()

    # ------------------------------------------------------------- helpers

    def _load_accounts(self, keep: Optional[str] = None) -> None:
        sel = self.query_one("#input-account", Select)
        options = list(get_account_options() or [("Karta", "Karta"), ("Gotówka", "Gotówka")])
        values = {v for _, v in options}
        if keep and keep not in values:
            options.append((f"{keep} (nieaktywne)", keep))
            values.add(keep)
        sel.set_options(options)
        if keep:
            sel.value = keep
        elif options:
            sel.value = options[0][1]

    def _load_categories(self, keep: Optional[str] = None) -> None:
        cats = list(get_unique_categories() or [])
        if keep and keep not in cats:
            cats.append(keep)
        sel = self.query_one("#input-category", Select)
        sel.set_options([(c, c) for c in cats])
        sel.value = keep if keep else Select.BLANK

    # -------------------------------------------------- API (MainDashboard)

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#form-title-label", Label).update("NOWA TRANSAKCJA")
        self.query_one("#input-date", Input).value = ""
        self.query_one("#input-type", Select).value = "Wydatek"
        self._load_accounts()
        self.query_one("#input-amount", Input).value = ""
        self.query_one("#input-shop", Input).value = ""
        self.query_one("#input-desc", Input).value = ""
        self.query_one("#input-registered", Checkbox).value = True
        self._load_categories()
        self.scroll_home(animate=False)

    def load_existing_data(self, data) -> None:
        data = dict(data)
        self.editing_id = int(data["id"])
        code = data.get("human_code") or f"TX{self.editing_id:06d}"
        self.query_one("#form-title-label", Label).update(f"EDYCJA TRANSAKCJI {code}")
        self.query_one("#input-date", Input).value = str(data.get("date") or "")
        self.query_one("#input-type", Select).value = data.get("type") or "Wydatek"
        self._load_accounts(keep=data.get("account_type") or "Karta")
        self.query_one("#input-amount", Input).value = f"{float(data.get('amount') or 0.0):.2f}"
        self._load_categories(keep=data.get("category") or None)
        self.query_one("#input-shop", Input).value = data.get("shop") or ""
        self.query_one("#input-desc", Input).value = data.get("description") or ""
        self.query_one("#input-registered", Checkbox).value = bool(data.get("is_registered"))

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        raw_date = self.query_one("#input-date", Input).value
        final_date = parse_user_date(raw_date, get_active_month_str())
        if final_date is None:
            return None, "Niepoprawna data! Wpisz np. 12, 12.05, 12.05.2026 albo 2026-05-12."

        amount = parse_amount(self.query_one("#input-amount", Input).value)
        if amount is None:
            return None, "Podaj poprawną kwotę!"
        if amount <= 0:
            return None, "Kwota musi być większa od zera!"

        t_type = self.query_one("#input-type", Select).value
        category_val = self.query_one("#input-category", Select).value
        account = self.query_one("#input-account", Select).value
        shop = self.query_one("#input-shop", Input).value.strip()
        desc = self.query_one("#input-desc", Input).value.strip()
        is_reg = self.query_one("#input-registered", Checkbox).value

        if account in (None, Select.BLANK):
            return None, "Wybierz konto!"

        if category_val in (None, Select.BLANK):
            if t_type == "Wydatek":
                if not get_unique_categories():
                    return None, "Brak kategorii — dodaj je w zakładce 3 (Kategorie)."
                return None, "Wybierz kategorię dla wydatku!"
            category_val = ""

        if not shop:
            return None, "Wpisz sklep lub opis!"

        return {
            "date": final_date,
            "type": t_type,
            "account": account,
            "category": category_val,
            "shop": shop,
            "amount": amount,
            "desc": desc,
            "is_reg": is_reg,
        }, None
