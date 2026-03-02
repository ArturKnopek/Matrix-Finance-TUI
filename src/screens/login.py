from __future__ import annotations
import logging

from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Input, Button, Label
from textual.containers import Container

from src.database import get_setting, user_exists, set_setting

try:
    from src.core.auth import AuthService  # type: ignore
except Exception as e:
    logging.error(f"Nie można załadować AuthService: {e}")
    AuthService = None


class LoginScreen(Screen):
    """Ekran logowania. Obsługuje Enter (logowanie) i Esc (wyjście)."""

    BINDINGS = [
        ("enter", "login", "Zaloguj"),
        ("escape", "exit", "Wyjście"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="login-center"):
            with Container(id="login-wrapper", classes="yellow-box"):
                yield Label("AUTORYZACJA UŻYTKOWNIKA", classes="box-title")
                yield Input(placeholder="Login", id="user-login", classes="standard-input")
                yield Input(placeholder="Hasło", password=True, id="user-password", classes="standard-input")

                with Container(id="login-actions"):
                    yield Button("ZALOGUJ", id="btn-login", classes="btn-green")
                    yield Button("WYJDŹ", id="btn-exit", classes="btn-red")

                with Container(id="login-extra"):
                    yield Button("DODAJ NOWE KONTO", id="btn-create-account", classes="btn-link")
                    yield Button("IMPORTUJ KOPIĘ Z DOKUMENTÓW", id="btn-import-backup", classes="btn-link")

    def on_mount(self) -> None:
        self.reset_login_fields(keep_username=True)
        try: self.query_one("#user-login", Input).focus()
        except Exception: pass

    def on_screen_resume(self) -> None:
        self.reset_login_fields(keep_username=True)
        try: self.query_one("#user-password", Input).focus()
        except Exception: pass

    def action_login(self) -> None: self.attempt_login()
    def action_exit(self) -> None: self.app.exit()

    def reset_login_fields(self, keep_username: bool = True) -> None:
        try:
            if not keep_username:
                self.query_one("#user-login", Input).value = ""
            self.query_one("#user-password", Input).value = ""
        except Exception: pass

    def attempt_login(self) -> None:
        login = self.query_one("#user-login", Input).value.strip()
        password = self.query_one("#user-password", Input).value or ""

        if AuthService is None:
            return self.notify("Brak modułu logowania.", severity="error")

        try:
            if not user_exists():
                set_setting("run_wizard_on_boot", "1")
                self.app.switch_screen("welcome")
                return
        except Exception:
            return self.notify("Błąd bazy logowania. Spróbuj ponownie.", severity="error")

        try:
            user_id = AuthService.verify_login(username=login, password=password)
            if not user_id:
                self.query_one("#user-password", Input).value = ""
                return self.notify("Nieprawidłowy login lub hasło.", severity="error")

            from src.database import set_active_user_db, init_user_db
            db_path = set_active_user_db(user_id)
            init_user_db(db_path)

            if hasattr(self.app, "set_current_user"):
                self.app.set_current_user(user_id, login)

            self.reset_login_fields(keep_username=True)
            self.app.switch_screen("main_dashboard")

        except Exception as e:
            self.notify(f"Błąd logowania: {e}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-login": self.attempt_login()
        elif event.button.id == "btn-exit": self.app.exit()
        elif event.button.id == "btn-create-account": self._start_create_account()
        elif event.button.id == "btn-import-backup":
            try:
                from src.screens.modal_screen import ImportBackupModal
                self.app.push_screen(ImportBackupModal())
            except Exception as e:
                self.notify(f"Błąd otwierania importu: {e}", severity="error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in ("user-login", "user-password"):
            self.attempt_login()

    def _start_create_account(self) -> None:
        try:
            set_setting("run_wizard_on_boot", "1")
            self.app.switch_screen("welcome")
        except Exception as e:
            self.notify(f"Nie można uruchomić kreatora: {e}", severity="error")