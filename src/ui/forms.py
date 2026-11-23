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

class AccountDialog(FormDialog):
    WIDE = True

    def __init__(self, name: Optional[str] = None, preset_kind: str = "checking") -> None:
        self.row = dict(acc_api.get_account(name)) if name else None
        super().__init__(f"EDYCJA KONTA: {name}" if name else "NOWE KONTO / PRODUKT")
        self.preset_kind = preset_kind

    def compose_body(self) -> Iterable[Widget]:
        r = self.row or {}
        kind = r.get("account_kind") or self.preset_kind
        yield form_row("Rodzaj:", Select(acc_api.kind_options(), value=kind, id="f-kind", allow_blank=False,
                                         classes="row-select", disabled=bool(self.row and acc_api.kind_info(kind).has_term)))
        yield form_row("Nazwa:", text_input("f-name", "np. Revolut, Lokata 6M, IKE ETF", r.get("name") or ""))
        yield form_row("Instytucja:", text_input("f-institution", "np. Revolut, PKO BP, XTB", r.get("institution") or "",
                                                 suggester=SuggestFromList(acc_api.INSTITUTIONS, case_sensitive=False)))
        if not self.row:
            yield form_row("Saldo początkowe:", amount_input("f-opening", "0,00"), row_id="row-opening")
        # --- lokaty / obligacje ---
        yield form_row("Z konta:", account_select("f-source", liquid_only=True), row_id="row-source")
        yield form_row("Kwota lokaty:", amount_input("f-principal", "kwota przelewana z konta"), row_id="row-principal")
        yield form_row("Okres (mies.):", text_input("f-term", "np. 3, 6, 12", str(r.get("term_months") or ""),
                                                    restrict=r"^[0-9]*$"), row_id="row-term")
        yield form_row("Data założenia:", text_input("f-start", DATE_HINT), row_id="row-start")
        yield form_row("", Checkbox("Odnawiaj automatycznie (kapitalizacja odsetek)", id="f-renew",
                                    value=bool(r.get("auto_renew"))), row_id="row-renew", classes="checkbox-row")
        # --- oprocentowanie / limity ---
        yield form_row("Oprocentowanie %:", amount_input("f-rate", "np. 5,5",
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
        if event.select.id == "f-kind":
            self._apply_kind()
        self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_preview()

    def _apply_kind(self) -> None:
        info = acc_api.kind_info(self.value("f-kind"))
        new_term = info.has_term and not self.row
        self.toggle_row("row-source", new_term)
        self.toggle_row("row-principal", new_term)
        self.toggle_row("row-start", new_term)
        self.toggle_row("row-term", new_term)
        self.toggle_row("row-renew", info.has_term)
        self.toggle_row("row-rate", info.has_rate)
        self.toggle_row("row-tax", info.has_rate)
        self.toggle_row("row-limit", info.retirement)
        if not self.row:
            self.toggle_row("row-opening", not info.has_term)
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            label = self.query_one("#f-preview", Label)
        except Exception:
            return
        info = acc_api.kind_info(self.value("f-kind"))
        rate = parse_amount(self.value("f-rate") or "") or 0.0
        tax = parse_amount(self.value("f-tax") or "") or 0.0
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
            base = float((self.row or {}).get("balance") or parse_amount(self.value("f-opening") or "") or 0.0) \
                if self.row else (parse_amount(self.value("f-opening") or "") or 0.0)
            label.update(f"odsetki netto ≈ {money(base * rate / 100 / 12 * (1 - tax / 100))} / mies.")
            return
        label.update(info.group + " · " + ("środki dostępne od ręki" if info.liquid else "środki ulokowane"))

    def submit_form(self) -> Any:
        name = self.value("f-name")
        if not name:
            raise FormError("Podaj nazwę konta.", "f-name")
        kind = self.value("f-kind")
        info = acc_api.kind_info(kind)
        rate = parse_amount(self.value("f-rate") or "0") or 0.0
        tax = parse_amount(self.value("f-tax") or "19")
        tax = 19.0 if tax is None else tax
        limit = parse_amount(self.value("f-limit") or "0") or 0.0
        institution = self.value("f-institution")

        if self.row:
            ok, msg = acc_api.update_account(
                self.row["name"], new_name=name, institution=institution or None, interest_rate=rate, tax_rate=tax,
                yearly_limit=limit, include_in_net_worth=1 if self.value("f-networth") else 0,
                auto_renew=1 if self.value("f-renew") else 0, account_kind=kind)
            if not ok:
                raise FormError(msg, "f-name")
            return {"message": f"Zapisano konto {name}."}

        if info.has_term:
            principal = parse_required_amount(self.value("f-principal"), "f-principal")
            months = int(self.value("f-term") or 0)
            if months <= 0:
                raise FormError("Podaj okres w miesiącach.", "f-term")
            start = parse_required_date(self.value("f-start"), "f-start")
            ok, msg = acc_api.open_term_deposit(name, self.value("f-source"), principal, rate, months, start,
                                                institution, kind, bool(self.value("f-renew")), tax)
            if not ok:
                raise FormError(msg)
            return {"message": f"Założono {info.label.lower()}: {name} ({money(principal)})."}

        opening = parse_amount(self.value("f-opening") or "0")
        if opening is None:
            raise FormError("Niepoprawne saldo początkowe.", "f-opening")
        ok, msg = acc_api.add_account(name, opening, account_kind=kind, institution=institution or None,
                                      interest_rate=rate, tax_rate=tax, yearly_limit=limit,
                                      include_in_net_worth=bool(self.value("f-networth")))
        if not ok:
            raise FormError(msg, "f-name")
        return {"message": f"Dodano konto {name}."}


# =============================================================================
# Operacje na koncie
# =============================================================================

ACCOUNT_OPERATIONS = {
    "deposit": "WPŁATA Z INNEGO KONTA",
    "withdraw": "WYPŁATA NA INNE KONTO",
    "valuation": "AKTUALIZACJA WYCENY",
    "external": "WPŁATA ZEWNĘTRZNA",
    "interest": "DOPISZ ODSETKI / ZYSK",
    "close": "ZAMKNIJ KONTO",
}


class AccountOperationDialog(FormDialog):
    def __init__(self, account: str, operation: str) -> None:
        self.account = dict(acc_api.get_account(account))
        self.operation = operation
        super().__init__(f"{ACCOUNT_OPERATIONS[operation]}: {account}", "danger" if operation == "close" else None)
        self.SAVE_LABEL = "ZATWIERDŹ"

    def compose_body(self) -> Iterable[Widget]:
        a = self.account
        info = acc_api.kind_info(a["account_kind"])
        yield form_row("Saldo / wartość:", info_line("f-current", money(float(a["balance"] or 0))))
        op = self.operation
        if op in ("deposit", "withdraw"):
            others = [(lbl, v) for lbl, v in acc_api.get_account_options(with_balance=True) if v != a["name"]]
            label = "Z konta:" if op == "deposit" else "Na konto:"
            yield form_row(label, Select(others, value=others[0][1] if others else Select.BLANK, id="f-other",
                                         allow_blank=not others, classes="row-select"))
        if op == "valuation":
            yield form_row("Nowa wartość:", amount_input("f-amount", "aktualna wycena portfela"))
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
        }
        if op in hints:
            yield Label(hints[op], classes="dialog-note")

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
