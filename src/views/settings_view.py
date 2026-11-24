"""Ustawienia: wygląd (motyw, animacje), miesiąc roboczy, opcje, bezpieczeństwo, dane, użytkownicy."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select

from src.finance.storage import (
    get_active_month_str,
    get_all_users,
    get_setting,
    get_user_by_id,
    reset_user_db_hard,
    set_active_month_str,
    set_setting,
)
from src.ui.dialogs import ConfirmDialog, InfoDialog, form_row
from src.ui.theme import palette, theme_options
from src.views.base import DataChanged, ViewMixin
from src.views.reports_view import MONTHS_PL


class SettingsView(ViewMixin, VerticalScroll):
    TITLE = "USTAWIENIA"
    ACTIONS = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class("form-view")
        self._users: dict = {}

    def compose(self) -> ComposeResult:
        yield Label("WYGLĄD", classes="section-title")
        yield form_row("Motyw kolorów:", Select(theme_options(), value=get_setting("ui_theme", "matrix"),
                                                id="set-theme", allow_blank=False, classes="row-select"))
        yield form_row("", Checkbox("Animacje (deszcz Matrix na ekranie logowania)", id="chk-animations",
                                    value=get_setting("ui_animations", "1") == "1"), classes="checkbox-row")

        yield Label(Text("MIESIĄC ROBOCZY · klawisze [ oraz ] zmieniają go w każdej zakładce"),
                    classes="section-title")
        yield form_row("Rok:", Input(id="set-year", classes="row-input", max_length=4, restrict=r"^[0-9]*$"))
        yield form_row("Miesiąc:", Select([(f"{n} ({i:02d})", f"{i:02d}") for i, n in enumerate(MONTHS_PL, 1)],
                                          value=f"{datetime.now().month:02d}", id="set-month", allow_blank=False,
                                          classes="row-select"))
        yield form_row("", Button("USTAW MIESIĄC", id="btn-set-month", classes="btn-inline"))

        yield Label("OPCJE", classes="section-title")
        yield form_row("", Checkbox("Pomijaj potwierdzenie usuwania", id="chk-skip-delete"), classes="checkbox-row")
        yield form_row("", Checkbox("Zapisuj szczegółowe logi (debug.log)", id="chk-dev-mode"), classes="checkbox-row")

        yield Label("BEZPIECZEŃSTWO", classes="section-title")
        yield form_row("Hasło:", Button("ZMIEŃ HASŁO", id="btn-password", classes="btn-inline"))
        yield form_row("Szyfrowanie danych:", Label("", id="set-enc-status", classes="row-value"))
        yield form_row("", Button("", id="btn-encryption", classes="btn-inline"))
        yield form_row("Klucz YubiKey:", Label("", id="set-yk-status", classes="row-value"))
        yield form_row("", Button("", id="btn-yubikey", classes="btn-inline"))

        yield Label("SYNCHRONIZACJA Z TELEFONEM (OneDrive)", classes="section-title")
        yield form_row("Stan:", Label("", id="set-sync-status", classes="row-value"))
        yield form_row("", Button("USTAW SYNCHRONIZACJĘ", id="btn-sync-setup", classes="btn-inline"))
        yield form_row("", Button("SYNCHRONIZUJ TERAZ (Ctrl+Y)", id="btn-sync-now", classes="btn-inline"))

        yield Label("DANE", classes="section-title")
        yield form_row("Eksport:", Button("EKSPORTUJ DANE (JSON / MFX / CSV / .matrix)", id="btn-export",
                                          classes="btn-inline"))
        yield form_row("Import:", Button("IMPORTUJ DANE", id="btn-import", classes="btn-inline"))
        yield form_row("Raport:", Button("DRUKUJ RAPORT MIESIĘCZNY", id="btn-print", classes="btn-inline"))

        yield Label("UŻYTKOWNICY", classes="section-title")
        yield form_row("Użytkownik:", Select([], id="sel-user-delete", allow_blank=True, prompt="Wybierz…",
                                             classes="row-select"))
        yield form_row("", Button("USUŃ UŻYTKOWNIKA", id="btn-delete-user", classes="btn-inline -danger"))

        yield Label("STREFA NIEBEZPIECZNA", classes="section-title -danger")
        yield form_row("", Button("WYCZYŚĆ WSZYSTKIE MOJE DANE", id="btn-reset-db", classes="btn-inline -danger"))

    def on_mount(self) -> None:
        self.load_data()

    # ---------------------------------------------------------------- dane

    def load_data(self) -> None:
        y, m = get_active_month_str().split("-")
        self.query_one("#set-year", Input).value = y
        self.query_one("#set-month", Select).value = m
        with self.prevent(Checkbox.Changed, Select.Changed):
            self.query_one("#chk-skip-delete", Checkbox).value = get_setting("skip_delete_confirm") == "1"
            self.query_one("#chk-dev-mode", Checkbox).value = get_setting("dev_mode") == "1"
            self.query_one("#chk-animations", Checkbox).value = get_setting("ui_animations", "1") == "1"
            self.query_one("#set-theme", Select).value = get_setting("ui_theme", "matrix")
        self._refresh_security()
        self._refresh_sync()
        rows = get_all_users()
        self._users = {r["id"]: r["username"] for r in rows}
        sel = self.query_one("#sel-user-delete", Select)
        sel.set_options([(r["username"], r["id"]) for r in rows])
        current = getattr(self.app, "current_user_id", None)
        if current in self._users:
            sel.value = current

    def _refresh_security(self) -> None:
        p = palette()
        user = get_user_by_id(getattr(self.app, "current_user_id", "") or "")
        encrypted = getattr(self.app, "vault", None) is not None
        self.query_one("#set-enc-status", Label).update(
            Text("WŁĄCZONE — dane na dysku zaszyfrowane (AES)", style=f"bold {p.positive}") if encrypted
            else Text("wyłączone — baza zapisana jako zwykły plik", style=p.warning))
        self.query_one("#btn-encryption", Button).label = "WYŁĄCZ SZYFROWANIE" if encrypted else "WŁĄCZ SZYFROWANIE"
        yk = bool(user and int(user["yubikey_enabled"] or 0))
        self.query_one("#set-yk-status", Label).update(
            Text("WYMAGANY przy logowaniu (eksperymentalne)", style=f"bold {p.positive}") if yk
            else Text("nieaktywny (eksperymentalne)", style=p.muted))
        self.query_one("#btn-yubikey", Button).label = "WYŁĄCZ KLUCZ YUBIKEY" if yk else "ZAREJESTRUJ KLUCZ YUBIKEY"

    def _refresh_sync(self) -> None:
        from src.finance import sync

        p = palette()
        label = self.query_one("#set-sync-status", Label)
        if not sync.is_configured():
            label.update(Text("wyłączona — ustaw folder OneDrive i hasło", style=p.muted))
            return
        last = sync.get_sync_setting(sync.SET_LAST)
        info = sync.get_sync_setting(sync.SET_LAST_INFO)
        auto = "automatyczna" if sync.auto_enabled() else "ręczna (Ctrl+Y)"
        text = Text()
        text.append(f"WŁĄCZONA ({auto})", style=f"bold {p.positive}")
        text.append(f" · ostatnio {sync.format_stamp(last)}" if last else " · jeszcze nie synchronizowano",
                    style=p.muted)
        if info:
            text.append(f" · {info}", style=p.muted)
        text.append(f"\n{sync.get_sync_setting(sync.SET_FOLDER)}", style=p.muted)
        label.update(text)

    # ---------------------------------------------------------------- zdarzenia

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "set-theme" and event.value not in (None, Select.BLANK):
            event.stop()
            self.app.apply_theme(str(event.value))  # type: ignore[attr-defined]
            self.notify(f"Motyw: {dict((v, k) for k, v in theme_options())[event.value]}")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        key = {"chk-dev-mode": "dev_mode", "chk-skip-delete": "skip_delete_confirm",
               "chk-animations": "ui_animations"}.get(event.checkbox.id or "")
        if not key:
            return
        set_setting(key, "1" if event.value else "0")
        if key == "dev_mode":
            from src.utils.logging_setup import apply_debug_logging

            self.notify(f"Logi diagnostyczne: {'WŁ' if event.value else 'WYŁ'}\n{apply_debug_logging(event.value)}")
        else:
            self.notify("Zapisano ustawienie.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "set-year":
            event.stop()
            self._set_month()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        handler = {
            "btn-set-month": self._set_month,
            "btn-password": self._password,
            "btn-encryption": self._encryption,
            "btn-yubikey": self._yubikey,
            "btn-export": self._export,
            "btn-import": self._import,
            "btn-print": self._print,
            "btn-sync-setup": self._sync_setup,
            "btn-sync-now": self._sync_now,
            "btn-delete-user": self._delete_user,
            "btn-reset-db": self._reset,
        }.get(event.button.id or "")
        if handler:
            handler()

    # ---------------------------------------------------------------- akcje

    def _set_month(self) -> None:
        y = self.query_one("#set-year", Input).value.strip()
        m = self.query_one("#set-month", Select).value
        if len(y) != 4 or not y.isdigit():
            self.notify("Podaj rok w formacie RRRR.", severity="warning")
            return
        set_active_month_str(f"{y}-{m}")
        self.post_message(DataChanged(f"Miesiąc roboczy: {y}-{m}"))

    def _sync_setup(self) -> None:
        from src.screens.modals import SyncSettingsDialog

        self.open_dialog(SyncSettingsDialog(), after=lambda _: self._refresh_sync())

    def _sync_now(self) -> None:
        self.screen.action_sync_now()  # type: ignore[attr-defined]
        self._refresh_sync()

    def _password(self) -> None:
        from src.screens.modals import ChangePasswordDialog

        self.open_dialog(ChangePasswordDialog(self.app.current_username, self.app.current_user_id))  # type: ignore

    def _encryption(self) -> None:
        from src.screens.modals import EncryptionDialog

        enable = getattr(self.app, "vault", None) is None
        self.open_dialog(EncryptionDialog(self.app.current_user_id, self.app.current_username, enable),  # type: ignore
                         after=lambda _: self._refresh_security())

    def _yubikey(self) -> None:
        from src.core import yubikey
        from src.screens.modals import YubiKeyEnrollDialog

        uid = self.app.current_user_id  # type: ignore[attr-defined]
        if yubikey.is_enabled(get_user_by_id(uid)):
            def disable(result: Any) -> None:
                if result and result[0]:
                    yubikey.disable(uid)
                    self._refresh_security()
                    self.notify("Klucz YubiKey wyłączony.")

            self.app.push_screen(ConfirmDialog("Wyłączyć wymaganie klucza YubiKey przy logowaniu?",
                                               title="YUBIKEY"), disable)
            return

        def show_code(result: Any) -> None:
            self._refresh_security()
            if isinstance(result, dict) and result.get("recovery_code"):
                self.app.push_screen(InfoDialog(
                    "KOD AWARYJNY", "Klucz zarejestrowany. Zapisz kod awaryjny — pozwoli zalogować się bez klucza. "
                                    "Nie zostanie pokazany ponownie.", result["recovery_code"]))

        self.app.push_screen(YubiKeyEnrollDialog(uid, self.app.current_username), show_code)  # type: ignore

    def _export(self) -> None:
        from src.screens.modals import ExportDataDialog

        self.open_dialog(ExportDataDialog(self.app.current_username))  # type: ignore[attr-defined]

    def _import(self) -> None:
        from src.screens.modals import ImportDataDialog

        self.open_dialog(ImportDataDialog())

    def _print(self) -> None:
        from src.finance import data_io

        path = data_io.save_monthly_report(get_active_month_str(), auto_print=True)
        opened = data_io.open_for_print(path)
        self.notify(("Raport otwarty w przeglądarce (drukowanie):\n" if opened else "Zapisano raport:\n") + str(path))

    def _delete_user(self) -> None:
        from src.screens.modals import DeleteUserDialog

        target = self.query_one("#sel-user-delete", Select).value
        if target in (None, Select.BLANK):
            self.notify("Wybierz użytkownika.", severity="warning")
            return

        def after(result: Any) -> None:
            if result == "self":
                self.app.screen.action_logout(after_delete=True)  # type: ignore[attr-defined]

        self.app.push_screen(DeleteUserDialog(str(target), self._users.get(target, "?"),
                                              self.app.current_username, self.app.current_user_id),  # type: ignore
                             lambda r: (after(r), self.load_data() if r and r != "self" else None))

    def _reset(self) -> None:
        def on_answer(result: Any) -> None:
            if result and result[0]:
                reset_user_db_hard()
                self.post_message(DataChanged("Dane zostały wyczyszczone.", severity="warning"))

        self.app.push_screen(ConfirmDialog("CZY NA PEWNO WYCZYŚCIĆ WSZYSTKIE DANE?\nTransakcje, konta, koperty, cele "
                                           "i zlecenia znikną bezpowrotnie!", title="RESET DANYCH", danger=True),
                             on_answer)
