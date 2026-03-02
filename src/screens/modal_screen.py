from __future__ import annotations
from typing import Tuple
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Input

class ConfirmationModal(ModalScreen[Tuple[bool, bool]]):
    BINDINGS = [("enter", "confirm", "Tak"), ("escape", "cancel", "Nie"), ("y", "confirm", "Tak"), ("n", "cancel", "Nie")]
    def __init__(self, message: str, show_checkbox: bool = True) -> None:
        super().__init__()
        self.message = message
        self.show_checkbox = show_checkbox
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(self.message, id="modal-msg")
            if self.show_checkbox:
                with Container(id="modal-chk"):
                    yield Checkbox("Nie pytaj ponownie", value=False, id="modal-dont-ask")
            with Horizontal(id="modal-btns"):
                yield Button("TAK", id="btn-yes", classes="btn-green")
                yield Button("NIE", id="btn-no", classes="btn-red")
    def on_mount(self) -> None:
        try: self.query_one("#btn-yes", Button).focus()
        except Exception: pass
    def _get_dont_ask_value(self) -> bool:
        if not self.show_checkbox: return False
        try: return self.query_one("#modal-dont-ask", Checkbox).value
        except Exception: return False
    def action_confirm(self) -> None: self.dismiss((True, self._get_dont_ask_value()))
    def action_cancel(self) -> None: self.dismiss((False, self._get_dont_ask_value()))
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes": self.action_confirm()
        else: self.action_cancel()

class ChangePasswordModal(ModalScreen[bool]):
    BINDINGS = [("enter", "save", "Zapisz"), ("escape", "close_modal", "Anuluj")]
    def __init__(self, username: str, user_id: str):
        super().__init__()
        self.username = username
        self.user_id = user_id
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(f"ZMIANA HASŁA — {self.username}", id="modal-msg")
            yield Input(password=True, placeholder="Stare hasło", id="old-pass")
            yield Input(password=True, placeholder="Nowe hasło", id="new-pass-1")
            yield Input(password=True, placeholder="Powtórz nowe hasło", id="new-pass-2")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("ZAPISZ", id="btn-save", classes="btn-green")
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel": self.dismiss(False)
        elif event.button.id == "btn-save": self._try_change_password()
    def action_close_modal(self) -> None: self.dismiss(False)
    def action_save(self) -> None: self._try_change_password()
    def _try_change_password(self) -> None:
        from src.core.auth import AuthService
        from src.database import get_user_by_username, update_user_password
        old_input = self.query_one("#old-pass", Input)
        p1 = self.query_one("#new-pass-1", Input).value or ""
        p2 = self.query_one("#new-pass-2", Input).value or ""
        row = get_user_by_username(self.username)
        if not row: return self.notify("Błąd użytkownika.", severity="error")
        if not AuthService.verify_password(old_input.value or "", row["password_hash"]):
            self.notify("Stare hasło jest nieprawidłowe!", severity="error")
            old_input.value = ""
            old_input.focus()
            return
        if len(p1) < 6: return self.notify("Nowe hasło musi mieć min. 6 znaków!", severity="warning")
        if p1 != p2: return self.notify("Hasła nie są identyczne!", severity="warning")
        if update_user_password(self.user_id, AuthService.hash_password(p1)):
            self.notify("Hasło zmienione.", severity="information")
            self.dismiss(True)
        else: self.notify("Błąd zmiany hasła!", severity="error")

class DeleteUserModal(ModalScreen[bool]):
    BINDINGS = [("enter", "confirm_delete", "Usuń"), ("escape", "cancel", "Anuluj")]
    def __init__(self, target_user_id: str, target_username: str, current_username: str, current_user_id: str):
        super().__init__()
        self.target_user_id = target_user_id
        self.target_username = target_username
        self.current_username = current_username
        self.current_user_id = current_user_id
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(f"USUŃ UŻYTKOWNIKA — {self.target_username}", id="modal-msg")
            yield Label("Podaj HASŁO USUWANEGO użytkownika.", classes="info-text")
            yield Input(password=True, placeholder="Hasło", id="del-pass")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("USUŃ", id="btn-delete", classes="btn-green")
    def on_mount(self) -> None:
        try: self.query_one("#del-pass", Input).focus()
        except Exception: pass
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel": self.dismiss(False)
        elif event.button.id == "btn-delete": self.action_confirm_delete()
    def action_cancel(self) -> None: self.dismiss(False)
    def action_confirm_delete(self) -> None:
        from src.core.auth import AuthService
        from src.database import get_user_by_username, delete_user
        pwd_input = self.query_one("#del-pass", Input)
        pwd = pwd_input.value or ""
        row = get_user_by_username(self.target_username)
        if not row or not AuthService.verify_password(pwd, row["password_hash"]):
            self.notify("Hasło jest nieprawidłowe!", severity="error")
            pwd_input.value = ""
            pwd_input.focus()
            return
        if delete_user(self.target_user_id):
            if str(self.target_user_id) == str(self.current_user_id):
                try:
                    if hasattr(self.app, "clear_session"): self.app.clear_session()
                    self.notify("Zostałeś wylogowany.", severity="information")
                    self.app.switch_screen("login")
                except Exception: pass
            self.notify("Usunięto użytkownika", severity="information")
            self.dismiss(True)

# ================= NOWE MODALE DLA KOPII ZAPASOWEJ =================

class ExportBackupModal(ModalScreen[bool]):
    """Modal eksportu bazy danych do Dokumentów."""
    BINDINGS = [("escape", "cancel", "Anuluj")]
    def __init__(self, current_username: str):
        super().__init__()
        self.current_username = current_username

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("EKSPORT ZASZYFROWANEJ KOPII", id="modal-msg")
            # Zmieniony tekst informacyjny:
            yield Label("Kopia danych zostanie bezpiecznie zapisana w folderze Dokumenty jako 'Matrix_Backup.matrix'.", classes="info-text")
            yield Input(password=True, placeholder="Twoje obecne hasło", id="exp-pass")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("ZAPISZ", id="btn-export", classes="btn-green")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel": self.dismiss(False)
        elif event.button.id == "btn-export": self.action_export_backup()

    def action_export_backup(self) -> None:
        from pathlib import Path
        pwd = self.query_one("#exp-pass", Input).value or ""
        from src.core.auth import AuthService
        from src.database import get_user_by_username, get_active_user_db
        from src.utils.crypto_utils import encrypt_file

        row = get_user_by_username(self.current_username)
        if not row or not AuthService.verify_password(pwd, row["password_hash"]):
            self.notify("Podane hasło jest nieprawidłowe!", severity="error")
            self.query_one("#exp-pass", Input).value = ""
            return

        # ZMIANA ŚCIEŻKI NA DOKUMENTY:
        docs_dir = Path.home() / "Documents"
        if not docs_dir.exists(): docs_dir = Path.home()
        out_file = docs_dir / "Matrix_Backup.matrix"

        source_db = get_active_user_db()
        success = encrypt_file(source_db, str(out_file), pwd)

        if success:
            self.notify(f"Zaszyfrowano bazę do: Dokumenty/Matrix_Backup.matrix", severity="information")
            self.dismiss(True)
        else:
            self.notify("Krytyczny błąd podczas tworzenia kopii!", severity="error")


class ImportBackupModal(ModalScreen[bool]):
    """Modal importu bazy danych z Dokumentów."""
    BINDINGS = [("escape", "cancel", "Anuluj")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("IMPORT KOPII ZAPASOWEJ", id="modal-msg")
            # Zmieniony tekst informacyjny:
            yield Label("Program wczyta plik 'Matrix_Backup.matrix' z folderu Dokumenty.", classes="info-text")
            yield Input(placeholder="Nowy Login (np. po zmianie komputera)", id="imp-login")
            yield Input(password=True, placeholder="Hasło (te, którym zaszyfrowano plik)", id="imp-pass")
            with Horizontal(id="modal-btns"):
                yield Button("ANULUJ", id="btn-cancel", classes="btn-red")
                yield Button("IMPORTUJ", id="btn-import", classes="btn-green")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel": self.dismiss(False)
        elif event.button.id == "btn-import": self.action_import_backup()

    def action_import_backup(self) -> None:
        from pathlib import Path
        # ZMIANA ŚCIEŻKI NA DOKUMENTY:
        docs_dir = Path.home() / "Documents"
        if not docs_dir.exists(): docs_dir = Path.home()
        backup_file = docs_dir / "Matrix_Backup.matrix"

        if not backup_file.exists():
            self.notify("Błąd: Nie znaleziono pliku Matrix_Backup.matrix w Dokumentach!", severity="error")
            return

        login = self.query_one("#imp-login", Input).value.strip()
        pwd = self.query_one("#imp-pass", Input).value or ""

        if len(login) < 3 or len(pwd) < 6:
            self.notify("Login musi mieć min. 3 znaki, a hasło min. 6 znaków.", severity="warning")
            return

        from src.core.auth import AuthService
        from src.database import init_auth_db, create_user, DATA_DIR, delete_user
        from src.utils.crypto_utils import decrypt_file

        init_auth_db()
        password_hash = AuthService.hash_password(pwd)
        ok, msg, user_id = create_user(login, password_hash)

        if not ok or not user_id:
            self.notify(msg or "Nie udało się utworzyć użytkownika.", severity="error")
            return

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        user_db_path = str(DATA_DIR / f"{user_id}.db")

        success = decrypt_file(str(backup_file), user_db_path, pwd)
        if not success:
            delete_user(user_id)
            if Path(user_db_path).exists():
                Path(user_db_path).unlink()
            self.notify("Błędne hasło lub uszkodzony plik kopii!", severity="error")
            return

        self.notify("Kopia zapasowa odzyskana! Zaloguj się.", severity="information")
        self.dismiss(True)