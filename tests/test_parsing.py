from datetime import date

from src.utils.parsing import parse_amount, parse_user_date

TODAY = date(2026, 11, 23)


def test_dates():
    assert parse_user_date("", "2026-10", TODAY) == "2026-11-23"
    assert parse_user_date("wczoraj", None, TODAY) == "2026-11-22"
    assert parse_user_date("5", "2026-10", TODAY) == "2026-10-05"
    assert parse_user_date("05.03", "2026-10", TODAY) == "2026-03-05"
    assert parse_user_date("5-3-25", None, TODAY) == "2025-03-05"
    assert parse_user_date("2026-02-28", None, TODAY) == "2026-02-28"
    assert parse_user_date("31", "2026-02", TODAY) is None
    assert parse_user_date("abc", None, TODAY) is None


def test_amounts():
    assert parse_amount("12,50") == 12.5
    assert parse_amount("1 200,50") == 1200.5
    assert parse_amount("10+5*2") == 20.0
    assert parse_amount("(10+5)/3") == 5.0
    assert parse_amount("1/0") is None
    assert parse_amount("__import__('os')") is None
    assert parse_amount("") is None
