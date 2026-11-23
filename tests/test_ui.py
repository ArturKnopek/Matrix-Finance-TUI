"""
Testy interfejsu (Textual Pilot) — uruchamiają prawdziwą aplikację bez terminala.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.utils.smart_table import SmartTable

SIZES = [(64, 20), (80, 24), (100, 30), (120, 36), (180, 50)]


def run(coro):
    return asyncio.run(coro)


def _user_id(db) -> str:
    return Path(db.get_active_user_db()).stem


async def _open_dashboard(app, pilot, db):
    app.set_current_user(_user_id(db), "tester")
    await app.switch_screen("main_dashboard")
    await pilot.pause(0.3)
    return app.screen


def _app():
    from src.app import MatrixApp

    return MatrixApp()


# --------------------------------------------------------------------------
# Transakcje
# --------------------------------------------------------------------------

def test_add_transaction_via_form(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            assert screen._current_view() == "view-nowa-tranzakcja"
            form = screen.query_one("#view-nowa-tranzakcja")
            form.query_one("#input-amount").value = "12,5+2.5"
            form.query_one("#input-category").value = "Jedzenie"
            form.query_one("#input-shop").value = "[Sklep] test"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            assert screen._current_view() == "view-tranzakcje"

    run(scenario())
    rows = db.fetch_transactions()
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(15.0)
    assert rows[0]["shop"] == "[Sklep] test"
    assert db.get_account_balance("Karta") == pytest.approx(985.0)


def test_quick_transaction_from_dashboard_returns_to_dashboard(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            form = screen.query_one("#view-nowa-tranzakcja")
            form.query_one("#input-type").value = "Dochód"
            form.query_one("#input-amount").value = "100"
            form.query_one("#input-shop").value = "Zwrot"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            assert screen._current_view() == "view-pulpit"

    run(scenario())
    assert db.get_account_balance("Karta") == pytest.approx(1100.0)


def test_validation_error_keeps_form_open(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2", "ctrl+n")
            await pilot.pause(0.2)
            screen.query_one("#input-amount").value = "abc"
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            assert screen._current_view() == "view-nowa-tranzakcja"
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert screen._current_view() == "view-tranzakcje"

    run(scenario())
    assert db.fetch_transactions() == []


def test_delete_transaction_with_confirmation(user_db):
    db = user_db
    db.add_transaction(date.today().isoformat(), "Wydatek", "Jedzenie", "Karta", "A", 50, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            await pilot.press("ctrl+d")
            await pilot.pause(0.2)
            assert app.screen.__class__.__name__ == "ConfirmationModal"
            await pilot.press("t")
            await pilot.pause(0.3)
            assert app.screen is screen

    run(scenario())
    assert db.fetch_transactions() == []
    assert db.get_account_balance("Karta") == pytest.approx(1000.0)


def test_single_click_selects_row_without_opening_editor(user_db):
    db = user_db
    today = date.today().isoformat()
    for shop in ("A", "B", "C"):
        db.add_transaction(today, "Wydatek", "Jedzenie", "Karta", shop, 1, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            table = screen.query_one("#my-smart-table #smart-datatable")
            await pilot.click(table, offset=(3, 2))  # nagłówek = y 0, wiersz 2 = y 2
            await pilot.pause(0.2)
            assert screen._current_view() == "view-tranzakcje"
            assert table.cursor_row == 1
            await pilot.click(table, offset=(3, 2))  # drugie kliknięcie = edycja
            await pilot.pause(0.3)
            assert screen._current_view() == "view-nowa-tranzakcja"

    run(scenario())


def test_page_down_moves_to_next_page(user_db):
    db = user_db
    today = date.today().isoformat()
    for i in range(60):
        db.add_transaction(today, "Wydatek", "Jedzenie", "Karta", f"S{i}", 1, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("2")
            await pilot.pause(0.3)
            smart = screen.query_one("#my-smart-table", SmartTable)
            assert smart.total_pages > 1
            await pilot.press("pagedown")
            await pilot.pause(0.2)
            assert smart.current_page == 2
            await pilot.press("pageup")
            await pilot.pause(0.2)
            assert smart.current_page == 1

    run(scenario())


# --------------------------------------------------------------------------
# Skarbonki / cykliczne
# --------------------------------------------------------------------------

def test_piggy_deposit_with_plus_key(user_db):
    db = user_db
    db.add_piggy_bank("Wakacje", 1000, "Karta")

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("4")
            await pilot.pause(0.3)
            await pilot.press("plus")
            await pilot.pause(0.2)
            assert screen._current_view() == "view-op-skarbonka"
            screen.query_one("#pig-op-amount").value = "100"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            assert screen._current_view() == "view-skarbonki"

    run(scenario())
    assert float(db.get_all_piggy_banks()[0]["current_amount"]) == pytest.approx(100.0)
    assert db.get_account_balance("Karta") == pytest.approx(900.0)


def test_new_recurring_in_the_past_offers_catch_up(user_db):
    db = user_db
    start = (date.today() - timedelta(days=14)).isoformat()

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("5")
            await pilot.pause(0.2)
            await pilot.press("ctrl+n")
            await pilot.pause(0.2)
            form = screen.query_one("#view-nowe-cykliczne")
            form.query_one("#rec-input-name").value = "Kawa"
            form.query_one("#rec-input-amount").value = "10"
            form.query_one("#rec-input-category").value = "Jedzenie"
            form.query_one("#rec-input-cycle").value = "Tygodniowo"
            form.query_one("#rec-input-date").value = start
            await pilot.press("ctrl+s")
            await pilot.pause(0.4)
            assert app.screen.__class__.__name__ == "ConfirmationModal"
            await pilot.press("t")
            await pilot.pause(0.3)

    run(scenario())
    assert len(db.fetch_transactions()) == 3  # dziś-14, dziś-7, dziś
    assert db.get_account_balance("Karta") == pytest.approx(970.0)


def test_ctrl_p_pauses_recurring_instead_of_command_palette(user_db):
    db = user_db
    db.add_recurring("Netflix", 49, "Wydatek", "Rozrywka", "Karta", "Miesięcznie",
                     (date.today() + timedelta(days=3)).isoformat(), 1)

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await _open_dashboard(app, pilot, db)
            await pilot.press("5")
            await pilot.pause(0.3)
            await pilot.press("ctrl+p")
            await pilot.pause(0.3)

    run(scenario())
    assert int(db.get_all_recurring()[0]["is_registered"]) == 0


# --------------------------------------------------------------------------
# Ustawienia / raporty
# --------------------------------------------------------------------------

def test_settings_checkbox_saves_immediately(user_db):
    db = user_db
    db.set_setting("skip_delete_confirm", "0")

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("7")
            await pilot.pause(0.3)
            chk = screen.query_one("#chk-skip-delete")
            chk.focus()
            await pilot.press("space")
            await pilot.pause(0.2)

    run(scenario())
    assert db.get_setting("skip_delete_confirm") == "1"
    db.set_setting("skip_delete_confirm", "0")


def test_settings_add_account_and_set_balance(user_db):
    db = user_db

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("7")
            await pilot.pause(0.3)
            view = screen.query_one("#view-ustawienia")
            view.query_one("#set-new-account").value = "Lokata"
            view.query_one("#set-new-account-balance").value = "2500"
            await screen._handle_action("btn-add-account")
            await pilot.pause(0.2)
            view.query_one("#set-bal-account").value = "Gotówka"
            await pilot.pause(0.1)
            view.query_one("#set-bal-value").value = "321,5"
            await screen._handle_action("btn-set-balance")
            await pilot.pause(0.2)

    run(scenario())
    assert db.get_account_balance("Lokata") == pytest.approx(2500.0)
    assert db.get_account_balance("Gotówka") == pytest.approx(321.5)


def test_archive_month_from_reports(user_db):
    db = user_db
    ym = date.today().strftime("%Y-%m")
    db.add_transaction(f"{ym}-01", "Wydatek", "Jedzenie", "Karta", "A", 10, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("6")
            await pilot.pause(0.3)
            await screen._handle_action("btn-archive")
            await pilot.pause(0.2)
            assert app.screen.__class__.__name__ == "ConfirmationModal"
            await pilot.press("t")
            await pilot.pause(0.3)

    run(scenario())
    assert db.fetch_transactions(month_filter=ym) == []
    assert db.get_monthly_summary(ym)[1] == pytest.approx(10.0)


def test_txt_and_csv_reports_contain_data(user_db):
    db = user_db
    ym = date.today().strftime("%Y-%m")
    db.add_transaction(f"{ym}-02", "Wydatek", "Jedzenie", "Karta", "Biedronka", 42.5, "", True)

    async def scenario():
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            await pilot.press("6")
            await pilot.pause(0.3)
            view = screen.query_one("#view-raporty")
            return view.generate_txt_report(), view.generate_csv_report()

    txt_path, csv_path = run(scenario())
    txt = Path(txt_path).read_text(encoding="utf-8")
    assert "42.50 PLN" in txt and "Biedronka" in txt
    csv_text = Path(csv_path).read_text(encoding="utf-8-sig")
    assert "Biedronka" in csv_text and "42,50" in csv_text


# --------------------------------------------------------------------------
# Responsywność
# --------------------------------------------------------------------------

@pytest.mark.parametrize("size", SIZES)
def test_layout_fits_terminal(user_db, size):
    """Stopka i kolumny tabel mieszczą się w oknie dla typowych rozmiarów terminala."""
    db = user_db
    today = date.today().isoformat()
    for i in range(30):
        db.add_transaction(today, "Wydatek", "Rozrywka", "Karta", f"Bardzo długa nazwa sklepu nr {i}",
                           1234.56, "opis " * 15, True)

    async def scenario():
        app = _app()
        async with app.run_test(size=size) as pilot:
            screen = await _open_dashboard(app, pilot, db)
            assert screen.has_class("-compact") == (size[0] < 100)
            for key in "1234567":
                await pilot.press(key)
                await pilot.pause(0.25)
                footer = screen.query_one("#footer")
                buttons = [b for b in screen.query(".footer-btn") if b.display]
                right_edge = max(b.region.right for b in buttons)
                assert right_edge <= footer.region.right, (size, key, right_edge, footer.region)
            await pilot.press("2")
            await pilot.pause(0.3)
            smart = screen.query_one("#my-smart-table", SmartTable)
            table = smart.table
            used = sum(w + 2 * table.cell_padding for _, w in smart.active_columns)
            assert used <= table.size.width, (size, used, table.size.width)
            assert table.row_count == min(30, smart.rows_per_page)

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
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert screen.has_class("-compact")

    run(scenario())


# --------------------------------------------------------------------------
# Logowanie
# --------------------------------------------------------------------------

def test_login_and_logout_flow(user_db):
    db = user_db
    from src.core.auth import AuthService

    AuthService.create_user("janek", "tajne123")
    user = db.get_user_by_username("janek")
    db.init_user_db(str(db.DATA_DIR / f"{user['id']}.db"))

    async def scenario():
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("enter")  # ekran powitalny -> logowanie
            await pilot.pause(0.2)
            assert app.screen.__class__.__name__ == "LoginScreen"
            app.screen.query_one("#user-login").value = "janek"
            app.screen.query_one("#user-login").focus()
            await pilot.press("enter")  # Enter w loginie -> przejście do hasła
            await pilot.pause(0.1)
            assert app.screen.focused.id == "user-password"
            app.screen.query_one("#user-password").value = "tajne123"
            await pilot.press("enter")
            await pilot.pause(0.4)
            assert app.screen.__class__.__name__ == "MainDashboard"
            assert app.current_username == "janek"
            await pilot.press("ctrl+l")
            await pilot.pause(0.3)
            assert app.screen.__class__.__name__ == "LoginScreen"
            assert app.current_user_id is None

    run(scenario())
