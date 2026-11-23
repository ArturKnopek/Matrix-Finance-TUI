"""
Testy interfejsu (Textual Pilot) — uruchamiają prawdziwą aplikację bez terminala.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.finance import accounts, autosave, goals, ledger, recurring, storage
from src.ui.smart_table import SmartTable

SIZES = [(64, 20), (80, 24), (100, 30), (120, 36), (180, 50)]


def run(coro):
    return asyncio.run(coro)


def _user_id(db) -> str:
    return Path(db.get_active_user_db()).stem


def _app():
    from src.app import MatrixApp

    storage.set_setting("ui_animations", "0")
    return MatrixApp()


async def _open_dashboard(app, pilot, db):
    app.set_current_user(_user_id(db), "tester")
    await app.switch_screen("main_dashboard")
    await pilot.pause(0.3)
    return app.screen


def _dialog_name(app) -> str:
    return app.screen.__class__.__name__


# --------------------------------------------------------------------------- transakcje

def test_add_transaction_via_dialog(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "TransactionDialog"
            dlg = app.screen
            dlg.query_one("#f-amount").value = "12,5+2.5"
            dlg.query_one("#f-category").value = "Jedzenie"
            dlg.query_one("#f-shop").value = "[Sklep] test"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "MainDashboard"

    run(scenario())
    rows = ledger.fetch_transactions()
    assert len(rows) == 1 and rows[0]["amount"] == pytest.approx(15.0) and rows[0]["shop"] == "[Sklep] test"
    assert db.get_account_balance("Karta") == pytest.approx(985.0)


def test_validation_error_is_shown_inside_dialog(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            app.screen.query_one("#f-amount").value = "abc"
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            assert _dialog_name(app) == "TransactionDialog"
            error = app.screen.query_one("#dialog-error")
            assert error.display and "kwot" in str(error.render()).lower()
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert _dialog_name(app) == "MainDashboard"

    run(scenario())
    assert ledger.fetch_transactions() == []


def test_delete_transaction_with_confirmation(user_db):
    db = user_db
    ledger.add_transaction(date.today().isoformat(), "Wydatek", "Jedzenie", "Karta", "A", 50, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            await pilot.press("ctrl+d")
            await pilot.pause(0.2)
            assert _dialog_name(app) == "ConfirmDialog"
            await pilot.press("t")
            await pilot.pause(0.3)

    run(scenario())
    assert ledger.fetch_transactions() == []
    assert db.get_account_balance("Karta") == pytest.approx(1000.0)


def test_transfer_dialog_from_anywhere(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("8")
            await pilot.pause(0.2)
            await pilot.press("ctrl+t")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "TransferDialog"
            dlg = app.screen
            dlg.query_one("#f-source").value = "Karta"
            dlg.query_one("#f-target").value = "Gotówka"
            dlg.query_one("#f-amount").value = "100"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)

    run(scenario())
    assert db.get_account_balance("Karta") == pytest.approx(900)
    assert db.get_account_balance("Gotówka") == pytest.approx(300)


def test_single_click_selects_row_without_opening_editor(user_db):
    db = user_db
    for shop in ("A", "B", "C"):
        ledger.add_transaction(date.today().isoformat(), "Wydatek", "Jedzenie", "Karta", shop, 1, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            table = screen.query_one("#trans-table #smart-datatable")
            await pilot.click(table, offset=(3, 2))
            await pilot.pause(0.2)
            assert _dialog_name(app) == "MainDashboard" and table.cursor_row == 1
            await pilot.click(table, offset=(3, 2))
            await pilot.pause(0.3)
            assert _dialog_name(app) == "TransactionDialog"

    run(scenario())


def test_page_down_moves_to_next_page(user_db):
    db = user_db
    for i in range(60):
        ledger.add_transaction(date.today().isoformat(), "Wydatek", "Jedzenie", "Karta", f"S{i}", 1, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            smart = screen.query_one("#trans-table", SmartTable)
            assert smart.total_pages > 1
            await pilot.press("pagedown")
            await pilot.pause(0.2)
            assert smart.current_page == 2

    run(scenario())


# --------------------------------------------------------------------------- konta / cele / automaty

def test_open_term_deposit_from_accounts_view(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("4")
            await pilot.pause(0.3)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            dlg = app.screen
            assert _dialog_name(app) == "AccountDialog"
            dlg.query_one("#f-kind").value = "deposit"
            await pilot.pause(0.1)
            dlg.query_one("#f-name").value = "Lokata test"
            dlg.query_one("#f-source").value = "Karta"
            dlg.query_one("#f-principal").value = "400"
            dlg.query_one("#f-term").value = "6"
            dlg.query_one("#f-rate").value = "5"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "MainDashboard"

    run(scenario())
    assert db.get_account_balance("Lokata test") == pytest.approx(400)
    assert db.get_account_balance("Karta") == pytest.approx(600)


def test_autosave_rule_from_accounts_view(user_db):
    db = user_db
    accounts.add_account("Oszczędności", 0, account_kind="savings")

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("4")
            await pilot.pause(0.3)
            await pilot.press("a")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "AutosaveRuleDialog"
            dlg = app.screen
            dlg.query_one("#f-source").value = "Karta"
            dlg.query_one("#f-value").value = "10"
            dlg.query_one("#f-target-account").value = "Oszczędności"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)

    run(scenario())
    assert len(autosave.get_autosave_rules("Karta")) == 1
    ledger.add_transaction(date.today().isoformat(), "Dochód", "", "Karta", "Pensja", 1000, "", True)
    assert db.get_account_balance("Oszczędności") == pytest.approx(100)


def test_goal_deposit_with_plus_key(user_db):
    db = user_db
    goals.add_piggy_bank("Wakacje", 1000, "Karta")

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("5")
            await pilot.pause(0.3)
            await pilot.press("plus")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "GoalOperationDialog"
            app.screen.query_one("#f-amount").value = "100"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)

    run(scenario())
    assert float(goals.get_all_piggy_banks()[0]["current_amount"]) == pytest.approx(100.0)
    assert db.get_account_balance("Karta") == pytest.approx(900.0)
    inc, exp = db.get_monthly_balance(date.today().strftime("%Y-%m"))
    assert exp == 0  # wpłata na cel nie jest wydatkiem


def test_new_recurring_in_the_past_offers_catch_up(user_db):
    db = user_db
    start = (date.today() - timedelta(days=14)).isoformat()

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("6")
            await pilot.pause(0.3)
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            dlg = app.screen
            assert _dialog_name(app) == "RecurringDialog"
            dlg.query_one("#f-name").value = "Kawa"
            dlg.query_one("#f-amount").value = "10"
            dlg.query_one("#f-category").value = "Jedzenie"
            dlg.query_one("#f-cycle").value = "Tygodniowo"
            dlg.query_one("#f-start").value = start
            await pilot.press("ctrl+s")
            await pilot.pause(0.5)
            assert _dialog_name(app) == "ConfirmDialog"
            await pilot.press("t")
            await pilot.pause(0.3)

    run(scenario())
    assert len(ledger.fetch_transactions()) == 3
    assert db.get_account_balance("Karta") == pytest.approx(970.0)


def test_ctrl_p_pauses_recurring(user_db):
    db = user_db
    recurring.add_recurring("Netflix", 49, "Wydatek", "Rozrywka", "Karta", "Miesięcznie",
                            (date.today() + timedelta(days=3)).isoformat(), 1)

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("6")
            await pilot.pause(0.3)
            await pilot.press("ctrl+p")
            await pilot.pause(0.3)

    run(scenario())
    assert int(recurring.get_all_recurring()[0]["is_registered"]) == 0


# --------------------------------------------------------------------------- nawigacja

def test_month_switch_and_global_search(user_db):
    db = user_db
    ledger.add_transaction("2025-03-04", "Wydatek", "Jedzenie", "Karta", "Unikalny sklep", 5, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 36)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            before = storage.get_active_month_str()
            await pilot.press("right_square_bracket")
            await pilot.pause(0.2)
            assert storage.get_active_month_str() != before
            await pilot.press("ctrl+f")
            await pilot.pause(0.2)
            assert _dialog_name(app) == "SearchDialog"
            await pilot.press(*"unikalny")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.4)
            assert screen._current_view() == "view-transactions"
            assert storage.get_active_month_str() == "2025-03"

    run(scenario())


def test_calendar_view_keyboard(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("7")
            await pilot.pause(0.4)
            cal = screen.query_one("#cal-main")
            assert cal.has_focus
            first = cal.selected
            await pilot.press("left" if first > 1 else "right")
            await pilot.pause(0.2)
            assert cal.selected != first
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "TransactionDialog"
            assert app.screen.query_one("#f-date").value == cal.selected_date.isoformat()

    run(scenario())


def test_toggle_sidebar_in_compact_mode(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            assert screen.has_class("-compact")
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert not screen.has_class("-compact")

    run(scenario())


@pytest.mark.parametrize("size", SIZES)
def test_layout_fits_terminal(user_db, size):
    """Stopka i kolumny tabel mieszczą się w oknie dla typowych rozmiarów terminala."""
    db = user_db
    for i in range(30):
        ledger.add_transaction(date.today().isoformat(), "Wydatek", "Rozrywka", "Karta",
                               f"Bardzo długa nazwa sklepu nr {i}", 1234.56, "opis " * 15, True)

    async def scenario():
        app = _app()
        async with app.run_test(size=size) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            assert screen.has_class("-compact") == (size[0] < 100)
            for key in "123456789":
                await pilot.press(key)
                await pilot.pause(0.25)
                footer = screen.query_one("#footer")
                buttons = [b for b in screen.query(".footer-btn") if b.display]
                assert max(b.region.right for b in buttons) <= footer.region.right, (size, key)
            await pilot.press("2")
            await pilot.pause(0.3)
            smart = screen.query_one("#trans-table", SmartTable)
            table = smart.table
            used = sum(w + 2 * table.cell_padding for _, w in smart.active_columns)
            assert used <= table.size.width, (size, used, table.size.width)

    run(scenario())


# --------------------------------------------------------------------------- ustawienia / raporty

def test_theme_switch_applies_immediately(user_db):
    db = user_db
    from src.ui.theme import palette

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("9")
            await pilot.pause(0.3)
            app.screen.query_one("#set-theme").value = "amber"
            await pilot.pause(0.3)
            assert app.theme == "mx-amber"
            assert palette().name == "amber"

    try:
        run(scenario())
        assert storage.get_setting("ui_theme") == "amber"
    finally:
        storage.set_setting("ui_theme", "matrix")
        from src.ui.theme import set_palette

        set_palette("matrix")


def test_archive_month_from_reports(user_db):
    db = user_db
    ym = date.today().strftime("%Y-%m")
    ledger.add_transaction(f"{ym}-01", "Wydatek", "Jedzenie", "Karta", "A", 10, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("8")
            await pilot.pause(0.3)
            await pilot.press("ctrl+d")
            await pilot.pause(0.2)
            assert _dialog_name(app) == "ConfirmDialog"
            await pilot.press("t")
            await pilot.pause(0.3)

    run(scenario())
    assert ledger.fetch_transactions(month_filter=ym) == []
    assert db.get_monthly_summary(ym)[1] == pytest.approx(10.0)


def test_reports_exports(user_db):
    db = user_db
    ym = date.today().strftime("%Y-%m")
    ledger.add_transaction(f"{ym}-02", "Wydatek", "Jedzenie", "Karta", "Biedronka", 42.5, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("8")
            await pilot.pause(0.3)
            view = screen.query_one("#view-reports")
            return view.generate_txt_report(), view.generate_csv_report()

    txt_path, csv_path = run(scenario())
    assert "42.50 PLN" in Path(txt_path).read_text(encoding="utf-8")
    assert "Biedronka" in Path(csv_path).read_text(encoding="utf-8-sig")


# --------------------------------------------------------------------------- logowanie

def _create_login_user(db, name="janek", password="tajne123"):
    """Tworzy użytkownika o unikalnym loginie (baza logowania jest wspólna dla sesji testów)."""
    import uuid

    from src.core.auth import AuthService

    login = f"{name}{uuid.uuid4().hex[:6]}"
    uid = AuthService.create_user(login, password)
    db.init_user_db(str(db.DATA_DIR / f"{uid}.db"))
    return uid, login


async def _login(app, pilot, name, password):
    await pilot.pause(0.2)
    await pilot.press("enter")
    await pilot.pause(0.2)
    assert _dialog_name(app) == "LoginScreen"
    app.screen.query_one("#user-login").value = name
    app.screen.query_one("#user-password").value = password
    await pilot.press("enter")
    await pilot.pause(0.5)


def test_login_and_logout_flow(user_db):
    db = user_db
    _, login = _create_login_user(db)

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _login(app, pilot, login, "tajne123")
            assert _dialog_name(app) == "MainDashboard" and app.current_username == login
            await pilot.press("ctrl+l")
            await pilot.pause(0.3)
            assert _dialog_name(app) == "LoginScreen" and app.current_user_id is None

    run(scenario())


def test_login_with_encrypted_data(user_db):
    db = user_db
    from src.core import vault

    uid, login = _create_login_user(db, "szyfr", "tajne123")
    db.set_active_user_db(uid)
    ledger.add_transaction(date.today().isoformat(), "Wydatek", "Jedzenie", "Karta", "Sekret", 9, "", True)
    vault.DataVault.enable(uid, "tajne123").close()

    async def scenario():
        app = _app()
        async with app.run_test(size=(110, 32)) as pilot:
            await _login(app, pilot, login, "tajne123")
            assert _dialog_name(app) == "MainDashboard"
            assert app.vault is not None
            assert [r["shop"] for r in ledger.fetch_transactions()] == ["Sekret"]
            assert not db.user_db_path(uid).exists()
            await pilot.press("ctrl+l")
            await pilot.pause(0.3)
            assert app.vault is None

    run(scenario())
    assert vault.is_encrypted(uid) and not db.user_db_path(uid).exists()


def test_login_requires_yubikey(user_db):
    db = user_db
    from src.core import yubikey

    class FakeKey:
        def challenge_response(self, challenge_hex, slot, timeout=20.0):
            return hmac.new(b"klucz", bytes.fromhex(challenge_hex), hashlib.sha1).hexdigest()

    uid, login = _create_login_user(db, "yubi", "tajne123")
    yubikey.set_backend(FakeKey())
    try:
        yubikey.enroll(uid)

        async def scenario():
            app = _app()
            async with app.run_test(size=(110, 32)) as pilot:
                await _login(app, pilot, login, "tajne123")
                await pilot.pause(0.5)
                assert _dialog_name(app) == "MainDashboard"
                assert app.current_username == login

        run(scenario())
    finally:
        yubikey.set_backend(None)
