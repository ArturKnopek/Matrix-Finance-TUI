"""
Okna systemowe: pomoc, wyszukiwanie globalne, bezpieczeństwo (hasło, szyfrowanie, YubiKey),
eksport/import danych, usuwanie użytkownika, import kopii przy logowaniu.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Select
from textual.widgets.option_list import Option

from src.core.auth import AuthService
from src.finance import data_io
from src.finance.analytics import SearchHit, search_everything
from src.finance.storage import (
    DATA_DIR,
    create_user,
    delete_user,
    get_active_month_str,
    get_user_by_id,
    get_user_by_username,
    init_auth_db,
    init_user_db,
    update_user_password,
)
from src.ui.dialogs import ConfirmDialog, Dialog, FormDialog, FormError, InfoDialog, form_row
from src.ui.theme import palette
from src.utils.crypto_utils import decrypt_file

BACKUP_FILENAME = "Matrix_Backup.matrix"


def documents_dir() -> Path:
    docs = Path.home() / "Documents"
    return docs if docs.exists() else Path.home()


def password_input(widget_id: str, placeholder: str) -> Input:
    return Input(password=True, placeholder=placeholder, id=widget_id, classes="row-input")


# =============================================================================
# Pomoc
# =============================================================================

HELP_SECTIONS = [
    ("NAWIGACJA", [
        ("1 – 9", "przełączanie zakładek"),
        ("[  ]", "poprzedni / następny miesiąc roboczy"),
        ("Ctrl+F", "szukaj wszędzie (transakcje, konta, koperty, cele, zlecenia)"),
        ("↑ ↓ / Tab", "poruszanie się po menu, tabelach i polach"),
        ("Enter", "otwórz / edytuj zaznaczone"),
        ("ESC", "zamknij okno · wróć do menu"),
        ("F2 / Ctrl+B", "pokaż / ukryj menu boczne"),
        ("PgUp / PgDn", "strony tabel"),
    ]),
    ("OPERACJE", [
        ("Ctrl+N", "nowy element w bieżącej zakładce (na pulpicie: transakcja)"),
        ("Ctrl+T", "przelew między kontami (z każdego miejsca)"),
        ("Ctrl+E / Ctrl+D", "edytuj / usuń zaznaczone"),
        ("+ / -", "wpłata / wypłata (konta, cele)"),
        ("K", "korekta: saldo konta · stan koperty · stan celu"),
        ("M", "Koperty: przesuń środki do innej koperty"),
        ("W / A / O", "Konta: wycena lub odsetki / auto-oszczędzanie / wpłata zewnętrzna"),
        ("Ctrl+P", "pauza zlecenia / reguły"),
        ("Ctrl+R", "odśwież, zaksięguj zlecenia i rozlicz lokaty"),
    ]),
    ("FORMULARZE", [
        ("Enter", "następne pole (w ostatnim — zapis)"),
        ("Ctrl+S", "zapisz"),
        ("Data", "puste = dziś · 12 · 12.05 · 12.05.2026 · wczoraj"),
        ("Kwota", "12,50 · 1 200 · działania: 12.5+3*2"),
    ]),
    ("SYSTEM", [
        ("F1", "pomoc"),
        ("Ctrl+L", "wyloguj (zaszyfrowana baza zostaje zapisana)"),
        ("Ctrl+Q", "wyjście"),
    ]),
]


class HelpDialog(Dialog):
    TITLE_TEXT = "POMOC — SKRÓTY KLAWISZOWE"
    VARIANT = "info"
    WIDE = True
    BINDINGS = [Binding("escape", "cancel", show=False), Binding("f1", "cancel", show=False),
                Binding("q", "cancel", show=False)]

    def compose_body(self) -> Iterable[Widget]:
        p = palette()
        for title, rows in HELP_SECTIONS:
            yield Label(title, classes="section-title")
            for key, desc in rows:
                line = Text()
                line.append(f"{key:>16}  ", style=f"bold {p.accent}")
                line.append(desc, style=p.text)
                yield Label(line, classes="help-row")

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button("ZAMKNIJ (ESC)", id="btn-cancel", classes="btn-primary")

    def focus_first(self) -> None:
        self.query_one("#btn-cancel", Button).focus()


HelpModal = HelpDialog


# =============================================================================
# Wyszukiwanie globalne
# =============================================================================

KIND_LABELS = {"transaction": "Transakcja", "account": "Konto", "envelope": "Koperta", "goal": "Cel",
               "recurring": "Zlecenie", "view": "Przejdź"}


class SearchDialog(Dialog):
    """Szukaj wszędzie. Wynik: SearchHit wybranego elementu (albo None)."""

    TITLE_TEXT = "SZUKAJ WSZĘDZIE"
    HINT = "↑↓ — wybór · Enter — otwórz · ESC — zamknij"
    WIDE = True
    BINDINGS = [Binding("escape", "cancel", show=False), Binding("down", "focus_results", show=False)]

    def __init__(self, views: Optional[List[SearchHit]] = None) -> None:
        super().__init__()
        self.views = views or []
        self.hits: List[SearchHit] = []

    def compose_body(self) -> Iterable[Widget]:
        yield Input(placeholder="wpisz nazwę, kwotę, kod (TX…), konto, kopertę…", id="search-input",
                    classes="row-input")
        yield OptionList(id="search-results")
        yield Label("", id="search-count", classes="dialog-note")

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button("ZAMKNIJ", id="btn-cancel", classes="btn-secondary")

    def on_mount(self) -> None:
        super().on_mount()
        self._show("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._show(event.value)

    def _show(self, query: str) -> None:
        q = query.strip().lower()
        views = [h for h in self.views if q and (q in h.title.lower() or q in h.detail.lower())] if q \
            else list(self.views)
        self.hits = views + (search_everything(q) if len(q) >= 2 else [])
        options = self.query_one("#search-results", OptionList)
        options.clear_options()
        p = palette()
        for i, hit in enumerate(self.hits):
            text = Text()
            text.append(f"{KIND_LABELS.get(hit.kind, hit.kind):<11}", style=p.muted)
            text.append(hit.title, style=f"bold {p.text}")
            text.append(f"  {hit.detail}", style=p.muted)
            options.add_option(Option(text, id=str(i)))
        count = len(self.hits) - len(views)
        self.query_one("#search-count", Label).update(
            "wpisz min. 2 znaki" if len(q) < 2 else f"znaleziono: {count}" if count else "brak wyników")
        if self.hits:
            options.highlighted = 0

    def action_focus_results(self) -> None:
        self.query_one("#search-results", OptionList).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.hits:
            idx = self.query_one("#search-results", OptionList).highlighted or 0
            self.dismiss(self.hits[idx])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.hits[int(event.option.id)])


# =============================================================================
# Hasło / użytkownicy
# =============================================================================

class ChangePasswordDialog(FormDialog):
    def __init__(self, username: str, user_id: str) -> None:
        super().__init__(f"ZMIANA HASŁA — {username}")
        self.username, self.user_id = username, user_id

    def compose_body(self) -> Iterable[Widget]:
        yield form_row("Stare hasło:", password_input("f-old", "obecne hasło"))
        yield form_row("Nowe hasło:", password_input("f-new1", "min. 6 znaków"))
        yield form_row("Powtórz:", password_input("f-new2", "powtórz nowe hasło"))

    def submit_form(self) -> Any:
        row = get_user_by_username(self.username)
        if not row or not AuthService.verify_password(self.value("f-old") or "", row["password_hash"]):
            raise FormError("Stare hasło jest nieprawidłowe.", "f-old")
        new = self.query_one("#f-new1", Input).value
        if len(new) < 6:
            raise FormError("Nowe hasło musi mieć min. 6 znaków.", "f-new1")
        if new != self.query_one("#f-new2", Input).value:
            raise FormError("Hasła nie są identyczne.", "f-new2")
        if not update_user_password(self.user_id, AuthService.hash_password(new)):
            raise FormError("Nie udało się zmienić hasła.")
        vault = getattr(self.app, "vault", None)
        if vault is not None:
            vault.rekey(new)
        return {"message": "Hasło zmienione. Uwaga: wcześniejsze kopie zapasowe mają stare hasło."}


ChangePasswordModal = ChangePasswordDialog


class DeleteUserDialog(FormDialog):
    """Wynik: "self" (usunięto zalogowanego), True (innego), None (anulowano)."""

    VARIANT = "danger"
    SAVE_LABEL = "USUŃ"

    def __init__(self, target_user_id: str, target_username: str, current_username: str, current_user_id: str):
        super().__init__(f"USUŃ UŻYTKOWNIKA — {target_username}", "danger")
        self.target_user_id, self.target_username = target_user_id, target_username
        self.current_user_id = current_user_id

    def compose_body(self) -> Iterable[Widget]:
        yield Label("Wszystkie dane tego użytkownika zostaną bezpowrotnie usunięte.", classes="dialog-note")
        yield form_row("Hasło użytkownika:", password_input("f-pass", "hasło usuwanego użytkownika"))

    def submit_form(self) -> Any:
        row = get_user_by_username(self.target_username)
        if not row or not AuthService.verify_password(self.query_one("#f-pass", Input).value, row["password_hash"]):
            raise FormError("Hasło jest nieprawidłowe.", "f-pass")
        if str(self.target_user_id) == str(self.current_user_id):
            vault = getattr(self.app, "vault", None)
            if vault is not None:
                vault.close()
                self.app.vault = None
        if not delete_user(self.target_user_id):
            raise FormError("Nie udało się usunąć użytkownika.")
        return "self" if str(self.target_user_id) == str(self.current_user_id) else True


DeleteUserModal = DeleteUserDialog


# =============================================================================
# Szyfrowanie danych na dysku
# =============================================================================

class EncryptionDialog(FormDialog):
    """Włączenie / wyłączenie szyfrowania bazy na dysku (wymaga hasła)."""

    def __init__(self, user_id: str, username: str, enable: bool) -> None:
        self.user_id, self.username, self.enable = user_id, username, enable
        super().__init__("WŁĄCZ SZYFROWANIE DANYCH" if enable else "WYŁĄCZ SZYFROWANIE DANYCH",
                         None if enable else "danger")
        self.SAVE_LABEL = "WŁĄCZ" if enable else "WYŁĄCZ"

    def compose_body(self) -> Iterable[Widget]:
        if self.enable:
            yield Label("Baza będzie przechowywana na dysku wyłącznie w postaci zaszyfrowanej (AES, klucz z "
                        "hasła). Podczas pracy dane są tylko w pamięci. Bez hasła nie da się ich odczytać — "
                        "zrób też kopię zapasową.", classes="dialog-note")
        else:
            yield Label("Baza zostanie zapisana na dysku jako zwykły (niezaszyfrowany) plik.", classes="dialog-note")
        yield form_row("Hasło:", password_input("f-pass", "Twoje hasło"))

    def submit_form(self) -> Any:
        from src.core.vault import DataVault

        password = self.query_one("#f-pass", Input).value
        row = get_user_by_username(self.username)
        if not row or not AuthService.verify_password(password, row["password_hash"]):
            raise FormError("Hasło jest nieprawidłowe.", "f-pass")
        if self.enable:
            self.app.vault = DataVault.enable(self.user_id, password)
            return {"message": "Szyfrowanie włączone. Dane na dysku są zaszyfrowane."}
        vault = getattr(self.app, "vault", None)
        if vault is None:
            raise FormError("Sesja nie jest zaszyfrowana.")
        vault.disable()
        self.app.vault = None
        return {"message": "Szyfrowanie wyłączone."}


# =============================================================================
# YubiKey
# =============================================================================

class YubiKeyEnrollDialog(FormDialog):
    """Rejestracja klucza (EKSPERYMENTALNE). Po sukcesie pokazuje kod awaryjny."""

    SAVE_LABEL = "ZAREJESTRUJ"

    def __init__(self, user_id: str, username: str) -> None:
        super().__init__("KLUCZ YUBIKEY (EKSPERYMENTALNE)")
        self.user_id, self.username = user_id, username

    def compose_body(self) -> Iterable[Widget]:
        from src.core import yubikey

        status = "znaleziono" if yubikey.backend_available() else "NIE znaleziono (pip install yubikey-manager)"
        yield Label("Klucz będzie wymagany przy logowaniu (po haśle). Przygotuj slot poleceniem:\n"
                    "  ykman otp chalresp --generate --touch 2", classes="dialog-note")
        yield form_row("Program ykman:", Label(status, classes="row-value"))
        yield form_row("Slot klucza:", Select([("2 (zalecany)", "2"), ("1", "1")], value="2", id="f-slot",
                                              allow_blank=False, classes="row-select"))
        yield form_row("Hasło:", password_input("f-pass", "potwierdź hasłem"))

    def submit_form(self) -> Any:
        from src.core import yubikey

        row = get_user_by_username(self.username)
        if not row or not AuthService.verify_password(self.query_one("#f-pass", Input).value, row["password_hash"]):
            raise FormError("Hasło jest nieprawidłowe.", "f-pass")
        try:
            code = yubikey.enroll(self.user_id, int(self.value("f-slot")))
        except yubikey.YubiKeyError as e:
            raise FormError(f"Klucz: {e}") from e
        return {"recovery_code": code}


class YubiKeyLoginDialog(Dialog):
    """Drugi krok logowania. Wynik: True (zweryfikowano) / None (anulowano)."""

    TITLE_TEXT = "WERYFIKACJA KLUCZEM YUBIKEY"
    HINT = "Dotknij klucza · ESC — anuluj"

    def __init__(self, user_id: str) -> None:
        super().__init__()
        self.user_id = user_id

    def compose_body(self) -> Iterable[Widget]:
        yield Label("Włóż klucz YubiKey i dotknij go, gdy zacznie migać…", id="yk-status")
        yield form_row("Kod awaryjny:", Input(placeholder="XXXX-XXXX-XXXX-XXXX (gdy nie masz klucza)",
                                              id="f-recovery", classes="row-input"))

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button("PONÓW", id="btn-retry", classes="btn-primary")
        yield Button("ANULUJ", id="btn-cancel", classes="btn-secondary")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#btn-retry", Button).focus()
        self.verify_key()

    @work(thread=True, exclusive=True)
    def verify_key(self) -> None:
        from src.core import yubikey

        try:
            ok = yubikey.verify(self.user_id)
        except yubikey.YubiKeyError as e:
            self.app.call_from_thread(self._status, f"⚠ {e}")
            return
        if ok:
            self.app.call_from_thread(self.dismiss, True)
        else:
            self.app.call_from_thread(self._status, "⚠ To nie jest zarejestrowany klucz.")

    def _status(self, text: str) -> None:
        self.query_one("#yk-status", Label).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        from src.core import yubikey

        event.stop()
        if yubikey.verify_recovery_code(self.user_id, event.value):
            self.dismiss(True)
        else:
            self.show_error("Nieprawidłowy kod awaryjny.", "f-recovery")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-retry":
            self._status("Dotknij klucza…")
            self.verify_key()
        else:
            self.dismiss(None)


# =============================================================================
# Eksport / import danych
# =============================================================================

EXPORT_FORMATS = [
    ("Pełny eksport JSON (czytelny)", "json"),
    ("Pełny eksport zaszyfrowany (.mfx)", "mfx"),
    ("Transakcje CSV (Excel)", "csv"),
    ("Kopia całej bazy .matrix (do importu jako nowy użytkownik)", "matrix"),
]


class ExportDataDialog(FormDialog):
    SAVE_LABEL = "EKSPORTUJ"
    WIDE = True

    def __init__(self, username: str = "") -> None:
        super().__init__("EKSPORT DANYCH")
        self.username = username

    def compose_body(self) -> Iterable[Widget]:
        yield form_row("Format:", Select(EXPORT_FORMATS, value="json", id="f-format", allow_blank=False,
                                         classes="row-select"))
        yield form_row("Plik:", Input(id="f-path", classes="row-input"))
        yield form_row("", Checkbox("Tylko bieżący miesiąc (CSV)", id="f-month"), row_id="row-month",
                       classes="checkbox-row")
        yield form_row("Hasło szyfrowania:", password_input("f-pass", "min. 6 znaków"), row_id="row-pass")
        yield Label("", id="f-format-note", classes="dialog-note")

    def on_mount(self) -> None:
        super().on_mount()
        self._apply()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply()

    def _default_path(self, fmt: str) -> Path:
        folder = data_io.default_export_dir()
        if fmt == "matrix":
            return documents_dir() / BACKUP_FILENAME
        ext = {"json": "json", "mfx": "mfx", "csv": "csv"}[fmt]
        return folder / f"matrix_finance_{data_io.timestamp()}.{ext}"

    def _apply(self) -> None:
        fmt = self.value("f-format")
        self.query_one("#f-path", Input).value = str(self._default_path(fmt))
        self.toggle_row("row-pass", fmt in ("mfx", "matrix"))
        self.toggle_row("row-month", fmt == "csv")
        notes = {
            "json": "Wszystkie dane w czytelnym formacie JSON — NIEZASZYFROWANE.",
            "mfx": "Wszystkie dane zaszyfrowane hasłem (AES). Import: Ustawienia → Import danych.",
            "csv": "Transakcje (średnik, UTF-8) — otwiera się w Excelu / Arkuszach.",
            "matrix": "Zaszyfrowana kopia bazy. Import na ekranie logowania jako nowy użytkownik.",
        }
        self.query_one("#f-format-note", Label).update(notes[fmt])

    def submit_form(self) -> Any:
        fmt = self.value("f-format")
        path = Path(self.value("f-path") or str(self._default_path(fmt))).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        password = self.query_one("#f-pass", Input).value
        if fmt in ("mfx", "matrix") and len(password) < 6:
            raise FormError("Hasło szyfrowania musi mieć min. 6 znaków.", "f-pass")
        if fmt == "json":
            data_io.export_json(str(path))
        elif fmt == "mfx":
            data_io.export_json(str(path), password)
        elif fmt == "csv":
            count = data_io.export_transactions_csv(str(path), get_active_month_str() if self.value("f-month") else None)
            return {"message": f"Zapisano {count} transakcji:\n{path}"}
        else:
            if not data_io.export_encrypted_backup(str(path), password):
                raise FormError("Nie udało się zapisać kopii.")
        return {"message": f"Zapisano:\n{path}"}


class ImportDataDialog(FormDialog):
    SAVE_LABEL = "IMPORTUJ"
    VARIANT = "danger"
    WIDE = True

    def __init__(self) -> None:
        super().__init__("IMPORT DANYCH", "danger")

    def compose_body(self) -> Iterable[Widget]:
        yield form_row("Rodzaj:", Select([("Pełne dane (.json / .mfx) — ZASTĄPI obecne", "full"),
                                          ("Transakcje z CSV — dopisze do historii", "csv")],
                                         value="full", id="f-kind", allow_blank=False, classes="row-select"))
        yield form_row("Plik:", Input(str(data_io.default_export_dir()) + "/", id="f-path", classes="row-input"))
        yield form_row("Hasło (.mfx):", password_input("f-pass", "tylko dla plików zaszyfrowanych"),
                       row_id="row-pass")
        yield form_row("", Checkbox("Aktualizuj salda kont (CSV)", id="f-balances"), row_id="row-balances",
                       classes="checkbox-row")
        yield Label("", id="f-note", classes="dialog-note")

    def on_mount(self) -> None:
        super().on_mount()
        self._apply()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply()

    def _apply(self) -> None:
        full = self.value("f-kind") == "full"
        self.toggle_row("row-pass", full)
        self.toggle_row("row-balances", not full)
        self.query_one("#f-note", Label).update(
            "UWAGA: pełny import usuwa wszystkie obecne dane i wczytuje dane z pliku." if full else
            "Kolumny: data;typ;kategoria;konto;sklep;kwota;opis (format eksportu CSV).")

    def submit_form(self) -> Any:
        path = Path(self.value("f-path") or "").expanduser()
        if not path.is_file():
            raise FormError("Nie znaleziono pliku.", "f-path")
        if self.value("f-kind") == "full":
            try:
                counts = data_io.import_json(str(path), self.query_one("#f-pass", Input).value or None)
            except ValueError as e:
                raise FormError(str(e), "f-pass") from e
            return {"message": f"Zaimportowano: {counts.get('transactions', 0)} transakcji, "
                               f"{counts.get('accounts', 0)} kont."}
        imported, errors = data_io.import_transactions_csv(str(path), bool(self.value("f-balances")))
        extra = f" Błędy: {len(errors)} (np. {errors[0]})" if errors else ""
        return {"message": f"Zaimportowano {imported} transakcji.{extra}"}


ExportBackupModal = ExportDataDialog


class ImportBackupDialog(FormDialog):
    """Ekran logowania: odtworzenie kopii .matrix jako nowy użytkownik."""

    SAVE_LABEL = "IMPORTUJ"

    def __init__(self) -> None:
        super().__init__("IMPORT KOPII ZAPASOWEJ")

    def compose_body(self) -> Iterable[Widget]:
        yield form_row("Plik kopii:", Input(str(documents_dir() / BACKUP_FILENAME), id="f-path", classes="row-input"))
        yield form_row("Nowy login:", Input(placeholder="min. 3 znaki", id="f-login", classes="row-input"))
        yield form_row("Hasło kopii:", password_input("f-pass", "hasło, którym zaszyfrowano kopię"))

    def submit_form(self) -> Any:
        backup_file = Path(self.value("f-path")).expanduser()
        if not backup_file.exists():
            raise FormError(f"Nie znaleziono pliku {backup_file}", "f-path")
        login = self.value("f-login")
        pwd = self.query_one("#f-pass", Input).value
        if len(login) < 3 or " " in login:
            raise FormError("Login: min. 3 znaki, bez spacji.", "f-login")
        if len(pwd) < 6:
            raise FormError("Hasło: min. 6 znaków.", "f-pass")
        init_auth_db()
        ok, msg, user_id = create_user(login, AuthService.hash_password(pwd))
        if not ok or not user_id:
            raise FormError(msg or "Nie udało się utworzyć użytkownika.", "f-login")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        target = DATA_DIR / f"{user_id}.db"
        if not decrypt_file(str(backup_file), str(target), pwd):
            delete_user(user_id)
            raise FormError("Błędne hasło lub uszkodzony plik kopii.", "f-pass")
        try:
            init_user_db(str(target))
        except Exception as e:
            delete_user(user_id)
            raise FormError(f"Plik nie jest poprawną kopią: {e}") from e
        return {"message": "Kopia odzyskana — zaloguj się nowym loginem."}


ImportBackupModal = ImportBackupDialog

__all__ = [
    "ChangePasswordDialog", "ConfirmDialog", "DeleteUserDialog", "EncryptionDialog", "ExportDataDialog",
    "HelpDialog", "ImportBackupDialog", "ImportDataDialog", "InfoDialog", "SearchDialog", "YubiKeyEnrollDialog",
    "YubiKeyLoginDialog", "get_user_by_id",
]
