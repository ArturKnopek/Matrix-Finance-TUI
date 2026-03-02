from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label
from textual.containers import Container, Horizontal
from textual.events import Resize

from src.database import get_all_recurring, get_piggy_bank_by_id
from src.utils.smart_table import SmartTable


class RecurringView(Container):
    """
    Widok Płatności Cyklicznych z użyciem SmartTable.
    - Pokazuje kod RR000001 (rr_code) zamiast ID (kolumna ID znika z UI)
    - ID zostaje wewnętrznie (SmartTable użyje jako row_key)
    - Waluta: PLN
    - 'Kiedy' pokazuje start_date + opis cyklu
    """

    COLUMNS_CONFIG = [
        ("rr_code", "Kod", 8),
        ("name", "Nazwa", 20),
        ("amount", "Kwota", 12),
        ("type", "Typ", 15),
        ("details", "Cel / Kategoria", 20),
        ("date", "Kiedy", 18),
        ("status", "Auto-Płatność", 15),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_data_cache = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="rec-header-panel"):
            yield Label("LISTA ZDEFINIOWANYCH PŁATNOŚCI", classes="rec-header-title")

        yield SmartTable(
            id="rec-smart-table",
            columns_def=self.COLUMNS_CONFIG,
            sacrificial_col="details",
            expandable_col=None,
            backup_expand_col=None,
            rows_per_page_offset=4,
        )

    def on_mount(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        """Pobiera dane i odświeża tabelę."""
        self.fetch_fresh_data()
        self.regenerate_table_data()

    def refresh_table(self) -> None:
        self.load_data()

    def on_resize(self, event: Resize) -> None:
        # set_data() w SmartTable i tak przeliczy układ,
        # więc tu tylko regenerujemy dane jeśli cache nie jest puste
        if self.raw_data_cache:
            self.regenerate_table_data()

    def fetch_fresh_data(self) -> None:
        self.raw_data_cache = get_all_recurring() or []

    def get_selected_recurring_id(self):
        """Zwraca wewnętrzne ID (int jako string) zaznaczonej płatności cyklicznej."""
        return self.query_one("#rec-smart-table", SmartTable).get_selected_id()

    # ---------------------------------------------------------------------
    # Dane do tabeli
    # ---------------------------------------------------------------------

    def regenerate_table_data(self) -> None:
        table = self.query_one("#rec-smart-table", SmartTable)

        if not self.raw_data_cache:
            table.set_data([])
            return

        cycle_map = {
            "Dziennie": "co dzień",
            "Tygodniowo": "co tydz.",
            "Miesięcznie": "co m-c",
            "Rocznie": "co rok",
        }

        processed_data = []

        for row in self.raw_data_cache:
            r = dict(row)  # sqlite3.Row -> dict (bezpieczne .get)

            r_id = r.get("id")
            name = r.get("name", "")
            amount = float(r.get("amount", 0.0) or 0.0)
            r_type = r.get("type", "")

            # Kod RR do wyświetlania (fallback z id jeśli brak w DB)
            rr_code = r.get("rr_code") or (f"RR{int(r_id):06d}" if r_id is not None else "")

            # Cel / Kategoria
            if r_type == "Na Skarbonkę":
                piggy_id = r.get("piggy_id")
                if piggy_id:
                    # Spróbuj wyciągnąć PB000001 z piggy_banks (fallback do ID)
                    try:
                        pig = get_piggy_bank_by_id(int(piggy_id))
                        pig_dict = dict(pig) if pig else {}
                        pb_code = pig_dict.get("pb_code") or f"PB{int(piggy_id):06d}"
                        details = f"Cel: {pb_code}"
                    except Exception:
                        details = f"Cel ID: {piggy_id}"
                else:
                    details = "Cel: ---"
            else:
                details = r.get("category") or "---"

            # Kiedy: data startu + cykl
            start_date = r.get("start_date") or ""
            cycle = r.get("cycle") or "Miesięcznie"
            cycle_txt = cycle_map.get(cycle, cycle.lower())
            date_str = f"{start_date} ({cycle_txt})"

            # Status auto-płatności (is_registered)
            is_reg = int(r.get("is_registered", 0) or 0) == 1
            status_str = "TAK" if is_reg else "NIE"
            status_colored = f"[#00FF41]{status_str}[/]" if is_reg else f"[grey]{status_str}[/]"

            # Kolor kwoty
            if r_type == "Wydatek":
                color = "[#FF0000]"
            elif r_type == "Dochód":
                color = "[#00FF41]"
            else:
                color = "[#FFD700]"  # Na Skarbonkę

            amt_str = f"{color}{amount:.2f} PLN[/]"

            processed_data.append({
                # UI
                "rr_code": rr_code,
                "name": name,
                "amount": amt_str,
                "clean_amount": f"{amount:.2f}",
                "type": r_type,
                "details": details,
                "date": date_str,
                "status": status_colored,
                "clean_status": status_str,

                # WEWNĘTRZNIE: zostaw id jako klucz wiersza
                "id": str(r_id) if r_id is not None else "",
            })

        table.set_data(processed_data)