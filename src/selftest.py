"""
Test instalacji: `python main.py --selftest`

Sprawdza na tymczasowych danych (Twoje dane nie są dotykane), czy działa:
biblioteki, baza SQLite, silnik budżetu, szyfrowanie, eksport/import
oraz interfejs (uruchamiany bez okna, we wszystkich zakładkach).
Zwraca 0, gdy wszystko jest w porządku. Używany też przez instalator Windows
(skrót „Sprawdź instalację”) i automatyczne testy instalatora.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, List, Tuple


def _check(results: List[Tuple[str, bool, str]], name: str, fn: Callable[[], str]) -> None:
    started = time.perf_counter()
    try:
        info = fn() or ""
        ok = True
    except Exception as e:  # pragma: no cover - raport błędu
        info = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        ok = False
    results.append((name, ok, info))
    mark = "OK " if ok else "BŁĄD"
    print(f"[{mark}] {name:<34} {info.splitlines()[0] if info else ''}  ({time.perf_counter() - started:.1f}s)",
          flush=True)
    if not ok:
        print(info, flush=True)


def _libraries() -> str:
    import cryptography
    import rich  # noqa: F401
    import textual
    from importlib.metadata import version

    return f"textual {textual.__version__}, rich {version('rich')}, cryptography {cryptography.__version__}"


def _engine() -> str:
    from src.core.auth import AuthService
    from src.finance import accounts, analytics, envelopes, goals, ledger, storage

    storage.init_auth_db()
    uid = AuthService.create_user("selftest", "selftest-haslo")
    assert AuthService.verify_login("selftest", "selftest-haslo") == uid
    storage.init_user_db(storage.set_active_user_db(uid), 1000.0, 200.0)
    ym = storage.get_active_month_str()
    ledger.add_transaction(f"{ym}-01", "Dochód", "Wynagrodzenie", "Karta", "Pensja", 5000, "", True)
    ledger.add_transaction(f"{ym}-02", "Wydatek", "Jedzenie", "Karta", "Sklep", 123.45, "", True)
    accounts.add_account("Oszczędnościowe", 0, account_kind="savings", interest_rate=5)
    accounts.transfer_between_accounts("Karta", "Oszczędnościowe", 500)
    assert abs(accounts.set_account_balance("Gotówka", 250) - 50) < 0.001
    goals.add_piggy_bank("Wakacje", 3000, "Karta")
    food = {c["name"]: c["id"] for c in envelopes.get_all_categories_data()}["Jedzenie"]
    envelopes.adjust_envelope(food, ym, 10)
    income, expense = analytics.get_monthly_balance(ym)
    assert (income, expense) == (5000.0, 123.45), (income, expense)
    nw = accounts.get_net_worth()["total"]
    assert abs(nw - (1000 + 200 + 5000 - 123.45 + 50)) < 0.01, nw
    return f"majątek {nw:.2f}, bilans +{income:.2f} / -{expense:.2f}"


def _export_import(tmp: Path) -> str:
    from src.finance import data_io, ledger

    before = len(ledger.fetch_transactions())
    path = tmp / "eksport.mfx"
    data_io.export_json(str(path), password="tajne")
    data_io.import_json(str(path), password="tajne")
    after = len(ledger.fetch_transactions())
    assert before == after, (before, after)
    report = data_io.save_monthly_report(ledger.fetch_transactions()[0]["date"][:7], folder=tmp)
    assert report.stat().st_size > 1000
    return f"{after} transakcji, raport HTML {report.stat().st_size // 1024} KB"


def _encryption() -> str:
    from src.core.vault import DataVault, encrypted_path
    from src.finance import ledger, storage

    uid = Path(storage.get_active_user_db()).stem
    count = len(ledger.fetch_transactions())
    vault = DataVault.enable(uid, "selftest-haslo")
    vault.close()
    assert encrypted_path(uid).exists() and not storage.user_db_path(uid).exists()
    vault = DataVault(uid, "selftest-haslo")
    vault.open()
    assert len(ledger.fetch_transactions()) == count
    vault.disable()
    storage.set_active_user_db(uid)
    return "baza zaszyfrowana i odczytana ponownie (AES)"


async def _ui_scenario() -> str:
    from src.app import MatrixApp
    from src.finance import storage

    storage.set_setting("ui_animations", "0")
    uid = Path(storage.get_active_user_db()).stem
    app = MatrixApp()
    visited = []
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(0.2)
        app.set_current_user(uid, "selftest")
        await app.switch_screen("main_dashboard")
        await pilot.pause(0.5)
        for _ in range(3):  # okna startowe (np. przypomnienia)
            if app.screen.__class__.__name__ == "MainDashboard":
                break
            await pilot.press("escape")
            await pilot.pause(0.2)
        for key in "123456789":
            await pilot.press(key)
            await pilot.pause(0.25)
            visited.append(app.screen.query_one("#content-frame").current)
        await pilot.press("1")
        await pilot.press("ctrl+n")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "TransactionDialog", app.screen
        await pilot.press("escape")
        await pilot.pause(0.2)
    assert len(set(visited)) == 9, visited
    return f"9 zakładek, okno transakcji ({platform.system()})"


def run_selftest() -> int:
    """Uruchamiaj PRZED importem modułów `src` (ustawia tymczasowy katalog danych)."""
    for stream in (sys.stdout, sys.stderr):  # konsola Windows / przekierowanie do pliku: bez wyjątków kodowania
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    tmp = Path(tempfile.mkdtemp(prefix="matrix_finance_selftest_"))
    os.environ["MATRIX_FINANCE_HOME"] = str(tmp / "dane")
    from src.version import APP_NAME, APP_VERSION

    print(f"{APP_NAME} {APP_VERSION} — test instalacji")
    print(f"Python {platform.python_version()} ({sys.executable}) · {platform.platform()}")
    results: List[Tuple[str, bool, str]] = []
    try:
        _check(results, "Biblioteki", _libraries)
        _check(results, "Silnik budżetu i baza SQLite", _engine)
        if results[-1][1]:
            _check(results, "Eksport / import / raport", lambda: _export_import(tmp))
            _check(results, "Szyfrowanie danych", _encryption)
            _check(results, "Interfejs (bez okna)", lambda: asyncio.run(_ui_scenario()))
    finally:
        try:
            from src.finance.storage import clear_active_user_db

            clear_active_user_db()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [name for name, ok, _ in results if not ok]
    print("-" * 60)
    if failed:
        print(f"WYNIK: BŁĘDY ({', '.join(failed)})")
        return 1
    print("WYNIK: WSZYSTKO DZIAŁA ✔" if _can_encode("✔") else "WYNIK: WSZYSTKO DZIALA")
    return 0


def _can_encode(text: str) -> bool:
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False
