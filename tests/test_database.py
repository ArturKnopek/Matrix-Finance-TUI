from __future__ import annotations

from datetime import date

import pytest


def test_new_db_has_default_categories_and_ordered_accounts(user_db):
    db = user_db
    cats = db.get_unique_categories()
    assert "Jedzenie" in cats and "Inne" in cats
    assert db.get_account_names() == ["Karta", "Gotówka"]


def test_default_categories_are_not_reseeded_after_delete(user_db):
    db = user_db
    for row in db.get_all_categories_data():
        db.delete_category(row["id"])
    db.init_user_db(db.get_active_user_db())
    assert db.get_unique_categories() == []


def test_income_without_category_does_not_violate_foreign_key(user_db):
    db = user_db
    db.add_transaction("2026-01-05", "Dochód", "", "Karta", "Pensja", 5000, "", True)
    rows = db.fetch_transactions(month_filter="2026-01")
    assert len(rows) == 1 and rows[0]["category"] is None
    assert db.get_account_balance("Karta") == pytest.approx(6000.0)


def test_unknown_category_is_created_on_the_fly(user_db):
    db = user_db
    db.add_transaction("2026-01-05", "Wydatek", "Nowa kat", "Karta", "Sklep", 10, "", True)
    assert "Nowa kat" in db.get_unique_categories()


def test_unknown_account_is_rejected_and_rolled_back(user_db):
    db = user_db
    with pytest.raises(ValueError):
        db.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Nie ma", "X", 10, "", True)
    assert db.fetch_transactions() == []


def test_update_and_delete_transaction_keep_balance_consistent(user_db):
    db = user_db
    db.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Karta", "Sklep", 100, "", True)
    t_id = db.fetch_transactions()[0]["id"]
    db.update_transaction(t_id, "2026-01-05", "Wydatek", "Jedzenie", "Gotówka", "Sklep", 50, "", True)
    assert db.get_account_balance("Karta") == pytest.approx(1000.0)
    assert db.get_account_balance("Gotówka") == pytest.approx(150.0)
    db.delete_transaction(t_id)
    assert db.get_account_balance("Gotówka") == pytest.approx(200.0)


def test_search_is_case_insensitive_for_polish_letters(user_db):
    db = user_db
    db.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Karta", "ŻABKA", 12, "", True)
    assert len(db.fetch_transactions(search_text="żab")) == 1
    assert len(db.fetch_transactions(search_text="jedz")) == 1


def test_category_spending_map(user_db):
    db = user_db
    db.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Karta", "A", 100, "", True)
    db.add_transaction("2026-01-06", "Dochód", "Jedzenie", "Karta", "Zwrot", 30, "", True)
    db.add_transaction("2026-02-01", "Wydatek", "Jedzenie", "Karta", "B", 999, "", True)
    spent = db.get_category_spending_map("2026-01")
    assert spent["Jedzenie"] == pytest.approx(70.0)
    assert db.get_category_spent("Jedzenie", "2026-01") == pytest.approx(70.0)


# --------------------------------------------------------------------------
# Płatności cykliczne
# --------------------------------------------------------------------------

def test_monthly_occurrences_keep_anchor_day():
    from src.database import recurring_occurrence

    start = date(2026, 1, 31)
    got = [recurring_occurrence(start, "Miesięcznie", n) for n in range(4)]
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_yearly_leap_day():
    from src.database import recurring_occurrence

    start = date(2024, 2, 29)
    assert recurring_occurrence(start, "Rocznie", 1) == date(2025, 2, 28)
    assert recurring_occurrence(start, "Rocznie", 4) == date(2028, 2, 29)


def test_recurring_catches_up_all_missed_occurrences(user_db):
    db = user_db
    db.add_recurring("Netflix", 50, "Wydatek", "Rozrywka", "Karta", "Miesięcznie", "2026-01-10", 1)
    today = date(2026, 4, 15)
    assert db.check_due_payments_count(today) == 4  # sty, lut, mar, kwi
    assert db.check_and_process_recurring(today) == 4
    assert db.get_account_balance("Karta") == pytest.approx(800.0)
    assert db.check_due_payments_count(today) == 0
    assert db.check_and_process_recurring(today) == 0  # idempotentne
    dates = sorted(r["date"] for r in db.fetch_transactions())
    assert dates == ["2026-01-10", "2026-02-10", "2026-03-10", "2026-04-10"]


def test_recurring_income_without_category(user_db):
    db = user_db
    db.add_recurring("Pensja", 4000, "Dochód", "", "Karta", "Miesięcznie", "2026-01-01", 1)
    assert db.check_and_process_recurring(date(2026, 1, 1)) == 1
    assert db.get_account_balance("Karta") == pytest.approx(5000.0)


def test_recurring_to_piggy_bank(user_db):
    db = user_db
    db.add_piggy_bank("Wakacje", 1000, "Karta")
    pig_id = db.get_all_piggy_banks()[0]["id"]
    db.add_recurring("Odkładanie", 25, "Na Skarbonkę", "Oszczędności", "Karta", "Tygodniowo", "2026-01-01", 1, pig_id)
    assert db.check_and_process_recurring(date(2026, 1, 22)) == 4
    assert float(db.get_piggy_bank_by_id(pig_id)["current_amount"]) == pytest.approx(100.0)
    assert db.get_account_balance("Karta") == pytest.approx(900.0)


def test_paused_recurring_is_skipped(user_db):
    db = user_db
    db.add_recurring("Siłownia", 99, "Wydatek", "Zdrowie", "Karta", "Miesięcznie", "2026-01-01", 1)
    r_id = db.get_all_recurring()[0]["id"]
    assert db.toggle_recurring_pause(r_id) is False
    assert db.check_due_payments_count(date(2026, 3, 1)) == 0
    assert db.check_and_process_recurring(date(2026, 3, 1)) == 0


def test_upcoming_recurring_uses_cycle_and_reports_overdue(user_db):
    db = user_db
    db.add_recurring("Tygodniówka", 10, "Wydatek", "Inne", "Karta", "Tygodniowo", "2026-01-01", 1)
    db.add_recurring("Czynsz", 1500, "Wydatek", "Rachunki", "Karta", "Miesięcznie", "2026-01-20", 1)
    up = db.get_upcoming_recurring(today=date(2026, 1, 3))
    assert [u["name"] for u in up] == ["Tygodniówka", "Czynsz"]
    assert up[0]["days"] == -2  # zaległa od 1 stycznia
    db.check_and_process_recurring(date(2026, 1, 3))
    up = db.get_upcoming_recurring(today=date(2026, 1, 3))
    assert up[0]["next_due"] == date(2026, 1, 8)


def test_deleted_category_does_not_break_recurring(user_db):
    db = user_db
    db.add_recurring("Prąd", 120, "Wydatek", "Rachunki", "Karta", "Miesięcznie", "2026-01-05", 1)
    cat_id = next(c["id"] for c in db.get_all_categories_data() if c["name"] == "Rachunki")
    db.delete_category(cat_id)
    assert db.check_and_process_recurring(date(2026, 1, 5)) == 1


# --------------------------------------------------------------------------
# Skarbonki / archiwum / kopia
# --------------------------------------------------------------------------

def test_piggy_deposit_withdraw_and_refund_on_delete(user_db):
    db = user_db
    db.add_piggy_bank("Laptop", 3000, "Karta")
    pig_id = db.get_all_piggy_banks()[0]["id"]
    db.update_piggy_bank_balance(pig_id, 300, "Karta", True)
    assert db.get_account_balance("Karta") == pytest.approx(700.0)
    with pytest.raises(Exception):
        db.update_piggy_bank_balance(pig_id, -500, "Karta", True)
    refunded = db.delete_piggy_bank(pig_id)
    assert refunded == pytest.approx(300.0)
    assert db.get_account_balance("Karta") == pytest.approx(1000.0)


def test_duplicate_piggy_name_returns_message(user_db):
    db = user_db
    assert db.add_piggy_bank("Auto", 100, "Karta")[0]
    db.add_piggy_bank("Dom", 100, "Karta")
    dom_id = next(p["id"] for p in db.get_all_piggy_banks() if p["name"] == "Dom")
    ok, msg = db.update_piggy_bank(dom_id, "Auto", 100, "Karta")
    assert not ok and "istnieje" in msg


def test_archive_month_keeps_summary(user_db):
    db = user_db
    db.add_transaction("2025-12-05", "Wydatek", "Jedzenie", "Karta", "A", 40, "", True)
    assert db.archive_month("2025-12") == 1
    assert db.fetch_transactions(month_filter="2025-12") == []
    assert db.get_monthly_summary("2025-12") == (0.0, 40.0)


def test_encrypted_backup_roundtrip(user_db, tmp_path):
    db = user_db
    from src.utils.crypto_utils import decrypt_file
    import sqlite3

    db.add_transaction("2026-01-05", "Wydatek", "Jedzenie", "Karta", "WAL-test", 1, "", True)
    out = tmp_path / "backup.matrix"
    assert db.export_encrypted_backup(str(out), "haslo123")
    restored = tmp_path / "restored.db"
    assert decrypt_file(str(out), str(restored), "haslo123")
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT shop FROM transactions").fetchone()[0] == "WAL-test"
    conn.close()
    assert not decrypt_file(str(out), str(tmp_path / "x.db"), "zle-haslo")


def test_legacy_migration_script(user_db, tmp_path):
    """Stara baza budget.db trafia do nowego użytkownika w ~/.matrix_finance."""
    db = user_db
    import sqlite3

    from src import migrate

    old = tmp_path / "budget.db"
    db.init_user_db(str(old), start_card=10.0)
    conn = sqlite3.connect(old)
    conn.execute("INSERT INTO transactions (date, type, category, account_type, shop, amount) "
                 "VALUES ('2025-05-01', 'Wydatek', 'Jedzenie', 'Karta', 'Stary sklep', 5)")
    conn.commit()
    conn.close()

    migrate.main(["--old-db", str(old), "--user", "migrowany", "--password", "haslo123"])

    from src.core.auth import AuthService
    user_id = AuthService.verify_login("migrowany", "haslo123")
    assert user_id
    db.set_active_user_db(user_id)
    assert [r["shop"] for r in db.fetch_transactions()] == ["Stary sklep"]
