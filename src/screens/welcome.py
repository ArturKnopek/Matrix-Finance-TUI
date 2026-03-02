from __future__ import annotations

import math
import logging
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Static, Button, Label, Input
from textual.containers import Vertical, Container, Horizontal

from src.database import (
    get_setting,
    set_setting,
    init_auth_db,
    create_user,
    init_user_db,
    DATA_DIR,
)

# Globalny import - naprawia "zatrzaśnięcie" w kreatorze
try:
    from src.core.auth import AuthService
except Exception as e:
    logging.error(f"Nie załadowano AuthService w welcome: {e}")
    AuthService = None

LOGO = r"""
  ____  _    _ _____   _____ ______ _______
 |  _ \| |  | |  __ \ / ____|  ____|__   __|
 | |_) | |  | | |  | | |  __| |__     | |
 |  _ <| |  | | |  | | | |_ |  __|    | |
 | |_) | |__| | |__| | |__| | |____   | |
 |____/ \____/|_____/ \_____|______|  |_|
""".strip("\n")


class WelcomeScreen(Screen):
    """Ekran powitalny: splash + kreator konta (wizard) w okienku."""

    BINDINGS = [
        ("enter", "start_or_create", "Start / Utwórz"),
        ("space", "start_or_create", "Start / Utwórz"),
        ("escape", "cancel", "Wyjście / Anuluj"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="main-bundle"):
            yield Static(LOGO, id="ascii-logo")
            yield Button("KLIKNIJ ABY ROZPOCZĄĆ", id="start-btn")

        with Container(id="wizard-bundle", classes="hidden"):
            with Container(id="wizard-window", classes="yellow-box"):
                yield Label("KREATOR: NOWE KONTO", classes="box-title")

                yield Input(placeholder="Login (nazwa użytkownika)", id="w-username", classes="standard-input")
                yield Input(placeholder="Hasło", password=True, id="w-pass-1", classes="standard-input")
                yield Input(placeholder="Powtórz hasło", password=True, id="w-pass-2", classes="standard-input")

                yield Label("--- SALDO POCZĄTKOWE ---", classes="separator-line")

                with Horizontal(classes="form-row"):
                    yield Label("Karta:", classes="row-label")
                    yield Input(placeholder="np. 3000.00", id="w-start-card", classes="row-input")

                with Horizontal(classes="form-row"):
                    yield Label("Gotówka:", classes="row-label")
                    yield Input(placeholder="np. 200.00", id="w-start-cash", classes="row-input")

                with Horizontal(id="wizard-actions"):
                    yield Button("UTWÓRZ KONTO", id="btn-w-create", classes="btn-green")
                    yield Button("ANULUJ", id="btn-w-cancel", classes="btn-red")

    def on_mount(self) -> None:
        self._blink_on = False
        self.set_interval(0.6, self._toggle_blink)
        self._sync_mode()

    def on_screen_resume(self) -> None:
        self._sync_mode()

    def _sync_mode(self) -> None:
        run_wizard = get_setting("run_wizard_on_boot", "0") == "1"
        if run_wizard:
            set_setting("run_wizard_on_boot", "0")
            self._show_wizard()
        else:
            self._show_splash()

    def _toggle_blink(self) -> None:
        try:
            if self._is_wizard_visible():
                return
            btn = self.query_one("#start-btn", Button)
            self._blink_on = not self._blink_on
            if self._blink_on:
                btn.add_class("blink")
            else:
                btn.remove_class("blink")
        except Exception:
            pass

    def _is_wizard_visible(self) -> bool:
        try:
            wiz = self.query_one("#wizard-bundle")
            return "hidden" not in wiz.classes
        except Exception:
            return False

    def _show_splash(self) -> None:
        self.query_one("#main-bundle").remove_class("hidden")
        self.query_one("#wizard-bundle").add_class("hidden")

    def _show_wizard(self) -> None:
        self.query_one("#main-bundle").add_class("hidden")
        self.query_one("#wizard-bundle").remove_class("hidden")
        try:
            self.query_one("#w-username", Input).focus()
        except Exception:
            pass

    def action_start_or_create(self) -> None:
        if self._is_wizard_visible():
            self._create_account()
        else:
            self.app.switch_screen("login")

    def action_cancel(self) -> None:
        if self._is_wizard_visible():
            self._clear_wizard_inputs()
            self.app.switch_screen("login")
        else:
            self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.app.switch_screen("login")
            return
        if event.button.id == "btn-w-cancel":
            self._clear_wizard_inputs()
            self.app.switch_screen("login")
            return
        if event.button.id == "btn-w-create":
            self._create_account()
            return

    def _clear_wizard_inputs(self) -> None:
        for wid in ("#w-username", "#w-pass-1", "#w-pass-2", "#w-start-card", "#w-start-cash"):
            try:
                self.query_one(wid, Input).value = ""
            except Exception:
                pass

    def _read_float(self, input_id: str) -> float | None:
        try:
            raw = self.query_one(input_id, Input).value.strip().replace(",", ".")
            if raw == "":
                return 0.0
            val = float(raw)
            # Zabezpieczenie przed błędem z 'inf' i ujemnymi stawkami
            if math.isinf(val) or math.isnan(val) or val < 0:
                return None
            return val
        except Exception:
            return None

    def _create_account(self) -> None:
        username = self.query_one("#w-username", Input).value.strip()
        p1 = self.query_one("#w-pass-1", Input).value or ""
        p2 = self.query_one("#w-pass-2", Input).value or ""
        start_card = self._read_float("#w-start-card")
        start_cash = self._read_float("#w-start-cash")

        if len(username) < 3 or " " in username:
            self.notify("Login musi mieć min. 3 znaki i nie może zawierać spacji.", severity="warning")
            return

        if len(p1) < 6:
            self.notify("Hasło musi mieć co najmniej 6 znaków.", severity="warning")
            return

        if p1 != p2:
            self.notify("Hasła nie są identyczne.", severity="warning")
            return

        if start_card is None or start_cash is None:
            self.notify("Wpisz poprawne liczby (większe od zera) dla sald startowych.", severity="error")
            return

        try:
            if AuthService is None:
                raise ValueError("Brak modułu zabezpieczeń.")

            init_auth_db()
            password_hash = AuthService.hash_password(p1)

            ok, msg, user_id = create_user(username, password_hash)
            if not ok or not user_id:
                self.notify(msg or "Nie udało się utworzyć użytkownika.", severity="error")
                return

            DATA_DIR.mkdir(exist_ok=True)
            user_db_path = str(DATA_DIR / f"{user_id}.db")

            init_user_db(user_db_path, start_card=start_card, start_cash=start_cash)

            set_setting("first_run_done", "1")
            self.notify("Konto utworzone. Zaloguj się nowym użytkownikiem.", severity="information")

            self._clear_wizard_inputs()
            self.app.switch_screen("login")

        except Exception as e:
            logging.error(f"Błąd tworzenia konta: {e}")
            self.notify(f"Nie udało się utworzyć konta: {e}", severity="error")