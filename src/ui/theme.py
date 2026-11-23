"""
Motywy kolorystyczne.

Każdy motyw to paleta (Palette). Ta sama paleta trafia:
  - do CSS jako zmienne ($mx-accent, $mx-positive, …) poprzez motyw Textual,
  - do kodu Pythona (paski, kwoty, kalendarz) przez funkcję `palette()`.
Zmiana motywu w Ustawieniach działa od razu, bez restartu.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Tuple

from textual.theme import Theme


@dataclass(frozen=True)
class Palette:
    name: str
    label: str
    accent: str  # główny kolor motywu
    accent_mid: str
    accent_dim: str
    accent_dark: str
    accent_deep: str
    positive: str = "#3DDC84"  # przychody, sukces
    negative: str = "#FF4D4D"  # wydatki, błędy
    warning: str = "#FFC94A"  # ostrzeżenia
    info: str = "#FFD700"  # wyróżnienia (cele)
    transfer: str = "#5EC8FF"  # przelewy
    bg: str = "#000000"
    panel: str = "#060807"
    field: str = "#1b1d1c"
    field_focus: str = "#2c2f2d"
    text: str = "#E6E6E6"
    muted: str = "#8A8F8C"
    faint: str = "#4E5350"
    on_accent: str = "#000000"  # tekst na tle akcentu

    def css_variables(self) -> Dict[str, str]:
        return {f"mx-{k.replace('_', '-')}": v for k, v in asdict(self).items() if k not in ("name", "label")}


THEMES: Dict[str, Palette] = {
    p.name: p for p in (
        Palette("matrix", "Matrix (zielony)", "#00FF41", "#00C832", "#008822", "#004411", "#001F08",
                positive="#00FF41"),
        Palette("amber", "Bursztyn (pomarańczowy)", "#FF9F1C", "#F28500", "#A85A00", "#4D2A00", "#231300",
                panel="#090604", field="#1f1a15", field_focus="#332a20"),
        Palette("cyber", "Cyber (cyjan)", "#00E5FF", "#00B8D4", "#00838F", "#00363D", "#00191C",
                panel="#04080a", field="#151c1e", field_focus="#22302f"),
        Palette("violet", "Fiolet", "#C77DFF", "#A45BEA", "#7B2CBF", "#3A145E", "#1B0930",
                panel="#07050a", field="#1c1822", field_focus="#2c2535"),
        Palette("crimson", "Karmazyn (czerwony)", "#FF5C5C", "#E03E3E", "#A12626", "#4A1111", "#220808",
                negative="#FF8A3D", panel="#0a0505", field="#211717", field_focus="#332323"),
        Palette("mono", "Monochromatyczny", "#F0F0F0", "#C8C8C8", "#8C8C8C", "#3C3C3C", "#1A1A1A",
                positive="#BDEBC8", negative="#FFB3B3", panel="#070707"),
    )
}
DEFAULT_THEME = "matrix"
_current = THEMES[DEFAULT_THEME]


def palette() -> Palette:
    """Paleta aktualnego motywu (dla kodu rysującego kolory w Pythonie)."""
    return _current


def set_palette(name: str) -> Palette:
    global _current
    _current = THEMES.get(name, THEMES[DEFAULT_THEME])
    return _current


def theme_id(name: str) -> str:
    return f"mx-{name}"


def textual_theme(p: Palette) -> Theme:
    return Theme(
        name=theme_id(p.name),
        primary=p.accent,
        secondary=p.accent_mid,
        accent=p.accent,
        foreground=p.text,
        background=p.bg,
        surface=p.panel,
        panel=p.field,
        success=p.positive,
        warning=p.warning,
        error=p.negative,
        dark=True,
        variables=p.css_variables(),
    )


def all_textual_themes() -> List[Theme]:
    return [textual_theme(p) for p in THEMES.values()]


def theme_options() -> List[Tuple[str, str]]:
    return [(p.label, p.name) for p in THEMES.values()]
