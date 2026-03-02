from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import calendar
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.widgets import Button, Label, Select

from src.database import get_transactions_by_month, get_active_month_str


class ReportsView(Container):
    """
    Widok Raportów (kompaktowy, 2-kolumnowy).
    Funkcje:
    - wybór roku/miesiąca (kompatybilne z MainDashboard: #rep-year, #rep-month)
    - filtr konta: Wszystkie / Karta / Gotówka
    - bilans, ratio, średnia dzienna, dni aktywne
    - porównanie z poprzednim miesiącem (Δ)
    - TOP: kategorie i sklepy
    - największy wydatek/dochod
    - eksport: TXT i CSV
    - skróty klawiszowe: R refresh, G TXT, C CSV
    """

    BINDINGS = [
        ("r", "refresh", "Odśwież"),
        ("g", "generate_txt", "TXT"),
        ("c", "generate_csv", "CSV"),
    ]

    # -------------------------
    # UI
    # -------------------------

    def compose(self) -> ComposeResult:
        now = datetime.now()
        current_year = str(now.year)
        current_month = f"{now.month:02d}"

        with VerticalScroll(id="form-scroll-container"):
            yield Label("CENTRUM RAPORTOWANIA", classes="form-header")

            with Grid(id="rep-grid"):
                # =========================
                # LEWA KOLUMNA: zakres + akcje + eksport
                # =========================
                with Container(id="rep-left"):
                    yield Label("--- ZAKRES ---", classes="separator-line")

                    with Horizontal(classes="form-row"):
                        yield Label("Rok:", classes="row-label")
                        yield Select(
                            [(current_year, current_year)],
                            id="rep-year",
                            classes="row-select",
                            allow_blank=False,
                        )

                    with Horizontal(classes="form-row"):
                        yield Label("Miesiąc:", classes="row-label")
                        yield Select(
                            [(current_month, current_month)],
                            id="rep-month",
                            classes="row-select",
                            allow_blank=False,
                        )

                    with Horizontal(classes="form-row"):
                        yield Label("Konto:", classes="row-label")
                        yield Select(
                            [("Wszystkie", "ALL"), ("Karta", "Karta"), ("Gotówka", "Gotówka")],
                            value="ALL",
                            id="rep-account",
                            classes="row-select",
                            allow_blank=False,
                        )

                    with Horizontal(classes="form-row"):
                        yield Label("Okres:", classes="row-label")
                        yield Label("...", id="rep-period-display", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Akcja:", classes="row-label")
                        yield Button("[R] ODŚWIEŻ", id="btn-rep-refresh", classes="btn-inline")

                    yield Label("--- EKSPORT / ARCHIWUM ---", classes="separator-line")

                    with Horizontal(classes="form-row"):
                        yield Label("TXT:", classes="row-label")
                        yield Button("[G] GENERUJ .TXT", id="btn-gen-report", classes="btn-inline")

                    with Horizontal(classes="form-row"):
                        yield Label("CSV:", classes="row-label")
                        yield Button("[C] GENERUJ .CSV", id="btn-gen-csv", classes="btn-inline")

                    with Horizontal(classes="form-row"):
                        yield Label("Archiwum:", classes="row-label")
                        yield Button("ZARCHIWIZUJ", id="btn-archive", classes="btn-inline btn-inline-danger")

                # =========================
                # PRAWA KOLUMNA: metryki + topy
                # =========================
                with Container(id="rep-right"):
                    yield Label("--- BILANS ---", classes="separator-line")

                    with Horizontal(classes="form-row"):
                        yield Label("Przychody:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-income", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Wydatki:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-expense", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Bilans:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-balance", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Δ vs poprzedni:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-delta", classes="row-input")

                    yield Label("--- EFEKTYWNOŚĆ ---", classes="separator-line")

                    with Horizontal(classes="form-row"):
                        yield Label("Zużycie:", classes="row-label")
                        yield Label("0.0%", id="rep-ratio", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Śr./dzień:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-daily", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Dni aktywne:", classes="row-label")
                        yield Label("0", id="rep-active-days", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Śr./aktywny:", classes="row-label")
                        yield Label("0.00 PLN", id="rep-daily-active", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Liczba trans.:", classes="row-label")
                        yield Label("0", id="rep-count", classes="row-input")

                    yield Label("--- TOP / EKSTREMA ---", classes="separator-line")

                    with Horizontal(classes="form-row"):
                        yield Label("Top kategorie:", classes="row-label")
                        yield Label("-", id="rep-top-cats", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Top sklepy:", classes="row-label")
                        yield Label("-", id="rep-top-shops", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Max wydatek:", classes="row-label")
                        yield Label("-", id="rep-max-exp", classes="row-input")

                    with Horizontal(classes="form-row"):
                        yield Label("Max dochód:", classes="row-label")
                        yield Label("-", id="rep-max-inc", classes="row-input")

            yield Label("", classes="menu-spacer")

    def on_mount(self) -> None:
        self._init_period_selectors()
        self.update_report()

    def generate_report(self) -> None:
        self.update_report()

    # -------------------------
    # Actions / shortcuts
    # -------------------------

    def action_refresh(self) -> None:
        self.update_report()
        self.notify("Dane raportu odświeżone.", severity="information")

    def action_generate_txt(self) -> None:
        path = self.generate_txt_report()
        self.notify(f"Wygenerowano TXT: {path}", severity="information")

    def action_generate_csv(self) -> None:
        path = self.generate_csv_report()
        self.notify(f"Wygenerowano CSV: {path}", severity="information")

    # -------------------------
    # UI events
    # -------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid == "btn-rep-refresh":
            self.action_refresh()
            event.stop()

        elif bid == "btn-gen-report":
            self.action_generate_txt()
            event.stop()

        elif bid == "btn-gen-csv":
            self.action_generate_csv()
            event.stop()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("rep-year", "rep-month", "rep-account"):
            self.update_report()

    # -------------------------
    # Data helpers
    # -------------------------

    def _init_period_selectors(self) -> None:
        current_ym = get_active_month_str()
        y_str, m_str = current_ym.split("-")
        y = int(y_str)

        years = [str(yy) for yy in range(y - 5, y + 1)]
        months = [f"{mm:02d}" for mm in range(1, 13)]

        year_sel = self.query_one("#rep-year", Select)
        month_sel = self.query_one("#rep-month", Select)

        year_sel.set_options([(yy, yy) for yy in years])
        month_sel.set_options([(mm, mm) for mm in months])

        year_sel.value = y_str
        month_sel.value = m_str

        try:
            self.query_one("#rep-account", Select).value = "ALL"
        except Exception:
            pass

    def _get_selected_ym(self) -> str:
        y = self.query_one("#rep-year", Select).value
        m = self.query_one("#rep-month", Select).value
        return f"{y}-{m}"

    def _get_selected_account(self) -> str:
        return self.query_one("#rep-account", Select).value

    @staticmethod
    def _prev_month(ym: str) -> str:
        y, m = map(int, ym.split("-"))
        if m == 1:
            return f"{y-1}-12"
        return f"{y}-{m-1:02d}"

    @staticmethod
    def _filter_transactions(transactions: List[Any], account_filter: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for t in transactions:
            d = dict(t)
            if account_filter != "ALL":
                if (d.get("account_type") or "") != account_filter:
                    continue
            out.append(d)
        return out

    @staticmethod
    def _calc_stats(tx: List[Dict[str, Any]]) -> Dict[str, Any]:
        income = 0.0
        expense = 0.0
        count = 0

        active_days_set = set()
        by_cat = defaultdict(float)
        by_shop = defaultdict(float)

        max_exp: Optional[Tuple[float, str, str, str]] = None
        max_inc: Optional[Tuple[float, str, str, str]] = None

        for t in tx:
            count += 1
            t_type = t.get("type", "")
            amt = float(t.get("amount") or 0.0)
            date = t.get("date") or ""
            shop = t.get("shop") or ""
            cat = t.get("category") or "---"
            desc = t.get("description") or ""

            if t_type == "Dochód":
                income += amt
                label = shop or desc or "—"
                if (max_inc is None) or (amt > max_inc[0]):
                    max_inc = (amt, label, date, cat)

            elif t_type == "Wydatek":
                expense += amt

                try:
                    active_days_set.add(str(date)[:10])
                except Exception:
                    pass

                by_cat[cat] += amt
                by_shop[shop or "—"] += amt

                label = shop or desc or "—"
                if (max_exp is None) or (amt > max_exp[0]):
                    max_exp = (amt, label, date, cat)

        balance = income - expense
        ratio = (expense / income) * 100 if income > 0 else 0.0

        return {
            "income": income,
            "expense": expense,
            "balance": balance,
            "ratio": ratio,
            "count": count,
            "active_days": len(active_days_set),
            "by_cat": by_cat,
            "by_shop": by_shop,
            "max_exp": max_exp,
            "max_inc": max_inc,
        }

    # -------------------------
    # Main report
    # -------------------------

    def update_report(self) -> None:
        ym = self._get_selected_ym()
        acc_filter = self._get_selected_account()
        self.query_one("#rep-period-display", Label).update(f"{ym} | {acc_filter}")

        try:
            tx_raw = get_transactions_by_month(ym) or []
        except Exception:
            tx_raw = []
        tx = self._filter_transactions(tx_raw, acc_filter)
        stats = self._calc_stats(tx)

        prev_ym = self._prev_month(ym)
        try:
            prev_raw = get_transactions_by_month(prev_ym) or []
        except Exception:
            prev_raw = []
        prev_tx = self._filter_transactions(prev_raw, acc_filter)
        prev_stats = self._calc_stats(prev_tx)

        delta_balance = stats["balance"] - prev_stats["balance"]

        now = datetime.now()
        if ym == now.strftime("%Y-%m"):
            denom = max(1, now.day)
        else:
            year, month = map(int, ym.split("-"))
            denom = calendar.monthrange(year, month)[1]

        daily_avg = stats["expense"] / denom if denom > 0 else 0.0
        daily_active = stats["expense"] / max(1, stats["active_days"])

        top_cats = sorted(stats["by_cat"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_shops = sorted(stats["by_shop"].items(), key=lambda x: x[1], reverse=True)[:5]

        top_cats_str = " | ".join([f"{k} {v:.0f}" for k, v in top_cats]) if top_cats else "-"
        top_shops_str = " | ".join([f"{k} {v:.0f}" for k, v in top_shops]) if top_shops else "-"

        if stats["max_exp"]:
            a, label, date, cat = stats["max_exp"]
            max_exp_str = f"{a:.2f} PLN ({label})"
        else:
            max_exp_str = "-"

        if stats["max_inc"]:
            a, label, date, cat = stats["max_inc"]
            max_inc_str = f"{a:.2f} PLN ({label})"
        else:
            max_inc_str = "-"

        self._set_money("#rep-income", stats["income"], positive_green=True)
        self._set_money("#rep-expense", stats["expense"], expense_red=True)
        self._set_money("#rep-balance", stats["balance"])
        self._set_money("#rep-delta", delta_balance)

        self.query_one("#rep-ratio", Label).update(f"{stats['ratio']:.1f}%")
        self.query_one("#rep-daily", Label).update(f"{daily_avg:.2f} PLN")
        self.query_one("#rep-active-days", Label).update(str(stats["active_days"]))
        self.query_one("#rep-daily-active", Label).update(f"{daily_active:.2f} PLN")
        self.query_one("#rep-count", Label).update(str(stats["count"]))

        self.query_one("#rep-top-cats", Label).update(top_cats_str)
        self.query_one("#rep-top-shops", Label).update(top_shops_str)
        self.query_one("#rep-max-exp", Label).update(max_exp_str)
        self.query_one("#rep-max-inc", Label).update(max_inc_str)

    def _set_money(self, widget_id: str, value: float, positive_green: bool = False, expense_red: bool = False) -> None:
        lbl = self.query_one(widget_id, Label)
        lbl.update(f"{value:.2f} PLN")

        if positive_green:
            lbl.styles.color = "#00FF41"
            return

        if expense_red:
            lbl.styles.color = "#FF0000" if value > 0 else "#00FF41"
            return

        lbl.styles.color = "#FF0000" if value < 0 else "#00FF41"

    # -------------------------
    # Export
    # -------------------------

    def _get_filtered_transactions_for_export(self) -> List[Dict[str, Any]]:
        ym = self._get_selected_ym()
        acc_filter = self._get_selected_account()
        try:
            tx_raw = get_transactions_by_month(ym) or []
        except Exception:
            tx_raw = []
        return self._filter_transactions(tx_raw, acc_filter)

    def generate_txt_report(self) -> str:
        ym = self._get_selected_ym()
        acc_filter = self._get_selected_account()

        def plain(lbl_id: str) -> str:
            try:
                return str(self.query_one(lbl_id, Label).renderable.plain)
            except Exception:
                try:
                    return str(self.query_one(lbl_id, Label).renderable)
                except Exception:
                    return ""

        inc = plain("#rep-income")
        exp = plain("#rep-expense")
        bal = plain("#rep-balance")
        delta = plain("#rep-delta")
        ratio = plain("#rep-ratio")
        daily = plain("#rep-daily")
        active = plain("#rep-active-days")
        daily_a = plain("#rep-daily-active")
        cnt = plain("#rep-count")
        top_c = plain("#rep-top-cats")
        top_s = plain("#rep-top-shops")
        mx_e = plain("#rep-max-exp")
        mx_i = plain("#rep-max-inc")

        # FIX: Generowanie w Dokumentach
        docs_dir = Path.home() / "Documents"
        if not docs_dir.exists():
            docs_dir = Path.home()

        out_dir = docs_dir / "Matrix_Raporty"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"report_{ym}_{acc_filter}.txt"

        content = (
            f"RAPORT: {ym} | Konto: {acc_filter}\n"
            f"{'-'*60}\n"
            f"Przychody: {inc}\n"
            f"Wydatki:   {exp}\n"
            f"Bilans:    {bal}\n"
            f"Δ vs poprzedni: {delta}\n"
            f"{'-'*60}\n"
            f"Zużycie: {ratio}\n"
            f"Średnio/dzień: {daily}\n"
            f"Dni aktywne: {active}\n"
            f"Śr./aktywny: {daily_a}\n"
            f"Liczba transakcji: {cnt}\n"
            f"{'-'*60}\n"
            f"Top kategorie: {top_c}\n"
            f"Top sklepy:   {top_s}\n"
            f"Max wydatek:  {mx_e}\n"
            f"Max dochód:   {mx_i}\n"
            f"{'-'*60}\n"
            f"Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        out_path.write_text(content, encoding="utf-8")
        return str(out_path)

    def generate_csv_report(self) -> str:
        ym = self._get_selected_ym()
        acc_filter = self._get_selected_account()
        tx = self._get_filtered_transactions_for_export()

        # FIX: Generowanie na Pulpicie
        desktop_dir = Path.home() / "Desktop"
        if not desktop_dir.exists():
            desktop_dir = Path.home()

        out_dir = desktop_dir / "Matrix_Raporty"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"transactions_{ym}_{acc_filter}.csv"

        def esc(x: Any) -> str:
            s = str(x if x is not None else "")
            s = s.replace('"', '""')
            return f'"{s}"'

        lines = ["id,date,type,category,account_type,shop,amount,description,is_registered"]
        for r in tx:
            lines.append(",".join([
                esc(r.get("id", "")),
                esc(r.get("date", "")),
                esc(r.get("type", "")),
                esc(r.get("category", "")),
                esc(r.get("account_type", "")),
                esc(r.get("shop", "")),
                esc(r.get("amount", "")),
                esc(r.get("description", "")),
                esc(r.get("is_registered", "")),
            ]))

        out_path.write_text("\n".join(lines), encoding="utf-8")
        return str(out_path)