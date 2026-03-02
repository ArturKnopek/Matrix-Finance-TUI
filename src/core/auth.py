from __future__ import annotations
import os, hmac, hashlib
from typing import Optional
from src.database import get_user_by_username, create_user as db_create_user

class AuthService:
    ALG = "pbkdf2_sha256"
    ITER = 200_000

    @staticmethod
    def hash_password(password: str) -> str:
        salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, AuthService.ITER)
        return f"{AuthService.ALG}${AuthService.ITER}${salt.hex()}${dk.hex()}"

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        try:
            alg, iters, salt_hex, hash_hex = stored.split("$", 3)
            if alg != AuthService.ALG:
                return False
            iters = int(iters)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False

    @staticmethod
    def create_user(username: str, password: str) -> str:
        pwd_hash = AuthService.hash_password(password)
        ok, msg, user_id = db_create_user(username, pwd_hash)
        if not ok or not user_id:
            raise ValueError(msg or "Nie udało się utworzyć użytkownika.")
        return user_id

    @staticmethod
    def verify_login(username: str, password: str) -> Optional[str]:
        row = get_user_by_username(username)
        if not row or int(row["is_active"] or 0) != 1:
            return None
        if AuthService.verify_password(password, row["password_hash"]):
            return row["id"]
        return None
