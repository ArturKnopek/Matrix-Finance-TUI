from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Select

from src.database import fetch_transactions, get_active_month_str, get_account_options, get_unique_categories
from src.utils.smart_table import Col, SmartTable
from src.utils.ui_tools import GREEN, RED, WidthClassesMixin, money

ALL = "__ALL__"


class TransactionsView(WidthClassesMixin, Vertical):
    """
    Widok transakcji:
    - pasek narzędzi: wyszukiwanie + filtr kategorii + filtr konta + bilans,
    - SmartTable: kolumny same dopasowują się do szerokości okna
      (przy wąskim oknie najpierw znika notatka, potem konto, potem kod).
    """

    COLUMNS = [
        Col("human_code", "Kod", 8, hide_priority=2),
        Col("date", "Data", 5),
        Col("category", "Kategoria", 6, max_width=20),
        Col("amount", "Kwota", 9, align="right"),
        Col("account", "Konto", 5, max_width=14, hide_priority=3),
        Col("shop", "Sklep / opis", 10, max_width=32, flex=1),
        Col("desc", "Notatka", 12, max_width=60, flex=2, hide_priority=4),
    ]

    BINDINGS = [
        ("/", "focus_search", "Szukaj"),
        ("escape", "clear_filters", "Wyczyść"),
        ("ctrl+r", "reload", "Odśwież"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._search_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="trans-toolbar", classes="toolbar"):
            yield Input(placeholder="Szukaj (/)...", id="trans-search")
            yield Select([("Wszystkie kategorie", ALL)], value=ALL, id="trans-cat-select", allow_blank=False)
            yield Select([("Wszystkie konta", ALL)], value=ALL, id="trans-acc-select", allow_blank=False)
            yield Label("", id="trans-sum-label")
        yield SmartTable(self.COLUMNS, id="my-smart-table", empty_text="brak transakcji w tym miesiącu")

    def on_mount(self) -> None:
        self.load_filters()

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#my-smart-table", SmartTable).focus_table()

    # ------------------------------------------------------------- actions

    def action_focus_search(self) -> None:
        self.query_one("#trans-search", Input).focus()

    def action_clear_filters(self) -> None:
        search = self.query_one("#trans-search", Input)
        cat = self.query_one("#trans-cat-select", Select)
        acc = self.query_one("#trans-acc-select", Select)
        if not search.value and cat.value == ALL and acc.value == ALL and not search.has_focus:
            raise SkipAction()  # brak filtrów -> ESC obsłuży ekran (powrót do menu)
        search.value = ""
        cat.value = ALL
        acc.value = ALL
        self.load_data()
        self.focus_table()

    def action_reload(self) -> None:
        self.load_filters()
        self.load_data()

    # ------------------------------------------------------------- toolbar

    def load_filters(self) -> None:
        cat_sel = self.query_one("#trans-cat-select", Select)
        cats = get_unique_categories() or []
        current = cat_sel.value
        cat_sel.set_options([("Wszystkie kategorie", ALL)] + [(c, c) for c in cats])
        cat_sel.value = current if current in cats else ALL

        acc_sel = self.query_one("#trans-acc-select", Select)
        accounts = get_account_options(active_only=False)
        current = acc_sel.value
        acc_sel.set_options([("Wszystkie konta", ALL)] + list(accounts))
        acc_sel.value = current if current in {v for _, v in accounts} else ALL

    # zgodność wsteczna
    load_categories = load_filters

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "trans-search":
            return
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.15, self.load_data)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("trans-cat-select", "trans-acc-select"):
            self.load_data()

    # ---------------------------------------------------------------- data

    def load_data(self) -> None:
        search_query = self.query_one("#trans-search", Input).value.strip()
        raw_cat = self.query_one("#trans-cat-select", Select).value
        raw_acc = self.query_one("#trans-acc-select", Select).value
        category_filter = None if raw_cat in (Select.BLANK, ALL, None) else raw_cat
        account_filter = None if raw_acc in (Select.BLANK, ALL, None) else raw_acc

        rows = fetch_transactions(search_query, category_filter, get_active_month_str()) or []

        processed = []
        total = 0.0
        for row in rows:
            r = dict(row)
            if account_filter and r.get("account_type") != account_filter:
                continue

            tx_id = r.get("id")
            is_expense = r.get("type") == "Wydatek"
            amount = float(r.get("amount") or 0.0)
            signed = -amount if is_expense else amount
            total += signed

            try:
                short_date = datetime.strptime(str(r.get("date")), "%Y-%m-%d").strftime("%d.%m")
            except ValueError:
                short_date = str(r.get("date") or "")

            amount_txt = money(signed, "", signed=True)
            processed.append({
                "id": str(tx_id),
                "human_code": r.get("human_code") or (f"TX{int(tx_id):06d}" if tx_id is not None else ""),
                "date": short_date,
                "category": r.get("category") or "---",
                "amount": Text(amount_txt, style=RED if is_expense else GREEN),
                "clean_amount": amount_txt,
                "account": r.get("account_type") or "",
                "shop": r.get("shop") or "",
                "desc": r.get("description") or "",
            })

        self.query_one("#my-smart-table", SmartTable).set_data(processed)

        color = GREEN if total >= 0 else RED
        label = Text("BILANS: ", style="bold " + GREEN)
        label.append(money(total, signed=True), style=f"bold {color}")
        self.query_one("#trans-sum-label", Label).update(label)

    def get_selected_transaction_id(self):
        return self.query_one("#my-smart-table", SmartTable).get_selected_id()
