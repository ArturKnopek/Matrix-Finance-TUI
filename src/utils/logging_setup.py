"""
Logowanie do pliku.

Interfejs TUI zajmuje cały terminal, więc komunikaty z `logging` wypisywane na
stderr ginęły. Teraz błędy (WARNING+) zawsze trafiają do ~/.matrix_finance/matrix.log,
a po włączeniu trybu diagnostycznego w Ustawieniach — wszystko (DEBUG) do debug.log.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.utils.paths import data_home

LOG_DIR = data_home()
MAIN_LOG = LOG_DIR / "matrix.log"
DEBUG_LOG = LOG_DIR / "debug.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DEBUG_HANDLER_NAME = "matrix-debug"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(h, "name", "") == "matrix-main" for h in root.handlers):
        handler = RotatingFileHandler(MAIN_LOG, maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.name = "matrix-main"
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)


def apply_debug_logging(enabled: bool) -> Path:
    """Włącza/wyłącza szczegółowe logowanie do debug.log. Zwraca ścieżkę pliku."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    existing = [h for h in root.handlers if getattr(h, "name", "") == _DEBUG_HANDLER_NAME]
    if enabled and not existing:
        handler = RotatingFileHandler(DEBUG_LOG, maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        handler.name = _DEBUG_HANDLER_NAME
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
    elif not enabled:
        for h in existing:
            root.removeHandler(h)
            h.close()
        root.setLevel(logging.INFO)
    return DEBUG_LOG
