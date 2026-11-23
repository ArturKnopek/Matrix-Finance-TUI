"""Automaty: zlecenia cykliczne oraz reguły auto-oszczędzania (dwie tabele, Tab przełącza)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from src.finance import autosave as autosave_api
from src.finance import recurring as rec_api
from src.finance.goals import get_all_piggy_banks
from src.finance.storage import get_active_month_str
from src.ui.smart_table import Col, SmartTable
from src.ui.theme import palette
from src.ui.widgets import money
from src.views.base import ViewAction, ViewMixin
from src.views.dashboard_view import describe_days

CYCLE_SHORT = {"Dziennie": "co dzień", "Tygodniowo": "co tydz.", "Miesięcznie": "co m-c", "Kwartalnie": "co kw.",
               "Rocznie": "co rok"}


class AutomationView(ViewMixin, Vertical):
    TITLE = "AUTOMATY — ZLECENIA I AUTO-OSZCZĘDZANIE"
    REC_COLUMNS = [
        Col("code", "Kod", 8, hide_priority=4),
        Col("name", "Zlecenie", 10, max_width=26, flex=1),
        Col("amount", "Kwota", 9, align="right"),
        Col("type", "Rodzaj", 6, max_width=13, hide_priority=2),
        Col("details", "Koperta / cel / konto", 8, max_width=24, hide_priority=3),
        Col("cycle", "Cykl", 6, hide_priority=1),
        Col("next", "Następna", 10),
        Col("status", "Status", 8),
    ]
    RULE_COLUMNS = [
        Col("source", "Konto", 6, max_width=18),
        Col("rule", "Reguła", 12, max_width=34, flex=1),
        Col("target", "Odkładaj do", 8, max_width=24),
        Col("status", "Status", 8),
    ]
    ACTIONS = [
        ViewAction("new", "^N", "NOWE", "NOWE"),
        ViewAction("edit", "^E", "EDYTUJ", "EDYT."),
        ViewAction("delete", "^D", "USUŃ", "USUŃ"),
        ViewAction("pause", "^P", "PAUZA / WZNÓW", "PAUZA"),
        ViewAction("new_rule", "A", "NOWA REGUŁA AUTO", "AUTO"),
    ]
    BINDINGS = [("a", "new_rule_key", "Nowa reguła")]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._focus_rules = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="auto-header", classes="view-header"):
            yield Label("ZLECENIA CYKLICZNE", classes="view-header-title")
            yield Label("", id="auto-stats", classes="view-header-stats")
        yield SmartTable(self.REC_COLUMNS, id="rec-table", empty_text="brak zleceń — ^N dodaje (pensja, rachunki…)")
        with Horizontal(id="rules-header", classes="view-header"):
            yield Label("AUTO-OSZCZĘDZANIE", classes="view-header-title")
            yield Label("", id="rules-stats", classes="view-header-stats")
        yield SmartTable(self.RULE_COLUMNS, id="rules-table",
                         empty_text="brak reguł — A dodaje (np. 10% każdej wypłaty na oszczędności)")

    def on_show(self) -> None:
        self.call_after_refresh(self.focus_table)

    def focus_table(self) -> None:
        self.query_one("#rules-table" if self._focus_rules else "#rec-table", SmartTable).focus_table()

    def on_descendant_focus(self, event) -> None:
        rules = self.query_one("#rules-table", SmartTable)
        self._focus_rules = rules in event.widget.ancestors_with_self

    # ---------------------------------------------------------------- wybór

    def _rec(self):
        r_id = self.query_one("#rec-table", SmartTable).get_selected_id()
        return rec_api.get_recurring_by_id(int(r_id)) if r_id else None

    def _rule(self):
        r_id = self.query_one("#rules-table", SmartTable).get_selected_id()
        return autosave_api.get_autosave_rule(int(r_id)) if r_id else None

    # ---------------------------------------------------------------- akcje

    def do_new(self) -> None:
        if self._focus_rules:
            return self.do_new_rule()
        from src.ui.forms import RecurringDialog

        self.open_dialog(RecurringDialog())

    def do_new_rule(self) -> None:
        from src.ui.forms import AutosaveRuleDialog

        self.open_dialog(AutosaveRuleDialog())

    def action_new_rule_key(self) -> None:
        self.do_new_rule()

    def do_edit(self) -> None:
        from src.ui.forms import AutosaveRuleDialog, RecurringDialog

        if self._focus_rules:
            rule = self._rule()
            return self.open_dialog(AutosaveRuleDialog(rule)) if rule else self.warn_select("regułę")
        row = self._rec()
        self.open_dialog(RecurringDialog(row)) if row else self.warn_select("zlecenie")

    def do_delete(self) -> None:
        if self._focus_rules:
            rule = self._rule()
            if not rule:
                return self.warn_select("regułę")
            return self.confirm("Usunąć regułę auto-oszczędzania?",
                                lambda: (autosave_api.delete_autosave_rule(int(rule["id"])), "Usunięto regułę.")[1])
        row = self._rec()
        if not row:
            return self.warn_select("zlecenie")
        self.confirm(f"Usunąć zlecenie „{row['name']}”?",
                     lambda: (rec_api.delete_recurring(int(row["id"])), f"Usunięto {row['rr_code']}.")[1])

    def do_pause(self) -> None:
        from src.views.base import DataChanged

        if self._focus_rules:
            rule = self._rule()
            if not rule:
                return self.warn_select("regułę")
            active = autosave_api.toggle_autosave_rule(int(rule["id"]))
            self.post_message(DataChanged(f"Reguła {'AKTYWNA' if active else 'WSTRZYMANA'}."))
            return
        row = self._rec()
        if not row:
            return self.warn_select("zlecenie")
        active = rec_api.toggle_recurring_pause(int(row["id"]))
        self.post_message(DataChanged(f"{row['rr_code']} → {'AKTYWNE' if active else 'WSTRZYMANE'}"))

    # ---------------------------------------------------------------- dane

    def load_data(self) -> None:
        p = palette()
        goals = {int(g["id"]): g["name"] for g in get_all_piggy_banks()}
        today = date.today()
        rows = []
        for r in rec_api.get_all_recurring():
            r = dict(r)
            r_type = r["type"]
            active = int(r.get("is_registered") or 0) == 1
            if r_type == "Na Skarbonkę":
                details = f"cel: {goals.get(int(r.get('piggy_id') or 0), '---')}"
            elif r_type == "Przelew":
                details = f"→ {r.get('target_account') or '---'}"
            else:
                details = r.get("category") or "—"
            nxt = rec_api.get_recurring_next_due(r)
            days = (nxt - today).days if nxt else None
            if not active:
                status = Text("PAUZA", style=p.muted)
            elif days is not None and days < 0:
                status = Text("ZALEGŁE", style=f"bold {p.negative}")
            else:
                status = Text(describe_days(days) if days is not None and days <= 7 else "aktywne", style=p.positive)
            color = p.negative if r_type == "Wydatek" else p.positive if r_type == "Dochód" else p.transfer
            amount = money(float(r["amount"]), "")
            rows.append({
                "id": str(r["id"]), "code": r.get("rr_code") or "", "name": r["name"],
                "amount": Text(amount, style=color), "clean_amount": amount, "type": r_type, "details": details,
                "cycle": CYCLE_SHORT.get(r["cycle"], r["cycle"]), "next": nxt.strftime("%d.%m.%Y") if nxt else "—",
                "status": status, "clean_status": status.plain,
            })
        self.query_one("#rec-table", SmartTable).set_data(rows)

        summary = rec_api.monthly_cost_summary()
        stats = Text()
        stats.append("koszty/m-c ", style=p.muted)
        stats.append(money(summary["cost"], ""), style=f"bold {p.negative}")
        stats.append("  wpływy ", style=p.muted)
        stats.append(money(summary["income"], ""), style=f"bold {p.positive}")
        stats.append("  odkładanie ", style=p.muted)
        stats.append(money(summary["saving"], ""), style=f"bold {p.transfer}")
        self.query_one("#auto-stats", Label).update(stats)

        rules = []
        for rule in autosave_api.get_autosave_rules():
            target = rule["target"]
            if rule["target_kind"] == "goal":
                target = f"cel: {goals.get(int(target), '?')}"
            active = int(rule["is_active"]) == 1
            status = Text("AKTYWNA" if active else "PAUZA", style=p.positive if active else p.muted)
            rules.append({"id": str(rule["id"]), "source": rule["source_account"],
                          "rule": autosave_api.describe_rule(rule).split(": ", 1)[-1], "target": target,
                          "status": status, "clean_status": status.plain})
        self.query_one("#rules-table", SmartTable).set_data(rules)
        saved = autosave_api.autosave_total_in_month(get_active_month_str())
        self.query_one("#rules-stats", Label).update(Text(f"odłożono automatycznie w tym miesiącu: {money(saved)}",
                                                          style=p.muted))

    def selected_rule_or_rec(self) -> Optional[str]:
        return "rule" if self._focus_rules else "recurring"
