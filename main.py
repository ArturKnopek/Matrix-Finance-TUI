import sys
import logging
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    """
    Upewnia się, że katalog projektu (tam gdzie jest main.py) jest na sys.path.
    Dzięki temu importy typu 'from src...' zadziałają niezależnie od CWD.
    """
    project_root = Path(__file__).resolve().parent
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )


def main() -> int:
    _ensure_project_root_on_path()
    _setup_logging()

    # Importy po ustawieniu sys.path (bezpieczniej)
    from src.database import init_auth_db
    from src.app import MatrixApp

    logging.info(">>> [BOOT] Sprawdzanie spójności bazy danych...")

    try:
        init_auth_db()
        logging.info(">>> [BOOT] Baza danych zweryfikowana pomyślnie.")
    except Exception as e:
        logging.error("\n!!! BŁĄD KRYTYCZNY BAZY DANYCH !!!")
        logging.error(f"Nie udało się utworzyć tabel: {e}\n")

        # Pauza tylko jeśli uruchomione w interaktywnym terminalu
        if sys.stdin.isatty():
            input("Naciśnij Enter, aby zamknąć program...")

        return 1

    logging.info(">>> [BOOT] Uruchamianie interfejsu...")
    app = MatrixApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
