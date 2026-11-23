"""
Narzędzia UI: paski postępu (Rich) oraz samoskalujące się widżety.

Najważniejsza zmiana względem wcześniejszej wersji: ProgressMeter sam rysuje pasek
na podstawie SWOJEJ aktualnej szerokości (w render()), więc nie trzeba już
ręcznie przeliczać szerokości przy każdej zmianie rozmiaru okna.
"""

from __future__ import annotations


from typing import Any, Optional, Sequence

from rich.text import Text
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

GREEN = "#00FF41"
YELLOW = "#FFD700"
RED = "#FF3333"
EMPTY = "#333333"
BLOCK = "■"


# ============================================================================
#  HELPERY
# ============================================================================

def calculate_max_width(
    items: Sequence[Sequence[Any]],
    key_idx: int = 1,
    min_w: int = 12,
    max_w: int = 20,
) -> int:
    """Zwraca szerokość (w znakach) dopasowaną do najdłuższej nazwy w liście."""
    if not items:
        return min_w
    current_max = 0
    for item in items:
        try:
            txt = str(item[key_idx])
        except Exception:
            txt = ""
        current_max = max(current_max, Text(txt).cell_len)
    return max(min_w, min(current_max + 2, max_w))


def pick_color(pct: float, is_savings: bool) -> str:
    """Kolor paska: oszczędzanie (więcej = lepiej) vs zużycie budżetu (więcej = gorzej)."""
    if is_savings:
        if pct >= 100:
            return GREEN
        if pct >= 50:
            return YELLOW
        return RED
    if pct < 75:
        return GREEN
    if pct < 90:
        return YELLOW
    return RED


def money(value: float, currency: str = "PLN", signed: bool = False) -> str:
    """Format kwoty z separatorem tysięcy: 12 345.67 PLN."""
    fmt = f"{value:+,.2f}" if signed else f"{value:,.2f}"
    return f"{fmt.replace(',', ' ')} {currency}".rstrip()


def progress_text(
    pct: Optional[float],
    width: int,
    is_savings: bool = False,
    show_suffix: bool = True,
    empty_label: str = "bez limitu",
    color: Optional[str] = None,
) -> Text:
    """
    Pasek postępu jako rich.Text o DOKŁADNEJ szerokości `width`.
    pct=None -> brak punktu odniesienia (np. kategoria bez limitu).
    """
    width = max(1, int(width))
    if pct is None:
        label = empty_label
        if len(label) > width and " (" in label:
            label = label.split(" (", 1)[0]  # „1 200.00 PLN (bez limitu)” -> „1 200.00 PLN”
        return Text(label[:width].rjust(width), style="italic #666666")

    pct = float(pct)
    color = color or pick_color(pct, is_savings)
    suffix = f" {pct:5.1f}%" if show_suffix else ""
    if len(suffix) >= width:  # bardzo wąsko -> sam procent
        return Text(f"{pct:.0f}%".rjust(width)[:width], style=color)

    bar_width = width - len(suffix)
    filled = int(round(max(0.0, min(pct, 100.0)) / 100.0 * bar_width))
    text = Text()
    text.append(BLOCK * filled, style=color)
    text.append(BLOCK * (bar_width - filled), style=EMPTY)
    if suffix:
        text.append(suffix, style=color)
    return text


def get_progress_bar_str(
    current: float,
    total: float,
    width: int = 20,
    is_savings: bool = False,
    show_suffix: bool = True,
    empty_gray: str = "[#333333]",
) -> str:
    """(Zgodność wsteczna) pasek z danych current/total jako Rich markup."""
    pct = (current / total) * 100.0 if total > 0 else 0.0
    return progress_text(pct, max(8, width), is_savings, show_suffix).markup


def get_pct_bar_str(
    pct: float,
    width: int = 30,
    is_savings: bool = False,
    show_suffix: bool = True,
    empty_gray: str = "[#333333]",
) -> str:
    """(Zgodność wsteczna) pasek z procentu jako Rich markup."""
    return progress_text(pct, max(8, width), is_savings, show_suffix).markup


# ============================================================================
#  WIDŻETY
# ============================================================================

class ProgressMeter(Widget):
    """Pasek postępu, który zawsze wypełnia dokładnie dostępną szerokość."""

    DEFAULT_CSS = """
    ProgressMeter {
        width: 1fr;
        height: 1;
        min-width: 6;
    }
    """

    pct: reactive[Optional[float]] = reactive(None)

    def __init__(
        self,
        pct: Optional[float] = None,
        is_savings: bool = False,
        show_suffix: bool = True,
        empty_label: str = "bez limitu",
        color: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.is_savings = is_savings
        self.show_suffix = show_suffix
        self.empty_label = empty_label
        self.color = color
        self.set_reactive(ProgressMeter.pct, pct)

    def render(self) -> Text:
        return progress_text(self.pct, self.size.width, self.is_savings, self.show_suffix, self.empty_label,
                             self.color)


def get_universal_bar(
    label: str,
    pct: Optional[float],
    label_width: int,
    is_savings: bool = False,
    show_bullet: bool = True,
    bar_width: int = 30,  # zachowane dla zgodności – pasek i tak dopasowuje się sam
    empty_label: str = "bez limitu",
) -> Horizontal:
    """Wiersz listy na pulpicie: [• Nazwa][pasek wypełniający resztę miejsca]."""
    prefix = "• " if show_bullet else ""
    name = Label(prefix + (label or ""), classes="uni-name")
    name.styles.width = int(label_width)
    meter = ProgressMeter(pct, is_savings=is_savings, empty_label=empty_label, classes="uni-bar")
    return Horizontal(name, meter, classes="uni-row")


class WidthClassesMixin:
    """
    Nadaje widokowi klasy zależne od JEGO szerokości (nie całego terminala):
    -narrow (< NARROW_AT) oraz -tiny (< TINY_AT). Pozwala CSS-em chować mniej
    ważne elementy, gdy widok jest wąski (np. przy otwartym menu bocznym).
    """

    NARROW_AT = 90
    TINY_AT = 70

    def on_resize(self, event) -> None:  # type: ignore[override]
        width = event.size.width
        self.set_class(width < self.NARROW_AT, "-narrow")  # type: ignore[attr-defined]
        self.set_class(width < self.TINY_AT, "-tiny")  # type: ignore[attr-defined]
