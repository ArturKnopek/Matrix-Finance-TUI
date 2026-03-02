from __future__ import annotations

from math import ceil
from typing import Callable, Optional, Any, Mapping, Sequence

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Button, DataTable, Label


Formatter = Callable[[Mapping[str, Any], int], str]
ColumnDef = tuple[str, str, int]            # (key, header, min_width)
ActiveCol = tuple[str, str, int]            # (key, header, computed_width)


class SmartTable(Container):
    """
    Uniwersalny komponent tabeli z:
    - Paginacją
    - Inteligentnym ukrywaniem kolumn (sacrificial_col)
    - Rozciąganiem wybranej kolumny (expandable_col / backup_expand_col)
    - Formatowaniem komórek zależnie od aktualnej szerokości kolumny (formatters)

    Wskazówki:
    - Jeśli wartość zawiera Rich markup (kolory), dodaj również "clean_<key>"
      (tekst bez markup), aby szerokości były liczone poprawnie.
    """

    def __init__(
        self,
        columns_def: Sequence[ColumnDef],
        sacrificial_col: str | None = None,
        expandable_col: str | None = None,
        backup_expand_col: str | None = None,
        rows_per_page_offset: int = 1,
        formatters: Optional[dict[str, Formatter]] = None,
        debounce_resize: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.columns_def = list(columns_def)
        self.sacrificial_col = sacrificial_col
        self.expandable_col = expandable_col
        self.backup_expand_col = backup_expand_col
        self.rows_per_page_offset = rows_per_page_offset

        # Formatter: kol_key -> (item_dict, width) -> str
        self.formatters: dict[str, Formatter] = formatters or {}

        # Dane
        self.all_data: list[Mapping[str, Any]] = []
        self.current_page: int = 1
        self.total_pages: int = 1
        self.rows_per_page: int = 10
        self.active_columns_config: list[ActiveCol] = []

        # Debounce resize (żeby nie mielić przy przeciąganiu okna)
        self._debounce_resize = max(0.0, float(debounce_resize))
        self._resize_scheduled = False

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="smart-table-container", classes="table-container") as v:
            # usuwa rezerwację miejsca na scrollbar
            v.styles.scrollbar_size = (0, 0)
            yield DataTable(id="smart-datatable")

        with Horizontal(id="pagination-bar"):
            yield Button("<<", id="page-first", classes="page-btn")
            yield Button("<", id="page-prev", classes="page-btn")
            yield Label("STRONA 1 / 1", id="page-info")
            yield Button(">", id="page-next", classes="page-btn")
            yield Button(">>", id="page-last", classes="page-btn")

    def on_mount(self) -> None:
        table = self.query_one("#smart-datatable", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        # jeśli chcesz ciaśniej:
        # table.cell_padding = (0, 1)

    # ---------------------------------------------------------------------
    # API dla rodzica
    # ---------------------------------------------------------------------

    def set_data(self, data: list[Any]) -> None:
        """
        Ustawia dane tabeli.

        Normalizujemy WSZYSTKO do dict, żeby uniknąć przypadków
        Mapping bez .get (np. sqlite3.Row).
        """
        normalized: list[dict[str, Any]] = []

        for row in data:
            # 1) jeśli już dict -> bierzemy bez zmian
            if isinstance(row, dict):
                normalized.append(row)
                continue

            # 2) jeśli to sqlite3.Row / Mapping / cokolwiek iterowalnego w pary -> dict(row)
            try:
                normalized.append(dict(row))  # sqlite3.Row też tu wchodzi
                continue
            except Exception:
                pass

            # 3) ostatnia deska ratunku
            normalized.append({"value": row})

        self.all_data = normalized
        self.current_page = 1
        self.recalculate_layout()

    # ---------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------

    def on_resize(self, event: Resize) -> None:
        # Debounce: przelicz dopiero po krótkiej chwili
        if self._debounce_resize <= 0:
            self.recalculate_layout()
            return

        if self._resize_scheduled:
            return

        self._resize_scheduled = True

        def _do() -> None:
            self._resize_scheduled = False
            self.recalculate_layout()

        self.set_timer(self._debounce_resize, _do)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid not in {"page-next", "page-prev", "page-first", "page-last"}:
            return

        if bid == "page-next" and self.current_page < self.total_pages:
            self.current_page += 1
        elif bid == "page-prev" and self.current_page > 1:
            self.current_page -= 1
        elif bid == "page-first":
            self.current_page = 1
        elif bid == "page-last":
            self.current_page = self.total_pages

        self.refresh_table()

    # ---------------------------------------------------------------------
    # Layout
    # ---------------------------------------------------------------------

    def recalculate_layout(self) -> None:
        """Przelicza ilość wierszy na stronę i odświeża tabelę."""
        container = self.query_one("#smart-table-container")
        height = container.content_size.height or 10

        self.rows_per_page = max(5, int(height) - int(self.rows_per_page_offset))
        self.total_pages = ceil(len(self.all_data) / self.rows_per_page) or 1
        self._clamp_page()

        self.refresh_table()

    def _clamp_page(self) -> None:
        if self.current_page < 1:
            self.current_page = 1
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages

    def _get_available_width(self) -> int:
        """Szacuje dostępną szerokość na kolumny."""
        available_width = int(self.size.width)
        if available_width < 20:
            available_width = 80
        # stały margines Textual / DataTable (praktyczny hack)
        return max(10, available_width - 12)

    @staticmethod
    def _row_get(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
        """
        Bezpieczny odczyt z dict / sqlite3.Row:
        - jeśli obiekt ma .get() (dict) -> użyj
        - w przeciwnym razie spróbuj row[key] (sqlite3.Row)
        """
        try:
            getter = getattr(row, "get", None)
            if callable(getter):
                return getter(key, default)
        except Exception:
            pass

        try:
            return row[key]  # sqlite3.Row
        except Exception:
            return default

    def calculate_smart_layout(self) -> None:
        """Wylicza self.active_columns_config."""
        available_width = self._get_available_width()

        # 1) Liczenie szerokości treści
        content_widths: dict[str, int] = {}
        data_to_scan = self.all_data

        for col_key, col_header, min_w in self.columns_def:
            max_w = len(col_header)

            for row in data_to_scan:
                # clean_<key> ma priorytet (bez markup)
                val = self._row_get(row, f"clean_{col_key}", self._row_get(row, col_key, ""))
                length = len(str(val))
                if length > max_w:
                    max_w = length

            max_w += 2  # oddech

            # limity dla wybranych kolumn (żeby nie rozwalały układu)
            if col_key == "desc":
                max_w = min(max_w, 50)
            if col_key == "shop":
                max_w = min(max_w, 30)

            content_widths[col_key] = max(max_w, int(min_w))

        # 2) Ukrywanie kolumny poświęcanej
        total_needed = sum(content_widths.values())
        columns_to_show: list[ActiveCol] = []

        if total_needed > available_width and self.sacrificial_col:
            for key, header, _ in self.columns_def:
                if key == self.sacrificial_col:
                    continue
                columns_to_show.append((key, header, content_widths[key]))
        else:
            for key, header, _ in self.columns_def:
                columns_to_show.append((key, header, content_widths[key]))

        # 3) Fill Window (dodaj extra space do jednej kolumny)
        current_total = sum(c[2] for c in columns_to_show)
        extra_space = available_width - current_total

        if extra_space > 0 and (self.expandable_col or self.backup_expand_col):
            target_col = self.expandable_col
            if target_col and not any(c[0] == target_col for c in columns_to_show):
                target_col = None

            if not target_col:
                target_col = self.backup_expand_col if any(c[0] == self.backup_expand_col for c in columns_to_show) else None

            if target_col:
                new_cols: list[ActiveCol] = []
                for key, header, width in columns_to_show:
                    if key == target_col:
                        new_cols.append((key, header, width + extra_space))
                    else:
                        new_cols.append((key, header, width))
                columns_to_show = new_cols

        self.active_columns_config = columns_to_show

    # ---------------------------------------------------------------------
    # Render
    # ---------------------------------------------------------------------

    def refresh_table(self) -> None:
        """Odświeża tabelę na podstawie aktywnych kolumn i aktualnej strony."""
        self.calculate_smart_layout()

        table = self.query_one("#smart-datatable", DataTable)
        table.clear(columns=True)

        active_keys: list[str] = []
        width_map: dict[str, int] = {}

        for key, header, width in self.active_columns_config:
            table.add_column(header, key=key, width=width)
            active_keys.append(key)
            width_map[key] = width

        start = (self.current_page - 1) * self.rows_per_page
        end = start + self.rows_per_page
        page_items = self.all_data[start:end]

        for item in page_items:
            row_vals: list[Any] = []

            for k in active_keys:
                if k in self.formatters:
                    safe_w = max(5, width_map.get(k, 10) - 2)  # -2 na padding/ramki
                    try:
                        row_vals.append(self.formatters[k](item, safe_w))
                    except Exception:
                        row_vals.append(self._row_get(item, k, ""))
                else:
                    row_vals.append(self._row_get(item, k, ""))

            row_key = self._row_get(item, "id", str(item))
            table.add_row(*row_vals, key=str(row_key))

        self.query_one("#page-info").update(f"STRONA {self.current_page} / {self.total_pages}")

        is_first = (self.current_page == 1)
        is_last = (self.current_page == self.total_pages)
        self.query_one("#page-first").disabled = is_first
        self.query_one("#page-prev").disabled = is_first
        self.query_one("#page-next").disabled = is_last
        self.query_one("#page-last").disabled = is_last

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def get_selected_id(self) -> Optional[str]:
        """Zwraca ID zaznaczonego wiersza lub None."""
        table = self.query_one("#smart-datatable", DataTable)
        if table.cursor_coordinate is None:
            return None

        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return str(row_key.value)

    def get_column_current_width(self, col_key: str) -> int:
        """Zwraca aktualnie wyliczoną szerokość danej kolumny."""
        if not self.active_columns_config:
            self.calculate_smart_layout()

        for key, _, width in self.active_columns_config:
            if key == col_key:
                return width
        return 0