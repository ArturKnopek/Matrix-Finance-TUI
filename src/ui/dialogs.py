"""
Okna dialogowe — wspólny wygląd i zachowanie.

    Dialog         – ramka z tytułem, treść, komunikat błędu, przyciski, podpowiedź klawiszy
    ConfirmDialog  – pytanie TAK/NIE (wariant „danger” na czerwono)
    FormDialog     – formularz: Enter przechodzi do kolejnego pola, Ctrl+S zapisuje, ESC zamyka;
                     błąd walidacji pokazuje się w okienku (pole z błędem dostaje fokus)
    InfoDialog     – komunikat z przyciskiem OK
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, Select


def form_row(label: str, *widgets: Widget, row_id: Optional[str] = None, classes: str = "") -> Horizontal:
    """Wiersz formularza: etykieta o stałej szerokości + pole wypełniające resztę."""
    return Horizontal(Label(label, classes="row-label"), *widgets, id=row_id, classes=f"form-row {classes}".strip())


class FormError(Exception):
    """Błąd walidacji; `field` = id pola, które powinno dostać fokus."""

    def __init__(self, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.field = field


class Dialog(ModalScreen):
    """Bazowe okno: nadpisz compose_body() i compose_buttons()."""

    TITLE_TEXT = ""
    VARIANT = "default"  # default | danger | info
    HINT = "ESC — zamknij"
    WIDE = False

    BINDINGS = [Binding("escape", "cancel", "Zamknij", show=False)]

    def __init__(self, title: Optional[str] = None, variant: Optional[str] = None) -> None:
        super().__init__()
        self.dialog_title = title or self.TITLE_TEXT
        self.variant = variant or self.VARIANT

    def compose(self) -> ComposeResult:
        classes = f"dialog -{self.variant}" + (" -wide" if self.WIDE else "")
        with Vertical(id="dialog", classes=classes) as box:
            box.border_title = f" {self.dialog_title} "
            box.border_subtitle = self.HINT
            with VerticalScroll(id="dialog-body"):
                yield from self.compose_body()
            yield Label("", id="dialog-error")
            with Horizontal(id="dialog-buttons"):
                yield from self.compose_buttons()

    def compose_body(self) -> Iterable[Widget]:
        return []

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button("ZAMKNIJ", id="btn-cancel", classes="btn-secondary")

    def show_error(self, message: str, field: Optional[str] = None) -> None:
        label = self.query_one("#dialog-error", Label)
        label.update(f"⚠ {message}" if message else "")
        label.display = bool(message)
        if field:
            try:
                self.query_one(f"#{field}").focus()
            except Exception:
                pass

    def on_mount(self) -> None:
        self.query_one("#dialog-error", Label).display = False
        self.focus_first()

    def focus_first(self) -> None:
        for widget in self.query("#dialog-body Input, #dialog-body Select, #dialog-body Checkbox").results():
            if widget.display and not widget.disabled:
                widget.focus()
                return
        try:
            self.query_one("#dialog-buttons Button").focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-cancel":
            self.action_cancel()


class ConfirmDialog(Dialog):
    """Pytanie TAK/NIE. Wynik: (potwierdzono, „nie pytaj ponownie”)."""

    HINT = "T/Enter — tak · N/ESC — nie"
    BINDINGS = [
        Binding("escape", "cancel", "Nie", show=False),
        Binding("n", "cancel", "Nie", show=False),
        Binding("t", "confirm", "Tak", show=False),
        Binding("y", "confirm", "Tak", show=False),
    ]

    def __init__(self, message: str, show_checkbox: bool = False, title: str = "POTWIERDŹ",
                 danger: bool = False, yes: str = "TAK", no: str = "NIE") -> None:
        super().__init__(title, "danger" if danger else "default")
        self.message = message
        self.show_checkbox = show_checkbox
        self.yes, self.no = yes, no

    def compose_body(self) -> Iterable[Widget]:
        yield Label(self.message, id="confirm-message")
        if self.show_checkbox:
            yield Checkbox("Nie pytaj ponownie", id="confirm-dont-ask")

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button(f"{self.yes} (T)", id="btn-yes", classes="btn-danger" if self.variant == "danger" else "btn-primary")
        yield Button(f"{self.no} (N)", id="btn-cancel", classes="btn-secondary")

    def focus_first(self) -> None:
        self.query_one("#btn-yes", Button).focus()

    def _dont_ask(self) -> bool:
        return bool(self.show_checkbox and self.query_one("#confirm-dont-ask", Checkbox).value)

    def action_confirm(self) -> None:
        self.dismiss((True, self._dont_ask()))

    def action_cancel(self) -> None:
        self.dismiss((False, self._dont_ask()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_confirm() if event.button.id == "btn-yes" else self.action_cancel()


ConfirmationModal = ConfirmDialog  # zgodność wsteczna


class InfoDialog(Dialog):
    VARIANT = "info"
    HINT = "Enter / ESC — zamknij"

    def __init__(self, title: str, message: str, copyable: str = "") -> None:
        super().__init__(title)
        self.message = message
        self.copyable = copyable

    def compose_body(self) -> Iterable[Widget]:
        yield Label(self.message, id="info-message")
        if self.copyable:
            yield Input(self.copyable, id="info-copy", classes="row-input")

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button("OK", id="btn-cancel", classes="btn-primary")

    def focus_first(self) -> None:
        self.query_one("#btn-cancel", Button).focus()


class FormDialog(Dialog):
    """
    Formularz. Podklasa implementuje:
        compose_body()  – pola (użyj form_row),
        submit_form()   – walidacja + zapis; zwraca wynik (dismiss) albo rzuca FormError.
    """

    HINT = "Enter — dalej · Ctrl+S — zapisz · ESC — anuluj"
    SAVE_LABEL = "ZAPISZ"
    BINDINGS = [
        Binding("escape", "cancel", "Anuluj", show=False),
        Binding("ctrl+s", "submit", "Zapisz", show=False),
    ]

    def compose_buttons(self) -> Iterable[Widget]:
        yield Button(f"{self.SAVE_LABEL} (^S)", id="btn-save", classes="btn-primary")
        yield Button("ANULUJ (ESC)", id="btn-cancel", classes="btn-secondary")

    def submit_form(self) -> Any:  # pragma: no cover - nadpisywane
        raise NotImplementedError

    def action_submit(self) -> None:
        try:
            result = self.submit_form()
        except FormError as e:
            self.show_error(str(e), e.field)
            return
        except ValueError as e:  # błędy silnika (np. brak środków)
            self.show_error(str(e))
            return
        self.dismiss(result if result is not None else True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-save":
            self.action_submit()
        elif event.button.id == "btn-cancel":
            self.action_cancel()

    def _visible_inputs(self) -> list:
        return [w for w in self.query("#dialog-body Input").results()
                if w.display and not w.disabled and all(a.display for a in w.ancestors if isinstance(a, Widget))]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        inputs = self._visible_inputs()
        if event.input in inputs and inputs.index(event.input) < len(inputs) - 1:
            inputs[inputs.index(event.input) + 1].focus()
        else:
            self.action_submit()

    # ------------------------------------------------------------- helpers

    def value(self, widget_id: str) -> Any:
        widget = self.query_one(f"#{widget_id}")
        val = getattr(widget, "value", None)
        if isinstance(widget, Select) and val is Select.BLANK:
            return None
        return val.strip() if isinstance(val, str) else val

    def set_value(self, widget_id: str, value: Any) -> None:
        widget = self.query_one(f"#{widget_id}")
        if isinstance(widget, Select):
            try:
                widget.value = Select.BLANK if value in (None, "") else value
            except Exception:  # wartości nie ma na liście -> zostaw puste (jeśli wolno)
                try:
                    widget.clear()
                except Exception:
                    pass
            return
        widget.value = value  # type: ignore[attr-defined]

    def toggle_row(self, row_id: str, visible: bool) -> None:
        self.query_one(f"#{row_id}").display = visible


def select_options_with_current(options: list, current: Optional[str]) -> list:
    """Dodaje bieżącą wartość do listy opcji, gdy jej tam nie ma (np. konto nieaktywne)."""
    if current and current not in {v for _, v in options}:
        return options + [(f"{current} (nieaktywne)", current)]
    return options


def parse_required_amount(raw: str, field: str, allow_zero: bool = False) -> float:
    from src.utils.parsing import parse_amount

    value = parse_amount(raw or "")
    if value is None:
        raise FormError("Podaj poprawną kwotę (np. 12,50 albo 10+5).", field)
    if value < 0 or (value == 0 and not allow_zero):
        raise FormError("Kwota musi być większa od zera.", field)
    return value


def parse_required_date(raw: str, field: str, base_ym: Optional[str] = None) -> str:
    from src.utils.parsing import parse_user_date

    value = parse_user_date(raw or "", base_ym)
    if value is None:
        raise FormError("Niepoprawna data (np. 12, 12.05, 12.05.2026, wczoraj).", field)
    return value


def options_pairs(values: Iterable[Tuple[str, str]]) -> list:
    return list(values)
