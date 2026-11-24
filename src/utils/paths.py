"""
Ścieżki aplikacji (wspólne dla Linuksa, macOS i Windows).

    data_home()      – katalog danych: ~/.matrix_finance (Windows: C:\\Users\\<ty>\\.matrix_finance);
                       można go zmienić zmienną środowiskową MATRIX_FINANCE_HOME
                       (np. wersja przenośna na pendrivie albo testy).
    documents_dir()  – folder „Dokumenty” użytkownika; w Windows także przekierowany
                       (np. do OneDrive), odczytywany z systemu.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_home() -> Path:
    custom = os.environ.get("MATRIX_FINANCE_HOME", "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".matrix_finance"


def _windows_documents() -> Path | None:
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_PERSONAL = 5 („Dokumenty”), SHGFP_TYPE_CURRENT = 0 — uwzględnia przekierowanie do OneDrive
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # type: ignore[attr-defined]
            return Path(buf.value)
    except Exception:
        pass
    return None


def documents_dir() -> Path:
    if sys.platform.startswith("win"):
        docs = _windows_documents()
        if docs and docs.exists():
            return docs
    docs = Path.home() / "Documents"
    return docs if docs.exists() else Path.home()
