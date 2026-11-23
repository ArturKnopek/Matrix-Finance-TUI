from __future__ import annotations

import calendar
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select

from src.database import (
    get_account_options,
    get_active_month_str,
    get_transaction_year_range,
    get_transactions_by_month,
)
from src.utils.ui_tools import GREEN, RED, ProgressMeter, money
from src.views.transaction_form_view import form_row

MONTHS_PL = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień",
             "Październik", "Listopad", "Grudzień"]
TOP_N = 5


def reports_dir() -> Path:
    """Wspólny katalog raportów: ~/Documents/Matrix_Raporty (albo ~/Matrix_Raporty)."""
    docs = Path.home() / "Documents"
    base = docs if docs.exists() else Path.home()
    out = base / "Matrix_Raporty"
    out.mkdir(parents=True, exist_ok=True)
    return out


class ReportsView(VerticalScroll):
    """
    Centrum raportów: bilans, efektywność, TOP kategorie/sklepy z paskami,
    porównanie z poprzednim miesiącem, eksport TXT/CSV i archiwizacja miesiąca.
    Układ: 2 kolumny na szerokim ekranie, 1 kolumna na wąskim.
    """

    BINDINGS = [
        ("r", "refresh", "Odśwież"),
        ("g", "generate_txt", "TXT"),
        ("c", "generate_csv", "CSV"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_class("form-view")
        self._stats: Dict[str, Any] = {}
        self._prev_stats: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        now = datetime.now()
        yield Label("CENTRUM RAPORTOWANIA", classes="form-header")
        with Grid(id="rep-grid"):
            with Vertical(id="rep-left", classes="rep-col"):
                yield Label("ZAKRES", classes="separator-line")
                yield form_row("Rok:", Select([(str(now.year), str(now.year))], value=str(now.year), id="rep-year",
                                              classes="row-select", allow_blank=False))
                yield form_row("Miesiąc:", Select([(MONTHS_PL[now.month - 1], f"{now.month:02d}")],
                                                  value=f"{now.month:02d}", id="rep-month", classes="row-select",
                                                  allow_blank=False))
                yield form_row("Konto:", Select([("Wszystkie", "ALL")], value="ALL", id="rep-account",
                                                classes="row-select", allow_blank=False))
                yield Label("EKSPORT / ARCHIWUM", classes="separator-line")
                yield form_row("Odśwież:", Button("R  ODŚWIEŻ", id="btn-rep-refresh", classes="btn-inline"))
                yield form_row("Raport:", Button("G  GENERUJ .TXT", id="btn-gen-report", classes="btn-inline"))
                yield form_row("Dane:", Button("C  GENERUJ .CSV", id="btn-gen-csv", classes="btn-inline"))
                yield form_row("Archiwum:", Button("ZARCHIWIZUJ MIESIĄC", id="btn-archive",
                                                   classes="btn-inline btn-inline-danger"))
                yield Label("", id="rep-export-path", classes="form-hint")

            with Vertical(id="rep-right", classes="rep-col"):
                yield Label("BILANS", classes="separator-line")
                yield form_row("Przychody:", Label("0.00 PLN", id="rep-income", classes="row-value"))
                yield form_row("Wydatki:", Label("0.00 PLN", id="rep-expense", classes="row-value"))
                yield form_row("Bilans:", Label("0.00 PLN", id="rep-balance", classes="row-value"))
                yield form_row("Δ vs poprz. m-c:", Label("0.00 PLN", id="rep-delta", classes="row-value"))
                yield Label("EFEKTYWNOŚĆ", classes="separator-line")
                with Horizontal(classes="form-row"):
                    yield Label("Zużycie:", classes="row-label")
                    yield ProgressMeter(0.0, id="rep-ratio-bar")
                yield form_row("Średnio / dzień:", Label("0.00 PLN", id="rep-daily", classes="row-value"))
                yield form_row("Dni z wydatkami:", Label("0", id="rep-active-days", classes="row-value"))
                yield form_row("Śr. / dzień akt.:", Label("0.00 PLN", id="rep-daily-active", classes="row-value"))
                yield form_row("Liczba transakcji:", Label("0", id="rep-count", classes="row-value"))
                yield form_row("Max wydatek:", Label("-", id="rep-max-exp", classes="row-value"))
                yield form_row("Max dochód:", Label("-", id="rep-max-inc", classes="row-value"))

        with Grid(id="rep-top-grid"):
            with Vertical(id="rep-top-cats-box", classes="rep-col"):
                yield Label("TOP KATEGORIE (WYDATKI)", classes="separator-line")
                yield Vertical(id="rep-top-cats", classes="rep-top-list")
            with Vertical(id="rep-top-shops-box", classes="rep-col"):
                yield Label("TOP SKLEPY (WYDATKI)", classes="separator-line")
                yield Vertical(id="rep-top-shops", classes="rep-top-list")

    def on_mount(self) -> None:
        self._init_period_selectors()
        self.update_report()

    def load_data(self) -> None:
        """Wywoływane przy wejściu do zakładki / odświeżeniu."""
        self._init_period_selectors(keep_selection=True)
        self.update_report()

    def generate_report(self) -> None:
        self.update_report()

    # -------------------------------------------------------------- actions

    def action_refresh(self) -> None:
        self.update_report()
        self.notify("Dane raportu odświeżone.", severity="information")

    def action_generate_txt(self) -> None:
        try:
            path = self.generate_txt_report()
            self._show_export(path)
            self.notify(f"Zapisano raport TXT:\n{path}", severity="information")
        except Exception as e:
            self.notify(f"Błąd zapisu TXT: {e}", severity="error")

    def action_generate_csv(self) -> None:
        try:
            path = self.generate_csv_report()
            self._show_export(path)
            self.notify(f"Zapisano CSV:\n{path}", severity="information")
        except Exception as e:
            self.notify(f"Błąd zapisu CSV: {e}", severity="error")

    def _show_export(self, path: str) -> None:
        self.query_one("#rep-export-path", Label).update(f"Ostatni eksport: {path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-rep-refresh": self.action_refresh,
            "btn-gen-report": self.action_generate_txt,
            "btn-gen-csv": self.action_generate_csv,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            event.stop()
            handler()
        # btn-archive obsługuje MainDashboard (potrzebny modal potwierdzenia)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("rep-year", "rep-month", "rep-account"):
            self.update_report()

    # ------------------------------------------------------------- helpers

    def _init_period_selectors(self, keep_selection: bool = False) -> None:
        year_sel = self.query_one("#rep-year", Select)
        month_sel = self.query_one("#rep-month", Select)
        acc_sel = self.query_one("#rep-account", Select)

        prev_year, prev_month, prev_acc = year_sel.value, month_sel.value, acc_sel.value
        y_str, m_str = get_active_month_str().split("-")
        lo, hi = get_transaction_year_range()
        lo = min(lo, int(y_str))
        hi = max(hi, int(y_str))
        years = [str(y) for y in range(hi, lo - 1, -1)]

        with self.prevent(Select.Changed):
            year_sel.set_options([(y, y) for y in years])
            month_sel.set_options([(f"{name} ({i:02d})", f"{i:02d}") for i, name in enumerate(MONTHS_PL, 1)])
            accounts = get_account_options(active_only=False)
            acc_sel.set_options([("Wszystkie", "ALL")] + list(accounts))
            if keep_selection and prev_year in years:
                year_sel.value = prev_year
                month_sel.value = prev_month
            else:
                year_sel.value = y_str
                month_sel.value = m_str
            acc_values = {v for _, v in accounts}
            acc_sel.value = prev_acc if keep_selection and prev_acc in acc_values else "ALL"

    def get_selected_ym(self) -> str:
        return f"{self.query_one('#rep-year', Select).value}-{self.query_one('#rep-month', Select).value}"

    _get_selected_ym = get_selected_ym

    def _get_selected_account(self) -> str:
        return str(self.query_one("#rep-account", Select).value)

    @staticmethod
    def _prev_month(ym: str) -> str:
        y, m = map(int, ym.split("-"))
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    @staticmethod
    def _filter_transactions(transactions: List[Any], account_filter: str) -> List[Dict[str, Any]]:
        out = []
        for t in transactions:
            d = dict(t)
            if account_filter != "ALL" and (d.get("account_type") or "") != account_filter:
                continue
            out.append(d)
        return out

    def _load_tx(self, ym: str, acc_filter: str) -> List[Dict[str, Any]]:
        try:
            raw = get_transactions_by_month(ym, include_archive=True) or []
        except Exception:
            raw = []
        return self._filter_transactions(raw, acc_filter)

    @staticmethod
    def _calc_stats(tx: List[Dict[str, Any]]) -> Dict[str, Any]:
        income = expense = 0.0
        active_days = set()
        by_cat: Dict[str, float] = defaultdict(float)
        by_shop: Dict[str, float] = defaultdict(float)
        max_exp: Optional[Tuple[float, str, str]] = None
        max_inc: Optional[Tuple[float, str, str]] = None

        for t in tx:
            amt = float(t.get("amount") or 0.0)
            date = str(t.get("date") or "")[:10]
            label = t.get("shop") or t.get("description") or "—"
            if t.get("type") == "Dochód":
                income += amt
                if max_inc is None or amt > max_inc[0]:
                    max_inc = (amt, label, date)
            elif t.get("type") == "Wydatek":
                expense += amt
                active_days.add(date)
                by_cat[t.get("category") or "---"] += amt
                by_shop[t.get("shop") or "—"] += amt
                if max_exp is None or amt > max_exp[0]:
                    max_exp = (amt, label, date)

        return {
            "income": income,
            "expense": expense,
            "balance": income - expense,
            "ratio": (expense / income) * 100 if income > 0 else (100.0 if expense > 0 else 0.0),
            "count": len(tx),
            "active_days": len(active_days),
            "by_cat": dict(by_cat),
            "by_shop": dict(by_shop),
            "max_exp": max_exp,
            "max_inc": max_inc,
        }

    # --------------------------------------------------------- main report

    def update_report(self) -> None:
        ym = self.get_selected_ym()
        acc = self._get_selected_account()
        stats = self._calc_stats(self._load_tx(ym, acc))
        prev = self._calc_stats(self._load_tx(self._prev_month(ym), acc))

        now = datetime.now()
        year, month = map(int, ym.split("-"))
        days = max(1, now.day) if ym == now.strftime("%Y-%m") else calendar.monthrange(year, month)[1]
        stats["daily_avg"] = stats["expense"] / days
        stats["daily_active"] = stats["expense"] / max(1, stats["active_days"])
        stats["delta"] = stats["balance"] - prev["balance"]
        stats["ym"] = ym
        stats["account"] = acc
        self._stats, self._prev_stats = stats, prev

        self._set_money("#rep-income", stats["income"], GREEN)
        self._set_money("#rep-expense", stats["expense"], RED if stats["expense"] > 0 else GREEN)
        self._set_money("#rep-balance", stats["balance"], signed=True)
        self._set_money("#rep-delta", stats["delta"], signed=True)
        self.query_one("#rep-ratio-bar", ProgressMeter).pct = min(stats["ratio"], 999.9)
        self.query_one("#rep-daily", Label).update(money(stats["daily_avg"]))
        self.query_one("#rep-active-days", Label).update(str(stats["active_days"]))
        self.query_one("#rep-daily-active", Label).update(money(stats["daily_active"]))
        self.query_one("#rep-count", Label).update(str(stats["count"]))
        self.query_one("#rep-max-exp", Label).update(self._extreme(stats["max_exp"]))
        self.query_one("#rep-max-inc", Label).update(self._extreme(stats["max_inc"]))

        self._fill_top("#rep-top-cats", stats["by_cat"])
        self._fill_top("#rep-top-shops", stats["by_shop"])

    @staticmethod
    def _extreme(item: Optional[Tuple[float, str, str]]) -> str:
        if not item:
            return "-"
        amount, label, date = item
        return f"{money(amount)} · {label} ({date[8:10]}.{date[5:7]})"

    def _fill_top(self, selector: str, data: Dict[str, float]) -> None:
        cont = self.query_one(selector, Vertical)
        cont.remove_children()
        top = sorted(data.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        if not top:
            cont.mount(Label("brak wydatków", classes="dim-text"))
            return
        total = sum(data.values()) or 1.0
        rows = []
        for i, (name, value) in enumerate(top, 1):
            share = value / total * 100
            rows.append(Horizontal(
                Label(f"{i}. {name}", classes="top-name"),
                Label(money(value, ""), classes="top-value"),
                ProgressMeter(share, color="#00AA2B", classes="top-bar"),
                classes="top-row",
            ))
        cont.mount_all(rows)

    def _set_money(self, widget_id: str, value: float, color: Optional[str] = None, signed: bool = False) -> None:
        color = color or (RED if value < 0 else GREEN)
        self.query_one(widget_id, Label).update(Text(money(value, signed=signed), style=color))

    # -------------------------------------------------------------- export

    def _get_filtered_transactions_for_export(self) -> List[Dict[str, Any]]:
        return self._load_tx(self.get_selected_ym(), self._get_selected_account())

    def generate_txt_report(self) -> str:
        if not self._stats:
            self.update_report()
        s = self._stats
        ym, acc = s["ym"], s["account"]
        line = "-" * 60

        def top_lines(data: Dict[str, float]) -> str:
            top = sorted(data.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
            if not top:
                return "  (brak)\n"
            return "".join(f"  {i}. {k:<30} {money(v):>16}\n" for i, (k, v) in enumerate(top, 1))

        content = (
            f"RAPORT FINANSOWY: {ym} | Konto: {'Wszystkie' if acc == 'ALL' else acc}\n{line}\n"
            f"Przychody:            {money(s['income']):>18}\n"
            f"Wydatki:              {money(s['expense']):>18}\n"
            f"Bilans:               {money(s['balance'], signed=True):>18}\n"
            f"Δ vs poprzedni m-c:   {money(s['delta'], signed=True):>18}\n{line}\n"
            f"Zużycie przychodów:   {s['ratio']:>17.1f}%\n"
            f"Średnio / dzień:      {money(s['daily_avg']):>18}\n"
            f"Dni z wydatkami:      {s['active_days']:>18}\n"
            f"Śr. / dzień aktywny:  {money(s['daily_active']):>18}\n"
            f"Liczba transakcji:    {s['count']:>18}\n{line}\n"
            f"Max wydatek: {self._extreme(s['max_exp'])}\n"
            f"Max dochód:  {self._extreme(s['max_inc'])}\n{line}\n"
            f"TOP kategorie:\n{top_lines(s['by_cat'])}"
            f"TOP sklepy:\n{top_lines(s['by_shop'])}{line}\n"
            f"Wygenerowano: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        )
        out_path = reports_dir() / f"raport_{ym}_{acc}.txt"
        out_path.write_text(content, encoding="utf-8")
        return str(out_path)

    def generate_csv_report(self) -> str:
        ym = self.get_selected_ym()
        acc = self._get_selected_account()
        tx = self._get_filtered_transactions_for_export()
        out_path = reports_dir() / f"transakcje_{ym}_{acc}.csv"
        # utf-8-sig + średnik: poprawnie otwiera się w polskim Excelu
        with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["id", "data", "typ", "kategoria", "konto", "sklep", "kwota", "opis", "rejestrowana"])
            for r in sorted(tx, key=lambda t: (str(t.get("date")), t.get("id") or 0)):
                writer.writerow([
                    r.get("id", ""),
                    r.get("date", ""),
                    r.get("type", ""),
                    r.get("category") or "",
                    r.get("account_type") or "",
                    r.get("shop") or "",
                    f"{float(r.get('amount') or 0.0):.2f}".replace(".", ","),
                    r.get("description") or "",
                    r.get("is_registered", ""),
                ])
        return str(out_path)
