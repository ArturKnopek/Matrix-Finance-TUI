"""
Szyfrowanie danych na dysku (sejf sesji).

Gdy użytkownik włączy „Szyfrowanie danych na dysku”, jego baza istnieje na dysku
WYŁĄCZNIE jako zaszyfrowany plik `data/<id>.db.enc` (AES/Fernet, klucz z hasła PBKDF2).
Po zalogowaniu baza jest odszyfrowywana do pamięci RAM (SQLite in-memory, shared cache),
a co jakiś czas oraz przy wylogowaniu/wyjściu zapisywana z powrotem w postaci zaszyfrowanej.
Odszyfrowana baza nigdy nie trafia na dysk.

Odzyskiwanie po awarii: jeżeli obok pliku .enc leży nowszy niezaszyfrowany plik .db
(np. z czasu przed włączeniem szyfrowania), zostanie on użyty i zaszyfrowany.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

from src.finance.storage import (
    clear_active_user_db,
    set_active_user_db,
    set_active_user_db_uri,
    update_user_fields,
    user_db_path,
)
from src.utils.crypto_utils import decrypt_bytes, encrypt_bytes, write_atomic

ENC_SUFFIX = ".enc"
log = logging.getLogger(__name__)


def encrypted_path(user_id: str) -> Path:
    return Path(str(user_db_path(user_id)) + ENC_SUFFIX)


def is_encrypted(user_id: str) -> bool:
    return encrypted_path(user_id).exists()


def _as_rollback_journal(blob: bytes) -> bytes:
    """
    Bajty 18–19 nagłówka SQLite = wersja zapisu/odczytu (2 = WAL). Obraz bazy w trybie WAL
    nie da się otworzyć w pamięci, więc przełączamy go na klasyczny dziennik (1).
    """
    if len(blob) > 20 and blob[:16] == b"SQLite format 3\x00" and (blob[18] == 2 or blob[19] == 2):
        buf = bytearray(blob)
        buf[18] = buf[19] = 1
        return bytes(buf)
    return blob


def _serialize(conn: sqlite3.Connection) -> bytes:
    if hasattr(conn, "serialize"):
        return _as_rollback_journal(conn.serialize())
    fd, tmp = tempfile.mkstemp(suffix=".db")  # Python < 3.11
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        conn.backup(dst)
        dst.close()
        return _as_rollback_journal(Path(tmp).read_bytes())
    finally:
        Path(tmp).unlink(missing_ok=True)


def _connection_from_bytes(blob: bytes) -> sqlite3.Connection:
    blob = _as_rollback_journal(blob)
    if hasattr(sqlite3.Connection, "deserialize"):
        conn = sqlite3.connect(":memory:")
        conn.deserialize(blob)
        return conn
    fd, tmp = tempfile.mkstemp(suffix=".db")  # Python < 3.11
    os.close(fd)
    Path(tmp).write_bytes(blob)
    disk = sqlite3.connect(tmp)
    mem = sqlite3.connect(":memory:")
    disk.backup(mem)
    disk.close()
    Path(tmp).unlink(missing_ok=True)
    return mem


def _remove_plaintext(user_id: str) -> None:
    base = str(user_db_path(user_id))
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(base + suffix).unlink(missing_ok=True)
        except OSError as e:
            log.warning("Nie udało się usunąć %s: %s", base + suffix, e)


class DataVault:
    """Zaszyfrowana sesja jednego użytkownika."""

    def __init__(self, user_id: str, password: str) -> None:
        self.user_id = user_id
        self._password = password
        self.uri = f"file:mf_{user_id}?mode=memory&cache=shared"
        self._keeper: Optional[sqlite3.Connection] = None

    @property
    def is_open(self) -> bool:
        return self._keeper is not None

    def _load_into_memory(self, source: sqlite3.Connection) -> None:
        self._keeper = sqlite3.connect(self.uri, uri=True)
        source.backup(self._keeper)
        source.close()
        set_active_user_db_uri(self.uri)

    def open(self) -> None:
        """Odszyfrowuje bazę do pamięci i ustawia ją jako aktywną. Złe hasło -> ValueError."""
        enc = encrypted_path(self.user_id)
        plain = user_db_path(self.user_id)
        if plain.exists() and (not enc.exists() or plain.stat().st_mtime > enc.stat().st_mtime):
            log.warning("Znaleziono nowszą niezaszyfrowaną bazę — zostanie zaszyfrowana.")
            self._load_into_memory(sqlite3.connect(str(plain)))
            self.seal()
            _remove_plaintext(self.user_id)
            return
        if not enc.exists():
            raise FileNotFoundError("Brak zaszyfrowanej bazy użytkownika.")
        self._load_into_memory(_connection_from_bytes(decrypt_bytes(enc.read_bytes(), self._password)))

    def seal(self) -> None:
        """Zapisuje aktualny stan (z pamięci) do zaszyfrowanego pliku."""
        if not self._keeper:
            return
        write_atomic(encrypted_path(self.user_id), encrypt_bytes(_serialize(self._keeper), self._password))

    def close(self) -> None:
        """Zapis + zamknięcie sesji (dane znikają z pamięci)."""
        if not self._keeper:
            return
        try:
            self.seal()
        finally:
            self._keeper.close()
            self._keeper = None
            clear_active_user_db()

    def rekey(self, new_password: str) -> None:
        """Zmiana hasła: kolejne zapisy szyfrowane nowym hasłem."""
        self._password = new_password
        self.seal()

    # ------------------------------------------------------------------ włączanie / wyłączanie

    @classmethod
    def enable(cls, user_id: str, password: str) -> "DataVault":
        """Szyfruje bieżącą (plikową) bazę i przełącza sesję na pamięć."""
        plain = user_db_path(user_id)
        vault = cls(user_id, password)
        vault._load_into_memory(sqlite3.connect(str(plain)))
        vault.seal()
        _remove_plaintext(user_id)
        update_user_fields(user_id, encrypt_at_rest=1)
        return vault

    def disable(self) -> None:
        """Zapisuje bazę z powrotem jako zwykły plik i usuwa wersję zaszyfrowaną."""
        if not self._keeper:
            raise RuntimeError("Sesja nie jest otwarta.")
        plain = user_db_path(self.user_id)
        dst = sqlite3.connect(str(plain))
        self._keeper.backup(dst)
        dst.close()
        self._keeper.close()
        self._keeper = None
        encrypted_path(self.user_id).unlink(missing_ok=True)
        update_user_fields(self.user_id, encrypt_at_rest=0)
        set_active_user_db(self.user_id)
