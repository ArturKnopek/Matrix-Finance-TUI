"""
Szyfrowanie (AES-128-CBC + HMAC-SHA256 w formacie Fernet) z kluczem z hasła (PBKDF2-SHA256).

Format pliku/bajtów: 16 B soli + token Fernet. Ten sam format używa kopia .matrix,
eksport .mfx oraz szyfrowanie bazy na dysku (.db.enc).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT_SIZE = 16
KDF_ITERATIONS = 200_000


def derive_fernet(password: str, salt: bytes) -> Fernet:
    """Klucz szyfrujący z hasła i soli."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8"))))


_get_fernet = derive_fernet  # zgodność wsteczna


def encrypt_bytes(data: bytes, password: str, salt: Optional[bytes] = None) -> bytes:
    salt = salt or os.urandom(SALT_SIZE)
    return salt + derive_fernet(password, salt).encrypt(data)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    """Odszyfrowuje; przy złym haśle/uszkodzeniu rzuca ValueError."""
    if len(blob) <= SALT_SIZE:
        raise ValueError("Plik jest za krótki, by był zaszyfrowaną kopią.")
    try:
        return derive_fernet(password, blob[:SALT_SIZE]).decrypt(blob[SALT_SIZE:])
    except InvalidToken as e:
        raise ValueError("Błędne hasło lub uszkodzony plik.") from e


def write_atomic(path: str | Path, data: bytes) -> None:
    """Zapis przez plik tymczasowy + rename (brak „połówkowych” plików przy awarii)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def encrypt_file(input_path: str, output_path: str, password: str) -> bool:
    try:
        write_atomic(output_path, encrypt_bytes(Path(input_path).read_bytes(), password))
        return True
    except Exception:
        return False


def decrypt_file(input_path: str, output_path: str, password: str) -> bool:
    try:
        write_atomic(output_path, decrypt_bytes(Path(input_path).read_bytes(), password))
        return True
    except Exception:
        return False
