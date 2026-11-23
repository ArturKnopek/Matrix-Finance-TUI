from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select

from src.database import (
    get_account_balance,
    get_account_options,
    get_active_month_str,
    get_all_users,
    get_setting,
    set_setting,
)
from src.utils.parsing import AMOUNT_RESTRICT
from src.utils.ui_tools import money
from src.views.reports_view import MONTHS_PL
from src.views.transaction_form_view import form_row


class SettingsView(VerticalScroll):
    """Ustawienia: miesiąc roboczy, konta i salda, opcje systemowe, bezpieczeństwo, kopie."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self._user_label_by_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Label("KONFIGURACJA SYSTEMU", classes="form-header")

        yield Label("MIESIĄC ROBOCZY", classes="separator-line")
        yield form_row("Rok:", Input(placeholder="RRRR", id="set-year", classes="row-input", max_length=4,
                                     restrict=r"^[0-9]*$"))
        yield form_row("Miesiąc:", Select([(f"{name} ({i:02d})", f"{i:02d}") for i, name in enumerate(MONTHS_PL, 1)],
                                          value=f"{datetime.now().month:02d}", id="set-month", classes="row-select",
                                          allow_blank=False))
        yield form_row("Akcja:", Button("ZMIEŃ MIESIĄC", id="btn-set-month", classes="btn-inline"))
        yield form_row("", Button("WRÓĆ DO BIEŻĄCEGO", id="btn-set-month-now", classes="btn-inline"))

        yield Label("KONTA I SALDA", classes="separator-line")
        yield form_row("Konto:", Select([], prompt="Wybierz konto...", id="set-bal-account", classes="row-select",
                                        allow_blank=True))
        yield form_row("Nowe saldo (PLN):", Input(placeholder="0.00", id="set-bal-value", classes="row-input",
                                                  restrict=AMOUNT_RESTRICT))
        yield form_row("Zatwierdź:", Button("USTAW SALDO", id="btn-set-balance", classes="btn-inline"))
        yield form_row("Nowe konto:", Input(placeholder="np. Konto oszczędnościowe", id="set-new-account",
                                            classes="row-input"))
        yield form_row("Saldo początkowe:", Input(placeholder="0.00", id="set-new-account-balance",
                                                  classes="row-input", restrict=AMOUNT_RESTRICT))
        yield form_row("Dodaj:", Button("DODAJ KONTO", id="btn-add-account", classes="btn-inline"))

        yield Label("OPCJE (ZAPISYWANE OD RAZU)", classes="separator-line")
        yield form_row("Potwierdzenia:", Checkbox("Pomijaj potwierdzenie usuwania", id="chk-skip-delete"),
                       classes="checkbox-row")
        yield form_row("Diagnostyka:", Checkbox("Zapisuj szczegółowe logi (debug.log)", id="chk-dev-mode"),
                       classes="checkbox-row")

        yield Label("BEZPIECZEŃSTWO", classes="separator-line")
        yield form_row("Hasło:", Button("ZMIEŃ HASŁO", id="btn-open-pass-modal", classes="btn-inline"))
        yield form_row("Kopia zapasowa:", Button("EKSPORTUJ ZASZYFROWANĄ KOPIĘ", id="btn-export-backup",
                                                 classes="btn-inline"))

        yield Label("UŻYTKOWNICY", classes="separator-line")
        yield form_row("Użytkownik:", Select([], prompt="Wybierz...", id="sel-user-delete", classes="row-select",
                                             allow_blank=True))
        yield form_row("Akcja:", Button("USUŃ UŻYTKOWNIKA", id="btn-delete-user",
                                        classes="btn-inline btn-inline-danger"))

        yield Label("STREFA NIEBEZPIECZNA", classes="separator-line danger")
        yield form_row("Reset danych:", Button("WYCZYŚĆ WSZYSTKIE DANE", id="btn-reset-db",
                                               classes="btn-inline btn-inline-danger"))

    def on_mount(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        """Odświeża wartości (wywoływane przy każdym wejściu do zakładki)."""
        current_ym = get_active_month_str()
        if "-" in current_ym:
            y, m = current_ym.split("-")
            self.query_one("#set-year", Input).value = y
            self.query_one("#set-month", Select).value = m

        self._load_accounts()
        with self.prevent(Checkbox.Changed):
            self.query_one("#chk-dev-mode", Checkbox).value = get_setting("dev_mode", "0") == "1"
            self.query_one("#chk-skip-delete", Checkbox).value = get_setting("skip_delete_confirm", "0") == "1"
        self._load_users_select()

    def _load_accounts(self) -> None:
        sel = self.query_one("#set-bal-account", Select)
        current = sel.value
        options = [(f"{label} · {money(get_account_balance(value))}", value)
                   for label, value in get_account_options(active_only=True)]
        with self.prevent(Select.Changed):
            sel.set_options(options)
            values = [v for _, v in options]
            sel.value = current if current in values else (values[0] if values else Select.BLANK)
        self._fill_balance_input()

    def _fill_balance_input(self) -> None:
        acc = self.query_one("#set-bal-account", Select).value
        if acc not in (None, Select.BLANK):
            self.query_one("#set-bal-value", Input).value = f"{get_account_balance(acc):.2f}"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "set-bal-account":
            self._fill_balance_input()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = {"chk-dev-mode": "dev_mode", "chk-skip-delete": "skip_delete_confirm"}.get(event.checkbox.id or "")
        if not key:
            return
        event.stop()
        set_setting(key, "1" if event.value else "0")
        if key == "dev_mode":
            from src.utils.logging_setup import apply_debug_logging

            log_path = apply_debug_logging(event.value)
            self.notify(f"Logi diagnostyczne: {'WŁ' if event.value else 'WYŁ'}\n{log_path}")
        else:
            self.notify("Zapisano ustawienie.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-open-pass-modal":
            event.stop()
            user_id = getattr(self.app, "current_user_id", None)
            username = getattr(self.app, "current_username", None)
            if not user_id or not username:
                self.notify("Brak sesji.", severity="error")
                return
            from src.screens.modal_screen import ChangePasswordModal

            self.app.push_screen(ChangePasswordModal(username=username, user_id=user_id))
        elif event.button.id == "btn-set-month-now":
            event.stop()
            now = datetime.now()
            self.query_one("#set-year", Input).value = str(now.year)
            self.query_one("#set-month", Select).value = f"{now.month:02d}"
            self.query_one("#btn-set-month", Button).press()
        # pozostałe przyciski obsługuje MainDashboard

    def _load_users_select(self) -> None:
        try:
            rows = get_all_users()
            options = [(row["username"], row["id"]) for row in rows]
            sel = self.query_one("#sel-user-delete", Select)
            sel.set_options(options)
            self._user_label_by_id = {row["id"]: row["username"] for row in rows}
            cu = getattr(self.app, "current_user_id", None)
            if cu and cu in self._user_label_by_id:
                sel.value = cu
        except Exception:
            self._user_label_by_id = {}
