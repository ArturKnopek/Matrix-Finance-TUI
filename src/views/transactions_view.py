from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Select, Label

from src.database import fetch_transactions, get_unique_categories, get_active_month_str
from src.utils.smart_table import SmartTable


class TransactionsView(Horizontal):
    """
    Widok transakcji:
    - toolbar: wyszukiwanie + filtr kategorii + bilans
    - tabela: SmartTable z automatycznym dopasowaniem kolumn

    Standard:
    - w UI pokazujemy human_code: TX000001
    - wewnętrznie nadal operujemy na id (int jako string) do edycji/usuwania
    """

    COLUMNS_CONFIG = [
        ("human_code", "Kod", 9),
        ("date", "Data", 6),
        ("category", "Kat.", 8),
        ("amount", "Kwota", 10),
        ("shop", "Sklep", 12),
        ("desc", "Opis", 10),
    ]

    BINDINGS = [
        ("/", "focus_search", "Szukaj"),
        ("escape", "clear_filters", "Wyczyść"),
        ("ctrl+r", "reload", "Odśwież"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._search_timer = None  # debounce dla wyszukiwania

    def compose(self) -> ComposeResult:
        with Horizontal(id="trans-toolbar"):
            yield Input(placeholder="Szukaj...", id="trans-search")
            yield Select([], prompt="Kategoria", id="trans-cat-select")
            yield Label("BILANS: 0.00 PLN", id="trans-sum-label")

        yield SmartTable(
            id="my-smart-table",
            columns_def=self.COLUMNS_CONFIG,
            sacrificial_col="desc",
            expandable_col="desc",
            backup_expand_col="shop",
            rows_per_page_offset=1,
        )

    def on_mount(self) -> None:
        self.load_categories()
        self.load_data()

        try:
            self.query_one("#trans-search", Input).focus()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Akcje klawiszowe
    # ---------------------------------------------------------------------

    def action_focus_search(self) -> None:
        try:
            self.query_one("#trans-search", Input).focus()
        except Exception:
            pass

    def action_clear_filters(self) -> None:
        """Esc: czyści wyszukiwanie i filtr kategorii."""
        try:
            self.query_one("#trans-search", Input).value = ""
        except Exception:
            pass

        try:
            sel = self.query_one("#trans-cat-select", Select)
            sel.value = "CLEAR"
        except Exception:
            pass

        self.load_data()

    def action_reload(self) -> None:
        self.load_categories()
        self.load_data()

    # ---------------------------------------------------------------------
    # Toolbar
    # ---------------------------------------------------------------------

    def load_categories(self) -> None:
        """Ładuje listę kategorii do Select."""
        cats = get_unique_categories() or []
        options = [("Wszystkie", "CLEAR")] + [(c, c) for c in cats]

        select = self.query_one("#trans-cat-select", Select)
        select.set_options(options)

        if select.value in (Select.BLANK, None):
            select.value = "CLEAR"

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce: nie odpalamy bazy na każdy znak."""
        if event.input.id != "trans-search":
            return

        try:
            if self._search_timer is not None:
                self._search_timer.stop()
        except Exception:
            pass

        self._search_timer = self.set_timer(0.15, self.load_data)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "trans-cat-select":
            self.load_data()

    # ---------------------------------------------------------------------
    # Dane
    # ---------------------------------------------------------------------

    def load_data(self) -> None:
        """Pobiera dane z bazy, przygotowuje pod SmartTable i aktualizuje bilans."""
        search_query = self.query_one("#trans-search", Input).value.strip()
        raw_cat = self.query_one("#trans-cat-select", Select).value

        category_filter = None
        if raw_cat not in (Select.BLANK, "CLEAR", None):
            category_filter = raw_cat

        active_month = get_active_month_str()
        raw_rows = fetch_transactions(search_query, category_filter, active_month) or []

        processed = []
        total_sum = 0.0

        for row in raw_rows:
            r = dict(row)  # sqlite3.Row -> dict (bezpieczne .get)

            tx_id = r.get("id")
            raw_date = r.get("date")
            tx_type = r.get("type")

            category = r.get("category") or "---"
            shop = r.get("shop") or ""
            desc = r.get("description") or ""

            # human_code z DB (jeśli brak, fallback do TX000001 na podstawie id)
            try:
                human_code = r.get("human_code") or (f"TX{int(tx_id):06d}" if tx_id is not None else "")
            except Exception:
                human_code = ""

            # Skrócona data dd-mm
            try:
                dt = datetime.strptime(str(raw_date), "%Y-%m-%d")
                short_date = dt.strftime("%d-%m")
            except Exception:
                short_date = str(raw_date)

            # Kwota
            try:
                amount_val = float(r.get("amount") or 0.0)
            except Exception:
                amount_val = 0.0

            color = "[#FF0000]" if tx_type == "Wydatek" else "[#00FF41]"
            amt_str = f"{color}{amount_val:.2f} PLN[/]"
            clean_amt = f"{amount_val:.2f}"

            processed.append(
                {
                    # UI:
                    "human_code": human_code,

                    # reszta:
                    "date": short_date,
                    "category": category,
                    "shop": shop,
                    "amount": amt_str,
                    "clean_amount": clean_amt,
                    "desc": desc,
                    "raw_amount": amount_val,

                    # WEWNĘTRZNIE: id zostaje prawdziwym ID transakcji (dla edycji/usuwania)
                    "id": str(tx_id) if tx_id is not None else "",
                }
            )

            total_sum += amount_val if tx_type != "Wydatek" else -amount_val

        self.query_one("#my-smart-table", SmartTable).set_data(processed)

        color_sum = "[#00FF41]" if total_sum >= 0 else "[#FF0000]"
        self.query_one("#trans-sum-label", Label).update(
            f"BILANS: {color_sum}{total_sum:.2f} PLN[/]"
        )

    def get_selected_transaction_id(self):
        """Zwraca ID transakcji zaznaczonej w tabeli (ciągle integer id jako string)."""
        return self.query_one("#my-smart-table", SmartTable).get_selected_id()