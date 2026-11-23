"""Testy nowych funkcji silnika: przelewy, lokaty, inwestycje, koperty, auto-oszczędzanie, eksport."""
from __future__ import annotations

from datetime import date

import pytest

from src.finance import accounts, analytics, autosave, data_io, envelopes, goals, ledger, recurring


# --------------------------------------------------------------------------- przelewy

def test_transfer_moves_money_without_touching_budget(user_db):
    db = user_db
    accounts.add_account("Revolut", 0, account_kind="ewallet", institution="Revolut")
    accounts.transfer_between_accounts("Karta", "Revolut", 250, "2026-03-02")
    assert db.get_account_balance("Karta") == pytest.approx(750)
    assert db.get_account_balance("Revolut") == pytest.approx(250)
    assert analytics.get_monthly_balance("2026-03") == (0.0, 0.0)  # przelew to nie wydatek/dochód
    rows = ledger.fetch_transactions(month_filter="2026-03")
    assert {r["entry_subtype"] for r in rows} == {"transfer_out", "transfer_in"}


def test_deleting_one_leg_deletes_whole_transfer(user_db):
    db = user_db
    accounts.add_account("Oszczędnościowe", 0, account_kind="savings")
    accounts.transfer_between_accounts("Karta", "Oszczędnościowe", 100, "2026-03-02")
    t_id = ledger.fetch_transactions()[0]["id"]
    assert ledger.delete_transaction(t_id) == 2
    assert db.get_account_balance("Karta") == pytest.approx(1000)
    assert db.get_account_balance("Oszczędnościowe") == pytest.approx(0)


def test_transfer_requires_funds_and_editing_is_blocked(user_db):
    accounts.add_account("Lokata X", 0, account_kind="savings")
    with pytest.raises(ValueError):
        accounts.transfer_between_accounts("Gotówka", "Lokata X", 999)
    accounts.transfer_between_accounts("Gotówka", "Lokata X", 50)
    row = ledger.fetch_transactions()[0]
    with pytest.raises(ValueError):
        ledger.update_transaction(row["id"], row["date"], "Wydatek", "Inne", "Karta", "x", 1, "", True)


def test_balance_correction_is_logged(user_db):
    db = user_db
    diff = accounts.set_account_balance("Gotówka", 260)
    assert diff == pytest.approx(60)
    assert db.get_account_balance("Gotówka") == pytest.approx(260)
    assert ledger.fetch_transactions()[0]["entry_subtype"] == "correction_up"


# --------------------------------------------------------------------------- lokaty

def test_term_deposit_lifecycle_with_belka_tax(user_db):
    db = user_db
    ok, msg = accounts.open_term_deposit("Lokata 6M", "Karta", 600, 6.0, 6, start_date="2026-01-01",
                                         institution="Revolut")
    assert ok, msg
    assert db.get_account_balance("Karta") == pytest.approx(400)
    acc = accounts.get_account("Lokata 6M")
    proj = accounts.deposit_projection(acc, today=date(2026, 4, 1))
    assert proj["end"] == date(2026, 7, 1)
    assert 0 < proj["progress"] < 100
    # 600 * 6% * 181/365 = 17.85 brutto, podatek 19% = 3.39, netto 14.46
    assert proj["gross_interest"] == pytest.approx(17.85)
    assert proj["net_interest"] == pytest.approx(14.46)

    msgs = accounts.settle_matured_deposits(today=date(2026, 7, 2))
    assert msgs and "Karta" in msgs[0]
    assert db.get_account_balance("Karta") == pytest.approx(400 + 600 + 14.46)
    assert int(accounts.get_account("Lokata 6M")["is_active"]) == 0
    inc, _ = analytics.get_monthly_balance("2026-07")
    assert inc == pytest.approx(14.46)  # odsetki to dochód


def test_auto_renewing_deposit_capitalizes(user_db):
    db = user_db
    accounts.open_term_deposit("Odnawialna", "Karta", 500, 5.0, 3, start_date="2026-01-01", auto_renew=True)
    accounts.settle_matured_deposits(today=date(2026, 7, 15))  # 2 okresy
    acc = accounts.get_account("Odnawialna")
    assert int(acc["is_active"]) == 1
    assert acc["maturity_date"] == "2026-10-01"
    assert db.get_account_balance("Odnawialna") > 500


def test_breaking_deposit_returns_principal_only(user_db):
    db = user_db
    accounts.open_term_deposit("Krótka", "Karta", 300, 7.0, 12, start_date="2026-01-01")
    ok, _ = accounts.break_term_deposit("Krótka", today=date(2026, 3, 1))
    assert ok
    assert db.get_account_balance("Karta") == pytest.approx(1000)


def test_investment_valuation_and_retirement_limits(user_db):
    db = user_db
    accounts.add_account("IKE ETF", 0, account_kind="ike", yearly_limit=10000)
    accounts.transfer_between_accounts("Karta", "IKE ETF", 400, f"{date.today().year}-01-05")
    accounts.external_contribution("IKE ETF", 50)
    diff = accounts.update_valuation("IKE ETF", 520)
    assert diff == pytest.approx(70)
    assert db.get_account_balance("IKE ETF") == pytest.approx(520)
    assert accounts.contributions_in_year("IKE ETF") == pytest.approx(450)
    nw = accounts.get_net_worth()
    assert nw["Emerytalne"] == pytest.approx(520)
    assert nw["liquid"] == pytest.approx(600 + 200)
    assert analytics.get_monthly_balance(date.today().strftime("%Y-%m")) == (0.0, 0.0)


# --------------------------------------------------------------------------- koperty

def test_rollover_envelope_carries_unspent_money(user_db):
    with envelopes.open_user_db(write=True) as conn:
        conn.execute("UPDATE categories SET limit_amount = 500, rollover = 1, rollover_since = '2026-01' "
                     "WHERE name = 'Jedzenie'")
        conn.execute("UPDATE categories SET limit_amount = 200, rollover = 0 WHERE name = 'Transport'")
    ledger.add_transaction("2026-01-10", "Wydatek", "Jedzenie", "Karta", "A", 300, "", True)  # zostaje 200
    ledger.add_transaction("2026-02-10", "Wydatek", "Jedzenie", "Karta", "B", 650, "", True)  # 700 dostępne
    ledger.add_transaction("2026-01-10", "Wydatek", "Transport", "Karta", "C", 50, "", True)
    over = {e["name"]: e for e in envelopes.get_envelope_overview("2026-02")}
    assert over["Jedzenie"]["carried"] == pytest.approx(200)
    assert over["Jedzenie"]["available"] == pytest.approx(700)
    assert over["Jedzenie"]["remaining"] == pytest.approx(50)
    assert over["Transport"]["carried"] == 0  # bez przenoszenia
    march = {e["name"]: e for e in envelopes.get_envelope_overview("2026-03")}
    assert march["Jedzenie"]["carried"] == pytest.approx(50)
    summary = envelopes.get_budget_summary("2026-02")
    assert summary["budgeted"] == pytest.approx(700)


# --------------------------------------------------------------------------- auto-oszczędzanie

def test_income_percent_autosave_to_account(user_db):
    db = user_db
    accounts.add_account("Poduszka", 0, account_kind="savings")
    ok, msg = autosave.save_autosave_rule("Karta", "income_percent", 10, "account", "Poduszka")
    assert ok, msg
    ledger.add_transaction("2026-05-01", "Dochód", "Wynagrodzenie", "Karta", "Pensja", 5000, "", True)
    assert db.get_account_balance("Poduszka") == pytest.approx(500)
    assert db.get_account_balance("Karta") == pytest.approx(1000 + 5000 - 500)
    assert autosave.autosave_total_in_month("2026-05") == pytest.approx(500)


def test_roundup_autosave_to_goal(user_db):
    db = user_db
    goals.add_piggy_bank("Wakacje", 1000, "Karta")
    goal_id = goals.get_all_piggy_banks()[0]["id"]
    autosave.save_autosave_rule("Karta", "roundup", 10, "goal", str(goal_id))
    ledger.add_transaction("2026-05-02", "Wydatek", "Jedzenie", "Karta", "Sklep", 23.40, "", True)
    assert float(goals.get_piggy_bank_by_id(goal_id)["current_amount"]) == pytest.approx(6.60)
    assert db.get_account_balance("Karta") == pytest.approx(1000 - 30)


def test_recurring_income_triggers_autosave_and_transfer_type(user_db):
    db = user_db
    accounts.add_account("IKE", 0, account_kind="ike")
    autosave.save_autosave_rule("Karta", "income_percent", 20, "account", "Gotówka")
    recurring.add_recurring("Pensja", 1000, "Dochód", "", "Karta", "Miesięcznie", "2026-01-01", 1)
    recurring.add_recurring("Na IKE", 100, "Przelew", None, "Karta", "Kwartalnie", "2026-01-15", 1,
                            target_account="IKE")
    assert recurring.check_and_process_recurring(date(2026, 4, 20)) == 4 + 2
    assert db.get_account_balance("IKE") == pytest.approx(200)
    assert db.get_account_balance("Gotówka") == pytest.approx(200 + 4 * 200)


def test_goal_plan_monthly_needed(user_db):
    goals.add_piggy_bank("Auto", 12000, "Karta", target_date="2027-01-15")
    plan = goals.goal_plan(goals.get_all_piggy_banks()[0], today=date(2026, 1, 10))
    assert plan["months_left"] == 12
    assert plan["monthly_needed"] == pytest.approx(1000)


# --------------------------------------------------------------------------- analityka

def test_calendar_insights_and_search(user_db):
    ym = date.today().strftime("%Y-%m")
    ledger.add_transaction(f"{ym}-03", "Wydatek", "Jedzenie", "Karta", "Żabka", 20, "", True)
    recurring.add_recurring("Netflix", 49, "Wydatek", "Rozrywka", "Karta", "Miesięcznie", f"{ym}-15", 1)
    cal = analytics.get_calendar_data(ym)
    assert cal[3].spent == pytest.approx(20)
    assert any("Netflix" in p for p in cal[15].planned)
    assert analytics.get_insights(ym)
    kinds = {h.kind for h in analytics.search_everything("netf")}
    assert "recurring" in kinds
    assert any(h.kind == "transaction" for h in analytics.search_everything("żab"))


# --------------------------------------------------------------------------- eksport / import

def test_json_export_import_roundtrip_encrypted(user_db, tmp_path):
    db = user_db
    ledger.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Karta", "Przed eksportem", 10, "", True)
    path = tmp_path / "dane.mfx"
    data_io.export_json(str(path), password="sekret123")
    assert b"Przed eksportem" not in path.read_bytes() and b'"tables"' not in path.read_bytes()
    ledger.add_transaction("2026-01-06", "Wydatek", "Jedzenie", "Karta", "Po eksporcie", 10, "", True)
    with pytest.raises(ValueError):
        data_io.import_json(str(path), password="zle")
    counts = data_io.import_json(str(path), password="sekret123")
    assert counts["transactions"] == 1
    assert [r["shop"] for r in ledger.fetch_transactions()] == ["Przed eksportem"]
    assert db.get_account_balance("Karta") == pytest.approx(990)


def test_csv_export_and_import_without_balance_change(user_db, tmp_path):
    db = user_db
    ledger.add_transaction("2026-02-05", "Wydatek", "Jedzenie", "Karta", "Sklep; z średnikiem", 12.5, "x", True)
    path = tmp_path / "t.csv"
    assert data_io.export_transactions_csv(str(path)) == 1
    imported, errors = data_io.import_transactions_csv(str(path), update_balances=False)
    assert imported == 1 and not errors
    assert len(ledger.fetch_transactions()) == 2
    assert db.get_account_balance("Karta") == pytest.approx(987.5)  # import nie zmienił salda


def test_html_report(user_db, tmp_path):
    ledger.add_transaction("2026-02-05", "Wydatek", "Jedzenie", "Karta", "<script>", 12.5, "", True)
    path = data_io.save_monthly_report("2026-02", folder=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Raport miesięczny 2026-02" in text and "&lt;script&gt;" in text
