"""
Zgodna z `cryptography.fernet.Fernet` implementacja w czystym Pythonie (tylko biblioteka standardowa).

Używana automatycznie, gdy pakiet `cryptography` jest niedostępny (np. w aplikacji
na telefon), żeby pliki szyfrowane na komputerze (synchronizacja, eksport .mfx) dało
się odczytać i zapisać. Format tokenu jest identyczny jak w specyfikacji Fernet:

    0x80 | znacznik czasu (8 B) | IV (16 B) | szyfrogram AES-128-CBC (PKCS7) | HMAC-SHA256 (32 B)

zakodowane base64url. Klucz (32 B, base64url): 16 B klucza podpisu + 16 B klucza AES.
Tablice AES (S-box) są wyliczane w kodzie, a nie przepisywane ręcznie.
Testy porównują wyniki z biblioteką `cryptography` w obie strony.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import List


class InvalidToken(Exception):
    """Zły klucz (hasło) albo uszkodzone dane."""


# =============================================================================
# AES-128 (FIPS-197)
# =============================================================================

def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _gmul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _build_sbox() -> List[int]:
    sbox = [0] * 256
    for x in range(256):
        inv = 0
        if x:
            for y in range(1, 256):  # odwrotność w GF(2^8)
                if _gmul(x, y) == 1:
                    inv = y
                    break
        s = inv
        for shift in range(1, 5):  # przekształcenie afiniczne
            s ^= ((inv << shift) | (inv >> (8 - shift))) & 0xFF
        sbox[x] = s ^ 0x63
    return sbox


SBOX = _build_sbox()
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i
MUL = {n: [_gmul(x, n) for x in range(256)] for n in (2, 3, 9, 11, 13, 14)}
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key: bytes) -> List[List[int]]:
    if len(key) != 16:
        raise ValueError("AES-128 wymaga klucza 16 B")
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[b] for b in temp]
            temp[0] ^= RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ temp[j] for j in range(4)])
    return [sum(words[r * 4:(r + 1) * 4], []) for r in range(11)]


def _encrypt_block(block: bytes, rk: List[List[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[0])]
    m2, m3 = MUL[2], MUL[3]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]
        # ShiftRows (stan kolumnowy: indeks = wiersz + 4 * kolumna)
        s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
        if rnd != 10:
            t = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t += [m2[a0] ^ m3[a1] ^ a2 ^ a3, a0 ^ m2[a1] ^ m3[a2] ^ a3,
                      a0 ^ a1 ^ m2[a2] ^ m3[a3], m3[a0] ^ a1 ^ a2 ^ m2[a3]]
            s = t
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def _decrypt_block(block: bytes, rk: List[List[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[10])]
    m9, m11, m13, m14 = MUL[9], MUL[11], MUL[13], MUL[14]
    for rnd in range(9, -1, -1):
        # InvShiftRows
        s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
             s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
        s = [INV_SBOX[b] for b in s]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd != 0:
            t = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t += [m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3], m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3],
                      m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3], m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3]]
            s = t
    return bytes(s)


def aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    rk = _expand_key(key)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        prev = _encrypt_block(bytes(a ^ b for a, b in zip(data[i:i + 16], prev)), rk)
        out += prev
    return bytes(out)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise InvalidToken
    rk = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(block, rk), prev))
        prev = block
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise InvalidToken
    return bytes(out[:-pad])


# =============================================================================
# Fernet
# =============================================================================

class Fernet:
    def __init__(self, key: bytes | str) -> None:
        raw = base64.urlsafe_b64decode(key)
        if len(raw) != 32:
            raise ValueError("Klucz Fernet musi mieć 32 bajty (base64url).")
        self._signing_key, self._encryption_key = raw[:16], raw[16:]

    @staticmethod
    def generate_key() -> bytes:
        return base64.urlsafe_b64encode(os.urandom(32))

    def encrypt(self, data: bytes) -> bytes:
        iv = os.urandom(16)
        basic = b"\x80" + struct.pack(">Q", int(time.time())) + iv + aes_cbc_encrypt(self._encryption_key, iv, data)
        mac = hmac.new(self._signing_key, basic, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(basic + mac)

    def decrypt(self, token: bytes | str) -> bytes:
        try:
            data = base64.urlsafe_b64decode(token)
        except (TypeError, ValueError) as e:
            raise InvalidToken from e
        if len(data) < 1 + 8 + 16 + 16 + 32 or data[0] != 0x80:
            raise InvalidToken
        basic, mac = data[:-32], data[-32:]
        if not hmac.compare_digest(hmac.new(self._signing_key, basic, hashlib.sha256).digest(), mac):
            raise InvalidToken
        return aes_cbc_decrypt(self._encryption_key, basic[9:25], basic[25:])
