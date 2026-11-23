"""Raporty: bilans miesiąca, porównanie, trend 6 miesięcy, TOP koperty i sklepy, druk i eksport."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select

from src.finance import data_io
from src.finance.accounts import get_account_options
from src.finance.analytics import archive_month, get_trend, savings_rate
from src.finance.envelopes import month_add
from src.finance.ledger import get_transaction_year_range, get_transactions_by_month
from src.finance.storage import get_active_month_str
from src.ui.dialogs import form_row
from src.ui.theme import palette
from src.ui.widgets import Meter, money
from src.views.base import DataChanged, ViewAction, ViewMixin

MONTHS_PL = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień",
             "Październik", "Listopad", "Grudzień"]
TOP_N = 6


def reports_dir() -> Path:
    return data_io.default_export_dir()


class ReportsView(ViewMixin, VerticalScroll):
    TITLE = "RAPORTY"
    ACTIONS = [
        ViewAction("print", "P", "DRUKUJ RAPORT", "DRUK"),
        ViewAction("txt", "G", "RAPORT .TXT", "TXT"),
        ViewAction("csv", "C", "TRANSAKCJE .CSV", "CSV"),
        ViewAction("archive", "^D", "ARCHIWIZUJ", "ARCH."),
    ]
    BINDINGS = [("p", "run('print')", "Drukuj"), ("g", "run('txt')", "TXT"), ("c", "run('csv')", "CSV")]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_class("form-view")
        self._stats: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        now = datetime.now()
        with Horizontal(id="rep-filters"):
            yield Select([(str(now.year), str(now.year))], value=str(now.year), id="rep-year", allow_blank=False)
            yield Select([(f"{n} ({i:02d})", f"{i:02d}") for i, n in enumerate(MONTHS_PL, 1)],
                         value=f"{now.month:02d}", id="rep-month", allow_blank=False)
            yield Select([("Wszystkie konta", "ALL")], value="ALL", id="rep-account", allow_blank=False)
            yield Button("P DRUKUJ", id="btn-rep-print", classes="btn-inline")
            yield Button("G TXT", id="btn-rep-txt", classes="btn-inline")
            yield Button("C CSV", id="btn-rep-csv", classes="btn-inline")
        with Grid(id="rep-grid"):
            with Vertical(classes="rep-col"):
                yield Label("BILANS", classes="section-title")
                yield form_row("Przychody:", Label("", id="rep-income", classes="row-value"))
                yield form_row("Wydatki:", Label("", id="rep-expense", classes="row-value"))
                yield form_row("Bilans:", Label("", id="rep-balance", classes="row-value"))
                yield form_row("Δ vs poprz. m-c:", Label("", id="rep-delta", classes="row-value"))
                yield form_row("Stopa oszczędności:", Label("", id="rep-rate", classes="row-value"))
            with Vertical(classes="rep-col"):
                yield Label("EFEKTYWNOŚĆ", classes="section-title")
                with Horizontal(classes="form-row"):
                    yield Label("Zużycie przychodów:", classes="row-label")
                    yield Meter(0.0, "budget", id="rep-ratio-bar")
                yield form_row("Średnio / dzień:", Label("", id="rep-daily", classes="row-value"))
                yield form_row("Dni z wydatkami:", Label("", id="rep-active-days", classes="row-value"))
                yield form_row("Max wydatek:", Label("", id="rep-max-exp", classes="row-value"))
                yield form_row("Liczba wpisów:", Label("", id="rep-count", classes="row-value"))
        yield Label("TREND 6 MIESIĘCY", classes="section-title")
        yield Vertical(id="rep-trend", classes="rep-list")
        with Grid(id="rep-top-grid"):
            with Vertical(classes="rep-col"):
                yield Label("TOP KOPERTY", classes="section-title")
                yield Vertical(id="rep-top-cats", classes="rep-list")
            with Vertical(classes="rep-col"):
                yield Label("TOP SKLEPY / OPISY", classes="section-title")
                yield Vertical(id="rep-top-shops", classes="rep-list")
        yield Label("", id="rep-export-path", classes="view-hint")

    def on_mount(self) -> None:
        self._init_selectors()
        self.update_report()

    def load_data(self) -> None:
        self._init_selectors(keep=True)
        self.update_report()

    # ---------------------------------------------------------------- akcje

    def action_run(self, name: str) -> None:
        handler = getattr(self, f"do_{name}", None)
        if handler:
            handler()

    def do_print(self) -> None:
        path = data_io.save_monthly_report(self.get_selected_ym(), auto_print=True)
        opened = data_io.open_for_print(path)
        self._show_path(path)
        self.notify(("Otwarto raport w przeglądarce — okno drukowania pojawi się samo.\n" if opened else
                     "Nie udało się otworzyć przeglądarki — otwórz plik ręcznie:\n") + str(path))

    def do_txt(self) -> None:
        path = self.generate_txt_report()
        self._show_path(path)
        self.notify(f"Zapisano raport TXT:\n{path}")

    def do_csv(self) -> None:
        path = self.generate_csv_report()
        self._show_path(path)
        self.notify(f"Zapisano CSV:\n{path}")

    def do_archive(self) -> None:
        ym = self.get_selected_ym()
        self.confirm(f"Przenieść transakcje z {ym} do archiwum?\nZnikną z listy, ale zostaną w podsumowaniach.",
                     lambda: f"Zarchiwizowano {archive_month(ym)} transakcji z {ym}.", remember=False,
                     title="ARCHIWIZACJA")

    def _show_path(self, path: Any) -> None:
        self.query_one("#rep-export-path", Label).update(f"Ostatni plik: {path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {"btn-rep-print": self.do_print, "btn-rep-txt": self.do_txt, "btn-rep-csv": self.do_csv}
        if event.button.id in handlers:
            event.stop()
            handlers[event.button.id]()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("rep-year", "rep-month", "rep-account"):
            self.update_report()

    # ---------------------------------------------------------------- dane

    def _init_selectors(self, keep: bool = False) -> None:
        year_sel = self.query_one("#rep-year", Select)
        month_sel = self.query_one("#rep-month", Select)
        acc_sel = self.query_one("#rep-account", Select)
        prev = (year_sel.value, month_sel.value, acc_sel.value)
        y, m = get_active_month_str().split("-")
        lo, hi = get_transaction_year_range()
        years = [str(v) for v in range(max(hi, int(y)), min(lo, int(y)) - 1, -1)]
        accounts = get_account_options(active_only=False)
        with self.prevent(Select.Changed):
            year_sel.set_options([(v, v) for v in years])
            acc_sel.set_options([("Wszystkie konta", "ALL")] + list(accounts))
            if keep and prev[0] in years:
                year_sel.value, month_sel.value = prev[0], prev[1]
            else:
                year_sel.value, month_sel.value = y, m
            acc_sel.value = prev[2] if keep and prev[2] in {v for _, v in accounts} else "ALL"

    def get_selected_ym(self) -> str:
        return f"{self.query_one('#rep-year', Select).value}-{self.query_one('#rep-month', Select).value}"

    _get_selected_ym = get_selected_ym

    def _account(self) -> str:
        return str(self.query_one("#rep-account", Select).value)

    def _load_tx(self, ym: str) -> List[Dict[str, Any]]:
        acc = self._account()
        return [dict(t) for t in get_transactions_by_month(ym, include_archive=True)
                if acc == "ALL" or t["account_type"] == acc]

    @staticmethod
    def _calc_stats(tx: List[Dict[str, Any]]) -> Dict[str, Any]:
        income = expense = 0.0
        active_days = set()
        by_cat: Dict[str, float] = defaultdict(float)
        by_shop: Dict[str, float] = defaultdict(float)
        max_exp: Optional[Tuple[float, str, str]] = None
        for t in tx:
            amt = float(t.get("amount") or 0.0)
            if t.get("type") == "Dochód":
                income += amt
            elif t.get("type") == "Wydatek":
                expense += amt
                day = str(t.get("date") or "")[:10]
                active_days.add(day)
                by_cat[t.get("category") or "—"] += amt
                by_shop[t.get("shop") or "—"] += amt
                if max_exp is None or amt > max_exp[0]:
                    max_exp = (amt, t.get("shop") or t.get("description") or "—", day)
        return {"income": income, "expense": expense, "balance": income - expense,
                "ratio": (expense / income * 100) if income > 0 else (100.0 if expense else 0.0),
                "count": len(tx), "active_days": len(active_days), "by_cat": dict(by_cat),
                "by_shop": dict(by_shop), "max_exp": max_exp}

    def update_report(self) -> None:
        p = palette()
        ym = self.get_selected_ym()
        stats = self._calc_stats(self._load_tx(ym))
        prev = self._calc_stats(self._load_tx(month_add(ym, -1)))
        now = datetime.now()
        y, m = map(int, ym.split("-"))
        days = max(1, now.day) if ym == now.strftime("%Y-%m") else calendar.monthrange(y, m)[1]
        stats.update(ym=ym, account=self._account(), daily=stats["expense"] / days,
                     delta=stats["balance"] - prev["balance"], rate=savings_rate(stats["income"], stats["expense"]))
        self._stats = stats

        def put(widget_id: str, text: str, color: str) -> None:
            self.query_one(f"#{widget_id}", Label).update(Text(text, style=f"bold {color}"))

        put("rep-income", money(stats["income"]), p.positive)
        put("rep-expense", money(stats["expense"]), p.negative if stats["expense"] else p.text)
        put("rep-balance", money(stats["balance"], signed=True), p.positive if stats["balance"] >= 0 else p.negative)
        put("rep-delta", money(stats["delta"], signed=True), p.positive if stats["delta"] >= 0 else p.negative)
        put("rep-rate", "—" if stats["rate"] is None else f"{stats['rate']:.1f}%",
            p.positive if (stats["rate"] or 0) >= 20 else p.warning)
        self.query_one("#rep-ratio-bar", Meter).pct = min(stats["ratio"], 999.0)
        put("rep-daily", money(stats["daily"]), p.text)
        put("rep-active-days", str(stats["active_days"]), p.text)
        mx = stats["max_exp"]
        put("rep-max-exp", f"{money(mx[0])} · {mx[1]} ({mx[2][8:10]}.{mx[2][5:7]})" if mx else "—", p.text)
        put("rep-count", str(stats["count"]), p.text)
        self._fill_trend(ym)
        self._fill_top("#rep-top-cats", stats["by_cat"])
        self._fill_top("#rep-top-shops", stats["by_shop"])

    def _fill_trend(self, ym: str) -> None:
        p = palette()
        cont = self.query_one("#rep-trend", Vertical)
        cont.remove_children()
        trend = get_trend(6, ym)
        top = max([t["income"] for t in trend] + [t["expense"] for t in trend] + [1.0])
        rows = []
        for t in trend:
            rate = savings_rate(t["income"], t["expense"])
            name = Label(t["ym"], classes="row-label")
            rows.append(Horizontal(
                name,
                Meter(t["expense"] / top * 100, "share", show_pct=False, classes="trend-bar"),
                Label(Text(f"−{money(t['expense'], '')}" if t["expense"] else "—", style=p.negative),
                      classes="row-amount"),
                Label(Text(f"+{money(t['income'], '')}" if t["income"] else "—", style=p.positive),
                      classes="row-amount"),
                Label("" if rate is None else f"{rate:4.0f}%", classes="row-when"),
                classes="card-row"))
        cont.mount_all(rows)

    def _fill_top(self, selector: str, data: Dict[str, float]) -> None:
        cont = self.query_one(selector, Vertical)
        cont.remove_children()
        top = sorted(data.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        if not top:
            cont.mount(Label("brak wydatków", classes="dim-text"))
            return
        total = sum(data.values()) or 1.0
        cont.mount_all([Horizontal(Label(f"{i}. {name}", classes="row-name-flex"),
                                   Label(money(value, ""), classes="row-amount"),
                                   Meter(value / total * 100, "share", classes="top-bar"), classes="card-row")
                        for i, (name, value) in enumerate(top, 1)])

    # ---------------------------------------------------------------- eksport

    def generate_txt_report(self) -> str:
        if not self._stats:
            self.update_report()
        s = self._stats
        line = "-" * 60

        def top_lines(data: Dict[str, float]) -> str:
            top = sorted(data.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
            return "".join(f"  {i}. {k:<30} {money(v):>16}\n" for i, (k, v) in enumerate(top, 1)) or "  (brak)\n"

        rate_txt = "—" if s["rate"] is None else f"{s['rate']:.1f}%"
        content = (
            f"RAPORT FINANSOWY: {s['ym']} | Konto: {'Wszystkie' if s['account'] == 'ALL' else s['account']}\n{line}\n"
            f"Przychody:            {money(s['income']):>18}\n"
            f"Wydatki:              {money(s['expense']):>18}\n"
            f"Bilans:               {money(s['balance'], signed=True):>18}\n"
            f"Δ vs poprzedni m-c:   {money(s['delta'], signed=True):>18}\n"
            f"Stopa oszczędności:   {rate_txt:>18}\n"
            f"{line}\nTOP koperty:\n{top_lines(s['by_cat'])}TOP sklepy:\n{top_lines(s['by_shop'])}{line}\n"
            f"Wygenerowano: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        )
        out = reports_dir() / f"raport_{s['ym']}_{s['account']}.txt"
        out.write_text(content, encoding="utf-8")
        return str(out)

    def generate_csv_report(self) -> str:
        out = reports_dir() / f"transakcje_{self.get_selected_ym()}.csv"
        data_io.export_transactions_csv(str(out), self.get_selected_ym())
        return str(out)

    def notify_changed(self, message: str) -> None:
        self.post_message(DataChanged(message))
