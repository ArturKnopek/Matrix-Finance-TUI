"""
SmartTable — tabela z automatycznym dopasowaniem do rozmiaru okna.

Co robi sama, bez udziału widoków:
- liczy szerokości kolumn na podstawie treści i REALNEJ szerokości tabeli
  (z uwzględnieniem paddingu komórek),
- gdy brakuje miejsca: najpierw zwęża kolumny tekstowe (z wielokropkiem „…”),
  a dopiero gdy nawet minimalne szerokości się nie mieszczą — ukrywa kolumny
  wg priorytetu (hide_priority),
- nadmiar miejsca oddaje kolumnom „flex” (np. paski postępu, opis),
- dzieli dane na strony dokładnie wg wysokości tabeli; pasek stron chowa się,
  gdy wszystko mieści się na jednej stronie,
- zachowuje zaznaczony rekord przy odświeżaniu danych i zmianie rozmiaru okna,
- PageUp/PageDown oraz strzałki na krawędzi strony przełączają strony.
"""

from __future__ import annotations


from dataclasses import dataclass
from math import ceil
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import Button, DataTable, Label

CellValue = Union[str, Text, int, float, None]
RenderFn = Callable[[Mapping[str, Any], int], CellValue]

EMPTY_ROW_KEY = "__empty__"


@dataclass(frozen=True)
class Col:
    """Definicja kolumny SmartTable."""

    key: str
    header: str
    min_width: int = 4
    max_width: Optional[int] = None
    hide_priority: int = 0  # 0 = nigdy nie ukrywaj; im wyżej, tym wcześniej znika
    flex: int = 0  # waga przy rozdzielaniu wolnego miejsca
    align: str = "left"  # left | right | center
    render: Optional[RenderFn] = None  # treść zależna od szerokości (np. pasek postępu)


def _as_col(spec: Union[Col, Sequence[Any]]) -> Col:
    if isinstance(spec, Col):
        return spec
    key, header, min_w = spec[0], spec[1], spec[2]
    return Col(key=key, header=header, min_width=int(min_w))


def _row_get(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
    try:
        return row.get(key, default)  # type: ignore[union-attr]
    except AttributeError:
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            return default


def to_text(value: CellValue) -> Text:
    """Zamienia wartość komórki na rich.Text. Zwykłe stringi NIE są parsowane jako markup
    (dzięki temu opisy w stylu "[CYKLICZNE] Netflix" wyświetlają się poprawnie)."""
    if isinstance(value, Text):
        return value.copy()
    if value is None:
        return Text("")
    return Text(str(value))


def cell_width(value: CellValue) -> int:
    return to_text(value).cell_len


def compute_column_widths(
    columns: Sequence[Col],
    rows: Iterable[Mapping[str, Any]],
    available: int,
    cell_padding: int = 1,
) -> list[tuple[Col, int]]:
    """
    Czysta funkcja (łatwa do testowania) wyznaczająca widoczne kolumny i ich szerokości.

    available    – szerokość tabeli w znakach,
    cell_padding – padding komórki DataTable z każdej strony.
    """
    rows = list(rows)
    pad = 2 * max(0, int(cell_padding))

    natural: dict[str, int] = {}
    for col in columns:
        width = Text(col.header).cell_len
        if col.render is None or any(f"clean_{col.key}" in r for r in rows if isinstance(r, Mapping)):
            for row in rows:
                clean = _row_get(row, f"clean_{col.key}", None)
                value = clean if clean is not None else _row_get(row, col.key, "")
                width = max(width, cell_width(value))
        width = max(width, col.min_width)
        if col.max_width:
            width = min(width, col.max_width)
        natural[col.key] = max(1, width)

    visible = list(columns)

    def min_total() -> int:
        return sum(min(c.min_width, natural[c.key]) + pad for c in visible)

    # 1) Ukrywanie kolumn tylko wtedy, gdy nawet minimalne szerokości się nie mieszczą
    while min_total() > available:
        hideable = [c for c in visible if c.hide_priority > 0]
        if not hideable:
            break
        victim = max(hideable, key=lambda c: (c.hide_priority, columns.index(c)))
        visible.remove(victim)

    widths = {c.key: natural[c.key] for c in visible}
    overflow = sum(widths[c.key] + pad for c in visible) - available

    # 2) Zwężanie: zabieramy po 1 znaku kolumnie z największym zapasem ponad minimum
    while overflow > 0:
        candidates = [c for c in visible if widths[c.key] > c.min_width]
        if not candidates:
            break
        widest = max(candidates, key=lambda c: (widths[c.key] - c.min_width, c.flex))
        widths[widest.key] -= 1
        overflow -= 1

    # 3) Wolne miejsce -> kolumny flex (proporcjonalnie do wagi)
    if overflow < 0:
        extra = -overflow
        flex_cols = [c for c in visible if c.flex > 0]
        total_weight = sum(c.flex for c in flex_cols)
        if total_weight:
            given = 0
            for i, col in enumerate(flex_cols):
                share = extra - given if i == len(flex_cols) - 1 else (extra * col.flex) // total_weight
                widths[col.key] += share
                given += share

    return [(c, widths[c.key]) for c in visible]


class PagedDataTable(DataTable):
    """DataTable, który zgłasza prośbę o zmianę strony na krawędziach."""

    BINDINGS = [
        Binding("pagedown", "next_page", "Następna strona", show=False),
        Binding("pageup", "prev_page", "Poprzednia strona", show=False),
    ]

    class PageRequest(Message):
        def __init__(self, delta: int, cursor: str) -> None:
            super().__init__()
            self.delta = delta
            self.cursor = cursor  # "first" | "last" | "keep"

    def action_next_page(self) -> None:
        self.post_message(self.PageRequest(+1, "keep"))

    def action_prev_page(self) -> None:
        self.post_message(self.PageRequest(-1, "keep"))

    def action_cursor_down(self) -> None:
        if self.row_count and self.cursor_row >= self.row_count - 1:
            self.post_message(self.PageRequest(+1, "first"))
            return
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.row_count and self.cursor_row <= 0:
            self.post_message(self.PageRequest(-1, "last"))
            return
        super().action_cursor_up()

    async def _on_click(self, event: events.Click) -> None:
        # Pierwsze kliknięcie tylko zaznacza wiersz; edycja dopiero po kliknięciu
        # w już zaznaczony wiersz (lub Enter). Wcześniej każde kliknięcie otwierało edycję.
        meta = event.style.meta
        row = meta.get("row") if meta else None
        column = meta.get("column", 0) if meta else 0
        if row is not None and row >= 0 and row != self.cursor_row:
            event.prevent_default()
            event.stop()
            self.focus()
            self.cursor_coordinate = Coordinate(row, max(0, column))


class SmartTable(Vertical):
    """Tabela z paginacją i automatycznym dopasowaniem kolumn do szerokości okna."""

    DEFAULT_CSS = """
    SmartTable {
        width: 1fr;
        height: 1fr;
    }
    SmartTable > PagedDataTable {
        width: 1fr;
        height: 1fr;
    }
    SmartTable > #pagination-bar.-single-page {
        display: none;
    }
    """

    def __init__(
        self,
        columns_def: Sequence[Union[Col, Sequence[Any]]],
        empty_text: str = "brak danych",
        debounce_resize: float = 0.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.columns: list[Col] = [_as_col(c) for c in columns_def]
        self.empty_text = empty_text
        self._debounce = max(0.0, float(debounce_resize))
        self._resize_timer = None

        self.all_data: list[dict[str, Any]] = []
        self.current_page = 1
        self.total_pages = 1
        self.rows_per_page = 10
        self.active_columns: list[tuple[Col, int]] = []

        self._selected_key: Optional[str] = None
        self._render_signature: Optional[tuple] = None
        self._suppress_highlight = False

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        yield PagedDataTable(id="smart-datatable", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="pagination-bar"):
            yield Button("<<", id="page-first", classes="page-btn")
            yield Button("<", id="page-prev", classes="page-btn")
            yield Label("STRONA 1 / 1", id="page-info")
            yield Button(">", id="page-next", classes="page-btn")
            yield Button(">>", id="page-last", classes="page-btn")

    @property
    def table(self) -> PagedDataTable:
        return self.query_one("#smart-datatable", PagedDataTable)

    def focus_table(self) -> None:
        try:
            self.table.focus()
        except Exception:
            pass

    # ----------------------------------------------------------------- API

    def set_data(self, data: Iterable[Any]) -> None:
        """Ustawia dane. Zaznaczony rekord (po id) zostaje zachowany, jeśli nadal istnieje."""
        normalized: list[dict[str, Any]] = []
        for row in data:
            if isinstance(row, dict):
                normalized.append(row)
                continue
            try:
                normalized.append(dict(row))
            except Exception:
                normalized.append({"value": row})
        self.all_data = normalized
        self._render_signature = None
        self.recalculate_layout()

    def get_selected_id(self) -> Optional[str]:
        """Zwraca id zaznaczonego wiersza albo None (np. gdy tabela jest pusta)."""
        try:
            table = self.table
        except Exception:
            return None
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        key = str(row_key.value)
        return None if key == EMPTY_ROW_KEY else key

    def select_id(self, row_id: Any) -> None:
        self._selected_key = str(row_id)
        self._render_signature = None
        self.recalculate_layout()

    def get_column_current_width(self, col_key: str) -> int:
        for col, width in self.active_columns:
            if col.key == col_key:
                return width
        return 0

    # -------------------------------------------------------------- events

    def on_resize(self, event: events.Resize) -> None:
        if self._resize_timer is not None:
            self._resize_timer.stop()
        if self._debounce <= 0:
            self.recalculate_layout()
            return
        self._resize_timer = self.set_timer(self._debounce, self.recalculate_layout)

    def on_show(self) -> None:
        self.call_after_refresh(self.recalculate_layout)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid not in {"page-next", "page-prev", "page-first", "page-last"}:
            return
        event.stop()
        target = {
            "page-first": 1,
            "page-prev": self.current_page - 1,
            "page-next": self.current_page + 1,
            "page-last": self.total_pages,
        }[bid]
        self._go_to_page(target, "first")

    def on_paged_data_table_page_request(self, event: PagedDataTable.PageRequest) -> None:
        event.stop()
        self._go_to_page(self.current_page + event.delta, event.cursor)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._suppress_highlight:
            return
        key = event.row_key.value if event.row_key is not None else None
        if key and key != EMPTY_ROW_KEY:
            self._selected_key = str(key)

    # -------------------------------------------------------------- layout

    def _go_to_page(self, page: int, cursor: str) -> None:
        page = max(1, min(page, self.total_pages))
        if page == self.current_page:
            return
        cursor_row = self.table.cursor_row if self.table.row_count else 0
        self.current_page = page
        start = (page - 1) * self.rows_per_page
        page_items = self.all_data[start:start + self.rows_per_page]
        if page_items:
            if cursor == "last":
                idx = len(page_items) - 1
            elif cursor == "keep":
                idx = min(cursor_row, len(page_items) - 1)
            else:
                idx = 0
            self._selected_key = str(_row_get(page_items[idx], "id", ""))
        self._render_signature = None
        self.refresh_table()

    def _compute_rows_per_page(self) -> tuple[int, bool]:
        """Zwraca (wierszy_na_stronę, czy_jedna_strona) na podstawie wysokości komponentu."""
        height = int(self.content_size.height or 0)
        if height <= 0:
            return self.rows_per_page, len(self.all_data) <= self.rows_per_page
        header = 1
        single_rows = max(1, height - header)
        if len(self.all_data) <= single_rows:
            return single_rows, True
        return max(1, height - header - 1), False  # -1 na pasek stron

    def recalculate_layout(self) -> None:
        self._resize_timer = None
        if not self.is_mounted:
            return
        rows, single = self._compute_rows_per_page()
        self.rows_per_page = rows
        self.total_pages = max(1, ceil(len(self.all_data) / rows))
        try:
            self.query_one("#pagination-bar").set_class(single, "-single-page")
        except Exception:
            pass

        # strona z zaznaczonym rekordem (stabilne zaznaczenie przy zmianie rozmiaru)
        if self._selected_key is not None:
            for idx, item in enumerate(self.all_data):
                if str(_row_get(item, "id", "")) == self._selected_key:
                    self.current_page = idx // rows + 1
                    break
        self.current_page = max(1, min(self.current_page, self.total_pages))
        self.refresh_table()

    def _available_width(self) -> int:
        try:
            width = int(self.table.size.width or 0)
        except Exception:
            width = 0
        if width <= 0:
            width = int(self.content_size.width or 0)
        return width if width > 0 else 80

    def calculate_smart_layout(self) -> None:
        padding = getattr(self.table, "cell_padding", 1)
        self.active_columns = compute_column_widths(
            self.columns, self.all_data, self._available_width(), padding
        )

    # -------------------------------------------------------------- render

    def _format_cell(self, item: Mapping[str, Any], col: Col, width: int) -> Text:
        if col.render is not None:
            try:
                value = col.render(item, width)
            except Exception:
                value = _row_get(item, col.key, "")
        else:
            value = _row_get(item, col.key, "")
        text = to_text(value)
        text.no_wrap = True
        if text.cell_len > width:
            text.truncate(width, overflow="ellipsis")
        if col.align in ("right", "center"):
            text.justify = col.align  # type: ignore[assignment]
            # DataTable nie zawsze respektuje justify -> dopełniamy spacjami
            gap = width - text.cell_len
            if gap > 0:
                if col.align == "right":
                    text = Text(" " * gap) + text
                else:
                    left = gap // 2
                    text = Text(" " * left) + text + Text(" " * (gap - left))
        return text

    def refresh_table(self) -> None:
        if not self.is_mounted:
            return
        self.calculate_smart_layout()
        start = (self.current_page - 1) * self.rows_per_page
        page_items = self.all_data[start:start + self.rows_per_page]

        signature = (
            tuple((c.key, w) for c, w in self.active_columns),
            self.current_page,
            self.rows_per_page,
            len(self.all_data),
            self._selected_key,
        )
        if signature == self._render_signature:
            return
        self._render_signature = signature

        table = self.table
        self._suppress_highlight = True
        try:
            table.clear(columns=True)
            for col, width in self.active_columns:
                header = Text(col.header)
                if header.cell_len > width:
                    header.truncate(width, overflow="ellipsis")
                if col.align == "right":
                    header = Text(" " * max(0, width - header.cell_len)) + header
                table.add_column(header, key=col.key, width=width)

            if not page_items:
                if self.active_columns:
                    empty = [Text("")] * len(self.active_columns)
                    empty[0] = Text(self.empty_text, style="italic #555555")
                    table.add_row(*empty, key=EMPTY_ROW_KEY)
                table.show_cursor = False
            else:
                table.show_cursor = True
                cursor_idx = 0
                for idx, item in enumerate(page_items):
                    cells = [self._format_cell(item, col, width) for col, width in self.active_columns]
                    key = str(_row_get(item, "id", f"row-{start + idx}"))
                    table.add_row(*cells, key=key)
                    if key == self._selected_key:
                        cursor_idx = idx
                table.move_cursor(row=cursor_idx, animate=False)
                self._selected_key = str(_row_get(page_items[cursor_idx], "id", ""))
        finally:
            self._suppress_highlight = False

        self._update_pagination()

    def _update_pagination(self) -> None:
        try:
            info = self.query_one("#page-info", Label)
            info.update(f"STRONA {self.current_page}/{self.total_pages} · {len(self.all_data)} poz.")
            first = self.current_page <= 1
            last = self.current_page >= self.total_pages
            self.query_one("#page-first", Button).disabled = first
            self.query_one("#page-prev", Button).disabled = first
            self.query_one("#page-next", Button).disabled = last
            self.query_one("#page-last", Button).disabled = last
        except Exception:
            pass
