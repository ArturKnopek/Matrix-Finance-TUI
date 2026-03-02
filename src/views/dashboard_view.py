from datetime import datetime
import calendar
import logging
from textual.app import ComposeResult
from textual.containers import Grid, Vertical, Container, Horizontal, VerticalScroll
from textual.widgets import Label, Button
from textual.events import Resize

# --- IMPORTY DANYCH Z BAZY ---
from src.database import (
    get_account_balance, get_monthly_summary, get_all_piggy_banks,
    get_all_recurring, fetch_transactions, get_active_month_str,
    get_daily_spending_map, get_all_categories_data, get_category_spent
)

# --- IMPORT NARZĘDZI UI (PASKI UNIWERSALNE) ---
from src.utils.ui_tools import get_universal_bar, calculate_max_width, get_pct_bar_str, get_progress_bar_str


class DashboardView(Container):
    """
    Główny widok pulpitu (Dashboard).
    """

    def compose(self) -> ComposeResult:
        with Grid(id="dash-grid"):

            # Karta 1: Zasoby (Gotówka + Karta)
            with Container(classes="dash-card", id="card-resources"):
                yield Label("ZASOBY SYSTEMU", classes="card-header")
                yield Label("", classes="header-spacer")

                with Container(classes="res-row"):
                    yield Label("KARTA:", classes="res-lbl")
                    yield Label("...", id="val-balance-card", classes="res-val")

                with Container(classes="res-row"):
                    yield Label("GOTÓWKA:", classes="res-lbl")
                    yield Label("...", id="val-balance-cash", classes="res-val")

                yield Label("SUMA: ...", id="lbl-balance-total", classes="res-total")

            # Karta 2: Status Cyklu (Przychody vs Wydatki)
            with Container(classes="dash-card", id="card-status"):
                yield Label("STATUS CYKLU", id="lbl-month-title", classes="card-header")
                yield Label("", classes="header-spacer")

                with Container(classes="stat-row"):
                    yield Label("PRZYCHÓD:", classes="stat-lbl")
                    yield Label("...", id="val-inc", classes="stat-val safe")

                with Container(classes="stat-row"):
                    yield Label("WYDATKI:", classes="stat-lbl")
                    yield Label("...", id="val-exp", classes="stat-val danger")

                with Horizontal(id="row-consumption"):
                    yield Label("ZUŻYCIE:", classes="stat-lbl")
                    yield Label("", id="bar-consumption")
                    yield Label("0.0%", id="val-consumption", classes="stat-val neutral")

                with Container(classes="stat-row"):
                    yield Label("PRZEPŁYW:", classes="stat-lbl")
                    yield Label("...", id="val-flow", classes="stat-val neutral")

            # Karta 3: Nadchodzące operacje (Cykliczne)
            with Container(classes="dash-card", id="card-alerts"):
                yield Label("NADCHODZĄCE OPERACJE", classes="card-header")
                yield Label("", classes="header-spacer")
                yield Vertical(id="list-alerts", classes="simple-list")

            # Karta 4: Status Kategorii (Paski wydatków)
            with Container(classes="dash-card", id="card-categories"):
                yield Label("STATUS KATEGORII", classes="card-header")
                yield Label("", classes="header-spacer")
                yield Vertical(id="dash-cats-list", classes="simple-list")

            # Karta 5: Cele Oszczędnościowe (Skarbonki)
            with Container(classes="dash-card", id="card-goals"):
                yield Label("CELE OSZCZĘDNOŚCIOWE", classes="card-header")
                yield Label("", classes="header-spacer")
                yield Vertical(id="list-piggy", classes="simple-list")

            # Karta 6: Heatmapa (Kalendarz wydatków)
            with Container(classes="dash-card", id="card-heatmap"):
                yield Label("INTENSYWNOŚĆ WYDATKÓW", classes="card-header")
                yield Label("", classes="header-spacer")
                with Grid(id="calendar-grid"):
                    for day in ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]:
                        yield Label(day, classes="cal-header")
                    for i in range(42):
                        yield Label("", id=f"day-{i}", classes="cal-day empty")

    def on_mount(self):
        self.load_data()

    def load_data(self):
        self.refresh_balance()
        self.refresh_monthly_stats()
        self.refresh_alerts()
        self.refresh_piggy_banks()
        self.refresh_heatmap()
        self.refresh_categories()

    def _render_consumption_bar(self, pct: float) -> None:
        try:
            bar = self.query_one("#bar-consumption")
            w = bar.size.width or bar.content_size.width or 20
            w = max(12, int(w))

            try:
                bar_markup = get_pct_bar_str(pct, width=w, is_savings=False, show_suffix=False)
            except NameError:
                bar_markup = get_progress_bar_str(pct, 100.0, width=w, is_savings=False, show_suffix=False)

            bar.update(bar_markup)
        except Exception as e:
            logging.error(f"Błąd _render_consumption_bar: {e}")

    # =========================================================================
    # LOGIKA ODŚWIEŻANIA POSZCZEGÓLNYCH ELEMENTÓW
    # =========================================================================

    def refresh_monthly_stats(self):
        try:
            ym = get_active_month_str()
            self.query_one("#lbl-month-title").update(f"STATUS CYKLU: {ym}")

            inc, exp = get_monthly_summary(ym)

            self.query_one("#val-inc").update(f"{inc:.2f} PLN")
            self.query_one("#val-exp").update(f"{exp:.2f} PLN")
            self.query_one("#val-flow").update(f"{inc - exp:+.2f} PLN")

            if inc > 0:
                pct = (exp / inc) * 100
            else:
                pct = 100.0 if exp > 0 else 0.0

            pct = max(0.0, min(pct, 999.9))

            val = self.query_one("#val-consumption")
            val.remove_class("safe", "warning", "danger", "neutral")

            if pct < 75:
                val.add_class("safe")
            elif pct < 90:
                val.add_class("warning")
            else:
                val.add_class("danger")

            val.update(f"{pct:>5.1f}%")
            self.call_after_refresh(self._render_consumption_bar, pct)

        except Exception as e:
            logging.error(f"Błąd refresh_monthly_stats: {e}")

    def refresh_balance(self):
        try:
            c = get_account_balance("Karta")
            g = get_account_balance("Gotówka")
            self.query_one("#val-balance-card").update(f"{c:.2f} PLN")
            self.query_one("#val-balance-cash").update(f"{g:.2f} PLN")
            self.query_one("#lbl-balance-total").update(f"RAZEM:   {c + g:.2f} PLN")
        except Exception as e:
            logging.error(f"Błąd refresh_balance: {e}")

    def refresh_alerts(self):
        cont = self.query_one("#list-alerts")
        cont.remove_children()
        try:
            recur = get_all_recurring()
            active = [dict(r) for r in recur if str(dict(r).get('is_registered', 1)) == '1']

            if not active:
                cont.mount(Label("Brak danych.", classes="dim-text"))
                return

            now = datetime.now()
            items = []

            for r in active:
                pay_day = int(r['start_date'].split('-')[2])
                last_day_of_month = calendar.monthrange(now.year, now.month)[1]

                if pay_day >= now.day:
                    diff = pay_day - now.day
                else:
                    diff = (last_day_of_month - now.day) + pay_day

                items.append((diff, r))

            items.sort(key=lambda x: x[0])

            for diff, r in items[:8]:
                d_str = "DZISIAJ" if diff == 0 else "JUTRO" if diff == 1 else f"za {diff} dni"
                row = Container(
                    Label(f"• {r['name']}", classes="alert-name"),
                    Label(d_str, classes="alert-days"),
                    classes="alert-row"
                )
                cont.mount(row)
        except Exception as e:
            logging.error(f"Błąd refresh_alerts: {e}")

    def refresh_piggy_banks(self):
        cont = self.query_one("#list-piggy")
        cont.remove_children()
        try:
            pigs = get_all_piggy_banks()
            if not pigs:
                cont.mount(Label("Brak celów.", classes="dim-text"))
                return

            display_list = []
            for p in pigs:
                pct = int((p["current_amount"] / p["target_amount"]) * 100) if p["target_amount"] > 0 else 0
                display_list.append((pct, p["name"]))

            final_width = calculate_max_width(display_list, key_idx=1)
            bar_w = self._calc_bar_width("#list-piggy", final_width, right_gap=1)

            for pct, name in display_list:
                row = get_universal_bar(
                    name, pct,
                    label_width=final_width,
                    is_savings=True,
                    show_bullet=True,
                    bar_width=bar_w
                )
                cont.mount(row)

        except Exception as e:
            logging.error(f"Błąd refresh_piggy_banks: {e}")
            cont.mount(Label(f"Błąd: {e}", classes="error-text"))

    def refresh_categories(self) -> None:
        try:
            container = self.query_one("#dash-cats-list")
            container.remove_children()

            active_month = get_active_month_str()
            raw_data = get_all_categories_data()
            clean_data = []

            for row in raw_data:
                d = dict(row)
                name = d["name"]
                spent_val = get_category_spent(name, active_month)

                try:
                    s = float(spent_val or 0.0)
                except ValueError:
                    s = 0.0

                try:
                    l = float(d.get("limit_amount") or 0.0)
                except ValueError:
                    l = 0.0

                d["spent"] = s
                d["limit_amount"] = l
                clean_data.append(d)

            clean_data.sort(key=lambda x: x["spent"], reverse=True)
            top_cats = clean_data[:7]

            if not top_cats:
                container.mount(Label("Brak kategorii.", classes="info-text"))
                return

            temp_list = [[None, c["name"]] for c in top_cats]
            name_w = calculate_max_width(temp_list, key_idx=1, min_w=10, max_w=20)

            try:
                bar_w = self._calc_bar_width("#dash-cats-list", name_w)
                if bar_w < 5: bar_w = 20
            except Exception:
                bar_w = 20

            for cat in top_cats:
                spent = cat["spent"]
                limit = cat["limit_amount"]
                name = cat["name"]

                if limit > 0:
                    pct = (spent / limit) * 100
                else:
                    pct = 100.0 if spent > 0 else 0.0

                bar = get_universal_bar(
                    label=name,
                    pct=pct,
                    label_width=name_w,
                    is_savings=False,
                    bar_width=bar_w
                )
                container.mount(bar)

        except Exception as e:
            logging.error(f"Błąd refresh_categories: {e}")
            try:
                c = self.query_one("#dash-cats-list")
                c.remove_children()
                c.mount(Label(f"Błąd: {e}", classes="info-text"))
            except Exception:
                pass

    def refresh_heatmap(self):
        ym = get_active_month_str()
        spending = get_daily_spending_map(ym)
        try:
            year, month = map(int, ym.split('-'))
            cal = calendar.monthcalendar(year, month)
            grid_idx = 0
            now = datetime.now()

            for week in cal:
                for day in week:
                    if grid_idx >= 42: break
                    lbl = self.query_one(f"#day-{grid_idx}")

                    if day == 0:
                        lbl.update("")
                        lbl.classes = "cal-day empty"
                    else:
                        lbl.update(str(day))
                        amt = spending.get(day, 0)

                        if amt == 0:
                            cls = "cal-day neutral"
                        elif amt < 100:
                            cls = "cal-day low"
                        elif amt < 300:
                            cls = "cal-day med"
                        else:
                            cls = "cal-day high"

                        if now.day == day and now.month == month:
                            cls += " today-purple"

                        lbl.classes = cls
                    grid_idx += 1

            for i in range(grid_idx, 42):
                self.query_one(f"#day-{i}").update("")
                self.query_one(f"#day-{i}").classes = "cal-day empty"
        except Exception as e:
            logging.error(f"Błąd refresh_heatmap: {e}")

    def on_resize(self, event: Resize) -> None:
        try:
            self.refresh_monthly_stats()
            self.refresh_piggy_banks()
            self.refresh_categories()
        except Exception as e:
            logging.error(f"Błąd on_resize w Dashboard: {e}")

    def _calc_bar_width(self, list_container_id: str, label_width: int, right_gap: int = 1) -> int:
        cont = self.query_one(list_container_id)
        total_w = cont.content_size.width or cont.size.width or 60
        bar_w = total_w - label_width - 1 - right_gap
        return max(12, int(bar_w))