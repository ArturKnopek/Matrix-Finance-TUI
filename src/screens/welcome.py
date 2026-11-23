"""Ekran powitalny (animowany „deszcz Matrixa”) oraz kreator nowego konta użytkownika."""

from __future__ import annotations

import logging
import math

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

from src.core.auth import AuthService
from src.finance.storage import DATA_DIR, create_user, get_setting, init_auth_db, init_user_db, set_setting
from src.ui.dialogs import form_row
from src.ui.widgets import MatrixRain
from src.utils.parsing import AMOUNT_RESTRICT, parse_amount

LOGO = r"""
 __  __   _ _____ ___ _____  __
|  \/  | /_\_   _| _ \_ _\ \/ /
| |\/| |/ _ \| | |   /| | >  <
|_|  |_/_/ \_\_| |_|_\___/_/\_\
""".strip("\n")


class WelcomeScreen(Screen):
    BINDINGS = [
        ("enter", "start_or_create", "Start"),
        ("space", "start_or_create", "Start"),
        ("escape", "cancel", "Wyjście"),
    ]

    def compose(self) -> ComposeResult:
        yield MatrixRain(animated=self.app.animations_enabled, id="welcome-rain")  # type: ignore[attr-defined]
        with Vertical(id="main-bundle", classes="login-box"):
            yield Static(LOGO, id="ascii-logo")
            yield Label("F  I  N  A  N  C  E", id="logo-sub")
            yield Label("budżet domowy · koperty · oszczędzanie · inwestycje", id="tagline")
            yield Button("▶  ROZPOCZNIJ  (ENTER)", id="start-btn")
        with Vertical(id="wizard-window", classes="login-box hidden"):
            yield Label("Utwórz konto — dane zostają tylko na tym komputerze.", classes="box-subtitle")
            yield Input(placeholder="Login (min. 3 znaki)", id="w-username", classes="standard-input")
            yield Input(placeholder="Hasło (min. 6 znaków)", password=True, id="w-pass-1",
                        classes="standard-input")
            yield Input(placeholder="Powtórz hasło", password=True, id="w-pass-2", classes="standard-input")
            yield Label("SALDA POCZĄTKOWE", classes="section-title")
            yield form_row("Konto osobiste:", Input(placeholder="np. 3000", id="w-start-card", classes="row-input",
                                                    restrict=AMOUNT_RESTRICT))
            yield form_row("Gotówka:", Input(placeholder="np. 200", id="w-start-cash", classes="row-input",
                                             restrict=AMOUNT_RESTRICT))
            with Horizontal(id="wizard-actions"):
                yield Button("UTWÓRZ KONTO", id="btn-w-create", classes="btn-primary")
                yield Button("ANULUJ", id="btn-w-cancel", classes="btn-secondary")


    def on_mount(self) -> None:
        self.query_one("#main-bundle").border_title = " WITAJ "
        self.query_one("#wizard-window").border_title = " KREATOR: NOWE KONTO "
        self._blink = False
        self.set_interval(0.7, self._toggle_blink)
        self._sync_mode()

    def on_screen_resume(self) -> None:
        self._sync_mode()

    def _sync_mode(self) -> None:
        if get_setting("run_wizard_on_boot", "0") == "1":
            set_setting("run_wizard_on_boot", "0")
            self._show_wizard(True)
        else:
            self._show_wizard(False)

    def _toggle_blink(self) -> None:
        self._blink = not self._blink
        self.query_one("#start-btn", Button).set_class(self._blink, "blink")

    def _wizard_visible(self) -> bool:
        return not self.query_one("#wizard-window").has_class("hidden")

    def _show_wizard(self, visible: bool) -> None:
        self.query_one("#main-bundle").set_class(visible, "hidden")
        self.query_one("#wizard-window").set_class(not visible, "hidden")
        if visible:
            self.query_one("#w-username", Input).focus()
        else:
            self.query_one("#start-btn", Button).focus()

    def action_start_or_create(self) -> None:
        if self._wizard_visible():
            self._create_account()
        else:
            self.app.switch_screen("login")

    def action_cancel(self) -> None:
        if self._wizard_visible():
            self._clear()
            self.app.switch_screen("login")
        else:
            self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.app.switch_screen("login")
        elif event.button.id == "btn-w-cancel":
            self._clear()
            self.app.switch_screen("login")
        elif event.button.id == "btn-w-create":
            self._create_account()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        order = ["w-username", "w-pass-1", "w-pass-2", "w-start-card", "w-start-cash"]
        if event.input.id not in order:
            return
        event.stop()
        idx = order.index(event.input.id)
        if idx < len(order) - 1:
            self.query_one(f"#{order[idx + 1]}", Input).focus()
        else:
            self._create_account()

    def _clear(self) -> None:
        for wid in ("w-username", "w-pass-1", "w-pass-2", "w-start-card", "w-start-cash"):
            self.query_one(f"#{wid}", Input).value = ""

    def _amount(self, input_id: str) -> float | None:
        raw = self.query_one(f"#{input_id}", Input).value.strip()
        if not raw:
            return 0.0
        value = parse_amount(raw)
        if value is None or math.isinf(value) or value < 0:
            return None
        return value

    def _create_account(self) -> None:
        username = self.query_one("#w-username", Input).value.strip()
        p1 = self.query_one("#w-pass-1", Input).value
        p2 = self.query_one("#w-pass-2", Input).value
        card, cash = self._amount("w-start-card"), self._amount("w-start-cash")
        if len(username) < 3 or " " in username:
            self.notify("Login: min. 3 znaki, bez spacji.", severity="warning")
            return
        if len(p1) < 6:
            self.notify("Hasło musi mieć co najmniej 6 znaków.", severity="warning")
            return
        if p1 != p2:
            self.notify("Hasła nie są identyczne.", severity="warning")
            return
        if card is None or cash is None:
            self.notify("Wpisz poprawne (nieujemne) salda początkowe.", severity="error")
            return
        try:
            init_auth_db()
            ok, msg, user_id = create_user(username, AuthService.hash_password(p1))
            if not ok or not user_id:
                self.notify(msg or "Nie udało się utworzyć użytkownika.", severity="error")
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            init_user_db(str(DATA_DIR / f"{user_id}.db"), start_card=card, start_cash=cash)
            set_setting("first_run_done", "1")
            self.notify("Konto utworzone. Zaloguj się.", severity="information")
            self._clear()
            self.app.switch_screen("login")
        except Exception as e:
            logging.exception("Błąd tworzenia konta: %s", e)
            self.notify(f"Nie udało się utworzyć konta: {e}", severity="error")
