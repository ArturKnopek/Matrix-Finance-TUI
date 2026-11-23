from __future__ import annotations

import calendar
import logging
from datetime import date, datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import Label

from src.database import (
    get_accounts_overview,
    get_active_month_str,
    get_all_categories_data,
    get_all_piggy_banks,
    get_category_spending_map,
    get_daily_spending_map,
    get_monthly_summary,
    get_piggy_total,
    get_upcoming_recurring,
)
from src.utils.ui_tools import GREEN, RED, YELLOW, ProgressMeter, WidthClassesMixin, calculate_max_width, money
from src.views.recurring_view import describe_days

WEEKDAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]
CAL_CELLS = 42  # 6 tygodni x 7 dni


def _kv_row(key: str, value_id: str, value: str = "...", classes: str = "") -> Horizontal:
    return Horizontal(
        Label(key, classes="kv-key"),
        Label(value, id=value_id, classes="kv-val"),
        classes=f"kv-row {classes}".strip(),
    )


class DashboardView(WidthClassesMixin, VerticalScroll):
    """
    Pulpit. Układ kart dopasowuje się do szerokości terminala (klasy breakpointów
    na ekranie: 1, 2 lub 3 kolumny), a wszystkie paski i heatmapa skalują się same.
    """

    def compose(self) -> ComposeResult:
        with Grid(id="dash-grid"):
            with Vertical(id="card-resources", classes="dash-card"):
                yield Vertical(id="list-accounts", classes="kv-list")
                yield _kv_row("W CELACH:", "val-piggy-total", classes="kv-dim")
                yield _kv_row("MAJĄTEK:", "val-net-worth", classes="kv-total")

            with Vertical(id="card-status", classes="dash-card"):
                yield _kv_row("PRZYCHÓD:", "val-inc")
                yield _kv_row("WYDATKI:", "val-exp")
                with Horizontal(id="row-consumption", classes="kv-row"):
                    yield Label("ZUŻYCIE:", classes="kv-key")
                    yield ProgressMeter(0.0, id="bar-consumption")
                yield _kv_row("PRZEPŁYW:", "val-flow")

            with Vertical(id="card-alerts", classes="dash-card"):
                yield Vertical(id="list-alerts", classes="simple-list")

            with Vertical(id="card-categories", classes="dash-card"):
                yield Vertical(id="dash-cats-list", classes="simple-list")

            with Vertical(id="card-goals", classes="dash-card"):
                yield Vertical(id="list-piggy", classes="simple-list")

            with Vertical(id="card-heatmap", classes="dash-card"):
                with Grid(id="calendar-grid"):
                    for day in WEEKDAYS:
                        yield Label(day, classes="cal-header")
                    for i in range(CAL_CELLS):
                        yield Label("", id=f"day-{i}", classes="cal-day empty")

    def on_mount(self) -> None:
        titles = {
            "#card-resources": "ZASOBY",
            "#card-status": "STATUS CYKLU",
            "#card-alerts": "NADCHODZĄCE OPERACJE",
            "#card-categories": "STATUS KATEGORII",
            "#card-goals": "CELE OSZCZĘDNOŚCIOWE",
            "#card-heatmap": "INTENSYWNOŚĆ WYDATKÓW",
        }
        for selector, title in titles.items():
            self.query_one(selector).border_title = title
        self.load_data()

    def load_data(self) -> None:
        with self.app.batch_update():
            for refresh in (
                self.refresh_balance,
                self.refresh_monthly_stats,
                self.refresh_alerts,
                self.refresh_categories,
                self.refresh_piggy_banks,
                self.refresh_heatmap,
            ):
                try:
                    refresh()
                except Exception as e:  # jeden zepsuty kafelek nie blokuje reszty
                    logging.exception(f"Błąd odświeżania pulpitu ({refresh.__name__}): {e}")

    # ------------------------------------------------------------------ ZASOBY

    def refresh_balance(self) -> None:
        accounts = get_accounts_overview(active_only=True)
        cont = self.query_one("#list-accounts", Vertical)
        cont.remove_children()
        total = 0.0
        rows = []
        for acc in accounts:
            if acc["include_in_net_worth"]:
                total += acc["balance"]
            value = Label(money(acc["balance"], acc["currency"]), classes="kv-val")
            if acc["balance"] < 0:
                value.add_class("negative")
            rows.append(Horizontal(Label(f"{acc['name'].upper()}:", classes="kv-key"), value, classes="kv-row"))
        if not rows:
            rows.append(Label("Brak kont.", classes="dim-text"))
        cont.mount_all(rows)

        piggy_total = get_piggy_total()
        self.query_one("#val-piggy-total", Label).update(money(piggy_total))
        self.query_one("#val-net-worth", Label).update(money(total + piggy_total))
        self.query_one("#card-resources").border_subtitle = f"konta: {money(total)}"

    # ----------------------------------------------------------- STATUS CYKLU

    def refresh_monthly_stats(self) -> None:
        ym = get_active_month_str()
        self.query_one("#card-status").border_title = f"STATUS CYKLU {ym}"

        inc, exp = get_monthly_summary(ym)
        self.query_one("#val-inc", Label).update(Text(money(inc), style=GREEN))
        self.query_one("#val-exp", Label).update(Text(money(exp), style=RED if exp > 0 else GREEN))
        flow = inc - exp
        self.query_one("#val-flow", Label).update(Text(money(flow, signed=True), style=GREEN if flow >= 0 else RED))

        if inc > 0:
            pct = (exp / inc) * 100
        else:
            pct = 100.0 if exp > 0 else 0.0
        self.query_one("#bar-consumption", ProgressMeter).pct = max(0.0, min(pct, 999.9))

    # ------------------------------------------------------------- NADCHODZĄCE

    def refresh_alerts(self) -> None:
        cont = self.query_one("#list-alerts", Vertical)
        cont.remove_children()
        upcoming = get_upcoming_recurring(limit=20)
        if not upcoming:
            cont.mount(Label("Brak aktywnych płatności cyklicznych.", classes="dim-text"))
            return

        rows = []
        for item in upcoming:
            days = int(item["days"])
            r_type = item.get("type")
            sign = "+" if r_type == "Dochód" else "-"
            color = GREEN if r_type == "Dochód" else YELLOW if r_type == "Na Skarbonkę" else RED
            when = Label(describe_days(days), classes="alert-days")
            if days < 0:
                when.add_class("overdue")
            elif days <= 1:
                when.add_class("soon")
            rows.append(Horizontal(
                Label(f"• {item.get('name') or ''}", classes="alert-name"),
                Label(Text(f"{sign}{money(float(item.get('amount') or 0.0), '')}", style=color), classes="alert-amount"),
                when,
                classes="alert-row",
            ))
        cont.mount_all(rows)
        overdue = sum(1 for i in upcoming if i["days"] < 0)
        self.query_one("#card-alerts").border_subtitle = f"zaległe: {overdue}" if overdue else ""

    # -------------------------------------------------------------- KATEGORIE

    def refresh_categories(self) -> None:
        container = self.query_one("#dash-cats-list", Vertical)
        container.remove_children()

        month = get_active_month_str()
        spending = get_category_spending_map(month)
        items = []
        for row in get_all_categories_data() or []:
            name = row["name"]
            limit = float(row["limit_amount"] or 0.0)
            spent = float(spending.get(name, 0.0))
            if limit <= 0 and spent <= 0:
                continue  # nic do pokazania
            pct = (spent / limit) * 100 if limit > 0 else None
            items.append((name, pct, spent))

        if not items:
            container.mount(Label("Brak wydatków i limitów w tym miesiącu.", classes="dim-text"))
            return

        # najpierw najbardziej „zagrożone” limity, potem kategorie bez limitu wg kwoty
        items.sort(key=lambda x: (x[1] is None, -(x[1] or 0), -x[2]))
        name_w = calculate_max_width([(None, n) for n, _, _ in items], key_idx=1, min_w=8, max_w=18)
        rows = []
        for name, pct, spent in items:
            label = Label(f"• {name}", classes="uni-name")
            label.styles.width = name_w
            meter = ProgressMeter(pct, is_savings=False, empty_label=f"{money(spent)} (bez limitu)")
            rows.append(Horizontal(label, meter, classes="uni-row"))
        container.mount_all(rows)

    # ------------------------------------------------------------------- CELE

    def refresh_piggy_banks(self) -> None:
        cont = self.query_one("#list-piggy", Vertical)
        cont.remove_children()
        pigs = get_all_piggy_banks()
        if not pigs:
            cont.mount(Label("Brak celów — dodaj je w zakładce 4.", classes="dim-text"))
            return

        items = []
        for p in pigs:
            target = float(p["target_amount"] or 0.0)
            current = float(p["current_amount"] or 0.0)
            items.append((p["name"], (current / target) * 100 if target > 0 else 0.0))
        items.sort(key=lambda x: -x[1])

        name_w = calculate_max_width([(None, n) for n, _ in items], key_idx=1, min_w=8, max_w=18)
        rows = []
        for name, pct in items:
            label = Label(f"• {name}", classes="uni-name")
            label.styles.width = name_w
            rows.append(Horizontal(label, ProgressMeter(pct, is_savings=True), classes="uni-row"))
        cont.mount_all(rows)

    # ---------------------------------------------------------------- HEATMAPA

    NARROW_AT = 76

    def on_resize(self, event) -> None:
        # (klasy -narrow/-tiny nadaje WidthClassesMixin – Textual wywołuje handlery z całego MRO)
        self.call_after_refresh(self._fit_heatmap)

    def _fit_heatmap(self) -> None:
        """Gdy karta jest za niska na nagłówek dni + wszystkie tygodnie, chowamy nagłówek."""
        weeks = getattr(self, "_heatmap_weeks", 6)
        try:
            card = self.query_one("#card-heatmap")
            grid = self.query_one("#calendar-grid", Grid)
        except Exception:
            return
        available = card.content_size.height
        show_header = available <= 0 or available >= weeks + 1
        grid.set_class(not show_header, "-no-header")
        rows = (["1"] if show_header else []) + ["1fr"] * weeks
        grid.styles.grid_rows = " ".join(rows)

    def refresh_heatmap(self) -> None:
        ym = get_active_month_str()
        year, month = map(int, ym.split("-"))
        spending = get_daily_spending_map(ym)
        weeks = calendar.monthcalendar(year, month)
        today = date.today()
        max_amt = max(spending.values(), default=0.0)

        self._heatmap_weeks = len(weeks)
        self._fit_heatmap()

        idx = 0
        for week in weeks:
            for day in week:
                lbl = self.query_one(f"#day-{idx}", Label)
                lbl.display = True
                if day == 0:
                    lbl.update("")
                    lbl.set_classes("cal-day empty")
                    lbl.tooltip = None
                else:
                    amt = float(spending.get(day, 0.0))
                    if amt <= 0 or max_amt <= 0:
                        level = "neutral"
                    else:
                        ratio = amt / max_amt
                        level = "low" if ratio < 0.34 else "med" if ratio < 0.67 else "high"
                    classes = f"cal-day {level}"
                    if (year, month, day) == (today.year, today.month, today.day):
                        classes += " today"
                    lbl.set_classes(classes)
                    lbl.update(str(day))
                    lbl.tooltip = f"{day:02d}.{month:02d}.{year}: {money(amt)}"
                idx += 1

        for i in range(idx, CAL_CELLS):
            lbl = self.query_one(f"#day-{i}", Label)
            lbl.update("")
            lbl.display = False

        legend = Text()
        for level, color in (("mało", "#004d14"), ("średnio", "#008f24"), ("dużo", "#00FF41")):
            legend.append("■", style=color)
            legend.append(f" {level} ")
        if max_amt > 0:
            legend.append(f"· max {money(max_amt)}")
        self.query_one("#card-heatmap").border_subtitle = legend.markup
        self.query_one("#card-heatmap").border_title = f"INTENSYWNOŚĆ WYDATKÓW {datetime(year, month, 1):%m.%Y}"
