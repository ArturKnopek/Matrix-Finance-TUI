"""Ekran logowania: hasło → (opcjonalnie) klucz YubiKey → odszyfrowanie danych → pulpit."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label

from src.core.auth import AuthService
from src.finance.storage import get_user_by_username, init_user_db, set_active_user_db, set_setting, user_exists
from src.ui.widgets import MatrixRain


class LoginScreen(Screen):
    BINDINGS = [("escape", "exit", "Wyjście")]

    def compose(self) -> ComposeResult:
        yield MatrixRain(animated=self.app.animations_enabled, id="login-rain")  # type: ignore[attr-defined]
        with Vertical(id="login-wrapper", classes="login-box"):
            yield Label("MATRIX FINANCE", classes="box-title")
            yield Label("zaloguj się, aby kontynuować", classes="box-subtitle")
            yield Input(placeholder="Login", id="user-login", classes="standard-input")
            yield Input(placeholder="Hasło", password=True, id="user-password", classes="standard-input")
            with Container(id="login-actions"):
                yield Button("ZALOGUJ", id="btn-login", classes="btn-primary")
                yield Button("WYJDŹ", id="btn-exit", classes="btn-secondary")
            with Vertical(id="login-extra"):
                yield Button("+ NOWE KONTO", id="btn-create-account", classes="btn-link")
                yield Button("↺ IMPORTUJ KOPIĘ (.matrix)", id="btn-import-backup", classes="btn-link")


    def on_mount(self) -> None:
        self.query_one("#login-wrapper").border_title = " AUTORYZACJA "
        self.query_one("#user-login", Input).focus()

    def on_screen_resume(self) -> None:
        self.query_one("#user-password", Input).value = ""
        self.query_one("#user-password" if self.query_one("#user-login", Input).value else "#user-login",
                       Input).focus()

    def action_exit(self) -> None:
        self.app.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "user-login" and not self.query_one("#user-password", Input).value:
            self.query_one("#user-password", Input).focus()
            return
        self.attempt_login()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-login":
            self.attempt_login()
        elif bid == "btn-exit":
            self.app.exit()
        elif bid == "btn-create-account":
            set_setting("run_wizard_on_boot", "1")
            self.app.switch_screen("welcome")
        elif bid == "btn-import-backup":
            from src.screens.modals import ImportBackupDialog

            self.app.push_screen(ImportBackupDialog(), lambda r: r and self.notify(r.get("message", "")))

    # ------------------------------------------------------------------ logowanie

    def attempt_login(self) -> None:
        login = self.query_one("#user-login", Input).value.strip()
        password = self.query_one("#user-password", Input).value or ""
        try:
            if not user_exists():
                set_setting("run_wizard_on_boot", "1")
                self.app.switch_screen("welcome")
                return
        except Exception:
            self.notify("Błąd bazy logowania.", severity="error")
            return

        user_id = AuthService.verify_login(login, password)
        if not user_id:
            pwd = self.query_one("#user-password", Input)
            pwd.value = ""
            pwd.focus()
            self.notify("Nieprawidłowy login lub hasło.", severity="error")
            return

        user = get_user_by_username(login)
        from src.core import yubikey

        if yubikey.is_enabled(user):
            from src.screens.modals import YubiKeyLoginDialog

            def after_key(result: Any) -> None:
                if result:
                    self._finish_login(user_id, login, password)
                else:
                    self.notify("Logowanie przerwane — wymagany klucz YubiKey.", severity="warning")

            self.app.push_screen(YubiKeyLoginDialog(user_id), after_key)
            return
        self._finish_login(user_id, login, password)

    def _finish_login(self, user_id: str, login: str, password: str) -> None:
        from src.core.vault import DataVault, is_encrypted

        try:
            user = get_user_by_username(login)
            if int(user["encrypt_at_rest"] or 0) == 1 or is_encrypted(user_id):
                vault = DataVault(user_id, password)
                vault.open()
                self.app.vault = vault  # type: ignore[attr-defined]
                init_user_db(vault.uri)
            else:
                init_user_db(set_active_user_db(user_id))
            self.app.set_current_user(user_id, login)  # type: ignore[attr-defined]
            self.query_one("#user-password", Input).value = ""
            self.app.switch_screen("main_dashboard")
        except Exception as e:
            logging.exception("Błąd logowania: %s", e)
            self.notify(f"Błąd logowania: {e}", severity="error")
