"""
Logowanie z kluczem YubiKey — EKSPERYMENTALNE (drugi składnik po haśle).

Mechanizm: HMAC-SHA1 challenge-response (slot 1 lub 2 klucza YubiKey), obsługiwany
przez narzędzie `ykman` (pakiet yubikey-manager). Przygotowanie klucza (jednorazowo):

    ykman otp chalresp --generate --touch 2

Rejestracja zapisuje losowe wyzwanie i skrót SHA-256 odpowiedzi klucza; przy logowaniu
aplikacja wysyła to samo wyzwanie i porównuje skrót. Dodatkowo generowany jest kod
awaryjny (na wypadek zgubienia klucza) — przechowywany wyłącznie jako hash PBKDF2.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import subprocess
from typing import Optional, Protocol

from src.finance.storage import get_user_by_id, update_user_fields


class YubiKeyError(Exception):
    pass


class YubiKeyBackend(Protocol):
    def challenge_response(self, challenge_hex: str, slot: int, timeout: float = 20.0) -> str: ...


class YkmanCliBackend:
    """Komunikacja z kluczem przez `ykman otp calculate <slot> <wyzwanie>`."""

    def __init__(self, executable: Optional[str] = None) -> None:
        self.executable = executable or shutil.which("ykman")

    def available(self) -> bool:
        return bool(self.executable)

    def challenge_response(self, challenge_hex: str, slot: int, timeout: float = 20.0) -> str:
        if not self.executable:
            raise YubiKeyError("Nie znaleziono programu „ykman” (pip install yubikey-manager).")
        try:
            result = subprocess.run([self.executable, "otp", "calculate", str(slot), challenge_hex],
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise YubiKeyError("Nie dotknięto klucza na czas.") from e
        if result.returncode != 0:
            raise YubiKeyError((result.stderr or result.stdout or "Błąd ykman").strip().splitlines()[-1])
        response = result.stdout.strip().split()[-1] if result.stdout.strip() else ""
        if not response:
            raise YubiKeyError("Klucz nie zwrócił odpowiedzi.")
        return response.lower()


_backend: Optional[YubiKeyBackend] = None


def set_backend(backend: Optional[YubiKeyBackend]) -> None:
    """Podmiana backendu (testy, inne sposoby komunikacji)."""
    global _backend
    _backend = backend


def get_backend() -> YubiKeyBackend:
    return _backend or YkmanCliBackend()


def backend_available() -> bool:
    backend = get_backend()
    return bool(getattr(backend, "available", lambda: True)())


def _response_hash(challenge_hex: str, response_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(challenge_hex) + response_hex.lower().encode()).hexdigest()


def new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)


def enroll(user_id: str, slot: int = 2) -> str:
    """Rejestruje klucz (wymaga dotknięcia). Zwraca jednorazowo pokazywany kod awaryjny."""
    from src.core.auth import AuthService

    challenge = os.urandom(32).hex()
    response = get_backend().challenge_response(challenge, slot)
    recovery = new_recovery_code()
    update_user_fields(user_id, yubikey_enabled=1, yubikey_slot=int(slot), yubikey_challenge=challenge,
                       yubikey_response_hash=_response_hash(challenge, response),
                       recovery_hash=AuthService.hash_password(recovery))
    return recovery


def is_enabled(user_row) -> bool:
    try:
        return bool(user_row and int(user_row["yubikey_enabled"] or 0) == 1)
    except (KeyError, IndexError):
        return False


def verify(user_id: str) -> bool:
    """Wysyła zapisane wyzwanie do klucza i porównuje odpowiedź. Rzuca YubiKeyError przy problemach."""
    user = get_user_by_id(user_id)
    if not is_enabled(user):
        return True
    response = get_backend().challenge_response(user["yubikey_challenge"], int(user["yubikey_slot"] or 2))
    return hmac.compare_digest(_response_hash(user["yubikey_challenge"], response),
                               user["yubikey_response_hash"] or "")


def verify_recovery_code(user_id: str, code: str) -> bool:
    from src.core.auth import AuthService

    user = get_user_by_id(user_id)
    if not user or not user["recovery_hash"]:
        return False
    return AuthService.verify_password((code or "").strip().upper(), user["recovery_hash"])


def disable(user_id: str) -> None:
    update_user_fields(user_id, yubikey_enabled=0, yubikey_challenge=None, yubikey_response_hash=None,
                       recovery_hash=None)
