"""
Formularze (okna dialogowe) wszystkich operacji.

Każdy formularz sam zapisuje dane przez silnik (`src.finance`) i zwraca wynik
(zwykle True). Ekran wywołujący po prostu odświeża widoki.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from rich.text import Text
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Label, Select

from src.finance import accounts as acc_api
from src.finance import autosave as autosave_api
from src.finance import envelopes as env_api
from src.finance import goals as goals_api
from src.finance import ledger
from src.finance import recurring as rec_api
from src.finance.storage import get_active_month_str
from src.ui.dialogs import (
    FormDialog,
    FormError,
    form_row,
    parse_required_amount,
    parse_required_date,
    select_options_with_current,
)
from src.ui.theme import palette
from src.ui.widgets import meter_text, money
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount, parse_user_date

DATE_HINT = "puste = dziś · 12 · 12.05 · wczoraj"


def amount_input(widget_id: str, placeholder: str = "0,00  (można liczyć: 12.5+3)", value: str = "") -> Input:
    return Input(value, placeholder=placeholder, id=widget_id, classes="row-input", restrict=AMOUNT_RESTRICT)


def text_input(widget_id: str, placeholder: str = "", value: str = "", **kwargs: Any) -> Input:
    return Input(value, placeholder=placeholder, id=widget_id, classes="row-input", **kwargs)


def account_select(widget_id: str, liquid_only: bool = False, with_balance: bool = True,
                   current: Optional[str] = None, allow_blank: bool = False) -> Select:
    options = select_options_with_current(
        acc_api.get_account_options(active_only=True, liquid_only=liquid_only, with_balance=with_balance), current)
    value = current if current in {v for _, v in options} else (Select.BLANK if allow_blank else options[0][1])
    return Select(options, value=value, id=widget_id, classes="row-select", allow_blank=allow_blank,
                  prompt="Wybierz konto…")


def info_line(widget_id: str, text: str = "") -> Label:
    return Label(text, id=widget_id, classes="row-value")


# =============================================================================
# Transakcja (wydatek / dochód)
# =============================================================================

class TransactionDialog(FormDialog):
    """Nowy / edycja wydatku lub dochodu. Pokazuje na żywo stan wybranej koperty."""

    def __init__(self, row: Any = None, preset_date: Optional[str] = None, preset_account: Optional[str] = None,
                 preset_type: str = "Wydatek", preset_category: Optional[str] = None) -> None:
        self.row = dict(row) if row else None
        title = f"EDYCJA {self.row.get('human_code') or 'TRANSAKCJI'}" if self.row else "NOWA TRANSAKCJA"
        super().__init__(title)
        self.preset_date = preset_date
        self.preset_account = preset_account
        self.preset_type = preset_type
        self.preset_category = preset_category

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        t_type = r.get("type") or self.preset_type
        cats = env_api.get_unique_categories()
        cat = r.get("category") if self.row else self.preset_category
        cat_options = [(c, c) for c in cats] + ([(cat, cat)] if cat and cat not in cats else [])
        yield form_row("Rodzaj:", Select([("Wydatek", "Wydatek"), ("Dochód", "Dochód")], value=t_type, id="f-type",
                                         allow_blank=False, classes="row-select"))
        yield form_row("Kwota (PLN):", amount_input("f-amount", value=f"{float(r['amount']):.2f}" if r else ""))
        yield form_row("Koperta:", Select(cat_options, value=cat if cat else Select.BLANK, id="f-category",
                                          allow_blank=True, prompt="Wybierz kopertę…", classes="row-select"))
        yield form_row("", info_line("f-envelope-state"), row_id="row-envelope-state")
        yield form_row("Konto:", account_select("f-account", current=r.get("account_type") or self.preset_account))
        yield form_row("Data:", text_input("f-date", DATE_HINT, r.get("date") or self.preset_date or ""))
        yield form_row("Sklep / opis:", text_input("f-shop", "np. Biedronka", r.get("shop") or ""))
        yield form_row("Notatka:", text_input("f-desc", "opcjonalnie", r.get("description") or ""))
        yield form_row("", Checkbox("Zapisz w historii (odznacz = tylko korekta salda)", id="f-registered",
                                    value=bool(r.get("is_registered", 1)) if r else True), classes="checkbox-row")

    def on_mount(self) -> None:
        super().on_mount()
        self._update_envelope_state()
        if not self.row:
            self.query_one("#f-amount").focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("f-category", "f-type"):
            self._update_envelope_state()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "f-amount":
            self._update_envelope_state()

    def _update_envelope_state(self) -> None:
        label = self.query_one("#f-envelope-state", Label)
        cat = self.value("f-category")
        if not cat:
            label.update(Text("Dochód nie wymaga koperty" if self.value("f-type") == "Dochód" else "—",
                              style=palette().muted))
            return
        env = next((e for e in env_api.get_envelope_overview(get_active_month_str()) if e["name"] == cat), None)
        if not env or env["available"] <= 0:
            label.update(Text("koperta bez budżetu", style=palette().muted))
            return
        amount = parse_amount(self.value("f-amount") or "") or 0.0
        if self.value("f-type") == "Wydatek":
            spent = env["spent"] + amount - (float(self.row["amount"]) if self.row and self.row.get("category") == cat
                                             and self.row.get("type") == "Wydatek" else 0.0)
        else:
            spent = env["spent"] - amount
        pct = spent / env["available"] * 100
        text = meter_text(pct, 18, "budget")
        text.append(f"  zostanie {money(env['available'] - spent)}", style=palette().muted)
        label.update(text)

    def submit_form(self) -> Any:
        t_type = self.value("f-type")
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        category = self.value("f-category")
        if t_type == "Wydatek" and not category:
            raise FormError("Wybierz kopertę dla wydatku." if env_api.get_unique_categories()
                            else "Brak kopert — dodaj je w zakładce 3.", "f-category")
        account = self.value("f-account")
        if not account:
            raise FormError("Wybierz konto.", "f-account")
        day = parse_required_date(self.value("f-date"), "f-date", get_active_month_str())
        shop = self.value("f-shop")
        if not shop:
            raise FormError("Wpisz sklep lub opis.", "f-shop")
        args = (day, t_type, category or "", account, shop, amount, self.value("f-desc"), self.value("f-registered"))
        if self.row:
            ledger.update_transaction(int(self.row["id"]), *args)
            return {"message": f"Zaktualizowano {self.row.get('human_code')}."}
        ledger.add_transaction(*args)
        note = "" if day.startswith(get_active_month_str()) else f" (data {day} — poza bieżącym miesiącem)"
        return {"message": f"Dodano: {t_type.lower()} {money(amount)}.{note}"}


# =============================================================================
# Przelew między kontami
# =============================================================================

class TransferDialog(FormDialog):
    SAVE_LABEL = "PRZELEJ"

    def __init__(self, source: Optional[str] = None, target: Optional[str] = None, amount: str = "") -> None:
        super().__init__("PRZELEW MIĘDZY KONTAMI")
        self.source, self.target, self.amount = source, target, amount

    def compose_body(self) -> Iterable[Widget]:
        yield form_row("Z konta:", account_select("f-source", current=self.source))
        target = self.target
        if not target:
            names = acc_api.get_account_names()
            target = next((n for n in names if n != (self.source or names[0])), None)
        yield form_row("Na konto:", account_select("f-target", current=target))
        yield form_row("Kwota (PLN):", amount_input("f-amount", value=self.amount))
        yield form_row("Data:", text_input("f-date", DATE_HINT))
        yield form_row("Tytuł:", text_input("f-note", "opcjonalnie"))
        yield Label("Przelew nie jest wydatkiem ani dochodem — nie wpływa na budżet kopert.", classes="dialog-note")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#f-amount").focus()

    def submit_form(self) -> Any:
        source, target = self.value("f-source"), self.value("f-target")
        if source == target:
            raise FormError("Wybierz dwa różne konta.", "f-target")
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        day = parse_required_date(self.value("f-date"), "f-date")
        acc_api.transfer_between_accounts(source, target, amount, day, self.value("f-note"))
        return {"message": f"Przelano {money(amount)}: {source} → {target}."}


# =============================================================================
# Konto (nowe / edycja) — pola zależne od rodzaju
# =============================================================================

EXISTING = "__existing__"  # lokata już założona (bez przelewu)
NO_FUNDS = "__none__"  # zakup na raty — pieniądze nie wpłynęły na żadne konto


class AccountDialog(FormDialog):
    """
    Nowe konto / edycja. Pola zależą od rodzaju:
      * własny rodzaj — nazwa rodzaju, grupa i przełączniki właściwości,
      * lokata / obligacje — kwota, okres, z jakiego konta (albo „już założona” — bez przelewu),
      * kredyt / zakup na raty — kwota, liczba rat, oprocentowanie, rata, termin, konto spłaty, koperta.
    """

    WIDE = True

    def __init__(self, name: Optional[str] = None, preset_kind: str = "checking") -> None:
        self.row = dict(acc_api.get_account(name)) if name else None
        super().__init__(f"EDYCJA KONTA: {name}" if name else "NOWE KONTO / PRODUKT")
        self.preset_kind = preset_kind

    # ------------------------------------------------------------------ pola

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        kind = r.get("account_kind") or self.preset_kind
        locked = bool(self.row and (acc_api.kind_info(kind).has_term or kind in acc_api.LOAN_KINDS))
        yield form_row("Rodzaj:", Select(acc_api.kind_options(), value=kind, id="f-kind", allow_blank=False,
                                         classes="row-select", disabled=locked))
        yield form_row("Nazwa:", text_input("f-name", "np. Revolut, Lokata 6M, Ekspres na raty", r.get("name") or ""))
        yield form_row("Instytucja:", text_input("f-institution", "np. Revolut, PKO BP, XTB", r.get("institution") or "",
                                                 suggester=SuggestFromList(acc_api.INSTITUTIONS, case_sensitive=False)))
        # --- własny rodzaj ---
        flags = acc_api.parse_flags(r.get("custom_flags")) if r else {"valuation"}
        yield form_row("Nazwa rodzaju:", text_input("f-custom-label", "np. Obligacje co miesiąc, Konto walutowe",
                                                    r.get("custom_label") or ""), row_id="row-custom-label")
        yield form_row("Grupa:", Select([(g, g) for g in acc_api.KIND_GROUPS], value=r.get("custom_group") or
                                        "Inwestycje", id="f-custom-group", allow_blank=False, classes="row-select"),
                       row_id="row-custom-group")
        for flag, label in acc_api.CUSTOM_FLAGS.items():
            yield form_row("", Checkbox(label, id=f"f-flag-{flag}", value=flag in flags), row_id=f"row-flag-{flag}",
                           classes="checkbox-row")
        if not self.row:
            yield form_row("Saldo początkowe:", amount_input("f-opening", "0,00"), row_id="row-opening")
        # --- lokaty / obligacje ---
        sources = acc_api.get_account_options(liquid_only=True, with_balance=True)
        yield form_row("Z konta:", Select(sources + [("— lokata już założona (bez przelewu)", EXISTING)],
                                          value=EXISTING if acc_api.opening_mode() else sources[0][1],
                                          id="f-source", allow_blank=False, classes="row-select"), row_id="row-source")
        yield form_row("Po terminie na:", account_select("f-return", liquid_only=True), row_id="row-return")
        yield form_row("Kwota lokaty:", amount_input("f-principal", "kapitał lokaty / obligacji"), row_id="row-principal")
        yield form_row("Okres (mies.):", text_input("f-term", "np. 3, 6, 12", str(r.get("term_months") or ""),
                                                    restrict=r"^[0-9]*$"), row_id="row-term")
        yield form_row("Data założenia:", text_input("f-start", DATE_HINT), row_id="row-start")
        yield form_row("", Checkbox("Odnawiaj automatycznie (kapitalizacja odsetek)", id="f-renew",
                                    value=bool(r.get("auto_renew"))), row_id="row-renew", classes="checkbox-row")
        # --- kredyt / raty ---
        yield form_row("Kwota do spłaty:", amount_input("f-loan-amount", "cena na raty / kwota kredytu (lub ile zostało)"),
                       row_id="row-loan-amount")
        yield form_row("Liczba rat:", text_input("f-loan-count", "np. 10, 24, 360 (pozostałe)",
                                                str(r.get("term_months") or ""), restrict=r"^[0-9]*$"),
                       row_id="row-loan-count")
        yield form_row("Rata miesięczna:", amount_input("f-loan-payment", "puste = wylicz (rata równa)",
                                                        f"{float(r.get('loan_installment') or 0):.2f}" if r and
                                                        r.get("loan_installment") else ""), row_id="row-loan-payment")
        next_due = ""
        if r.get("loan_first_due"):
            from src.finance.loans import loan_status

            nd = loan_status(r).get("next_due")
            next_due = nd.isoformat() if nd else ""
        yield form_row("Najbliższa rata:", text_input("f-loan-due", "data, np. 05.12.2026", next_due),
                       row_id="row-loan-due")
        yield form_row("Spłacane z konta:", account_select("f-loan-from", liquid_only=True,
                                                            current=r.get("linked_account")), row_id="row-loan-from")
        cats = [c for c in env_api.get_unique_categories()]
        default_cat = r.get("loan_category") or ("Raty i kredyty" if "Raty i kredyty" not in cats else "Raty i kredyty")
        yield form_row("Koperta rat:", text_input("f-loan-cat", "np. Raty i kredyty", default_cat,
                                                  suggester=SuggestFromList(cats, case_sensitive=False)),
                       row_id="row-loan-cat")
        yield form_row("Pieniądze na:", Select([("— nie (zakup na raty)", NO_FUNDS)] + sources, value=NO_FUNDS,
                                               id="f-loan-funds", allow_blank=False, classes="row-select"),
                       row_id="row-loan-funds")
        yield form_row("", Checkbox("Kredyt już trwa — bez wpisów w historii (stan początkowy)", id="f-loan-opening",
                                    value=acc_api.opening_mode()), row_id="row-loan-opening", classes="checkbox-row")
        # --- oprocentowanie / limity ---
        yield form_row("Oprocentowanie %:", amount_input("f-rate", "np. 5,5 (raty 0% — zostaw puste)",
                                                         f"{float(r.get('interest_rate') or 0):g}" if r else ""),
                       row_id="row-rate")
        yield form_row("Podatek %:", amount_input("f-tax", "19 (podatek Belki)",
                                                  f"{float(r.get('tax_rate') if r.get('tax_rate') is not None else 19):g}"),
                       row_id="row-tax")
        yield form_row("Limit wpłat / rok:", amount_input("f-limit", "np. limit IKE/IKZE",
                                                          f"{float(r.get('yearly_limit') or 0):g}" if r else ""),
                       row_id="row-limit")
        yield form_row("", Checkbox("Wliczaj do majątku netto", id="f-networth",
                                    value=bool(r.get("include_in_net_worth", 1)) if r else True), classes="checkbox-row")
        yield form_row("Podgląd:", info_line("f-preview"), row_id="row-preview")

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_kind()
        self.query_one("#f-name").focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("f-kind", "f-source", "f-custom-group"):
            self._apply_kind()
        self._update_preview()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if (event.checkbox.id or "").startswith("f-flag-"):
            self._apply_kind()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_preview()

    # ------------------------------------------------------------------ właściwości wg formularza

    def _flags(self) -> str:
        return ",".join(f for f in acc_api.CUSTOM_FLAGS if self.value(f"f-flag-{f}"))

    def _info(self) -> Any:
        kind = self.value("f-kind")
        if kind == "custom":
            return acc_api.custom_kind(self.value("f-custom-label"), self.value("f-custom-group"), self._flags())
        return acc_api.kind_info(kind)

    def _apply_kind(self) -> None:
        kind = self.value("f-kind")
        info = self._info()
        custom = kind == "custom"
        loan = kind in acc_api.LOAN_KINDS
        new_term = info.has_term and not self.row
        existing = self.value("f-source") == EXISTING
        for row in ("row-custom-label", "row-custom-group", *[f"row-flag-{f}" for f in acc_api.CUSTOM_FLAGS]):
            self.toggle_row(row, custom)
        self.toggle_row("row-source", new_term)
        self.toggle_row("row-return", new_term and existing)
        self.toggle_row("row-principal", new_term)
        self.toggle_row("row-start", new_term)
        self.toggle_row("row-term", new_term)
        self.toggle_row("row-renew", info.has_term)
        for row in ("row-loan-count", "row-loan-payment", "row-loan-due", "row-loan-from", "row-loan-cat"):
            self.toggle_row(row, loan)
        for row in ("row-loan-amount", "row-loan-funds", "row-loan-opening"):
            self.toggle_row(row, loan and not self.row)
        self.toggle_row("row-rate", info.has_rate)
        self.toggle_row("row-tax", info.has_rate and not loan)
        self.toggle_row("row-limit", info.retirement)
        if not self.row:
            self.toggle_row("row-opening", not info.has_term and not loan)
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            label = self.query_one("#f-preview", Label)
        except Exception:
            return
        from src.finance.loans import annuity_payment

        kind = self.value("f-kind")
        info = self._info()
        rate = parse_amount(self.value("f-rate") or "") or 0.0
        tax = parse_amount(self.value("f-tax") or "") or 0.0
        if kind in acc_api.LOAN_KINDS:
            amount = parse_amount(self.value("f-loan-amount") or "") or (-float(self.row["balance"]) if self.row else 0)
            count = int(self.value("f-loan-count") or 0)
            if amount and count:
                payment = parse_amount(self.value("f-loan-payment") or "") or annuity_payment(amount, rate, count)
                total = payment * count
                label.update(f"rata {money(payment)} × {count} = {money(total)}"
                             + (f" · odsetki ≈ {money(max(0.0, total - amount))}" if rate else " · bez odsetek"))
            else:
                label.update("podaj kwotę i liczbę rat — ratę wyliczę sam (możesz ją wpisać ręcznie)")
            return
        if info.has_term and not self.row:
            principal = parse_amount(self.value("f-principal") or "") or 0.0
            months = int(self.value("f-term") or 0)
            if principal and months:
                start = date.today()
                gross, tax_amt, net = acc_api.interest_for_period(principal, rate, start,
                                                                  acc_api.add_months(start, months), tax)
                label.update(f"zysk netto ≈ {money(net)} (brutto {gross:.2f}, podatek {tax_amt:.2f})")
                return
        elif info.has_rate and rate:
            base = float((self.row or {}).get("balance") or 0.0) if self.row else \
                (parse_amount(self.value("f-opening") or "") or 0.0)
            label.update(f"odsetki netto ≈ {money(base * rate / 100 / 12 * (1 - tax / 100))} / mies.")
            return
        parts = [info.group, "środki dostępne od ręki" if info.liquid else "środki ulokowane"]
        if info.valuation:
            parts.append("wycena ręczna (W)")
        label.update(" · ".join(parts))

    # ------------------------------------------------------------------ zapis

    def submit_form(self) -> Any:
        name = self.value("f-name")
        if not name:
            raise FormError("Podaj nazwę konta.", "f-name")
        kind = self.value("f-kind")
        info = self._info()
        rate = parse_amount(self.value("f-rate") or "0") or 0.0
        tax = parse_amount(self.value("f-tax") or "19")
        tax = 19.0 if tax is None else tax
        limit = parse_amount(self.value("f-limit") or "0") or 0.0
        institution = self.value("f-institution")
        custom = {}
        if kind == "custom":
            if not self.value("f-custom-label"):
                raise FormError("Podaj nazwę rodzaju (np. Obligacje co miesiąc).", "f-custom-label")
            custom = {"custom_label": self.value("f-custom-label"), "custom_group": self.value("f-custom-group"),
                      "custom_flags": self._flags()}

        if self.row:
            extra: dict = dict(custom)
            if kind in acc_api.LOAN_KINDS:
                extra.update(self._loan_edit_fields())
            ok, msg = acc_api.update_account(
                self.row["name"], new_name=name, institution=institution or None, interest_rate=rate, tax_rate=tax,
                yearly_limit=limit, include_in_net_worth=1 if self.value("f-networth") else 0,
                auto_renew=1 if self.value("f-renew") else 0, account_kind=kind, **extra)
            if not ok:
                raise FormError(msg, "f-name")
            return {"message": f"Zapisano konto {name}.", "check_due": kind in acc_api.LOAN_KINDS}

        if kind in acc_api.LOAN_KINDS:
            return self._create_loan(name, kind, rate, institution)

        if info.has_term:
            principal = parse_required_amount(self.value("f-principal"), "f-principal")
            months = int(self.value("f-term") or 0)
            if months <= 0:
                raise FormError("Podaj okres w miesiącach.", "f-term")
            start = parse_required_date(self.value("f-start"), "f-start")
            existing = self.value("f-source") == EXISTING
            ok, msg = acc_api.open_term_deposit(name, None if existing else self.value("f-source"), principal, rate,
                                                months, start, institution, kind, bool(self.value("f-renew")), tax,
                                                return_to=self.value("f-return") if existing else None)
            if not ok:
                raise FormError(msg)
            how = " (stan początkowy, bez przelewu)" if existing else ""
            return {"message": f"Założono {info.label.lower()}: {name} ({money(principal)}){how}.",
                    "check_due": True}

        opening = parse_amount(self.value("f-opening") or "0")
        if opening is None:
            raise FormError("Niepoprawne saldo początkowe.", "f-opening")
        ok, msg = acc_api.add_account(name, opening, account_kind=kind, institution=institution or None,
                                      interest_rate=rate, tax_rate=tax, yearly_limit=limit,
                                      include_in_net_worth=bool(self.value("f-networth")), **custom)
        if not ok:
            raise FormError(msg, "f-name")
        return {"message": f"Dodano konto {name} ({info.label})."}

    def _loan_numbers(self) -> tuple:
        count = int(self.value("f-loan-count") or 0)
        if count <= 0:
            raise FormError("Podaj liczbę (pozostałych) rat.", "f-loan-count")
        due = parse_required_date(self.value("f-loan-due"), "f-loan-due")
        payment = parse_amount(self.value("f-loan-payment") or "")
        if self.value("f-loan-payment") and (payment is None or payment <= 0):
            raise FormError("Niepoprawna rata.", "f-loan-payment")
        if not self.value("f-loan-from"):
            raise FormError("Wybierz konto, z którego spłacasz raty.", "f-loan-from")
        return count, due, payment

    def _create_loan(self, name: str, kind: str, rate: float, institution: Optional[str]) -> Any:
        from src.finance import loans

        amount = parse_required_amount(self.value("f-loan-amount"), "f-loan-amount")
        count, due, payment = self._loan_numbers()
        funds = self.value("f-loan-funds")
        ok, msg = loans.open_loan(name, amount, count, due, self.value("f-loan-from"), rate, payment, kind,
                                  self.value("f-loan-cat") or None, None if funds == NO_FUNDS else funds,
                                  institution or None, record_history=not self.value("f-loan-opening"))
        if not ok:
            raise FormError(msg)
        pay = loans.loan_status(acc_api.get_account(name))["payment"]
        return {"message": f"Dodano {name}: {money(amount)}, {count} rat po {money(pay)}.", "check_due": True}

    def _loan_edit_fields(self) -> dict:
        from src.finance import loans

        count, due, payment = self._loan_numbers()
        paid = loans.loan_status(self.row)["paid"]
        first = acc_api.add_months(datetime.strptime(due, "%Y-%m-%d").date(), -paid)
        remaining = -float(self.row["balance"] or 0)
        return {"term_months": count, "loan_first_due": first.isoformat(), "linked_account": self.value("f-loan-from"),
                "loan_category": self.value("f-loan-cat") or loans.DEFAULT_CATEGORY,
                "loan_installment": payment or loans.annuity_payment(remaining, parse_amount(
                    self.value("f-rate") or "0") or 0.0, max(1, count - paid))}


# =============================================================================
# Operacje na koncie
# =============================================================================

ACCOUNT_OPERATIONS = {
    "deposit": "WPŁATA Z INNEGO KONTA",
    "withdraw": "WYPŁATA NA INNE KONTO",
    "valuation": "AKTUALIZACJA WYCENY",
    "external": "WPŁATA ZEWNĘTRZNA",
    "interest": "DOPISZ ODSETKI / ZYSK",
    "correction": "KOREKTA SALDA",
    "close": "ZAMKNIJ KONTO",
}


class AccountOperationDialog(FormDialog):
    def __init__(self, account: str, operation: str) -> None:
        self.account = dict(acc_api.get_account(account))
        self.operation = operation
        self.debt = acc_api.account_info(self.account).liability  # kredyt / raty: saldo ujemne = dług
        title = "NADPŁATA / SPŁATA" if self.debt and operation == "deposit" else \
            "KOREKTA: ILE ZOSTAŁO DO SPŁATY" if self.debt and operation == "correction" else ACCOUNT_OPERATIONS[operation]
        super().__init__(f"{title}: {account}", "danger" if operation == "close" else None)
        self.SAVE_LABEL = "ZATWIERDŹ"

    def _shown(self, balance: float) -> float:
        """Kwota w formularzu: dla zobowiązań — dług (dodatni), dla reszty — saldo."""
        return -balance if self.debt else balance

    def compose_body(self) -> Iterable[Widget]:
        a = self.account
        info = acc_api.account_info(a)
        balance = float(a["balance"] or 0)
        yield form_row("Do spłaty:" if self.debt else "Saldo / wartość:", info_line("f-current", money(self._shown(balance))))
        op = self.operation
        if op in ("deposit", "withdraw"):
            others = [(lbl, v) for lbl, v in acc_api.get_account_options(with_balance=True) if v != a["name"]]
            label = "Z konta:" if op == "deposit" else "Na konto:"
            yield form_row(label, Select(others, value=others[0][1] if others else Select.BLANK, id="f-other",
                                         allow_blank=not others, classes="row-select"))
        if op == "valuation":
            yield form_row("Nowa wartość:", amount_input("f-amount", "aktualna wycena portfela"))
        elif op == "correction":
            yield form_row("Zostało do spłaty:" if self.debt else "Rzeczywiste saldo:",
                           amount_input("f-amount", "np. stan z aplikacji banku", f"{self._shown(balance):.2f}"))
            yield form_row("Różnica:", info_line("f-diff", "—"))
            yield form_row("", Checkbox("Bez wpisu w historii (stan początkowy)", id="f-no-history",
                                        value=acc_api.opening_mode()), classes="checkbox-row")
        elif op == "close":
            others = [(lbl, v) for lbl, v in acc_api.get_account_options(with_balance=True) if v != a["name"]]
            yield form_row("Przelej resztę na:", Select(others, value=others[0][1] if others else Select.BLANK,
                                                        id="f-other", allow_blank=not others, classes="row-select"))
            yield Label("Konto zostanie zamknięte (ukryte); historia zostaje.", classes="dialog-note")
        else:
            suggestion = ""
            if op == "interest" and info.has_rate and float(a.get("interest_rate") or 0):
                rate, tax = float(a["interest_rate"]), float(a.get("tax_rate") or 0)
                suggestion = f"{float(a['balance']) * rate / 100 / 12 * (1 - tax / 100):.2f}"
            yield form_row("Kwota (PLN):", amount_input("f-amount", value=suggestion))
        if op != "close":
            yield form_row("Data:", text_input("f-date", DATE_HINT))
            yield form_row("Opis:", text_input("f-note", "opcjonalnie"))
        hints = {
            "external": "Np. wpłata pracodawcy/państwa do PPK — zwiększa saldo, ale nie jest dochodem budżetu.",
            "valuation": "Różnica zostanie zapisana jako wzrost/spadek wyceny (nie wpływa na budżet).",
            "interest": "Odsetki zapisują się jako dochód w kopercie „Odsetki i zyski”.",
            "correction": "Wpisz saldo zgodne z bankiem / portfelem. Różnica zapisze się w historii jako "
                          "„Korekta salda” — nie jest wydatkiem ani dochodem, więc nie zmienia budżetu. "
                          "„Bez wpisu w historii” — tylko ustawia stan (np. przy zakładaniu programu).",
        }
        if self.debt and op == "deposit":
            hints["deposit"] = "Nadpłata zmniejsza dług — kolejne raty spłacą resztę szybciej (kończą się same)."
        if op in hints:
            yield Label(hints[op], classes="dialog-note")

    def on_mount(self) -> None:
        super().on_mount()
        if self.operation == "correction":
            amount = self.query_one("#f-amount", Input)
            amount.focus()
            amount.action_select_all()
            self._update_diff()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "f-amount" and self.operation == "correction":
            self._update_diff()

    def _update_diff(self) -> None:
        p = palette()
        value = parse_amount(self.value("f-amount") or "")
        label = self.query_one("#f-diff", Label)
        if value is None:
            label.update(Text("niepoprawna kwota", style=p.negative))
            return
        diff = round(value - self._shown(float(self.account["balance"] or 0)), 2)
        style = p.positive if (diff > 0) != self.debt else p.negative
        label.update(Text(money(diff, signed=True) if diff else "bez zmian", style=style if diff else p.muted))

    def submit_form(self) -> Any:
        name = self.account["name"]
        op = self.operation
        if op == "close":
            ok, msg = acc_api.close_account(name, self.value("f-other"))
            if not ok:
                raise FormError(msg)
            return {"message": f"Zamknięto konto {name}."}
        day = parse_required_date(self.value("f-date"), "f-date")
        note = self.value("f-note")
        if op == "valuation":
            value = parse_required_amount(self.value("f-amount"), "f-amount", allow_zero=True)
            diff = acc_api.update_valuation(name, value, day, note)
            return {"message": f"Wycena {name}: {money(diff, signed=True)}."}
        if op == "correction":
            value = parse_amount(self.value("f-amount") or "")
            if value is None:
                raise FormError("Podaj poprawne saldo (może być ujemne, np. -120,50).", "f-amount")
            if self.debt:
                value = -abs(value)  # dług zapisujemy jako saldo ujemne
            diff = acc_api.set_account_balance(name, value, note or "Korekta salda", day,
                                               record=not self.value("f-no-history"))
            if not diff:
                return {"message": f"Saldo {name} bez zmian."}
            if self.debt:
                return {"message": f"{name}: do spłaty {money(-value)}."}
            return {"message": f"Korekta salda {name}: {money(diff, signed=True)} → {money(value)}."}
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        if op == "deposit":
            acc_api.transfer_between_accounts(self.value("f-other"), name, amount, day, note)
        elif op == "withdraw":
            acc_api.transfer_between_accounts(name, self.value("f-other"), amount, day, note)
        elif op == "external":
            acc_api.external_contribution(name, amount, day, note)
        elif op == "interest":
            acc_api.record_interest(name, amount, day, note)
        return {"message": f"{ACCOUNT_OPERATIONS[op].capitalize()}: {money(amount)}."}


# =============================================================================
# Koperta
# =============================================================================

class EnvelopeDialog(FormDialog):
    def __init__(self, row: Any = None) -> None:
        self.row = dict(row) if row else None
        super().__init__(f"EDYCJA KOPERTY {self.row['ct_code']}" if self.row else "NOWA KOPERTA")

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        yield form_row("Nazwa:", text_input("f-name", "np. Jedzenie", r.get("name") or ""))
        yield form_row("Budżet / mies.:", amount_input("f-budget", "0 = bez limitu",
                                                       f"{float(r.get('limit_amount') or 0):.2f}" if r else ""))
        yield form_row("", Checkbox("Elastyczna — niewydane środki przechodzą na kolejny miesiąc", id="f-rollover",
                                    value=bool(r.get("rollover"))), classes="checkbox-row")
        yield Label("Przykład: budżet 500 zł, wydano 420 zł → w kolejnym miesiącu dostępne 580 zł.",
                    classes="dialog-note")

    def submit_form(self) -> Any:
        name = self.value("f-name")
        if not name:
            raise FormError("Podaj nazwę koperty.", "f-name")
        budget = parse_amount(self.value("f-budget") or "0")
        if budget is None or budget < 0:
            raise FormError("Niepoprawny budżet.", "f-budget")
        if self.row:
            ok, msg = env_api.update_category(int(self.row["id"]), name, budget, bool(self.value("f-rollover")))
        else:
            ok, msg = env_api.add_category(name, budget, bool(self.value("f-rollover")))
        if not ok:
            raise FormError(msg, "f-name")
        return {"message": f"Zapisano kopertę {name}."}


ENVELOPE_ADJUST_MODES = [
    ("Ustaw kwotę „zostało”", "set"),
    ("Dołóż do koperty (+)", "add"),
    ("Odejmij z koperty (−)", "sub"),
    ("Przesuń do innej koperty", "move"),
    ("Cofnij korekty z tego miesiąca", "clear"),
]


class EnvelopeAdjustDialog(FormDialog):
    """Korekta koperty w miesiącu roboczym: ustawienie reszty, +/−, przesunięcie, cofnięcie."""

    def __init__(self, category_id: int, mode: str = "set") -> None:
        self.month = get_active_month_str()
        self.category_id = int(category_id)
        self.env = next(e for e in env_api.get_envelope_overview(self.month) if e["id"] == self.category_id)
        self.mode = mode
        super().__init__(f"KOREKTA KOPERTY: {self.env['name']} ({self.month})")
        self.SAVE_LABEL = "ZATWIERDŹ"

    def compose_body(self) -> Iterable[Widget]:
        e = self.env
        yield form_row("Stan koperty:", info_line("f-state", self._state_text()))
        yield form_row("Operacja:", Select(ENVELOPE_ADJUST_MODES, value=self.mode, id="f-mode", allow_blank=False,
                                           classes="row-select"))
        yield form_row("Kwota (PLN):", amount_input("f-amount"), row_id="row-amount")
        others = [(f"{x['name']}  (zostało {money(x['remaining'], '')})", str(x["id"]))
                  for x in env_api.get_envelope_overview(self.month) if x["id"] != self.category_id]
        yield form_row("Do koperty:", Select(others, value=others[0][1] if others else Select.BLANK, id="f-target",
                                             allow_blank=not others, prompt="Wybierz kopertę…", classes="row-select"),
                       row_id="row-target")
        yield form_row("Opis:", text_input("f-note", "opcjonalnie"), row_id="row-note")
        yield form_row("Po zmianie:", info_line("f-after", ""))
        count = len(env_api.get_envelope_adjustments(self.category_id, self.month))
        yield Label(f"Korekty dotyczą tylko miesiąca {self.month} (w kopercie elastycznej reszta przechodzi dalej). "
                    f"Zapisanych korekt w tym miesiącu: {count} (razem {money(e['adjustment'], signed=True)}).",
                    classes="dialog-note")

    def _state_text(self) -> Text:
        e, p = self.env, palette()
        t = Text()
        t.append("budżet ", style=p.muted)
        t.append(money(e["budget"], ""))
        if e["carried"]:
            t.append(" + z poprz. ", style=p.muted)
            t.append(money(e["carried"], ""))
        if e["adjustment"]:
            t.append(" + korekty ", style=p.muted)
            t.append(money(e["adjustment"], "", signed=True))
        t.append(" · wydano ", style=p.muted)
        t.append(money(e["spent"], ""))
        t.append(" · zostało ", style=p.muted)
        t.append(money(e["remaining"]), style=f"bold {p.negative if e['remaining'] < 0 else p.positive}")
        return t

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_mode()
        if self.mode == "set":
            self.set_value("f-amount", f"{self.env['remaining']:.2f}")
        self.query_one("#f-amount", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "f-mode":
            self._apply_mode()
        self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "f-amount":
            self._update_preview()

    def _apply_mode(self) -> None:
        mode = self.value("f-mode")
        self.toggle_row("row-amount", mode != "clear")
        self.toggle_row("row-target", mode == "move")
        self.toggle_row("row-note", mode in ("set", "add", "sub"))
        self._update_preview()

    def _change(self) -> Optional[float]:
        """O ile zmieni się „zostało” wybranej koperty (None = błędna kwota)."""
        mode = self.value("f-mode")
        if mode == "clear":
            return -self.env["adjustment"]
        value = parse_amount(self.value("f-amount") or "")
        if value is None:
            return None
        if mode == "set":
            return round(value - self.env["remaining"], 2)
        return value if mode == "add" else -value

    def _update_preview(self) -> None:
        p = palette()
        label = self.query_one("#f-after", Label)
        change = self._change()
        if change is None:
            label.update(Text("podaj kwotę", style=p.muted))
            return
        after = self.env["remaining"] + change
        t = Text()
        t.append("zostanie ", style=p.muted)
        t.append(money(after), style=f"bold {p.negative if after < 0 else p.positive}")
        t.append(f"  ({money(change, signed=True)})", style=p.muted)
        label.update(t)

    def submit_form(self) -> Any:
        mode = self.value("f-mode")
        name = self.env["name"]
        if mode == "clear":
            removed = env_api.clear_envelope_adjustments(self.category_id, self.month)
            if not removed:
                raise FormError("W tym miesiącu nie ma korekt tej koperty.")
            return {"message": f"Cofnięto korekty koperty {name} ({removed})."}
        note = self.value("f-note") if mode != "move" else ""
        if mode == "set":
            value = parse_amount(self.value("f-amount") or "")
            if value is None:
                raise FormError("Podaj poprawną kwotę (może być 0).", "f-amount")
            diff = env_api.set_envelope_remaining(self.category_id, self.month, value, note)
            if not diff:
                return {"message": f"Koperta {name} bez zmian."}
            return {"message": f"Koperta {name}: zostało {money(value)} ({money(diff, signed=True)})."}
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        if mode == "move":
            target = self.value("f-target")
            if not target:
                raise FormError("Wybierz kopertę docelową.", "f-target")
            env_api.move_between_envelopes(self.category_id, int(target), self.month, amount)
            dst = env_api.get_category_by_id(int(target))
            return {"message": f"Przesunięto {money(amount)}: {name} → {dst['name'] if dst else '?'}."}
        env_api.adjust_envelope(self.category_id, self.month, amount if mode == "add" else -amount,
                                note or ("Dołożono do koperty" if mode == "add" else "Odjęto z koperty"))
        return {"message": f"Koperta {name}: {money(amount if mode == 'add' else -amount, signed=True)}."}


# =============================================================================
# Cele
# =============================================================================

class GoalDialog(FormDialog):
    def __init__(self, row: Any = None) -> None:
        self.row = dict(row) if row else None
        super().__init__(f"EDYCJA CELU {self.row['pb_code']}" if self.row else "NOWY CEL OSZCZĘDNOŚCIOWY")

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        yield form_row("Nazwa celu:", text_input("f-name", "np. Wakacje 2027", r.get("name") or ""))
        yield form_row("Kwota celu:", amount_input("f-target", "0,00",
                                                   f"{float(r.get('target_amount') or 0):.2f}" if r else ""))
        yield form_row("Konto celu:", account_select("f-account", current=r.get("account_type")))
        yield form_row("Termin:", text_input("f-deadline", "opcjonalnie, np. 06.2027 → 01.06.2027",
                                             r.get("target_date") or ""))
        yield form_row("Plan:", info_line("f-plan"))

    def on_mount(self) -> None:
        super().on_mount()
        self._update_plan()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_plan()

    def _deadline(self) -> Optional[str]:
        raw = (self.value("f-deadline") or "").strip()
        if not raw:
            return None
        if raw.count(".") == 1 and len(raw.split(".")[1]) == 4:  # MM.RRRR
            raw = "01." + raw
        return parse_user_date(raw)

    def _update_plan(self) -> None:
        target = parse_amount(self.value("f-target") or "") or 0.0
        deadline = self._deadline()
        current = float((self.row or {}).get("current_amount") or 0.0)
        plan = goals_api.goal_plan({"target_amount": target, "current_amount": current, "target_date": deadline})
        if plan["monthly_needed"]:
            text = f"odkładaj {money(plan['monthly_needed'])} / mies. przez {plan['months_left']} mies."
        elif target:
            text = f"brakuje {money(plan['missing'])}"
        else:
            text = "—"
        self.query_one("#f-plan", Label).update(text)

    def submit_form(self) -> Any:
        name = self.value("f-name")
        if not name:
            raise FormError("Podaj nazwę celu.", "f-name")
        target = parse_required_amount(self.value("f-target"), "f-target")
        deadline = self._deadline()
        if self.value("f-deadline") and not deadline:
            raise FormError("Niepoprawny termin.", "f-deadline")
        if self.row:
            ok, msg = goals_api.update_piggy_bank(int(self.row["id"]), name, target, self.value("f-account"), deadline)
        else:
            ok, msg = goals_api.add_piggy_bank(name, target, self.value("f-account"), deadline)
        if not ok:
            raise FormError(msg, "f-name")
        return {"message": f"Zapisano cel {name}."}


class GoalOperationDialog(FormDialog):
    def __init__(self, goal_id: int, operation: str) -> None:
        self.goal = dict(goals_api.get_piggy_bank_by_id(goal_id))
        self.operation = operation
        title = "WPŁATA NA CEL" if operation == "deposit" else "WYPŁATA Z CELU"
        super().__init__(f"{title}: {self.goal['name']}")
        self.SAVE_LABEL = "ZATWIERDŹ"

    def compose_body(self) -> Iterable[Widget]:
        g = self.goal
        yield form_row("Stan celu:", info_line("f-state", f"{money(float(g['current_amount'] or 0))} / "
                                                          f"{money(float(g['target_amount'] or 0))}"))
        yield form_row("Kwota (PLN):", amount_input("f-amount"))
        yield form_row("Konto:", account_select("f-account", current=g.get("account_type")))

    def submit_form(self) -> Any:
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        change = amount if self.operation == "deposit" else -amount
        goals_api.update_piggy_bank_balance(int(self.goal["id"]), change, self.value("f-account"), True)
        verb = "Wpłacono" if change > 0 else "Wypłacono"
        return {"message": f"{verb} {money(amount)} ({self.goal['name']})."}


class GoalCorrectionDialog(FormDialog):
    """Korekta stanu celu bez ruchu pieniędzy na kontach."""

    def __init__(self, goal_id: int) -> None:
        self.goal = dict(goals_api.get_piggy_bank_by_id(goal_id))
        super().__init__(f"KOREKTA STANU CELU: {self.goal['name']}")
        self.SAVE_LABEL = "ZATWIERDŹ"

    def compose_body(self) -> Iterable[Widget]:
        g = self.goal
        yield form_row("Stan celu:", info_line("f-state", f"{money(float(g['current_amount'] or 0))} / "
                                                          f"{money(float(g['target_amount'] or 0))}"))
        yield form_row("Rzeczywisty stan:", amount_input("f-amount", "ile faktycznie jest odłożone",
                                                         f"{float(g['current_amount'] or 0):.2f}"))
        yield form_row("Różnica:", info_line("f-diff", "—"))
        yield Label("Korekta zmienia tylko stan celu — salda kont zostają bez zmian. "
                    "Żeby przenieść pieniądze między kontem a celem, użyj + / -.", classes="dialog-note")

    def on_mount(self) -> None:
        super().on_mount()
        amount = self.query_one("#f-amount", Input)
        amount.focus()
        amount.action_select_all()
        self._update_diff()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_diff()

    def _update_diff(self) -> None:
        p = palette()
        value = parse_amount(self.value("f-amount") or "")
        label = self.query_one("#f-diff", Label)
        if value is None or value < 0:
            label.update(Text("niepoprawna kwota", style=p.negative))
            return
        diff = round(value - float(self.goal["current_amount"] or 0), 2)
        label.update(Text(money(diff, signed=True) if diff else "bez zmian",
                          style=p.positive if diff > 0 else p.negative if diff < 0 else p.muted))

    def submit_form(self) -> Any:
        value = parse_amount(self.value("f-amount") or "")
        if value is None or value < 0:
            raise FormError("Podaj poprawny stan celu (0 lub więcej).", "f-amount")
        diff = goals_api.set_goal_amount(int(self.goal["id"]), value)
        if not diff:
            return {"message": f"Stan celu {self.goal['name']} bez zmian."}
        return {"message": f"Korekta celu {self.goal['name']}: {money(diff, signed=True)} → {money(value)}."}


# =============================================================================
# Zlecenie cykliczne
# =============================================================================

class RecurringDialog(FormDialog):
    WIDE = True

    def __init__(self, row: Any = None) -> None:
        self.row = dict(row) if row else None
        super().__init__(f"EDYCJA ZLECENIA {self.row['rr_code']}" if self.row else "NOWE ZLECENIE CYKLICZNE")

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        yield form_row("Rodzaj:", Select([(t, t) for t in rec_api.RECURRING_TYPES], value=r.get("type") or "Wydatek",
                                         id="f-type", allow_blank=False, classes="row-select"))
        yield form_row("Nazwa:", text_input("f-name", "np. Netflix, Pensja, Na IKE", r.get("name") or ""))
        yield form_row("Kwota (PLN):", amount_input("f-amount", value=f"{float(r['amount']):.2f}" if r else ""))
        cats = env_api.get_unique_categories()
        cat = r.get("category")
        yield form_row("Koperta:", Select([(c, c) for c in cats] + ([(cat, cat)] if cat and cat not in cats else []),
                                          value=cat if cat else Select.BLANK, id="f-category", allow_blank=True,
                                          prompt="Wybierz kopertę…", classes="row-select"), row_id="row-category")
        goals = [(g["name"], str(g["id"])) for g in goals_api.get_all_piggy_banks()]
        pig = str(r.get("piggy_id")) if r.get("piggy_id") else None
        yield form_row("Cel:", Select(goals, value=pig if pig in {v for _, v in goals} else Select.BLANK,
                                      id="f-goal", allow_blank=True, prompt="Wybierz cel…", classes="row-select"),
                       row_id="row-goal")
        yield form_row("Konto:", account_select("f-account", current=r.get("account_type")))
        yield form_row("Na konto:", account_select("f-target", current=r.get("target_account"), allow_blank=True),
                       row_id="row-target")
        yield form_row("Cykl:", Select([(c, c) for c in rec_api.RECURRING_CYCLES], value=r.get("cycle") or "Miesięcznie",
                                       id="f-cycle", allow_blank=False, classes="row-select"))
        yield form_row("Pierwsza płatność:", text_input("f-start", DATE_HINT,
                                                        r.get("start_date") or date.today().isoformat()))
        yield form_row("Kolejne terminy:", info_line("f-preview"))
        yield form_row("", Checkbox("Aktywne (księguj automatycznie)", id="f-active",
                                    value=bool(r.get("is_registered", 1)) if r else True), classes="checkbox-row")

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_type()
        self.query_one("#f-name").focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "f-type":
            self._apply_type()
        self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "f-start":
            self._update_preview()

    def _apply_type(self) -> None:
        t = self.value("f-type")
        self.toggle_row("row-category", t in ("Wydatek", "Dochód"))
        self.toggle_row("row-goal", t == "Na Skarbonkę")
        self.toggle_row("row-target", t == "Przelew")
        self._update_preview()

    def _update_preview(self) -> None:
        start = parse_user_date(self.value("f-start") or "")
        label = self.query_one("#f-preview", Label)
        if not start:
            label.update("niepoprawna data")
            return
        first = datetime.strptime(start, "%Y-%m-%d").date()
        cycle = self.value("f-cycle")
        label.update(" → ".join(rec_api.recurring_occurrence(first, cycle, n).strftime("%d.%m.%Y")
                                for n in range(3)) + " …")

    def submit_form(self) -> Any:
        r_type = self.value("f-type")
        name = self.value("f-name")
        if not name:
            raise FormError("Podaj nazwę.", "f-name")
        amount = parse_required_amount(self.value("f-amount"), "f-amount")
        start = parse_required_date(self.value("f-start"), "f-start")
        category = piggy_id = target = None
        if r_type == "Na Skarbonkę":
            if not self.value("f-goal"):
                raise FormError("Wybierz cel.", "f-goal")
            piggy_id = int(self.value("f-goal"))
        elif r_type == "Przelew":
            target = self.value("f-target")
            if not target or target == self.value("f-account"):
                raise FormError("Wybierz inne konto docelowe.", "f-target")
        else:
            category = self.value("f-category")
            if r_type == "Wydatek" and not category:
                raise FormError("Wybierz kopertę.", "f-category")
        args = (name, amount, r_type, category, self.value("f-account"), self.value("f-cycle"), start,
                1 if self.value("f-active") else 0, piggy_id, target)
        ok, msg = rec_api.update_recurring(int(self.row["id"]), *args) if self.row else rec_api.add_recurring(*args)
        if not ok:
            raise FormError(msg)
        return {"message": f"Zapisano zlecenie {name}.", "check_due": True}


# =============================================================================
# Reguła auto-oszczędzania
# =============================================================================

class AutosaveRuleDialog(FormDialog):
    def __init__(self, row: Any = None, source: Optional[str] = None) -> None:
        self.row = dict(row) if row else None
        self.source = source
        super().__init__("EDYCJA REGUŁY" if self.row else "NOWA REGUŁA AUTO-OSZCZĘDZANIA")

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        yield form_row("Konto źródłowe:", account_select("f-source", current=r.get("source_account") or self.source))
        yield form_row("Tryb:", Select([(label, code) for code, label in autosave_api.MODES.items()],
                                       value=r.get("mode") or "income_percent", id="f-mode", allow_blank=False,
                                       classes="row-select"))
        yield form_row("Wartość:", amount_input("f-value", "np. 10 (%) albo 5 (zł)",
                                                f"{float(r['value']):g}" if r else ""))
        yield form_row("Odkładaj do:", Select([("konta", "account"), ("celu", "goal")],
                                              value=r.get("target_kind") or "account", id="f-target-kind",
                                              allow_blank=False, classes="row-select"))
        target = r.get("target")
        yield form_row("Konto docelowe:", account_select("f-target-account", current=target
                                                          if r.get("target_kind", "account") == "account" else None,
                                                          allow_blank=True), row_id="row-target-account")
        goals = [(g["name"], str(g["id"])) for g in goals_api.get_all_piggy_banks()]
        yield form_row("Cel:", Select(goals, value=target if target in {v for _, v in goals} else Select.BLANK,
                                      id="f-target-goal", allow_blank=True, prompt="Wybierz cel…",
                                      classes="row-select"), row_id="row-target-goal")
        yield form_row("", Checkbox("Reguła aktywna", id="f-active", value=bool(r.get("is_active", 1)) if r else True),
                       classes="checkbox-row")
        yield form_row("Przykład:", info_line("f-example"))

    def on_mount(self) -> None:
        super().on_mount()
        self._apply()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._apply()

    def _apply(self) -> None:
        kind = self.value("f-target-kind")
        self.toggle_row("row-target-account", kind == "account")
        self.toggle_row("row-target-goal", kind == "goal")
        value = parse_amount(self.value("f-value") or "") or 0.0
        if self.value("f-mode") == "income_percent":
            example = f"wpływ 5 000 zł → odłożysz {money(5000 * value / 100)}"
        else:
            save = autosave_api.compute_autosave_amount("roundup", value or 1, "Wydatek", 23.40)
            example = f"wydatek 23,40 zł → odłożysz {money(save)}"
        self.query_one("#f-example", Label).update(example)

    def submit_form(self) -> Any:
        value = parse_required_amount(self.value("f-value"), "f-value")
        kind = self.value("f-target-kind")
        target = self.value("f-target-account") if kind == "account" else self.value("f-target-goal")
        if not target:
            raise FormError("Wybierz, gdzie odkładać.", "f-target-account" if kind == "account" else "f-target-goal")
        ok, msg = autosave_api.save_autosave_rule(self.value("f-source"), self.value("f-mode"), value, kind,
                                                  str(target), is_active=bool(self.value("f-active")),
                                                  rule_id=int(self.row["id"]) if self.row else None)
        if not ok:
            raise FormError(msg, "f-value")
        return {"message": "Zapisano regułę auto-oszczędzania."}
