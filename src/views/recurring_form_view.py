from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Checkbox, Input, Label, Select

from src.database import (
    get_account_options,
    get_active_month_str,
    get_all_piggy_banks,
    get_unique_categories,
    recurring_occurrence,
)
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount, parse_user_date
from src.views.transaction_form_view import FORM_HINT, form_row

CYCLES = [("Dziennie", "Dziennie"), ("Tygodniowo", "Tygodniowo"), ("Miesięcznie", "Miesięcznie"),
          ("Rocznie", "Rocznie")]
TYPES = [("Wydatek", "Wydatek"), ("Dochód", "Dochód"), ("Na Skarbonkę", "Na Skarbonkę")]


class RecurringFormView(VerticalScroll):
    """Formularz płatności cyklicznej (Wydatek / Dochód / Na Skarbonkę) z podglądem kolejnych terminów."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self.editing_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label("NOWA PŁATNOŚĆ CYKLICZNA", id="rec-form-title", classes="form-header")
        yield form_row("Rodzaj:", Select(TYPES, value="Wydatek", id="rec-input-type", allow_blank=False,
                                         classes="row-select"))
        yield form_row("Nazwa:", Input(placeholder="np. Netflix", id="rec-input-name", classes="row-input"))
        yield form_row("Kwota (PLN):", Input(placeholder="0.00", id="rec-input-amount", classes="row-input",
                                             restrict=AMOUNT_RESTRICT))
        yield form_row("Kategoria:", Select([], prompt="Wybierz...", id="rec-input-category", allow_blank=True,
                                            classes="row-select"), row_id="row-category")
        yield form_row("Cel:", Select([], prompt="Wybierz cel...", id="rec-input-piggy", allow_blank=True,
                                      classes="row-select"), row_id="row-piggy")
        yield form_row("Konto:", Select([], prompt="Wybierz konto...", id="rec-input-account", allow_blank=True,
                                        classes="row-select"))
        yield form_row("Cykl:", Select(CYCLES, value="Miesięcznie", id="rec-input-cycle", allow_blank=False,
                                       classes="row-select"))
        yield form_row("Pierwsza płatność:", Input(value=datetime.now().strftime("%Y-%m-%d"), id="rec-input-date",
                                                   classes="row-input"))
        yield form_row("Kolejne terminy:", Label("...", id="rec-preview", classes="row-value"))
        yield form_row("", Checkbox("Aktywna (księguj automatycznie)", value=True, id="rec-input-registered"),
                       classes="checkbox-row")
        yield Label(FORM_HINT, classes="form-hint")

    def on_mount(self) -> None:
        self._set_type_visibility("Wydatek")
        self._load_accounts()
        self.refresh_options()
        self._update_preview()

    # ---------------------------------------------------------- visibility

    def _set_type_visibility(self, r_type: str) -> None:
        show_piggy = r_type == "Na Skarbonkę"
        self.query_one("#row-category").display = not show_piggy
        self.query_one("#row-piggy").display = show_piggy

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "rec-input-type":
            self._set_type_visibility(str(event.value))
        if event.select.id in ("rec-input-cycle", "rec-input-type"):
            self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "rec-input-date":
            self._update_preview()

    def _update_preview(self) -> None:
        try:
            label = self.query_one("#rec-preview", Label)
            iso = parse_user_date(self.query_one("#rec-input-date", Input).value, get_active_month_str())
            if not iso:
                label.update("niepoprawna data")
                return
            start = datetime.strptime(iso, "%Y-%m-%d").date()
            cycle = self.query_one("#rec-input-cycle", Select).value
            dates = [recurring_occurrence(start, str(cycle), n).strftime("%d.%m.%Y") for n in range(3)]
            label.update(" → ".join(dates) + " …")
        except Exception:
            pass

    # ------------------------------------------------------------------ API

    def reset_form(self) -> None:
        self.editing_id = None
        self.query_one("#rec-form-title", Label).update("NOWA PŁATNOŚĆ CYKLICZNA")
        self.query_one("#rec-input-type", Select).value = "Wydatek"
        self.query_one("#rec-input-name", Input).value = ""
        self.query_one("#rec-input-amount", Input).value = ""
        self._load_accounts()
        self.query_one("#rec-input-cycle", Select).value = "Miesięcznie"
        self.query_one("#rec-input-date", Input).value = datetime.now().strftime("%Y-%m-%d")
        self.query_one("#rec-input-registered", Checkbox).value = True
        self.refresh_options()
        self.query_one("#rec-input-category", Select).value = Select.BLANK
        self.query_one("#rec-input-piggy", Select).value = Select.BLANK
        self._set_type_visibility("Wydatek")
        self._update_preview()

    def refresh_options(self) -> None:
        c_sel = self.query_one("#rec-input-category", Select)
        current_cat = c_sel.value
        cats = get_unique_categories() or []
        c_sel.set_options([(c, c) for c in cats])
        c_sel.value = current_cat if current_cat in cats else Select.BLANK

        p_sel = self.query_one("#rec-input-piggy", Select)
        current_pig = p_sel.value
        pigs = [(p["name"], str(p["id"])) for p in get_all_piggy_banks() or []]
        p_sel.set_options(pigs)
        p_sel.value = current_pig if current_pig in {v for _, v in pigs} else Select.BLANK

    def load_existing_data(self, data) -> None:
        self.refresh_options()
        d = dict(data)
        self.editing_id = int(d["id"])
        code = d.get("rr_code") or f"RR{self.editing_id:06d}"
        self.query_one("#rec-form-title", Label).update(f"EDYCJA ZLECENIA {code}")

        r_type = d.get("type") or "Wydatek"
        self.query_one("#rec-input-type", Select).value = r_type
        self._set_type_visibility(r_type)
        self.query_one("#rec-input-name", Input).value = d.get("name") or ""
        self.query_one("#rec-input-amount", Input).value = f"{float(d.get('amount') or 0.0):.2f}"
        self._load_accounts(keep=d.get("account_type") or "Karta")
        self.query_one("#rec-input-cycle", Select).value = d.get("cycle") or "Miesięcznie"
        self.query_one("#rec-input-date", Input).value = d.get("start_date") or datetime.now().strftime("%Y-%m-%d")
        self.query_one("#rec-input-registered", Checkbox).value = bool(d.get("is_registered"))

        cat_sel = self.query_one("#rec-input-category", Select)
        pig_sel = self.query_one("#rec-input-piggy", Select)
        if r_type == "Na Skarbonkę":
            piggy_id = d.get("piggy_id")
            pig_sel.value = str(piggy_id) if piggy_id else Select.BLANK
            cat_sel.value = Select.BLANK
        else:
            cat = d.get("category") or ""
            if cat and cat not in (get_unique_categories() or []):
                cat_sel.set_options([(c, c) for c in (get_unique_categories() or [])] + [(cat, cat)])
            cat_sel.value = cat if cat else Select.BLANK
            pig_sel.value = Select.BLANK
        self._update_preview()

    def get_data_and_validate(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        name = self.query_one("#rec-input-name", Input).value.strip()
        r_type = self.query_one("#rec-input-type", Select).value
        if not name:
            return None, "Podaj nazwę!"

        amount = parse_amount(self.query_one("#rec-input-amount", Input).value)
        if amount is None:
            return None, "Podaj poprawną kwotę!"
        if amount <= 0:
            return None, "Kwota musi być większa od zera!"

        start = parse_user_date(self.query_one("#rec-input-date", Input).value, get_active_month_str())
        if not start:
            return None, "Niepoprawna data pierwszej płatności!"

        account = self.query_one("#rec-input-account", Select).value
        if account in (None, Select.BLANK):
            return None, "Wybierz konto!"

        cat: Optional[str] = None
        piggy_id: Optional[int] = None
        if r_type == "Na Skarbonkę":
            raw_pig = self.query_one("#rec-input-piggy", Select).value
            if raw_pig in (None, Select.BLANK):
                return None, "Wybierz skarbonkę docelową!"
            piggy_id = int(raw_pig)
            cat = "Oszczędności"
        else:
            raw_cat = self.query_one("#rec-input-category", Select).value
            if r_type == "Wydatek" and raw_cat in (None, Select.BLANK):
                return None, "Wybierz kategorię!"
            cat = None if raw_cat in (None, Select.BLANK) else raw_cat

        return {
            "name": name,
            "amount": amount,
            "type": r_type,
            "category": cat,
            "account": account,
            "cycle": self.query_one("#rec-input-cycle", Select).value,
            "start_date": start,
            "is_registered": 1 if self.query_one("#rec-input-registered", Checkbox).value else 0,
            "piggy_id": piggy_id,
        }, None

    def _load_accounts(self, keep: Optional[str] = None) -> None:
        sel = self.query_one("#rec-input-account", Select)
        options = list(get_account_options() or [("Karta", "Karta"), ("Gotówka", "Gotówka")])
        if keep and keep not in {v for _, v in options}:
            options.append((keep, keep))
        sel.set_options(options)
        sel.value = keep or options[0][1]
