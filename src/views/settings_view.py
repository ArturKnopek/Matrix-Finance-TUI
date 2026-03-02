from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Input, Button, Label, Checkbox, Select
from textual.containers import Container, Horizontal, VerticalScroll

from src.database import get_account_balance, get_setting, set_setting, get_active_month_str, get_all_users

class SettingsView(Container):
    """Widok ustawień - styl 1:1 z formularzami."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form-scroll-container"):
            yield Label("KONFIGURACJA SYSTEMU", classes="form-header")

            yield Label("--- WIDOK DANYCH ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Rok:", classes="row-label")
                yield Input(placeholder="YYYY", id="set-year", classes="row-input", max_length=4)
            with Horizontal(classes="form-row"):
                yield Label("Miesiąc:", classes="row-label")
                months = [(f"{i:02d}", f"{i:02d}") for i in range(1, 13)]
                yield Select(months, prompt="Wybierz...", id="set-month", classes="row-select", allow_blank=False)
            with Horizontal(classes="form-row"):
                yield Label("Akcja:", classes="row-label")
                yield Button("ZMIEŃ WIDOK", id="btn-set-month", classes="btn-inline")

            yield Label("--- KOREKTA SALDA ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Karta (PLN):", classes="row-label")
                yield Input(placeholder="0.00", id="set-bal-card", classes="row-input")
            with Horizontal(classes="form-row"):
                yield Label("Gotówka (PLN):", classes="row-label")
                yield Input(placeholder="0.00", id="set-bal-cash", classes="row-input")
            with Horizontal(classes="form-row"):
                yield Label("Zatwierdź:", classes="row-label")
                yield Button("ZAKTUALIZUJ SALDA", id="btn-set-balance", classes="btn-inline")

            yield Label("--- SYSTEM / BEZPIECZEŃSTWO ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Tryb Debug:", classes="row-label")
                with Container(classes="row-input", id="chk-container"):
                    yield Checkbox("Włącz logi konsoli", id="chk-dev-mode")
            with Horizontal(classes="form-row"):
                yield Label("Potwierdzenia:", classes="row-label")
                with Container(classes="row-input", id="chk-container-2"):
                    yield Checkbox("Pomijaj potwierdzenie usuwania", id="chk-skip-delete")
            with Horizontal(classes="form-row"):
                yield Label("Zabezpieczenia:", classes="row-label")
                yield Button("ZAPISZ", id="btn-set-security", classes="btn-inline")

            yield Label("--- ZMIANA HASŁA ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Zmiana:", classes="row-label")
                yield Button("ZMIEŃ HASŁO", id="btn-open-pass-modal", classes="btn-inline")

            yield Label("--- UŻYTKOWNICY — USUŃ ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Wybierz użytkownika:", classes="row-label")
                yield Select([], prompt="Wybierz...", id="sel-user-delete", classes="row-select", allow_blank=True)
            with Horizontal(classes="form-row"):
                yield Label("Akcja:", classes="row-label")
                yield Button("USUŃ UŻYTKOWNIKA", id="btn-delete-user", classes="btn-inline btn-inline-danger")

            yield Label("--- KOPIA ZAPASOWA (ZASZYFROWANA) ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Pulpit:", classes="row-label")
                yield Button("EKSPORTUJ BAZĘ", id="btn-export-backup", classes="btn-inline")

            yield Label("--- NIEBEZPIECZNE ---", classes="separator-line")
            with Horizontal(classes="form-row"):
                yield Label("Reset Bazy:", classes="row-label")
                yield Button("!!! WYCZYŚĆ WSZYSTKO !!!", id="btn-reset-db", classes="btn-inline btn-inline-danger")

            yield Label("", classes="menu-spacer")

    def on_mount(self) -> None:
        current_ym = get_active_month_str()
        if "-" in current_ym:
            y, m = current_ym.split("-")
            self.query_one("#set-year", Input).value = y
            self.query_one("#set-month", Select).value = m
        c_bal = get_account_balance("Karta")
        g_bal = get_account_balance("Gotówka")
        self.query_one("#set-bal-card", Input).value = f"{c_bal:.2f}"
        self.query_one("#set-bal-cash", Input).value = f"{g_bal:.2f}"
        self.query_one("#chk-dev-mode", Checkbox).value = get_setting("dev_mode", "0") == "1"
        self.query_one("#chk-skip-delete", Checkbox).value = get_setting("skip_delete_confirm", "0") == "1"
        self._load_users_select()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid in {"btn-set-month", "btn-set-balance", "btn-set-security", "btn-reset-db", "btn-export-backup"}:
            return

        if bid == "btn-open-pass-modal":
            user_id = getattr(self.app, "current_user_id", None)
            username = getattr(self.app, "current_username", None)
            if not user_id or not username: return self.notify("Brak sesji.", severity="error")
            from src.screens.modal_screen import ChangePasswordModal
            self.app.push_screen(ChangePasswordModal(username=username, user_id=user_id))
            event.stop()

        if bid == "btn-delete-user":
            current_user_id = getattr(self.app, "current_user_id", None)
            current_username = getattr(self.app, "current_username", None)
            target = self.query_one("#sel-user-delete", Select)
            if not target.value: return self.notify("Wybierz użytkownika.", severity="warning")
            target_label = getattr(self, "_user_label_by_id", {}).get(target.value, "???")
            from src.screens.modal_screen import DeleteUserModal
            self.app.push_screen(DeleteUserModal(target.value, target_label, current_username, current_user_id))
            event.stop()

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