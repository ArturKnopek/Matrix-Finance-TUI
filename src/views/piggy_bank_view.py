from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label
from textual.containers import Container, Horizontal
from textual.events import Resize
from rich.text import Text

from src.database import get_all_piggy_banks
from src.utils.smart_table import SmartTable
from src.utils.ui_tools import get_progress_bar_str


class PiggyBankView(Container):
    """
    Widok Skarbonek (Celów) z użyciem SmartTable.
    - Pokazuje kod PB000001 (pb_code) zamiast ID.
    - ID zostaje wewnętrznie (SmartTable użyje jako key wiersza).
    - Kolumna 'progress' zawiera pasek + procent na końcu (suffix).
    - Pasek skaluje się przy zmianie rozmiaru okna.
    - Waluta w widoku: PLN.
    """

    COLUMNS_CONFIG = [
        ("pb_code", "Kod", 8),
        ("name", "Cel", 15),
        ("account", "Konto", 8),
        ("collected", "Uzbierano", 12),
        ("remaining", "Pozostało", 12),
        ("progress", "Postęp", 10),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_data_cache = []

    def compose(self) -> ComposeResult:
        # GÓRNY PASEK
        with Horizontal(id="piggy-header-panel"):
            yield Label("STATUS OSZCZĘDZANIA:", classes="piggy-header-title")

            with Horizontal(classes="piggy-stat-box"):
                yield Label("UZBIERANO:", classes="stat-label")
                yield Label("0.00 PLN / 0.00 PLN", id="lbl-piggy-total", classes="stat-value savings")

        # TABELA
        yield SmartTable(
            id="piggy-smart-table",
            columns_def=self.COLUMNS_CONFIG,
            sacrificial_col="remaining",      # ukryj "Pozostało" gdy brakuje miejsca
            expandable_col="progress",        # rozciągaj pasek
            backup_expand_col="name",
            rows_per_page_offset=4,
        )

    def on_mount(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        self.fetch_fresh_data()
        self._regenerate_with_current_width()

    def refresh_table(self) -> None:
        self.load_data()

    def on_resize(self, event: Resize) -> None:
        # SmartTable przelicza layout sam, ale pasek zależy od szerokości kolumny -> regenerujemy dane.
        if not self.raw_data_cache:
            return
        self._regenerate_with_current_width()

    # ---------------------------------------------------------------------
    # API dla MainDashboard
    # ---------------------------------------------------------------------

    def get_selected_piggy_id(self):
        """Zwraca ID zaznaczonego celu (wewnętrzne ID)."""
        return self.query_one("#piggy-smart-table", SmartTable).get_selected_id()

    # ---------------------------------------------------------------------
    # Dane
    # ---------------------------------------------------------------------

    def fetch_fresh_data(self) -> None:
        """Pobiera dane z bazy i aktualizuje nagłówek."""
        data = get_all_piggy_banks() or []
        self.raw_data_cache = data

        total_collected = sum(float(d["current_amount"] or 0.0) for d in data) if data else 0.0
        total_target = sum(float(d["target_amount"] or 0.0) for d in data) if data else 0.0

        try:
            self.query_one("#lbl-piggy-total", Label).update(
                f"{total_collected:.2f} PLN / {total_target:.2f} PLN"
            )
        except Exception:
            pass

    def _regenerate_with_current_width(self) -> None:
        """Helper: pobiera szerokość kolumny 'progress' i regeneruje dane."""
        try:
            table = self.query_one("#piggy-smart-table", SmartTable)
            table.calculate_smart_layout()
            current_width = table.get_column_current_width("progress")
            safe_width = max(12, int(current_width) - 4)
        except Exception:
            safe_width = 20

        self.regenerate_table_data(dynamic_bar_width=safe_width)

    def regenerate_table_data(self, dynamic_bar_width: int) -> None:
        """Buduje dane do SmartTable. Pasek 'Postęp' zawiera procent na końcu."""
        if not self.raw_data_cache:
            try:
                self.query_one("#piggy-smart-table", SmartTable).set_data([])
            except Exception:
                pass
            return

        processed_data = []
        safe_width = max(12, int(dynamic_bar_width))

        for pig in self.raw_data_cache:
            pig_dict = dict(pig)

            p_id = pig_dict.get("id")
            name = pig_dict.get("name", "")
            target = float(pig_dict.get("target_amount", 0.0) or 0.0)
            current = float(pig_dict.get("current_amount", 0.0) or 0.0)
            acc_type = pig_dict.get("account_type", "Karta") or "Karta"

            remaining = target - current

            # Kod PB do wyświetlania:
            # jeśli nie ma jeszcze pb_code w DB, fallback z id
            try:
                pb_code = pig_dict.get("pb_code") or (f"PB{int(p_id):06d}" if p_id is not None else "")
            except Exception:
                pb_code = ""

            progress_str = get_progress_bar_str(
                current=current,
                total=target,
                width=safe_width,
                is_savings=True,     # im więcej %, tym lepiej
                show_suffix=True     # procent na końcu paska
            )

            clean_prog = Text.from_markup(progress_str).plain

            processed_data.append({
                "pb_code": pb_code,
                "name": name,
                "account": acc_type,

                "collected": f"{current:.2f} PLN",
                "clean_collected": f"{current:.2f}",

                "remaining": f"{remaining:.2f} PLN",
                "clean_remaining": f"{remaining:.2f}",

                "progress": progress_str,
                "clean_progress": clean_prog,

                # ID zostaje wewnętrznie (SmartTable używa jako row_key)
                "id": str(p_id) if p_id is not None else "",
            })

        self.query_one("#piggy-smart-table", SmartTable).set_data(processed_data)