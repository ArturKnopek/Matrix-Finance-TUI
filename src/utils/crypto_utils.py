"""
Szyfrowanie (AES-128-CBC + HMAC-SHA256 w formacie Fernet) z kluczem z hasła (PBKDF2-SHA256).

Format pliku/bajtów: 16 B soli + token Fernet. Ten sam format używa kopia .matrix,
eksport .mfx, szyfrowanie bazy na dysku (.db.enc) i synchronizacja z telefonem.
Bez pakietu `cryptography` używana jest zgodna implementacja z fernet_compat.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

try:  # szybka implementacja (komputer)
    from cryptography.fernet import Fernet, InvalidToken

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # np. telefon bez pakietu cryptography — zgodna implementacja w czystym Pythonie
    from src.utils.fernet_compat import Fernet, InvalidToken  # type: ignore[assignment]

    HAVE_CRYPTOGRAPHY = False

SALT_SIZE = 16
KDF_ITERATIONS = 200_000


def derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 (200 000 iteracji) -> 32 B klucza w base64url (format Fernet)."""
    return base64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                                        KDF_ITERATIONS, dklen=32))


def derive_fernet(password: str, salt: bytes) -> Fernet:
    """Klucz szyfrujący z hasła i soli."""
    return Fernet(derive_key(password, salt))


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
