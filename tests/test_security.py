"""Szyfrowanie bazy na dysku oraz (eksperymentalne) logowanie kluczem YubiKey."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from src.core import vault, yubikey
from src.core.auth import AuthService
from src.finance import ledger, storage


def _make_user(name: str = "szyfr") -> str:
    storage.init_auth_db()
    uid = AuthService.create_user(name, "haslo123")
    storage.init_user_db(storage.set_active_user_db(uid), start_card=100)
    return uid


def test_vault_keeps_no_plaintext_on_disk(user_db):
    uid = _make_user()
    ledger.add_transaction("2026-01-02", "Wydatek", "Jedzenie", "Karta", "Tajny sklep", 10, "", True)
    v = vault.DataVault.enable(uid, "haslo123")
    plain = storage.user_db_path(uid)
    assert not plain.exists() and vault.is_encrypted(uid)
    assert b"Tajny sklep" not in vault.encrypted_path(uid).read_bytes()

    # praca w sesji (baza w pamięci)
    ledger.add_transaction("2026-01-03", "Wydatek", "Jedzenie", "Karta", "W sesji", 5, "", True)
    assert not plain.exists()
    v.close()

    v2 = vault.DataVault(uid, "haslo123")
    v2.open()
    assert {r["shop"] for r in ledger.fetch_transactions()} == {"Tajny sklep", "W sesji"}
    assert storage.get_user_by_id(uid)["encrypt_at_rest"] == 1
    v2.close()

    with pytest.raises(ValueError):
        vault.DataVault(uid, "zle-haslo").open()


def test_vault_rekey_and_disable(user_db):
    uid = _make_user("rekey")
    v = vault.DataVault.enable(uid, "haslo123")
    v.rekey("nowehaslo1")
    v.close()
    with pytest.raises(ValueError):
        vault.DataVault(uid, "haslo123").open()
    v2 = vault.DataVault(uid, "nowehaslo1")
    v2.open()
    v2.disable()
    assert storage.user_db_path(uid).exists() and not vault.is_encrypted(uid)
    assert storage.get_active_user_db() == str(storage.user_db_path(uid))


class FakeKey:
    """Udaje klucz YubiKey: HMAC-SHA1 z sekretem zapisanym w slocie."""

    def __init__(self, secret: bytes = b"sekret-klucza") -> None:
        self.secret = secret
        self.calls = 0

    def challenge_response(self, challenge_hex: str, slot: int, timeout: float = 20.0) -> str:
        self.calls += 1
        return hmac.new(self.secret, bytes.fromhex(challenge_hex), hashlib.sha1).hexdigest()


def test_yubikey_enroll_verify_and_recovery(user_db):
    uid = _make_user("yubi")
    key = FakeKey()
    yubikey.set_backend(key)
    try:
        recovery = yubikey.enroll(uid, slot=2)
        assert yubikey.is_enabled(storage.get_user_by_id(uid))
        assert yubikey.verify(uid)
        yubikey.set_backend(FakeKey(b"inny-klucz"))
        assert not yubikey.verify(uid)
        assert yubikey.verify_recovery_code(uid, recovery.lower())
        assert not yubikey.verify_recovery_code(uid, "AAAA-BBBB-CCCC-DDDD")
        yubikey.disable(uid)
        assert yubikey.verify(uid)  # wyłączony -> brak wymogu
    finally:
        yubikey.set_backend(None)


def test_ykman_missing_gives_clear_error(user_db):
    backend = yubikey.YkmanCliBackend(executable=None)
    backend.executable = None
    with pytest.raises(yubikey.YubiKeyError):
        backend.challenge_response("00", 2)


def test_delete_user_removes_encrypted_file(user_db):
    uid = _make_user("usun")
    vault.DataVault.enable(uid, "haslo123").close()
    assert vault.is_encrypted(uid)
    storage.delete_user(uid)
    assert not Path(str(storage.user_db_path(uid)) + ".enc").exists()
