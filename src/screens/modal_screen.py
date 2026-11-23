from __future__ import annotations

from pathlib import Path
from typing import Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label

BACKUP_FILENAME = "Matrix_Backup.matrix"


def documents_dir() -> Path:
    docs = Path.home() / "Documents"
    return docs if docs.exists() else Path.home()


class ConfirmationModal(ModalScreen[Tuple[bool, bool]]):
    BINDINGS = [("enter", "confirm", "Tak"), ("escape", "cancel", "Nie"), ("y", "confirm", "Tak"),
                ("t", "confirm", "Tak"), ("n", "cancel", "Nie")]

    def __init__(self, message: str, show_checkbox: bool = True) -> None:
        super().__init__()
        self.message = message
        self.show_checkbox = show_checkbox

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog", classes="modal-dialog"):
            yield Label(self.message, id="modal-msg")
            if self.show_checkbox:
                with Container(id="modal-chk"):
                    yield Checkbox("Nie pytaj ponownie", value=False, id="modal-dont-ask")
            with Horizontal(id="modal-btns"):
                yield Button("TAK (T)", id="btn-yes", classes="btn-green")
                yield Button("NIE (N)", id="btn-no", classes="btn-red")

    def on_mount(self) -> None:
        self.query_one("#btn-yes", Button).focus()

    def _get_dont_ask_value(self) -> bool:
        if not self.show_checkbox:
            return False
        try:
            return self.query_one("#modal-dont-ask", Checkbox).value
        except Exception:
            return False

    def action_confirm(self) -> None:
        self.dismiss((True, self._get_dont_ask_value()))

    def action_cancel(self) -> None:
        self.dismiss((False, self._get_dont_ask_value()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-yes":
            self.action_confirm()
        else:
            self.action_cancel()


class _FormModal(ModalScreen):
    """Wspólna baza modali z polami: ESC zamyka, Enter w polu = zatwierdź."""

    BINDINGS = [("escape", "cancel", "Anuluj")]

    def action_cancel(self) -> None:
        self.dismiss(False)

    def submit(self) -> None:  # pragma: no cover - nadpisywane
        raise NotImplementedError

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        inputs = list(self.query(Input))
        if event.input in inputs and inputs.index(event.input) < len(inputs) - 1:
            inputs[inputs.index(event.input) + 1].focus()  # Enter -> następne pole
        else:
            self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-cancel":
            self.dismiss(False)
        else:
            self.submit()

    def on_mount(self) -> None:
        inputs = list(self.query(Input))
        if inputs:
            inputs[0].focus()


class ChangePasswordModal(_FormModal):
    def __init__(self, username: str, user_id: str):
        super().__init__()
        self.username = username
        self.user_id = user_id

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog", classes="modal-dialog"):
            yield Label(f"ZMIANA HASŁA — {self.username}", id="modal-msg")
            yield Input(password=True, placeholder="Stare hasło", id="old-pass", classes="standard-input")
            yield Input(password=True, placeholder="Nowe hasło (min. 6 znaków)", id="new-pass-1",
                        classes="standard-input")
            yield Input(password=True, placeholder="Powtórz nowe hasło", id="new-pass-2", classes="standard-input")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("ZAPISZ", id="btn-save", classes="btn-green")

    def submit(self) -> None:
        from src.core.auth import AuthService
        from src.database import get_user_by_username, update_user_password

        old_input = self.query_one("#old-pass", Input)
        p1 = self.query_one("#new-pass-1", Input).value or ""
        p2 = self.query_one("#new-pass-2", Input).value or ""
        row = get_user_by_username(self.username)
        if not row:
            self.notify("Błąd użytkownika.", severity="error")
            return
        if not AuthService.verify_password(old_input.value or "", row["password_hash"]):
            self.notify("Stare hasło jest nieprawidłowe!", severity="error")
            old_input.value = ""
            old_input.focus()
            return
        if len(p1) < 6:
            self.notify("Nowe hasło musi mieć min. 6 znaków!", severity="warning")
            return
        if p1 != p2:
            self.notify("Hasła nie są identyczne!", severity="warning")
            return
        if update_user_password(self.user_id, AuthService.hash_password(p1)):
            self.notify("Hasło zmienione. Pamiętaj: stare kopie zapasowe mają stare hasło.",
                        severity="information")
            self.dismiss(True)
        else:
            self.notify("Błąd zmiany hasła!", severity="error")

    # zgodność wsteczna
    action_save = submit

    def action_close_modal(self) -> None:
        self.dismiss(False)


class DeleteUserModal(_FormModal):
    """Zwraca: False (anulowano), True (usunięto innego użytkownika), "self" (usunięto siebie)."""

    def __init__(self, target_user_id: str, target_username: str, current_username: str, current_user_id: str):
        super().__init__()
        self.target_user_id = target_user_id
        self.target_username = target_username
        self.current_username = current_username
        self.current_user_id = current_user_id

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog", classes="modal-dialog"):
            yield Label(f"USUŃ UŻYTKOWNIKA — {self.target_username}", id="modal-msg")
            yield Label("Wszystkie dane tego użytkownika zostaną usunięte.\nPodaj HASŁO usuwanego użytkownika.",
                        classes="info-text")
            yield Input(password=True, placeholder="Hasło", id="del-pass", classes="standard-input")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-green")
                yield Button("USUŃ", id="btn-delete", classes="btn-red")

    def submit(self) -> None:
        from src.core.auth import AuthService
        from src.database import delete_user, get_user_by_username

        pwd_input = self.query_one("#del-pass", Input)
        row = get_user_by_username(self.target_username)
        if not row or not AuthService.verify_password(pwd_input.value or "", row["password_hash"]):
            self.notify("Hasło jest nieprawidłowe!", severity="error")
            pwd_input.value = ""
            pwd_input.focus()
            return
        if not delete_user(self.target_user_id):
            self.notify("Nie udało się usunąć użytkownika.", severity="error")
            return
        self.notify(f"Usunięto użytkownika {self.target_username}.", severity="information")
        self.dismiss("self" if str(self.target_user_id) == str(self.current_user_id) else True)

    action_confirm_delete = submit


class ExportBackupModal(_FormModal):
    """Eksport zaszyfrowanej kopii bazy do folderu Dokumenty."""

    def __init__(self, current_username: str):
        super().__init__()
        self.current_username = current_username

    def compose(self) -> ComposeResult:
        target = documents_dir() / BACKUP_FILENAME
        with Vertical(id="modal-dialog", classes="modal-dialog"):
            yield Label("EKSPORT ZASZYFROWANEJ KOPII", id="modal-msg")
            yield Label(f"Plik: {target}\nIstniejąca kopia zostanie nadpisana.", classes="info-text")
            yield Input(password=True, placeholder="Twoje obecne hasło", id="exp-pass", classes="standard-input")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("ZAPISZ", id="btn-export", classes="btn-green")

    def submit(self) -> None:
        from src.core.auth import AuthService
        from src.database import export_encrypted_backup, get_user_by_username

        pwd_input = self.query_one("#exp-pass", Input)
        pwd = pwd_input.value or ""
        row = get_user_by_username(self.current_username)
        if not row or not AuthService.verify_password(pwd, row["password_hash"]):
            self.notify("Podane hasło jest nieprawidłowe!", severity="error")
            pwd_input.value = ""
            return

        out_file = documents_dir() / BACKUP_FILENAME
        if export_encrypted_backup(str(out_file), pwd):
            self.notify(f"Zapisano zaszyfrowaną kopię:\n{out_file}", severity="information")
            self.dismiss(True)
        else:
            self.notify("Krytyczny błąd podczas tworzenia kopii!", severity="error")

    action_export_backup = submit


class ImportBackupModal(_FormModal):
    """Import kopii z folderu Dokumenty jako nowe konto użytkownika."""

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog", classes="modal-dialog"):
            yield Label("IMPORT KOPII ZAPASOWEJ", id="modal-msg")
            yield Label(f"Plik: {documents_dir() / BACKUP_FILENAME}", classes="info-text")
            yield Input(placeholder="Nowy login (np. po zmianie komputera)", id="imp-login",
                        classes="standard-input")
            yield Input(password=True, placeholder="Hasło, którym zaszyfrowano kopię", id="imp-pass",
                        classes="standard-input")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("IMPORTUJ", id="btn-import", classes="btn-green")

    def submit(self) -> None:
        backup_file = documents_dir() / BACKUP_FILENAME
        if not backup_file.exists():
            self.notify(f"Nie znaleziono pliku {backup_file}", severity="error")
            return

        login = self.query_one("#imp-login", Input).value.strip()
        pwd = self.query_one("#imp-pass", Input).value or ""
        if len(login) < 3 or " " in login or len(pwd) < 6:
            self.notify("Login: min. 3 znaki bez spacji, hasło: min. 6 znaków.", severity="warning")
            return

        from src.core.auth import AuthService
        from src.database import DATA_DIR, create_user, delete_user, init_auth_db, init_user_db
        from src.utils.crypto_utils import decrypt_file

        init_auth_db()
        ok, msg, user_id = create_user(login, AuthService.hash_password(pwd))
        if not ok or not user_id:
            self.notify(msg or "Nie udało się utworzyć użytkownika.", severity="error")
            return

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        user_db_path = DATA_DIR / f"{user_id}.db"
        if not decrypt_file(str(backup_file), str(user_db_path), pwd):
            delete_user(user_id)
            user_db_path.unlink(missing_ok=True)
            self.notify("Błędne hasło lub uszkodzony plik kopii!", severity="error")
            return

        try:
            init_user_db(str(user_db_path))  # migracja schematu starszych kopii
        except Exception as e:
            delete_user(user_id)
            user_db_path.unlink(missing_ok=True)
            self.notify(f"Plik kopii nie jest poprawną bazą: {e}", severity="error")
            return

        self.notify("Kopia zapasowa odzyskana! Zaloguj się.", severity="information")
        self.dismiss(True)

    action_import_backup = submit


HELP_SECTIONS = [
    ("NAWIGACJA", [
        ("1 – 7", "przełączanie zakładek"),
        ("↑ ↓ / Tab", "poruszanie się po menu i polach"),
        ("Enter", "wejście do zakładki / edycja wiersza / zapis"),
        ("ESC", "anuluj formularz · powrót do menu"),
        ("F2 / Ctrl+B", "pokaż/ukryj menu boczne"),
        ("PgUp / PgDn", "poprzednia / następna strona tabeli"),
    ]),
    ("DANE", [
        ("Ctrl+N", "nowy element"),
        ("Ctrl+E", "edytuj zaznaczony"),
        ("Ctrl+D", "usuń zaznaczony"),
        ("Ctrl+S", "zapisz formularz"),
        ("Ctrl+P", "pauza / wznowienie płatności cyklicznej"),
        ("+ / -", "wpłata / wypłata (Skarbonki)"),
        ("/", "szukaj (Transakcje)"),
        ("Ctrl+R", "odśwież i zaksięguj zaległe płatności"),
    ]),
    ("FORMULARZE", [
        ("Data", "puste = dziś · 12 · 12.05 · 12.05.2026 · wczoraj"),
        ("Kwota", "12,50 · 1 200 · działania: 12.5+3*2"),
    ]),
    ("SYSTEM", [
        ("F1", "ta pomoc"),
        ("Ctrl+L", "wyloguj"),
        ("Ctrl+Q", "wyjście"),
    ]),
]


class HelpModal(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Zamknij"), ("f1", "close", "Zamknij"), ("enter", "close", "Zamknij"),
                ("q", "close", "Zamknij")]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog", classes="modal-dialog"):
            yield Label("POMOC — SKRÓTY KLAWISZOWE", id="modal-msg")
            with VerticalScroll(id="help-body"):
                for title, rows in HELP_SECTIONS:
                    yield Label(title, classes="separator-line")
                    for key, desc in rows:
                        line = Text()
                        line.append(f"{key:>12}  ", style="bold #00FF41")
                        line.append(desc, style="#dddddd")
                        yield Label(line, classes="help-row")
            with Horizontal(id="modal-btns"):
                yield Button("ZAMKNIJ (ESC)", id="btn-close", classes="btn-green")

    def on_mount(self) -> None:
        self.query_one("#btn-close", Button).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)
