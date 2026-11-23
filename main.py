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
    """Komunikaty startowe na konsolę; w trakcie działania TUI błędy trafiają do pliku."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        from src.utils.logging_setup import setup_logging

        setup_logging()
    except Exception as e:  # logowanie nie może zablokować startu
        logging.warning(f"Nie udało się skonfigurować logów w pliku: {e}")


def main() -> int:
    _ensure_project_root_on_path()
    _setup_logging()

    # Importy po ustawieniu sys.path (bezpieczniej)
    from src.finance.storage import init_auth_db
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

    try:
        from src.finance.storage import get_setting
        from src.utils.logging_setup import apply_debug_logging

        if get_setting("dev_mode", "0") == "1":
            apply_debug_logging(True)
    except Exception:
        pass

    logging.info(">>> [BOOT] Uruchamianie interfejsu...")
    # w trakcie działania TUI nie piszemy na konsolę (rozjeżdżałoby to ekran)
    for handler in list(logging.getLogger().handlers):
        if type(handler) is logging.StreamHandler:
            logging.getLogger().removeHandler(handler)

    app = MatrixApp()
    try:
        app.run()
    finally:
        app.close_vault()  # zaszyfrowana baza zawsze zapisana, także po błędzie
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
