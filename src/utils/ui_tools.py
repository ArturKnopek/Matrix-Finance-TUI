from __future__ import annotations

from typing import Iterable, Sequence, Any

from textual.containers import Container
from textual.widgets import Label


# ============================================================================
#  HELPERY
# ============================================================================

def calculate_max_width(
    items: Sequence[Sequence[Any]],
    key_idx: int = 1,
    min_w: int = 12,
    max_w: int = 20
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
        current_max = max(current_max, len(txt))

    # +2 na oddech, ale z ograniczeniem min/max
    return max(min_w, min(current_max + 2, max_w))


# ============================================================================
#  PASKI (Rich markup)
# ============================================================================

def _pick_color(pct: float, is_savings: bool) -> str:
    """Dobiera kolor paska w zależności od % i trybu (savings vs consumption)."""
    c_safe = "[#00FF41]"   # zielony
    c_warn = "[yellow]"    # żółty
    c_dang = "[red]"       # czerwony

    if is_savings:
        # im więcej %, tym lepiej
        if pct >= 100:
            return c_safe
        if pct >= 50:
            return c_warn
        return c_dang
    else:
        # im więcej %, tym gorzej
        if pct < 75:
            return c_safe
        if pct < 90:
            return c_warn
        return c_dang


def get_progress_bar_str(
    current: float,
    total: float,
    width: int = 20,
    is_savings: bool = False,
    show_suffix: bool = True,
    empty_gray: str = "[#333333]"
) -> str:
    """
    Pasek postępu z danych (current/total).

    - Kolorowe bloki = wypełnienie
    - Szare bloki = brakujące (widać ile brakuje do celu)
    - show_suffix=True dokleja procent na końcu i rezerwuje na niego miejsce

    Zwraca Rich markup.
    """
    width = max(8, int(width))

    if total <= 0:
        pct = 0.0
    else:
        pct = (current / total) * 100.0

    # ograniczamy dla rysowania paska
    pct_clamped = max(0.0, min(pct, 100.0))
    color = _pick_color(pct, is_savings)

    if show_suffix:
        suffix = f" {pct:>5.1f}%"
        suffix_len = len(suffix)
    else:
        suffix = ""
        suffix_len = 0

    bar_width = max(0, width - suffix_len)

    filled_len = int((pct_clamped / 100.0) * bar_width)
    empty_len = bar_width - filled_len

    block = "■"
    filled = block * max(0, filled_len)
    empty = block * max(0, empty_len)

    bar = f"{color}{filled}[/]{empty_gray}{empty}[/]"

    # procent na końcu w tym samym kolorze co pasek
    return f"{bar}{color}{suffix}[/]" if show_suffix else bar


def get_pct_bar_str(
    pct: float,
    width: int = 30,
    is_savings: bool = False,
    show_suffix: bool = True,
    empty_gray: str = "[#333333]"
) -> str:
    """
    Pasek postępu bazujący bezpośrednio na procentach.

    - Kolorowe bloki = wypełnienie
    - Szare bloki = brakujące
    - show_suffix=True dokleja procent na końcu i rezerwuje na niego miejsce

    Zwraca Rich markup.
    """
    width = max(8, int(width))
    pct = float(pct)
    pct_clamped = max(0.0, min(pct, 100.0))

    color = _pick_color(pct, is_savings)

    if show_suffix:
        suffix = f" {pct:>5.1f}%"
        suffix_len = len(suffix)
    else:
        suffix = ""
        suffix_len = 0

    bar_width = max(0, width - suffix_len)

    filled_len = int((pct_clamped / 100.0) * bar_width)
    empty_len = bar_width - filled_len

    block = "■"
    filled = block * max(0, filled_len)
    empty = block * max(0, empty_len)

    bar = f"{color}{filled}[/]{empty_gray}{empty}[/]"

    return f"{bar}{color}{suffix}[/]" if show_suffix else bar


# ============================================================================
#  WIDŻET: “uniwersalny wiersz” (Dashboard listy)
# ============================================================================

def get_universal_bar(
    label: str,
    pct: int,
    label_width: int,
    is_savings: bool = False,
    show_bullet: bool = True,
    bar_width: int = 30
) -> Container:
    """
    Wiersz do Dashboardu: [Nazwa] [Pasek + %]

    Pasek jest dokowany do prawej (dock=right), więc procent “siedzi” przy prawej
    krawędzi kontenera (zgodnie z Twoim wymaganiem).
    """
    prefix = "• " if show_bullet else ""
    safe_label = (prefix + (label or ""))[:label_width]

    lbl_name = Label(safe_label, classes="uni-name")
    lbl_name.styles.width = int(label_width)
    lbl_name.styles.flex_shrink = 0
    lbl_name.styles.dock = "left"
    lbl_name.styles.margin_right = 1  # 1 znak odstępu od paska

    bar_width = max(12, int(bar_width))
    bar_markup = get_pct_bar_str(
        pct=float(pct),
        width=bar_width,
        is_savings=is_savings,
        show_suffix=True
    )

    lbl_bar = Label(bar_markup, classes="uni-bar-track")
    lbl_bar.styles.width = bar_width
    lbl_bar.styles.flex_shrink = 0
    lbl_bar.styles.dock = "right"
    lbl_bar.styles.text_overflow = "clip"

    return Container(lbl_name, lbl_bar, classes="uni-row")