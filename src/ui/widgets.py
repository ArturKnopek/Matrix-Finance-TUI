"""
Widżety wielokrotnego użytku.

    money / compact_money  – formatowanie kwot
    meter_text / Meter      – JEDEN styl paska postępu w całej aplikacji
    KpiTile                 – kafelek z dużą liczbą (pulpit)
    MonthCalendar           – kalendarz miesiąca rysowany w dostępnym miejscu
    MatrixRain              – animacja „cyfrowego deszczu” (ekran powitalny i logowania)
    WidthClassesMixin       – klasy -narrow/-tiny wg szerokości samego widoku
"""

from __future__ import annotations

import calendar
import random
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from src.ui.theme import palette

# =============================================================================
# Kwoty
# =============================================================================


def money(value: float, currency: str = "PLN", signed: bool = False) -> str:
    """12 345.67 PLN (spacja jako separator tysięcy)."""
    fmt = f"{value:+,.2f}" if signed else f"{value:,.2f}"
    return f"{fmt.replace(',', ' ')} {currency}".rstrip()


def compact_money(value: float) -> str:
    """Krótki zapis do małych pól: 950, 1,2k, 12k, 1,5M."""
    v = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.1f}M".replace(".", ",")
    if v >= 10_000:
        return f"{sign}{v / 1000:.0f}k"
    if v >= 1000:
        return f"{sign}{v / 1000:.1f}k".replace(".", ",")
    return f"{sign}{v:.0f}"


def calculate_max_width(items: Sequence[Sequence[Any]], key_idx: int = 1, min_w: int = 12, max_w: int = 20) -> int:
    if not items:
        return min_w
    longest = max(Text(str(item[key_idx])).cell_len for item in items)
    return max(min_w, min(longest + 2, max_w))


# =============================================================================
# Paski postępu — jeden styl wszędzie
# =============================================================================

BAR_FULL = "━"
BAR_EMPTY = "─"


def meter_color(pct: float, mode: str) -> str:
    """
    mode="budget" – im więcej, tym gorzej (koperty, zużycie): zielony → żółty → czerwony,
    mode="goal"   – im więcej, tym lepiej (cele, lokaty): akcent → pozytywny po 100%,
    mode="share"  – udział (raporty): stały kolor akcentu.
    """
    p = palette()
    if mode == "budget":
        return p.positive if pct < 75 else p.warning if pct < 100 else p.negative
    if mode == "goal":
        return p.positive if pct >= 100 else p.accent
    return p.accent_mid


def meter_text(pct: Optional[float], width: int, mode: str = "budget", empty_label: str = "bez limitu",
               show_pct: bool = True) -> Text:
    """Pasek o DOKŁADNEJ szerokości `width`:  ━━━━━━━━────────  52%"""
    p = palette()
    width = max(1, int(width))
    if pct is None:
        label = empty_label
        if len(label) > width and " (" in label:
            label = label.split(" (", 1)[0]
        return Text(label[:width].rjust(width), style=f"italic {p.muted}")
    pct = float(pct)
    color = meter_color(pct, mode)
    suffix = f" {pct:4.0f}%" if show_pct else ""
    if len(suffix) >= width:
        return Text(f"{pct:.0f}%".rjust(width)[:width], style=color)
    bar_w = width - len(suffix)
    filled = int(round(max(0.0, min(pct, 100.0)) / 100.0 * bar_w))
    text = Text()
    text.append(BAR_FULL * filled, style=color)
    text.append(BAR_EMPTY * (bar_w - filled), style=p.faint)
    if suffix:
        text.append(suffix, style=f"bold {color}")
    return text


# zgodność wsteczna ze starszym kodem
def progress_text(pct: Optional[float], width: int, is_savings: bool = False, show_suffix: bool = True,
                  empty_label: str = "bez limitu", color: Optional[str] = None) -> Text:
    return meter_text(pct, width, "goal" if is_savings else "budget", empty_label, show_suffix)


class Meter(Widget):
    """Pasek postępu wypełniający dostępną szerokość (rysowany przy każdej zmianie rozmiaru)."""

    DEFAULT_CSS = """
    Meter { width: 1fr; height: 1; min-width: 5; }
    """

    pct: reactive[Optional[float]] = reactive(None)

    def __init__(self, pct: Optional[float] = None, mode: str = "budget", empty_label: str = "bez limitu",
                 show_pct: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.mode = mode
        self.empty_label = empty_label
        self.show_pct = show_pct
        self.set_reactive(Meter.pct, pct)

    def render(self) -> Text:
        return meter_text(self.pct, self.size.width, self.mode, self.empty_label, self.show_pct)


ProgressMeter = Meter  # zgodność wsteczna


# =============================================================================
# Kafelek KPI
# =============================================================================

class KpiTile(Vertical):
    """Kafelek: tytuł w ramce, duża wartość, linia opisu oraz opcjonalnie pasek lub wykres."""

    def __init__(self, title: str, extra: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class("kpi-tile")
        self.border_title = title
        self.extra = extra  # "" | "meter" | "sparkline"

    def compose(self):
        from textual.widgets import Sparkline

        yield Label("…", classes="kpi-value")
        if self.extra == "meter":
            yield Meter(None, mode="budget", classes="kpi-meter")
        elif self.extra == "sparkline":
            yield Sparkline([0, 0], classes="kpi-spark")
        yield Label("", classes="kpi-sub")

    def set(self, value: Any, sub: Any = "", tone: str = "", pct: Optional[float] = None,
            series: Optional[List[float]] = None) -> None:
        value_label = self.query_one(".kpi-value", Label)
        value_label.update(value)
        for t in ("pos", "neg", "warn"):
            value_label.set_class(t == tone, f"-{t}")
        self.query_one(".kpi-sub", Label).update(sub)
        if self.extra == "meter":
            self.query_one(".kpi-meter", Meter).pct = pct
        elif self.extra == "sparkline" and series is not None:
            from textual.widgets import Sparkline

            self.query_one(".kpi-spark", Sparkline).data = series if len(series) > 1 else [0, *series]


# =============================================================================
# Kalendarz miesiąca
# =============================================================================

WEEKDAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]


class MonthCalendar(Widget, can_focus=True):
    """
    Kalendarz rysowany w całości w dostępnym miejscu: komórki rosną z oknem,
    w większych komórkach widać kwotę dnia. Oznaczenia:
        • zaplanowane zlecenie      ◆ koniec lokaty/obligacji
        podkreślenie = dziś         odcień tła = intensywność wydatków
    """

    DEFAULT_CSS = """
    MonthCalendar { width: 1fr; height: 1fr; min-height: 5; }
    """

    BINDINGS = [
        Binding("left", "move(-1)", "Poprzedni dzień", show=False),
        Binding("right", "move(1)", "Następny dzień", show=False),
        Binding("up", "move(-7)", "Tydzień wcześniej", show=False),
        Binding("down", "move(7)", "Tydzień później", show=False),
        Binding("enter", "activate", "Otwórz dzień", show=False),
    ]

    class DaySelected(Message):
        def __init__(self, calendar: "MonthCalendar", day: date) -> None:
            super().__init__()
            self.calendar = calendar
            self.day = day

    class DayActivated(DaySelected):
        pass

    class MonthShift(Message):
        def __init__(self, delta: int) -> None:
            super().__init__()
            self.delta = delta

    selected: reactive[int] = reactive(0)

    def __init__(self, interactive: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.interactive = interactive
        self.can_focus = interactive
        today = date.today()
        self.year, self.month = today.year, today.month
        self.data: Dict[int, Any] = {}
        self._geom: Optional[Tuple[int, int, int, int, List[List[int]]]] = None

    # ----------------------------------------------------------------- API

    def set_month(self, ym: str, data: Dict[int, Any], selected: Optional[int] = None) -> None:
        self.year, self.month = map(int, ym.split("-"))
        self.data = data
        days_in_month = calendar.monthrange(self.year, self.month)[1]
        if selected is None:
            today = date.today()
            selected = today.day if (today.year, today.month) == (self.year, self.month) else 1
        self.set_reactive(MonthCalendar.selected, max(1, min(selected, days_in_month)))
        self.refresh()

    @property
    def selected_date(self) -> date:
        return date(self.year, self.month, max(1, self.selected))

    # ----------------------------------------------------------- rysowanie

    def _style_for(self, day: int, max_spent: float) -> Tuple[str, str]:
        """(styl tła komórki, kolor tekstu) wg intensywności wydatków."""
        p = palette()
        info = self.data.get(day)
        spent = float(getattr(info, "spent", 0.0) or 0.0)
        shades = ["#121212", p.accent_deep, p.accent_dark, p.accent_dim, p.accent_mid]
        level = 0
        if spent > 0 and max_spent > 0:
            ratio = spent / max_spent
            level = 1 if ratio < 0.25 else 2 if ratio < 0.5 else 3 if ratio < 0.8 else 4
        fg = p.on_accent if level == 4 else (p.text if level else p.muted)
        return shades[level], fg

    def render(self) -> Text:
        p = palette()
        width, height = self.size.width, self.size.height
        weeks = calendar.monthcalendar(self.year, self.month)
        if width < 14 or height < 2:
            return Text(f"{self.month:02d}.{self.year}", style=p.muted)

        show_header = height >= len(weeks) + 1
        avail = height - (1 if show_header else 0)
        if avail < len(weeks):  # za mało wierszy: pokazujemy tygodnie wokół zaznaczonego dnia
            sel_week = next((i for i, w in enumerate(weeks) if self.selected in w), 0)
            start = max(0, min(sel_week - avail // 2, len(weeks) - avail))
            weeks = weeks[start:start + avail]
        cell_h = max(1, min(4, avail // max(1, len(weeks))))
        cell_w = max(3, min(14, width // 7))
        pad = max(0, (width - cell_w * 7) // 2)
        max_spent = max((float(getattr(i, "spent", 0) or 0) for i in self.data.values()), default=0.0)
        today = date.today()
        is_current_month = (today.year, today.month) == (self.year, self.month)

        lines: List[Text] = []
        if show_header:
            header = Text(" " * pad)
            for i, name in enumerate(WEEKDAYS):
                header.append(name.center(cell_w)[:cell_w], style=f"bold {p.warning if i >= 5 else p.muted}")
            lines.append(header)

        inner = cell_w - 1
        for week in weeks:
            for line_no in range(cell_h):
                line = Text(" " * pad)
                for day in week:
                    if day == 0:
                        line.append(" " * cell_w)
                        continue
                    info = self.data.get(day)
                    bg, fg = self._style_for(day, max_spent)
                    is_today = is_current_month and day == today.day
                    if self.interactive and day == self.selected:
                        bg, fg = (p.accent if self.has_focus else p.accent_mid), p.on_accent
                    elif is_today and fg == p.muted:
                        fg = p.accent
                    style = f"{fg} on {bg}"
                    if line_no == 0:
                        markers = ""
                        if info is not None and getattr(info, "planned", None):
                            markers += "•"
                        if info is not None and getattr(info, "events", None):
                            markers += "◆"
                        num = f"{day:>2}"
                        content = (num + markers.rjust(max(0, inner - len(num))))[:inner] if inner > 2 else num
                        num_style = f"bold underline {style}" if is_today else style
                        line.append(content[:len(num)], style=num_style)
                        line.append(content[len(num):].ljust(inner - len(num)), style=f"{p.warning} on {bg}")
                    elif line_no == 1 and info is not None and (info.spent or info.income):
                        amount = compact_money(info.spent) if info.spent else compact_money(info.income)
                        color = fg if info.spent else p.positive
                        line.append(amount.rjust(inner)[:inner], style=f"{color} on {bg}")
                    else:
                        line.append(" " * inner, style=f"on {bg}")
                    line.append(" ")
                lines.append(line)

        self._geom = (pad, cell_w, 1 if show_header else 0, cell_h, weeks)
        return Text("\n").join(lines)

    # ----------------------------------------------------------- interakcja

    def watch_selected(self, old: int, new: int) -> None:
        self.refresh()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def action_move(self, delta: int) -> None:
        days_in_month = calendar.monthrange(self.year, self.month)[1]
        target = self.selected + delta
        if target < 1 or target > days_in_month:
            self.post_message(self.MonthShift(-1 if target < 1 else 1))
            return
        self.selected = target
        self.post_message(self.DaySelected(self, self.selected_date))

    def action_activate(self) -> None:
        self.post_message(self.DayActivated(self, self.selected_date))

    def on_click(self, event: events.Click) -> None:
        if not self.interactive or not self._geom:
            return
        pad, cell_w, header, cell_h, weeks = self._geom
        col = (event.x - pad) // cell_w
        row = (event.y - header) // cell_h
        if not (0 <= col < 7 and 0 <= row < len(weeks)):
            return
        day = weeks[row][col]
        if not day:
            return
        self.focus()
        if day == self.selected:
            self.post_message(self.DayActivated(self, self.selected_date))
        else:
            self.selected = day
            self.post_message(self.DaySelected(self, self.selected_date))


# =============================================================================
# Animacja „cyfrowego deszczu”
# =============================================================================

RAIN_CHARS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789$+-*=<>"


class MatrixRain(Widget):
    """Lekka animacja tła w stylu „Matrixa” (ok. 12 klatek/s, zatrzymuje się, gdy ekran jest niewidoczny)."""

    DEFAULT_CSS = """
    MatrixRain { width: 100%; height: 100%; }
    """

    def __init__(self, animated: bool = True, fps: float = 12.0, density: float = 0.55,
                 seed: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.animated = animated
        self.fps = fps
        self.density = density
        self._rng = random.Random(seed)
        self._drops: Dict[int, List[float]] = {}  # kolumna -> [y głowy, prędkość, długość]
        self._glyphs: Dict[int, List[str]] = {}
        self.frames = 0

    def on_mount(self) -> None:
        self._seed_columns()
        if self.animated:
            self.set_interval(1 / self.fps, self._tick)

    def on_resize(self, event: events.Resize) -> None:
        self._seed_columns()
        if not self.animated:  # bez animacji: jedna „zamrożona” klatka deszczu
            for _ in range(max(10, self.size.height)):
                self._advance()
            self.refresh()

    def _seed_columns(self) -> None:
        width, height = max(1, self.size.width), max(1, self.size.height)
        for col in range(0, width, 2):
            if col not in self._drops and self._rng.random() < self.density:
                self._drops[col] = [self._rng.uniform(-height, height), self._rng.uniform(0.3, 1.1),
                                    self._rng.randint(4, max(5, height // 2 + 3))]
            if col not in self._glyphs or len(self._glyphs[col]) < height:
                self._glyphs[col] = [self._rng.choice(RAIN_CHARS) for _ in range(height)]

    def _tick(self) -> None:
        if not self.is_attached or not self.display:
            return
        try:
            if self.app.screen is not self.screen:
                return
        except Exception:  # widżet odłączany razem z ekranem
            return
        self._advance()
        self.frames += 1
        self.refresh()

    def _advance(self) -> None:
        height = max(1, self.size.height)
        for col, drop in self._drops.items():
            drop[0] += drop[1]
            if drop[0] - drop[2] > height:
                drop[0] = self._rng.uniform(-height / 2, 0)
                drop[1] = self._rng.uniform(0.3, 1.1)
            glyphs = self._glyphs.get(col)
            if glyphs and self._rng.random() < 0.3:
                glyphs[self._rng.randrange(len(glyphs))] = self._rng.choice(RAIN_CHARS)

    def render(self) -> Text:
        p = palette()
        width, height = self.size.width, self.size.height
        grid: List[List[Tuple[str, str]]] = [[(" ", "")] * width for _ in range(height)]
        trail = [p.accent, p.accent_mid, p.accent_dim, p.accent_dark, p.accent_deep]
        for col, (head, _speed, length) in self._drops.items():
            if col >= width:
                continue
            glyphs = self._glyphs.get(col) or []
            for i in range(int(length)):
                row = int(head) - i
                if 0 <= row < height and row < len(glyphs):
                    if i == 0:
                        style = f"bold {p.text}"
                    else:
                        style = trail[min(len(trail) - 1, i * len(trail) // max(1, int(length)))]
                    grid[row][col] = (glyphs[row], style)
        text = Text()
        for r, row in enumerate(grid):
            for ch, style in row:
                text.append(ch, style=style or None)
            if r < height - 1:
                text.append("\n")
        return text


# =============================================================================
# Klasy szerokości widoku
# =============================================================================

class WidthClassesMixin:
    """Nadaje widokowi klasy -narrow (< NARROW_AT) i -tiny (< TINY_AT) wg jego własnej szerokości."""

    NARROW_AT = 90
    TINY_AT = 70

    def on_resize(self, event) -> None:  # type: ignore[override]
        width = event.size.width
        self.set_class(width < self.NARROW_AT, "-narrow")  # type: ignore[attr-defined]
        self.set_class(width < self.TINY_AT, "-tiny")  # type: ignore[attr-defined]
