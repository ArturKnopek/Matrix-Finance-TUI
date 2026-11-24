"""
Eksport, import i drukowanie.

Formaty:
    .json  – pełny eksport danych (czytelny, do przeniesienia lub analizy),
    .mfx   – ten sam eksport zaszyfrowany hasłem (AES / Fernet),
    .csv   – transakcje (średnik, UTF-8 z BOM — poprawnie otwiera się w polskim Excelu),
    .matrix – zaszyfrowana kopia całej bazy SQLite (import jako nowy użytkownik na ekranie logowania),
    .html  – miesięczny raport do druku / zapisu jako PDF z przeglądarki.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.finance.storage import (
    get_active_user_db,
    get_connection,
    init_user_db,
    list_user_tables,
    open_user_db,
)
from src.utils.crypto_utils import decrypt_bytes, encrypt_bytes, write_atomic

EXPORT_FORMAT = "matrix-finance-export"
EXPORT_VERSION = 2
CSV_COLUMNS = ["data", "typ", "kategoria", "konto", "sklep", "kwota", "opis", "podtyp"]
log = logging.getLogger(__name__)


def default_export_dir() -> Path:
    from src.utils.paths import documents_dir

    out = documents_dir() / "Matrix_Finance"
    out.mkdir(parents=True, exist_ok=True)
    return out


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")


# =============================================================================
# Kopia bazy (.matrix)
# =============================================================================

def export_user_db_snapshot(dest_path: str) -> None:
    """Spójna kopia bazy (SQLite backup API — bezpieczne w trybie WAL)."""
    src = get_connection()
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def snapshot_bytes() -> bytes:
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        export_user_db_snapshot(tmp)
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def export_encrypted_backup(out_file: str, password: str) -> bool:
    try:
        write_atomic(out_file, encrypt_bytes(snapshot_bytes(), password))
        return True
    except Exception as e:
        log.error("Błąd eksportu kopii: %s", e)
        return False


# =============================================================================
# JSON / MFX
# =============================================================================

LOCAL_SETTING_PREFIXES = ("sync_", "local_")  # ustawienia tego urządzenia (hasło synchronizacji, motyw telefonu…) — nie wędrują z danymi


def _is_local_setting(row: Dict[str, Any]) -> bool:
    return str(row.get("key") or "").startswith(LOCAL_SETTING_PREFIXES)


def export_data_dict() -> Dict[str, Any]:
    tables: Dict[str, List[Dict[str, Any]]] = {}
    with open_user_db() as conn:
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in list_user_tables():
            if table in existing:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
                if table == "settings":
                    rows = [r for r in rows if not _is_local_setting(r)]
                tables[table] = rows
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "exported_at": datetime.now().isoformat(),
            "tables": tables}


def export_json(path: str, password: Optional[str] = None) -> str:
    """Eksport wszystkich danych do JSON; z hasłem — zaszyfrowany (.mfx)."""
    payload = json.dumps(export_data_dict(), ensure_ascii=False, indent=2).encode("utf-8")
    write_atomic(path, encrypt_bytes(payload, password) if password else payload)
    return path


def read_export_file(path: str, password: Optional[str] = None) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    data = None
    if raw.lstrip().startswith(b"{"):
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None  # zaszyfrowany plik, którego sól przypadkiem zaczyna się od „{”
    if data is None:
        if not password:
            raise ValueError("Plik jest zaszyfrowany — podaj hasło.")
        data = json.loads(decrypt_bytes(raw, password).decode("utf-8"))
    if data.get("format") != EXPORT_FORMAT or not isinstance(data.get("tables"), dict):
        raise ValueError("To nie jest plik eksportu Matrix Finance.")
    return data


def import_json(path: str, password: Optional[str] = None) -> Dict[str, int]:
    """
    Zastępuje WSZYSTKIE dane bieżącego użytkownika danymi z eksportu.
    Kolumny nieznane w bieżącym schemacie są pomijane. Zwraca liczbę wierszy per tabela.
    """
    return import_data_dict(read_export_file(path, password))


def import_data_dict(data: Dict[str, Any]) -> Dict[str, int]:
    """Zastępuje dane bieżącego użytkownika zawartością eksportu (słownik). Ustawienia lokalne (sync_*) zostają."""
    counts: Dict[str, int] = {}
    with open_user_db(write=True) as conn:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        local_settings = [dict(r) for r in conn.execute("SELECT key, value FROM settings").fetchall()
                          if _is_local_setting(dict(r))]
        for table in reversed(list_user_tables()):
            conn.execute(f"DELETE FROM {table}")
        for table in list_user_tables():
            rows = data["tables"].get(table) or []
            if table == "settings":
                rows = [r for r in rows if not _is_local_setting(r)] + local_settings
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for row in rows:
                cols = [c for c in row if c in columns]
                if not cols:
                    continue
                conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [row[c] for c in cols])
            counts[table] = len(rows)
    init_user_db(get_active_user_db())  # dociągnięcie schematu / kodów
    return counts


# =============================================================================
# CSV
# =============================================================================

def export_transactions_csv(path: str, month: Optional[str] = None) -> int:
    query = "SELECT * FROM transactions"
    params: Tuple[Any, ...] = ()
    if month:
        query += " WHERE date LIKE ?"
        params = (f"{month}%",)
    with open_user_db() as conn:
        rows = conn.execute(query + " ORDER BY date, id", params).fetchall()
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for r in rows:
            writer.writerow([r["date"], r["type"], r["category"] or "", r["account_type"] or "", r["shop"] or "",
                             f"{float(r['amount'] or 0):.2f}".replace(".", ","), r["description"] or "",
                             r["entry_subtype"] or "regular"])
    return len(rows)


def import_transactions_csv(path: str, update_balances: bool = False,
                            default_account: str = "Karta") -> Tuple[int, List[str]]:
    """
    Import transakcji z CSV (format eksportu). Przelewy są pomijane.
    update_balances=False — wpisy trafiają do historii bez zmiany sald (import archiwum).
    Zwraca (liczba zaimportowanych, lista błędów).
    """
    from src.finance.ledger import EXPENSE, INCOME, add_transaction, insert_entry, normalize_category
    from src.utils.parsing import parse_amount

    imported, errors = 0, []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(fh, delimiter=delimiter)
        rows = list(reader)
    for i, row in enumerate(rows, start=2):
        try:
            t_type = (row.get("typ") or row.get("type") or "").strip()
            if t_type not in (EXPENSE, INCOME):
                continue
            day = (row.get("data") or row.get("date") or "").strip()[:10]
            datetime.strptime(day, "%Y-%m-%d")
            amount = parse_amount(str(row.get("kwota") or row.get("amount") or ""))
            if amount is None or amount <= 0:
                raise ValueError("niepoprawna kwota")
            account = (row.get("konto") or row.get("account_type") or default_account).strip() or default_account
            category = (row.get("kategoria") or row.get("category") or "").strip()
            shop = (row.get("sklep") or row.get("shop") or "").strip()
            desc = (row.get("opis") or row.get("description") or "").strip()
            if update_balances:
                add_transaction(day, t_type, category, account, shop, amount, desc, True, apply_autosave=False)
            else:
                with open_user_db(write=True) as conn:
                    insert_entry(conn, day, t_type, normalize_category(conn, category), account, shop, amount, desc, 0)
            imported += 1
        except Exception as e:
            errors.append(f"wiersz {i}: {e}")
    return imported, errors


# =============================================================================
# Raport miesięczny (HTML do druku)
# =============================================================================

def _fmt(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ") + " zł"


def build_monthly_report_html(ym: str, auto_print: bool = False) -> str:
    from src.finance.accounts import get_accounts_overview
    from src.finance.analytics import get_monthly_summary, savings_rate
    from src.finance.envelopes import get_envelope_overview
    from src.finance.goals import goals_overview
    from src.finance.ledger import describe_entry, get_transactions_by_month

    income, expense = get_monthly_summary(ym)
    rate = savings_rate(income, expense)
    envelopes = [e for e in get_envelope_overview(ym) if e["available"] > 0 or e["spent"] > 0]
    accounts = get_accounts_overview()
    goals = goals_overview()
    entries = [describe_entry(r) for r in get_transactions_by_month(ym, include_archive=True)]

    def esc(v: Any) -> str:
        return html.escape(str(v if v is not None else ""))

    def bar(pct: Optional[float]) -> str:
        if pct is None:
            return '<span class="muted">bez limitu</span>'
        cls = "ok" if pct < 75 else "warn" if pct < 100 else "bad"
        return (f'<div class="bar"><div class="fill {cls}" style="width:{min(pct, 100):.0f}%"></div></div>'
                f'<span class="pct">{pct:.0f}%</span>')

    env_rows = "".join(
        f"<tr><td>{esc(e['name'])}{' ↻' if e['rollover'] else ''}</td><td class=r>{_fmt(e['available'])}</td>"
        f"<td class=r>{_fmt(e['spent'])}</td><td class=r>{_fmt(e['remaining'])}</td><td>{bar(e['pct'])}</td></tr>"
        for e in envelopes) or '<tr><td colspan=5 class="muted">brak kopert z budżetem</td></tr>'
    acc_rows = "".join(
        f"<tr><td>{esc(a['name'])}</td><td>{esc(a['kind_label'])}</td><td>{esc(a.get('institution') or '')}</td>"
        f"<td class=r>{_fmt(a['balance'])}</td></tr>" for a in accounts)
    goal_rows = "".join(
        f"<tr><td>{esc(g['name'])}</td><td class=r>{_fmt(float(g['current_amount'] or 0))}</td>"
        f"<td class=r>{_fmt(float(g['target_amount'] or 0))}</td><td>{bar(g['pct'])}</td></tr>"
        for g in goals) or '<tr><td colspan=4 class="muted">brak celów</td></tr>'
    tx_rows = "".join(
        f"<tr><td>{esc(e['date'])}</td><td>{esc(e['kind_label'])}</td><td>{esc(e.get('category') or '')}</td>"
        f"<td>{esc(e.get('account_type'))}</td><td>{esc(e.get('shop'))}</td>"
        f"<td class='r {'neg' if e['signed_amount'] < 0 else 'pos'}'>{e['signed_amount']:+,.2f}</td></tr>"
        .replace(",", " ") for e in sorted(entries, key=lambda x: (x["date"], x["id"])))
    script = "<script>window.addEventListener('load',()=>window.print())</script>" if auto_print else ""
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>Raport {esc(ym)} — Matrix Finance</title>
<style>
 body{{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;margin:24px;max-width:960px}}
 h1{{margin:0 0 4px;font-size:22px}} h2{{margin:22px 0 6px;font-size:15px;border-bottom:1px solid #ccc}}
 .muted{{color:#777}} .kpis{{display:flex;gap:12px;margin-top:10px;flex-wrap:wrap}}
 .kpi{{border:1px solid #ddd;border-radius:6px;padding:8px 12px;min-width:150px}}
 .kpi b{{display:block;font-size:17px}} table{{border-collapse:collapse;width:100%}}
 td,th{{padding:4px 6px;border-bottom:1px solid #eee;text-align:left}} .r{{text-align:right;white-space:nowrap}}
 .pos{{color:#137333}} .neg{{color:#b3261e}} .bar{{display:inline-block;width:110px;height:8px;background:#eee;
 border-radius:4px;vertical-align:middle;margin-right:6px}} .fill{{height:8px;border-radius:4px}}
 .ok{{background:#2e9d4b}} .warn{{background:#e0a100}} .bad{{background:#d93025}} .pct{{font-size:11px}}
 @media print{{body{{margin:0}} h2{{break-after:avoid}} tr{{break-inside:avoid}}}}
</style>{script}</head><body>
<h1>Raport miesięczny {esc(ym)}</h1>
<div class="muted">Matrix Finance · wygenerowano {datetime.now():%Y-%m-%d %H:%M}</div>
<div class="kpis">
 <div class="kpi">Przychody<b class="pos">{_fmt(income)}</b></div>
 <div class="kpi">Wydatki<b class="neg">{_fmt(expense)}</b></div>
 <div class="kpi">Bilans<b>{_fmt(income - expense)}</b></div>
 <div class="kpi">Stopa oszczędności<b>{'—' if rate is None else f'{rate:.0f}%'}</b></div>
</div>
<h2>Koperty</h2><table><tr><th>Koperta</th><th class=r>Dostępne</th><th class=r>Wydano</th>
<th class=r>Pozostało</th><th>Wykorzystanie</th></tr>{env_rows}</table>
<h2>Konta</h2><table><tr><th>Konto</th><th>Rodzaj</th><th>Instytucja</th><th class=r>Saldo</th></tr>{acc_rows}</table>
<h2>Cele oszczędnościowe</h2><table><tr><th>Cel</th><th class=r>Uzbierano</th><th class=r>Cel</th>
<th>Postęp</th></tr>{goal_rows}</table>
<h2>Transakcje ({len(entries)})</h2><table><tr><th>Data</th><th>Rodzaj</th><th>Koperta</th><th>Konto</th>
<th>Opis</th><th class=r>Kwota</th></tr>{tx_rows}</table>
</body></html>"""


def save_monthly_report(ym: str, folder: Optional[Path] = None, auto_print: bool = False) -> Path:
    folder = folder or default_export_dir()
    path = folder / f"raport_{ym}.html"
    path.write_text(build_monthly_report_html(ym, auto_print=auto_print), encoding="utf-8")
    return path


def open_for_print(path: Path) -> bool:
    """Otwiera raport w przeglądarce (okno drukowania otwiera się samo). Zwraca False, gdy się nie da."""
    try:
        return bool(webbrowser.open(path.resolve().as_uri()))
    except Exception:
        return False


def send_text_to_printer(path: Path) -> Tuple[bool, str]:
    """Bezpośredni wydruk pliku tekstowego (lp/lpr albo Windows)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path), "print")  # type: ignore[attr-defined]
            return True, "Wysłano do drukarki."
        for cmd in ("lp", "lpr"):
            if shutil.which(cmd):
                subprocess.run([cmd, str(path)], check=True, capture_output=True, timeout=20)
                return True, f"Wysłano do drukarki ({cmd})."
        return False, "Nie znaleziono polecenia drukowania (lp/lpr)."
    except Exception as e:
        return False, f"Błąd drukowania: {e}"
