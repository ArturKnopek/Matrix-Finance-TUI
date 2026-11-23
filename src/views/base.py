"""
Wspólna baza widoków (zakładek).

Każdy widok deklaruje ACTIONS — listę akcji kontekstowych. Na ich podstawie ekran główny
buduje stopkę i obsługuje skróty (Ctrl+N, Ctrl+E, +, - …). Akcja `name` wywołuje metodę
`do_<name>()` widoku. Zmiana danych zgłaszana jest komunikatem DataChanged — ekran główny
pokazuje powiadomienie i odświeża wszystkie widoki.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from textual.message import Message

from src.finance.storage import get_setting, set_setting
from src.ui.dialogs import ConfirmDialog


@dataclass(frozen=True)
class ViewAction:
    name: str  # do_<name>()
    key: str  # etykieta klawisza w stopce, np. "^N"
    label: str  # pełna etykieta
    short: str  # krótka etykieta (wąskie okno)


class DataChanged(Message):
    """Dane się zmieniły — odśwież widoki (opcjonalnie pokaż komunikat)."""

    def __init__(self, message: str = "", check_due: bool = False, severity: str = "information") -> None:
        super().__init__()
        self.message = message
        self.check_due = check_due
        self.severity = severity


class OpenView(Message):
    """Prośba o przejście do innej zakładki (np. z pulpitu lub wyszukiwania)."""

    def __init__(self, view_id: str, select: Any = None) -> None:
        super().__init__()
        self.view_id = view_id
        self.select = select


class ViewMixin:
    """Mixin dla widoków: akcje, dialogi, potwierdzenia."""

    TITLE = ""
    ACTIONS: List[ViewAction] = []

    # --- do nadpisania ------------------------------------------------------
    def load_data(self) -> None:  # pragma: no cover - interfejs
        pass

    def focus_primary(self) -> None:
        focus_table = getattr(self, "focus_table", None)
        if callable(focus_table):
            focus_table()
        elif getattr(self, "focusable", False):
            self.focus()  # type: ignore[attr-defined]

    def select_ref(self, ref: Any) -> None:
        """Zaznacz element (np. po wyszukaniu)."""

    # --- akcje --------------------------------------------------------------
    def has_view_action(self, name: str) -> bool:
        return any(a.name == name for a in self.ACTIONS) and callable(getattr(self, f"do_{name}", None))

    def run_view_action(self, name: str) -> bool:
        handler = getattr(self, f"do_{name}", None)
        if not self.has_view_action(name) or not callable(handler):
            return False
        handler()
        return True

    # --- dialogi ------------------------------------------------------------
    def open_dialog(self, dialog: Any, after: Optional[Callable[[Any], None]] = None) -> None:
        def on_result(result: Any) -> None:
            if result is None or result is False:
                return
            if after:
                after(result)
            message = result.get("message", "") if isinstance(result, dict) else ""
            check_due = bool(result.get("check_due")) if isinstance(result, dict) else False
            self.post_message(DataChanged(message, check_due))  # type: ignore[attr-defined]

        self.app.push_screen(dialog, on_result)  # type: ignore[attr-defined]

    def confirm(self, message: str, on_yes: Callable[[], Optional[str]], danger: bool = True,
                remember: bool = True, title: str = "POTWIERDŹ") -> None:
        """Potwierdzenie (z opcją „nie pytaj ponownie” dla usuwania)."""

        def run() -> None:
            try:
                msg = on_yes()
            except ValueError as e:
                self.notify(str(e), severity="error")  # type: ignore[attr-defined]
                return
            self.post_message(DataChanged(msg or ""))  # type: ignore[attr-defined]

        if remember and get_setting("skip_delete_confirm") == "1":
            run()
            return

        def on_answer(result: Any) -> None:
            confirmed, dont_ask = result if result else (False, False)
            if dont_ask:
                set_setting("skip_delete_confirm", "1")
            if confirmed:
                run()

        self.app.push_screen(ConfirmDialog(message, show_checkbox=remember, title=title, danger=danger),  # type: ignore
                             on_answer)

    def warn_select(self, what: str = "element") -> None:
        self.notify(f"Zaznacz {what}.", severity="warning")  # type: ignore[attr-defined]
