from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label
from textual.containers import Container, Horizontal
from textual.events import Resize
from rich.text import Text

from src.database import (
    get_all_categories_data,
    get_category_spent,
    get_monthly_balance,
    get_active_month_str,
)
from src.utils.smart_table import SmartTable
from src.utils.ui_tools import get_progress_bar_str


class CategoriesView(Container):
    """
    Widok Kategorii:
    - Kolumna 'progress' zawiera pasek + procent NA KOŃCU (show_suffix=True).
    - Pasek skaluje się przy zmianie rozmiaru okna.
    - Waluta w widoku: PLN.
    - Kod kategorii (ct_code) jest tylko do wyświetlania, ID zostaje wewnętrzne.
    """

    COLUMNS_CONFIG = [
        ("ct_code", "Kod", 8),
        ("name", "Kategoria", 15),
        ("limit", "Limit", 12),
        ("spent", "Wydano", 12),
        ("remaining", "Pozostało", 12),
        ("progress", "Realizacja", 10),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_data_cache = []
        self.current_month_cache = ""

    def compose(self) -> ComposeResult:
        # GÓRNY PASEK
        with Horizontal(id="cat-header-panel"):
            yield Label("BILANS MIESIĄCA:", classes="cat-header-title")

            with Horizontal(classes="cat-stat-box"):
                yield Label("PRZYCHODY:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-income", classes="stat-value income")

            with Horizontal(classes="cat-stat-box"):
                yield Label("WYDATKI:", classes="stat-label")
                yield Label("0.00 PLN", id="lbl-expenses", classes="stat-value expense")

        # TABELA
        yield SmartTable(
            id="cat-smart-table",
            columns_def=self.COLUMNS_CONFIG,
            sacrificial_col="remaining",
            expandable_col="progress",
            backup_expand_col="name",
            rows_per_page_offset=2,
        )

    def on_mount(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        self.fetch_fresh_data()
        self._regenerate_with_current_width()

    def refresh_table(self) -> None:
        self.load_data()

    def on_resize(self, event: Resize) -> None:
        # SmartTable ma własny debounce i przelicza layout, ale
        # progres-bar zależy od szerokości kolumny, więc regenerujemy dane.
        if not self.raw_data_cache:
            return
        self._regenerate_with_current_width()

    def get_selected_category_id(self):
        """Zwraca ID zaznaczonej kategorii (wewnętrzne ID)."""
        return self.query_one("#cat-smart-table", SmartTable).get_selected_id()

    # ---------------------------------------------------------------------
    # Dane
    # ---------------------------------------------------------------------

    def fetch_fresh_data(self) -> None:
        # Respektujemy miesiąc roboczy ustawiony w Settings
        self.current_month_cache = get_active_month_str()

        try:
            income, expenses = get_monthly_balance(self.current_month_cache)
            self.query_one("#lbl-income").update(f"{income:.2f} PLN")
            self.query_one("#lbl-expenses").update(f"{expenses:.2f} PLN")
        except Exception:
            pass

        self.raw_data_cache = get_all_categories_data() or []

    def _regenerate_with_current_width(self) -> None:
        """Pobiera szerokość kolumny 'progress' i regeneruje dane."""
        try:
            table = self.query_one("#cat-smart-table", SmartTable)
            table.calculate_smart_layout()
            current_width = table.get_column_current_width("progress")
            safe_width = max(12, int(current_width) - 4)
        except Exception:
            safe_width = 20

        self.regenerate_table_data(dynamic_bar_width=safe_width)

    def regenerate_table_data(self, dynamic_bar_width: int) -> None:
        """Buduje dane do SmartTable."""
        if not self.raw_data_cache:
            try:
                self.query_one("#cat-smart-table", SmartTable).set_data([])
            except Exception:
                pass
            return

        processed_data = []
        safe_width = max(12, int(dynamic_bar_width))

        for cat in self.raw_data_cache:
            cat_dict = dict(cat)

            c_id = cat_dict.get("id")
            name = cat_dict.get("name", "")
            limit = float(cat_dict.get("limit_amount", 0.0) or 0.0)

            # Kod kategorii do wyświetlania:
            # jeśli nie ma w DB jeszcze ct_code, to fallback z id (CT000001)
            try:
                ct_code = cat_dict.get("ct_code") or (f"CT{int(c_id):06d}" if c_id is not None else "")
            except Exception:
                ct_code = ""

            spent = float(get_category_spent(name, self.current_month_cache) or 0.0)
            remaining = limit - spent

            progress_str = get_progress_bar_str(
                current=spent,
                total=limit,
                width=safe_width,
                is_savings=False,
                show_suffix=True,
            )

            clean_prog = Text.from_markup(progress_str).plain

            processed_data.append({
                "ct_code": ct_code,
                "name": name,

                "limit": f"{limit:.2f} PLN",
                "clean_limit": f"{limit:.2f}",

                "spent": f"{spent:.2f} PLN",
                "clean_spent": f"{spent:.2f}",

                "remaining": f"{remaining:.2f} PLN",
                "clean_remaining": f"{remaining:.2f}",

                "progress": progress_str,
                "clean_progress": clean_prog,

                # Zostawiamy id wewnętrznie (SmartTable używa jako row_key)
                "id": str(c_id) if c_id is not None else "",
            })

        self.query_one("#cat-smart-table", SmartTable).set_data(processed_data)