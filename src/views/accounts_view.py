"""Konta i produkty: codzienne, oszczędności (lokaty), inwestycje (obligacje, maklerskie, robodoradca), emerytalne."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.finance import accounts as acc_api
from src.finance.autosave import describe_rule, get_autosave_rules
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import meter_text, money
from src.views.base import ViewAction, ViewMixin


def _progress_cell(item: Any, width: int) -> Text:
    if item.get("progress") is None:
        return Text(item.get("progress_label") or "", style=palette().muted)
    return meter_text(item["progress"], width, "goal")


class AccountsView(ViewMixin, Vertical):
    TITLE = "KONTA, LOKATY I INWESTYCJE"
    COLUMNS = [
        Col("name", "Konto", 8, max_width=24),
        Col("kind", "Rodzaj", 6, max_width=22, hide_priority=3),
        Col("institution", "Instytucja", 6, max_width=16, hide_priority=4),
        Col("balance", "Saldo / wartość", 10, align="right"),
        Col("rate", "Oproc.", 6, align="right", hide_priority=2),
        Col("info", "Szczegóły", 10, max_width=34, hide_priority=1),
        Col("progress", "Postęp", 10, flex=1, render=_progress_cell),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWE KONTO", "NOWE"),
        ViewAction("edit", "^E", "EDYTUJ", "EDYT."),
        ViewAction("deposit", "+", "WPŁATA", "WPŁ."),
        ViewAction("withdraw", "-", "WYPŁATA", "WYP."),
        ViewAction("transfer", "^T", "PRZELEW", "PRZEL."),
        ViewAction("valuation", "W", "WYCENA / ODSETKI", "WYCENA"),
        ViewAction("correction", "K", "KOREKTA SALDA", "KOREKTA"),
        ViewAction("autosave", "A", "AUTO-OSZCZĘDZANIE", "AUTO"),
        ViewAction("delete", "^D", "ZAMKNIJ", "ZAMK."),
    ]
    BINDINGS = [("w", "view_action('valuation')", "Wycena"), ("a", "view_action('autosave')", "Auto"),
                ("o", "view_action('external')", "Wpłata zewn."), ("k", "view_action('correction')", "Korekta")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="acc-header", classes="view-header"):
            yield Label("MAJĄTEK", classes="view-header-title")
            yield Label("", id="acc-stats", classes="view-header-stats")
        yield SmartTable(self.COLUMNS, id="acc-table", empty_text="brak kont — ^N dodaje")
        yield Label("", id="acc-detail", classes="view-hint")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#acc-table", SmartTable).focus_table()

    def select_ref(self, ref: Any) -> None:
        self.query_one("#acc-table", SmartTable).select_id(ref)

    # ---------------------------------------------------------------- wybór

    def _selected_name(self) -> Optional[str]:
        return self.query_one("#acc-table", SmartTable).get_selected_id()

    def _selected(self):
        name = self._selected_name()
        return acc_api.get_account(name) if name else None

    def on_data_table_row_highlighted(self, event) -> None:
        self._update_detail()

    def _update_detail(self) -> None:
        row = self._selected()
        label = self.query_one("#acc-detail", Label)
        if not row:
            label.update("")
            return
        info = acc_api.kind_info(row["account_kind"])
        ops = ["+ wpłata", "- wypłata", "^T przelew"]
        if info.valuation:
            ops.append("W wycena")
        if info.has_rate and not info.has_term:
            ops.append("W odsetki")
        if info.retirement:
            ops.append("O wpłata zewnętrzna (np. pracodawca)")
        if info.has_term:
            ops = ["^D zerwij lokatę", "^E edytuj (odnawianie)"]
        ops.append("K korekta salda")
        rules = get_autosave_rules(row["name"])
        rule_txt = f" · auto: {describe_rule(rules[0])}" if rules else " · A — auto-oszczędzanie"
        label.update(f"{row['name']}: " + " · ".join(ops) + rule_txt)

    # ---------------------------------------------------------------- akcje

    def do_new(self) -> None:
        from src.ui.forms import AccountDialog

        self.open_dialog(AccountDialog())

    def do_edit(self) -> None:
        from src.ui.forms import AccountDialog

        name = self._selected_name()
        self.open_dialog(AccountDialog(name)) if name else self.warn_select("konto")

    def _op(self, operation: str) -> None:
        from src.ui.forms import AccountOperationDialog

        row = self._selected()
        if not row:
            return self.warn_select("konto")
        if acc_api.kind_info(row["account_kind"]).has_term and operation not in ("close", "correction"):
            self.notify("Lokata/obligacje: środki wrócą automatycznie po terminie; ^D — zerwanie.",
                        severity="warning")
            return
        self.open_dialog(AccountOperationDialog(row["name"], operation))

    def do_deposit(self) -> None:
        self._op("deposit")

    def do_withdraw(self) -> None:
        self._op("withdraw")

    def do_external(self) -> None:
        self._op("external")

    def do_valuation(self) -> None:
        row = self._selected()
        if not row:
            return self.warn_select("konto")
        info = acc_api.kind_info(row["account_kind"])
        self._op("valuation" if info.valuation else "interest")

    def do_correction(self) -> None:
        self._op("correction")

    def do_transfer(self) -> None:
        from src.ui.forms import TransferDialog

        self.open_dialog(TransferDialog(source=self._selected_name()))

    def do_autosave(self) -> None:
        from src.ui.forms import AutosaveRuleDialog

        name = self._selected_name()
        rules = get_autosave_rules(name) if name else []
        self.open_dialog(AutosaveRuleDialog(rules[0] if rules else None, source=name))

    def do_delete(self) -> None:
        row = self._selected()
        if not row:
            return self.warn_select("konto")
        if acc_api.kind_info(row["account_kind"]).has_term:
            name = row["name"]

            def do_break() -> str:
                ok, msg = acc_api.break_term_deposit(name)
                if not ok:
                    raise ValueError(msg)
                return msg

            self.confirm(f"Zerwać „{name}” przed terminem?\nKapitał wróci na konto powiązane BEZ odsetek.",
                         do_break, remember=False, title="ZERWANIE LOKATY")
            return
        self._op("close")

    # ---------------------------------------------------------------- dane

    def load_data(self) -> None:
        p = palette()
        rows = []
        for group in acc_api.KIND_GROUPS:
            for a in [x for x in acc_api.get_accounts_overview() if x["group"] == group]:
                info = a["kind"]
                rate = float(a.get("interest_rate") or 0)
                progress, progress_label, details = None, "", ""
                proj = a.get("projection")
                if proj:
                    progress = proj["progress"]
                    details = f"do {proj['end']:%d.%m.%Y} · +{proj['net_interest']:.2f} netto"
                elif info.retirement and float(a.get("yearly_limit") or 0) > 0:
                    progress = a.get("contributed_this_year", 0.0) / float(a["yearly_limit"]) * 100
                    details = f"wpłaty {a.get('contributed_this_year', 0):.0f} / limit {float(a['yearly_limit']):.0f}"
                elif a.get("monthly_interest_net"):
                    details = f"≈ +{a['monthly_interest_net']:.2f} / mies. netto"
                    progress_label = "oszczędności"
                elif info.valuation:
                    progress_label = "wycena ręczna (W)"
                balance_style = p.negative if a["balance"] < 0 else p.text
                rows.append({
                    "id": a["name"],
                    "name": a["name"],
                    "kind": f"{info.label}",
                    "institution": a.get("institution") or "",
                    "balance": Text(money(a["balance"], ""), style=f"bold {balance_style}"),
                    "clean_balance": money(a["balance"], ""),
                    "rate": f"{rate:g}%" if info.has_rate and rate else "",
                    "info": details or info.group,
                    "progress": progress,
                    "progress_label": progress_label,
                })
        self.query_one("#acc-table", SmartTable).set_data(rows)

        nw = acc_api.get_net_worth()
        stats = Text()
        placed = nw["total"] - nw["liquid"] - nw["goals"]
        for key, label, value in (("liquid", "dostępne", nw["liquid"]), ("placed", "ulokowane", placed),
                                  ("goals", "cele", nw["goals"]), ("total", "RAZEM", nw["total"])):
            if key != "total" and not value:
                continue
            stats.append(f" {label} ", style=p.muted)
            stats.append(money(value, ""), style=f"bold {p.accent if key == 'total' else p.text}")
        self.query_one("#acc-stats", Label).update(stats)
        self._update_detail()
