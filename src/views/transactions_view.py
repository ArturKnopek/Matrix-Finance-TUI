"""Transakcje miesiąca roboczego: wyszukiwanie, filtry (koperta, konto, rodzaj), bilans."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Select

from src.finance.accounts import get_account_options
from src.finance.envelopes import get_unique_categories
from src.finance.ledger import TRANSFER, delete_transaction, describe_entry, fetch_transactions, get_transaction_by_id
from src.finance.storage import get_active_month_str
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import WidthClassesMixin, money
from src.views.base import ViewAction, ViewMixin

ALL = "__ALL__"
BUDGET_ONLY = "__BUDGET__"
TYPE_FILTERS = [("Wydatki i dochody", BUDGET_ONLY), ("Wszystko (z przelewami)", ALL), ("Tylko wydatki", "Wydatek"),
                ("Tylko dochody", "Dochód"), ("Przelewy i operacje", TRANSFER)]


class TransactionsView(WidthClassesMixin, ViewMixin, Vertical):
    TITLE = "TRANSAKCJE"
    COLUMNS = [
        Col("human_code", "Kod", 8, hide_priority=2),
        Col("date", "Data", 5),
        Col("category", "Koperta / rodzaj", 8, max_width=22),
        Col("amount", "Kwota", 9, align="right"),
        Col("account", "Konto", 5, max_width=16, hide_priority=3),
        Col("shop", "Opis", 10, max_width=34, flex=1),
        Col("desc", "Notatka", 12, max_width=60, flex=2, hide_priority=4),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWA", "NOWA"),
        ViewAction("edit", "^E", "EDYTUJ", "EDYT."),
        ViewAction("delete", "^D", "USUŃ", "USUŃ"),
        ViewAction("transfer", "^T", "PRZELEW", "PRZEL."),
        ViewAction("filter", "/", "FILTRUJ", "FILTR"),
    ]
    BINDINGS = [("/", "focus_search", "Filtruj"), ("escape", "clear_filters", "Wyczyść")]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._search_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="trans-toolbar", classes="toolbar"):
            yield Input(placeholder="Filtruj (/)…", id="trans-search")
            yield Select([("Wszystkie koperty", ALL)], value=ALL, id="trans-cat-select", allow_blank=False)
            yield Select([("Wszystkie konta", ALL)], value=ALL, id="trans-acc-select", allow_blank=False)
            yield Select(TYPE_FILTERS, value=BUDGET_ONLY, id="trans-type-select", allow_blank=False)
            yield Label("", id="trans-sum-label")
        yield SmartTable(self.COLUMNS, id="trans-table", empty_text="brak transakcji w tym miesiącu — ^N dodaje")

    def on_mount(self) -> None:
        self.load_filters()

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#trans-table", SmartTable).focus_table()

    def select_ref(self, ref: Any) -> None:
        self.query_one("#trans-table", SmartTable).select_id(ref)

    # ---------------------------------------------------------------- akcje

    def _selected(self) -> Any:
        t_id = self.query_one("#trans-table", SmartTable).get_selected_id()
        return get_transaction_by_id(int(t_id)) if t_id else None

    def do_new(self) -> None:
        from src.ui.forms import TransactionDialog

        self.open_dialog(TransactionDialog())

    def do_edit(self) -> None:
        from src.ui.forms import TransactionDialog

        row = self._selected()
        if not row:
            return self.warn_select("transakcję")
        if row["type"] == TRANSFER:
            self.notify("Przelewów i operacji na celach nie edytuje się — usuń wpis (^D) i utwórz go ponownie.",
                        severity="warning")
            return
        self.open_dialog(TransactionDialog(row))

    def do_delete(self) -> None:
        row = self._selected()
        if not row:
            return self.warn_select("transakcję")
        code = row["human_code"]
        extra = "\nTo przelew — zostaną usunięte obie strony." if row["linked_group_id"] else ""

        def delete() -> str:
            n = delete_transaction(int(row["id"]))
            return f"Usunięto {code}" + (f" (+{n - 1} powiązany)" if n > 1 else "") + "."

        self.confirm(f"Usunąć {code}?\nSaldo konta zostanie skorygowane.{extra}", delete)

    def do_transfer(self) -> None:
        from src.ui.forms import TransferDialog

        self.open_dialog(TransferDialog())

    def do_filter(self) -> None:
        self.action_focus_search()

    def action_focus_search(self) -> None:
        self.query_one("#trans-search", Input).focus()

    def action_clear_filters(self) -> None:
        search = self.query_one("#trans-search", Input)
        selects = [self.query_one(f"#{i}", Select) for i in ("trans-cat-select", "trans-acc-select",
                                                              "trans-type-select")]
        defaults = (ALL, ALL, BUDGET_ONLY)
        if not search.value and all(s.value == d for s, d in zip(selects, defaults)) and not search.has_focus:
            raise SkipAction()
        search.value = ""
        for s, d in zip(selects, defaults):
            s.value = d
        self.load_data()
        self.focus_table()

    # ---------------------------------------------------------------- filtry

    def load_filters(self) -> None:
        cat_sel = self.query_one("#trans-cat-select", Select)
        cats = get_unique_categories()
        current = cat_sel.value
        cat_sel.set_options([("Wszystkie koperty", ALL)] + [(c, c) for c in cats])
        cat_sel.value = current if current in cats else ALL
        acc_sel = self.query_one("#trans-acc-select", Select)
        accounts = get_account_options(active_only=False)
        current = acc_sel.value
        acc_sel.set_options([("Wszystkie konta", ALL)] + list(accounts))
        acc_sel.value = current if current in {v for _, v in accounts} else ALL

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "trans-search":
            return
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.15, self.load_data)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "trans-search":
            event.stop()
            self.focus_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id and event.select.id.startswith("trans-"):
            self.load_data()

    # ---------------------------------------------------------------- dane

    def load_data(self) -> None:
        self.load_filters()
        p = palette()

        def val(widget_id: str) -> Any:
            v = self.query_one(f"#{widget_id}", Select).value
            return None if v in (Select.BLANK, ALL, BUDGET_ONLY, None) else v

        rows = fetch_transactions(self.query_one("#trans-search", Input).value.strip(), val("trans-cat-select"),
                                  get_active_month_str(), val("trans-acc-select"), val("trans-type-select"))
        if self.query_one("#trans-type-select", Select).value == BUDGET_ONLY:
            rows = [r for r in rows if r["type"] != TRANSFER]
        processed = []
        balance = 0.0
        for row in rows:
            e = describe_entry(row)
            signed = e["signed_amount"]
            if e["type"] != TRANSFER:
                balance += signed
            color = p.transfer if e["type"] == TRANSFER else p.negative if signed < 0 else p.positive
            if not int(e.get("is_registered") or 0):
                color = p.muted
            try:
                short_date = datetime.strptime(str(e["date"]), "%Y-%m-%d").strftime("%d.%m")
            except ValueError:
                short_date = str(e["date"])
            amount_txt = money(signed, "", signed=True)
            category = e.get("category") or ("↔ " + e["kind_label"] if e["type"] == TRANSFER else "—")
            processed.append({
                "id": str(e["id"]),
                "human_code": e.get("human_code") or "",
                "date": short_date,
                "category": category,
                "amount": Text(amount_txt, style=color),
                "clean_amount": amount_txt,
                "account": e.get("account_type") or "",
                "shop": e.get("shop") or "",
                "desc": e.get("description") or "",
            })
        self.query_one("#trans-table", SmartTable).set_data(processed)
        label = Text("BILANS ", style=f"bold {p.muted}")
        label.append(money(balance, signed=True), style=f"bold {p.positive if balance >= 0 else p.negative}")
        self.query_one("#trans-sum-label", Label).update(label)
