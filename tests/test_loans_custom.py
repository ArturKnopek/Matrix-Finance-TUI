"""Własne rodzaje kont, stany początkowe (bez historii) oraz kredyty i raty."""
from __future__ import annotations

from datetime import date

import pytest

from src.finance import accounts, analytics, envelopes, goals, ledger, loans, recurring


def _balance(name: str) -> float:
    return round(accounts.get_account_balance(name), 2)


# --------------------------------------------------------------------------- własny rodzaj konta

def test_custom_account_kind(user_db):
    ok, msg = accounts.add_account("Obligacje co miesiąc", 0, account_kind="custom", custom_label="Obligacje skarbowe",
                                   custom_group="Inwestycje", custom_flags="valuation,rate")
    assert ok, msg
    row = accounts.get_account("Obligacje co miesiąc")
    info = accounts.account_info(row)
    assert (info.label, info.group, info.valuation, info.has_rate, info.liquid, info.custom) == \
        ("Obligacje skarbowe", "Inwestycje", True, True, False, True)
    assert "Obligacje co miesiąc" not in accounts.get_account_names(liquid_only=True)
    accounts.add_account("Portfel PLN", 50, account_kind="custom", custom_label="Skarbonka domowa",
                         custom_group="Codzienne", custom_flags="liquid")
    assert "Portfel PLN" in accounts.get_account_names(liquid_only=True)
    over = {a["name"]: a for a in accounts.get_accounts_overview()}
    assert over["Obligacje co miesiąc"]["group"] == "Inwestycje"
    assert over["Obligacje co miesiąc"]["kind_label"] == "Obligacje skarbowe"
    # comiesięczna wpłata (przelew) + wycena ręczna działają jak dla inwestycji
    accounts.transfer_between_accounts("Karta", "Obligacje co miesiąc", 100, "2026-01-10")
    assert accounts.update_valuation("Obligacje co miesiąc", 103.5) == pytest.approx(3.5)
    ok, msg = accounts.update_account("Obligacje co miesiąc", custom_flags="valuation", custom_group="Oszczędności")
    assert ok and accounts.account_info(accounts.get_account("Obligacje co miesiąc")).group == "Oszczędności"


# --------------------------------------------------------------------------- stan początkowy

def test_opening_balances_without_history(user_db):
    accounts.set_opening_mode(True)
    assert accounts.opening_mode()
    assert accounts.set_account_balance("Karta", 4321.5, record=False) == pytest.approx(3321.5)
    assert _balance("Karta") == 4321.5
    assert ledger.fetch_transactions() == []  # bez wpisów
    ok, msg = accounts.open_term_deposit("Lokata (istniejąca)", None, 5000, 6.0, 12, start_date="2026-05-01",
                                         return_to="Karta")
    assert ok, msg
    assert _balance("Lokata (istniejąca)") == 5000 and _balance("Karta") == 4321.5
    assert accounts.get_account("Lokata (istniejąca)")["linked_account"] == "Karta"
    goals.add_piggy_bank("Wakacje", 3000, "Karta")
    g_id = goals.get_all_piggy_banks()[0]["id"]
    assert accounts.set_opening_balances({"Gotówka": 75, "Karta": 4321.5}, {g_id: 900}) == 2
    assert _balance("Gotówka") == 75 and float(goals.get_piggy_bank_by_id(g_id)["current_amount"]) == 900
    assert ledger.fetch_transactions() == []
    accounts.set_opening_mode(False)
    assert not accounts.opening_mode()


# --------------------------------------------------------------------------- raty 0%

def test_installments_zero_percent(user_db):
    ok, msg = loans.open_loan("Ekspres", 1500, 10, "2026-01-05", "Karta", 0.0, kind="installments",
                              category="Raty", day="2026-01-02")
    assert ok, msg
    assert _balance("Ekspres") == -1500
    nw = accounts.get_net_worth()
    assert nw["Zobowiązania"] == -1500 and nw["debt"] == 1500 and nw["liquid"] == 1200
    assert envelopes.get_category_by_id(next(c["id"] for c in envelopes.get_all_categories_data()
                                             if c["name"] == "Raty"))["limit_amount"] == 150
    assert recurring.check_due_payments_count(date(2026, 3, 10)) == 3
    up = [u for u in recurring.get_upcoming_recurring(today=date(2026, 1, 1)) if u.get("loan") == "Ekspres"]
    assert up and up[0]["amount"] == 150 and up[0]["next_due"] == date(2026, 1, 5)

    assert recurring.check_and_process_recurring(date(2026, 3, 10)) == 3
    assert _balance("Karta") == 1000 - 450 and _balance("Ekspres") == -1050
    st = loans.loan_status(accounts.get_account("Ekspres"), date(2026, 3, 10))
    assert (st["paid"], st["left"], st["next_due"], round(st["progress"])) == (3, 7, date(2026, 4, 5), 30)
    # rata to wydatek w kopercie (budżet), dług maleje — majątek się nie zmienia
    assert analytics.get_monthly_balance("2026-03") == (0.0, 150.0)
    assert {e["name"]: e for e in envelopes.get_envelope_overview("2026-03")}["Raty"]["spent"] == 150

    assert recurring.check_and_process_recurring(date(2027, 6, 1)) == 7  # dalej już nic
    st = loans.loan_status(accounts.get_account("Ekspres"), date(2027, 6, 1))
    assert st["finished"] and st["paid"] == 10 and _balance("Ekspres") == 0
    assert recurring.check_and_process_recurring(date(2027, 12, 1)) == 0


def test_installment_delete_and_edit_rules(user_db):
    loans.open_loan("Telefon", 600, 6, "2026-02-10", "Karta", 0.0)
    recurring.check_and_process_recurring(date(2026, 2, 10))
    expense = next(t for t in ledger.fetch_transactions() if t["type"] == "Wydatek")
    with pytest.raises(ValueError):
        ledger.update_transaction(expense["id"], expense["date"], "Wydatek", "Inne", "Karta", "x", 1, "", True)
    assert ledger.delete_transaction(expense["id"]) == 2  # wydatek + spłata
    assert _balance("Telefon") == -600 and _balance("Karta") == 1000


# --------------------------------------------------------------------------- kredyt z odsetkami

def test_loan_with_interest_and_disbursement(user_db):
    payment = loans.annuity_payment(10000, 12.0, 12)
    assert payment == pytest.approx(888.49, abs=0.01)
    ok, msg = loans.open_loan("Kredyt gotówkowy", 10000, 12, "2026-02-15", "Karta", 12.0, kind="loan",
                              disburse_to="Karta", day="2026-01-15")
    assert ok, msg
    assert _balance("Karta") == 11000 and _balance("Kredyt gotówkowy") == -10000
    assert accounts.get_net_worth()["total"] == pytest.approx(1200 - 10000 + 10000)  # pożyczka nie zmienia majątku
    assert analytics.get_monthly_balance("2026-01") == (0.0, 0.0)  # wypłata kredytu to nie dochód
    recurring.check_and_process_recurring(date(2026, 2, 15))
    rows = [t for t in ledger.fetch_transactions() if t["linked_group_id"] and t["linked_group_id"].startswith("loan-")
            and t["date"] == "2026-02-15"]
    exp = next(t for t in rows if t["type"] == "Wydatek")
    rep = next(t for t in rows if t["entry_subtype"] == loans.REPAY)
    assert exp["amount"] == pytest.approx(888.49) and rep["amount"] == pytest.approx(888.49 - 100.0)
    recurring.check_and_process_recurring(date(2027, 3, 1))
    st = loans.loan_status(accounts.get_account("Kredyt gotówkowy"), date(2027, 3, 1))
    assert st["finished"] and st["paid"] == 12
    assert st["interest_paid"] == pytest.approx(661.85, abs=0.2)


def test_overpayment_finishes_earlier(user_db):
    accounts.set_account_balance("Karta", 5000)
    loans.open_loan("Pralka", 2000, 10, "2026-01-20", "Karta", 0.0)
    recurring.check_and_process_recurring(date(2026, 1, 20))
    accounts.transfer_between_accounts("Karta", "Pralka", 1500, "2026-01-25")  # nadpłata
    assert _balance("Pralka") == -300
    recurring.check_and_process_recurring(date(2026, 12, 31))
    st = loans.loan_status(accounts.get_account("Pralka"), date(2026, 12, 31))
    assert st["finished"] and st["paid"] == 3  # 200 + 200 + 100 (ostatnia przycięta)


def test_existing_loan_as_opening_balance(user_db):
    ok, msg = loans.open_loan("Hipoteka", 250000, 240, "2026-12-10", "Karta", 7.5, kind="loan",
                              record_history=False)
    assert ok, msg
    assert _balance("Hipoteka") == -250000 and ledger.fetch_transactions() == []
    st = loans.loan_status(accounts.get_account("Hipoteka"), date(2026, 11, 25))
    assert st["payment"] == pytest.approx(loans.annuity_payment(250000, 7.5, 240)) and st["days"] == 15
