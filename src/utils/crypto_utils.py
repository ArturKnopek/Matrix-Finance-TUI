import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _get_fernet(password: str, salt: bytes) -> Fernet:
    """Generuje klucz szyfrujący na podstawie hasła i soli."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))
    return Fernet(key)

def encrypt_file(input_path: str, output_path: str, password: str) -> bool:
    """Szyfruje plik i dodaje na początek sól kryptograficzną."""
    try:
        salt = os.urandom(16)
        fernet = _get_fernet(password, salt)
        with open(input_path, 'rb') as f:
            data = f.read()
        encrypted = fernet.encrypt(data)
        with open(output_path, 'wb') as f:
            f.write(salt + encrypted)
        return True
    except Exception:
        return False

def decrypt_file(input_path: str, output_path: str, password: str) -> bool:
    """Odczytuje sól i deszyfruje zawartość pliku."""
    try:
        with open(input_path, 'rb') as f:
            content = f.read()
        salt = content[:16]
        encrypted = content[16:]
        fernet = _get_fernet(password, salt)
        decrypted = fernet.decrypt(encrypted)
        with open(output_path, 'wb') as f:
            f.write(decrypted)
        return True
    except Exception:
        return False