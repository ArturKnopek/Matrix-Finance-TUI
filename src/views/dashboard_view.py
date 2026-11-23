"""Pulpit: kafelki KPI, koperty, kalendarz, nadchodzące płatności, doradca, cele, struktura majątku."""

from __future__ import annotations

import logging

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import Label

from src.finance.accounts import KIND_GROUPS, get_accounts_overview, get_net_worth
from src.finance.analytics import get_calendar_data, get_insights, get_trend, savings_rate
from src.finance.envelopes import get_budget_summary, get_envelope_overview
from src.finance.goals import goals_overview
from src.finance.recurring import get_upcoming_recurring
from src.finance.storage import get_active_month_str
from src.ui.theme import palette
from src.ui.widgets import KpiTile, Meter, MonthCalendar, WidthClassesMixin, calculate_max_width, money
from src.views.base import ViewAction, ViewMixin

INSIGHT_ICONS = {"ok": ("✔", "positive"), "info": ("ℹ", "accent"), "warn": ("▲", "warning"),
                 "alert": ("✖", "negative")}


def describe_days(days: int) -> str:
    if days < 0:
        return "ZALEGŁE"
    if days == 0:
        return "DZIŚ"
    if days == 1:
        return "JUTRO"
    return f"za {days} dni"


class DashboardView(WidthClassesMixin, ViewMixin, VerticalScroll):
    TITLE = "PULPIT"
    NARROW_AT = 76
    ACTIONS = [
        ViewAction("new", "^N", "NOWA TRANSAKCJA", "NOWA"),
        ViewAction("transfer", "^T", "PRZELEW", "PRZEL."),
    ]

    def compose(self) -> ComposeResult:
        with Grid(id="dash-tiles"):
            yield KpiTile("MAJĄTEK NETTO", id="tile-networth")
            yield KpiTile("DO WYDANIA", extra="meter", id="tile-budget")
            yield KpiTile("BILANS MIESIĄCA", id="tile-flow")
            yield KpiTile("OSZCZĘDZANIE", extra="sparkline", id="tile-savings")
        with Grid(id="dash-grid"):
            with Vertical(id="card-envelopes", classes="dash-card"):
                yield Vertical(id="list-envelopes", classes="card-list")
            with Vertical(id="card-calendar", classes="dash-card"):
                yield MonthCalendar(interactive=False, id="dash-calendar")
            with Vertical(id="card-upcoming", classes="dash-card"):
                yield Vertical(id="list-upcoming", classes="card-list")
            with Vertical(id="card-advisor", classes="dash-card"):
                yield VerticalScroll(id="list-advisor", classes="card-list")
            with Vertical(id="card-goals", classes="dash-card"):
                yield Vertical(id="list-goals", classes="card-list")
            with Vertical(id="card-assets", classes="dash-card"):
                yield Vertical(id="list-assets", classes="card-list")

    def on_mount(self) -> None:
        for card_id, title in (("card-envelopes", "KOPERTY"), ("card-calendar", "KALENDARZ WYDATKÓW"),
                               ("card-upcoming", "NADCHODZĄCE"), ("card-advisor", "DORADCA"),
                               ("card-goals", "CELE"), ("card-assets", "STRUKTURA MAJĄTKU")):
            self.query_one(f"#{card_id}").border_title = title
        self.load_data()

    # ------------------------------------------------------------------ akcje

    def do_new(self) -> None:
        from src.ui.forms import TransactionDialog

        self.open_dialog(TransactionDialog())

    def do_transfer(self) -> None:
        from src.ui.forms import TransferDialog

        self.open_dialog(TransferDialog())

    def do_search(self) -> None:
        self.app.screen.action_search()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ dane

    def load_data(self) -> None:
        month = get_active_month_str()
        with self.app.batch_update():
            for part in (self._tiles, self._envelopes, self._calendar, self._upcoming, self._advisor,
                         self._goals, self._assets):
                try:
                    part(month)
                except Exception as e:
                    logging.exception("Błąd pulpitu (%s): %s", part.__name__, e)

    def _tiles(self, month: str) -> None:
        p = palette()
        nw = get_net_worth()
        invested = nw["total"] - nw["liquid"] - nw["goals"]
        self.query_one("#tile-networth", KpiTile).set(
            Text(money(nw["total"]), style=f"bold {p.accent}"),
            f"dostępne {money(nw['liquid'], '')} · ulokowane {money(invested + nw['goals'], '')}")

        b = get_budget_summary(month)
        pct = b["spent"] / b["available"] * 100 if b["available"] > 0 else None
        tone = "neg" if b["over_count"] else ""
        sub = f"z {money(b['available'], '')} · przekroczone: {b['over_count']}" if b["available"] > 0 \
            else "ustaw budżety kopert (zakładka 3)"
        self.query_one("#tile-budget", KpiTile).set(money(b["remaining"]), sub, tone, pct=pct)

        flow = b["income"] - b["expense"]
        self.query_one("#tile-flow", KpiTile).set(
            money(flow, signed=True), f"+{money(b['income'], '')} / −{money(b['expense'], '')}",
            "pos" if flow >= 0 else "neg")

        trend = get_trend(6, month)
        rate = savings_rate(b["income"], b["expense"])
        self.query_one("#tile-savings", KpiTile).set(
            "—" if rate is None else f"{rate:.0f}%",
            f"6 mies.: {money(sum(t['saved'] for t in trend), '')}",
            "" if rate is None else "pos" if rate >= 20 else "warn" if rate >= 0 else "neg",
            series=[max(0.0, t["saved"]) for t in trend])

    def _envelopes(self, month: str) -> None:
        cont = self.query_one("#list-envelopes", Vertical)
        cont.remove_children()
        items = [e for e in get_envelope_overview(month) if e["available"] > 0 or e["spent"] > 0]
        b = get_budget_summary(month)
        card = self.query_one("#card-envelopes")
        card.border_title = f"KOPERTY {month}"
        card.border_subtitle = f"do rozdysponowania {money(b['unallocated'], '')}" if b["income"] else ""
        if not items:
            cont.mount(Label("Brak budżetów — ustaw je w zakładce 3 (Koperty).", classes="dim-text"))
            return
        items.sort(key=lambda e: (e["pct"] is None, -(e["pct"] or 0), -e["spent"]))
        name_w = calculate_max_width([(None, e["name"]) for e in items], 1, 8, 16)
        rows = []
        for e in items:
            name = Label(("↻ " if e["rollover"] else "• ") + e["name"], classes="row-name")
            name.styles.width = name_w
            left = Label(money(e["remaining"], ""), classes="row-amount")
            if e["remaining"] < 0:
                left.add_class("-neg")
            rows.append(Horizontal(name, Meter(e["pct"], "budget", f"{money(e['spent'])} (bez limitu)"), left,
                                   classes="card-row"))
        cont.mount_all(rows)

    def _calendar(self, month: str) -> None:
        cal = self.query_one("#dash-calendar", MonthCalendar)
        cal.set_month(month, get_calendar_data(month))
        y, m = month.split("-")
        card = self.query_one("#card-calendar")
        card.border_title = f"KALENDARZ {m}.{y}"
        card.border_subtitle = "• zlecenie  ◆ lokata  odcień = wydatki"

    def _upcoming(self, month: str) -> None:
        p = palette()
        cont = self.query_one("#list-upcoming", Vertical)
        cont.remove_children()
        items = []
        for r in get_upcoming_recurring(limit=12):
            sign = "+" if r["type"] == "Dochód" else "−"
            color = p.positive if r["type"] == "Dochód" else \
                p.transfer if r["type"] in ("Przelew", "Na Skarbonkę") else p.negative
            items.append((r["days"], r["name"], Text(f"{sign}{money(float(r['amount']), '')}", style=color)))
        for acc in get_accounts_overview():
            proj = acc.get("projection")
            if proj and proj["days_left"] <= 31:
                items.append((proj["days_left"], f"◆ {acc['name']}",
                              Text(f"+{money(proj['net_interest'], '')}", style=p.positive)))
        items.sort(key=lambda x: x[0])
        if not items:
            cont.mount(Label("Brak zaplanowanych płatności.", classes="dim-text"))
            self.query_one("#card-upcoming").border_subtitle = ""
            return
        rows = []
        overdue = 0
        for days, name, amount in items[:12]:
            when = Label(describe_days(days), classes="row-when")
            if days < 0:
                when.add_class("-neg")
                overdue += 1
            elif days <= 1:
                when.add_class("-warn")
            rows.append(Horizontal(Label(f"• {name}", classes="row-name-flex"), Label(amount, classes="row-amount"),
                                   when, classes="card-row"))
        cont.mount_all(rows)
        self.query_one("#card-upcoming").border_subtitle = f"zaległe: {overdue}" if overdue else ""

    def _advisor(self, month: str) -> None:
        p = palette()
        cont = self.query_one("#list-advisor", VerticalScroll)
        cont.remove_children()
        rows = []
        for tip in get_insights(month)[:8]:
            icon, color_name = INSIGHT_ICONS.get(tip.level, ("•", "muted"))
            text = Text()
            text.append(f"{icon} ", style=f"bold {getattr(p, color_name)}")
            text.append(tip.text, style=p.text)
            rows.append(Label(text, classes="advice"))
        cont.mount_all(rows)

    def _goals(self, month: str) -> None:
        cont = self.query_one("#list-goals", Vertical)
        cont.remove_children()
        goals = goals_overview()
        if not goals:
            cont.mount(Label("Brak celów — dodaj je w zakładce 5.", classes="dim-text"))
            return
        goals.sort(key=lambda g: -g["pct"])
        name_w = calculate_max_width([(None, g["name"]) for g in goals], 1, 8, 16)
        rows = []
        for g in goals:
            name = Label(f"• {g['name']}", classes="row-name")
            name.styles.width = name_w
            rows.append(Horizontal(name, Meter(g["pct"], "goal"), classes="card-row"))
        cont.mount_all(rows)

    def _assets(self, month: str) -> None:
        cont = self.query_one("#list-assets", Vertical)
        cont.remove_children()
        nw = get_net_worth()
        total = nw["total"] or 1.0
        rows = []
        for group in [*KIND_GROUPS, "goals"]:
            value = nw.get(group, 0.0)
            if not value:
                continue
            name = Label(f"• {'Cele' if group == 'goals' else group}", classes="row-name")
            name.styles.width = 15
            rows.append(Horizontal(name, Meter(value / total * 100, "share"),
                                   Label(money(value, ""), classes="row-amount"), classes="card-row"))
        if not rows:
            rows.append(Label("Brak kont.", classes="dim-text"))
        cont.mount_all(rows)
