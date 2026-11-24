"""Zgodność szyfrowania w czystym Pythonie (telefon) z biblioteką cryptography (komputer)."""
from __future__ import annotations

import base64
import os

import pytest

cryptography = pytest.importorskip("cryptography")
from cryptography.fernet import Fernet as RealFernet  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402

from src.utils import fernet_compat  # noqa: E402
from src.utils.crypto_utils import derive_key  # noqa: E402


def test_aes_matches_fips197_vector():
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    rk = fernet_compat._expand_key(key)
    assert fernet_compat._encrypt_block(plain, rk).hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
    assert fernet_compat._decrypt_block(bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"), rk) == plain


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 31, 32, 100, 1000, 4099])
def test_cbc_matches_cryptography(size):
    key, iv, data = os.urandom(16), os.urandom(16), os.urandom(size)
    mine = fernet_compat.aes_cbc_encrypt(key, iv, data)
    pad = 16 - size % 16
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    assert mine == enc.update(data + bytes([pad]) * pad) + enc.finalize()
    assert fernet_compat.aes_cbc_decrypt(key, iv, mine) == data


@pytest.mark.parametrize("size", [0, 5, 16, 333, 20000])
def test_fernet_tokens_interoperate(size):
    key = RealFernet.generate_key()
    data = os.urandom(size)
    assert RealFernet(key).decrypt(fernet_compat.Fernet(key).encrypt(data)) == data
    assert fernet_compat.Fernet(key).decrypt(RealFernet(key).encrypt(data)) == data


def test_wrong_key_and_tampering_rejected():
    key = RealFernet.generate_key()
    token = RealFernet(key).encrypt(b"tajne dane")
    with pytest.raises(fernet_compat.InvalidToken):
        fernet_compat.Fernet(RealFernet.generate_key()).decrypt(token)
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[30] ^= 1
    with pytest.raises(fernet_compat.InvalidToken):
        fernet_compat.Fernet(key).decrypt(base64.urlsafe_b64encode(bytes(raw)))


def test_kdf_matches_cryptography():
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    assert derive_key("hasło-ąę", salt) == base64.urlsafe_b64encode(kdf.derive("hasło-ąę".encode()))
