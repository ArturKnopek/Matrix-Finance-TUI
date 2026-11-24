"""
Konfiguracja testów: izolujemy katalog domowy, żeby testy nigdy nie dotykały
prawdziwych baz w ~/.matrix_finance.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_HOME = tempfile.mkdtemp(prefix="matrix_finance_tests_")
os.environ["HOME"] = _TEST_HOME
os.environ["USERPROFILE"] = _TEST_HOME  # Windows
os.environ.pop("MATRIX_FINANCE_HOME", None)  # zawsze katalog testowy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def user_db():
    """Świeża baza użytkownika (Karta 1000, Gotówka 200) dla każdego testu."""
    from src import database as db

    db.init_auth_db()
    user_id = uuid.uuid4().hex
    path = db.set_active_user_db(user_id)
    db.init_user_db(path, start_card=1000.0, start_cash=200.0)
    yield db
    db.clear_active_user_db()
