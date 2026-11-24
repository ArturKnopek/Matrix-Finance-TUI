import sys
import logging
import os
from pathlib import Path

USAGE = """Matrix Finance — budżet domowy i oszczędzanie kopertowe (terminal).

Użycie: python main.py [opcja]
  (bez opcji)    uruchamia program
  --selftest     test instalacji na danych tymczasowych (Twoje dane nie są dotykane);
                 z --pause okno czeka na Enter
  --version      wersja programu
  --help         ta pomoc

Dane: ~/.matrix_finance (zmienna MATRIX_FINANCE_HOME zmienia lokalizację)."""


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


def _pause_if_launcher() -> None:
    """Okno konsoli otwarte przez skrót znika po zakończeniu — daj przeczytać komunikat błędu."""
    if os.environ.get("MATRIX_FINANCE_PAUSE_ON_ERROR") == "1" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nNaciśnij Enter, aby zamknąć okno...")
        except (EOFError, KeyboardInterrupt):
            pass


def main(argv: list | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    _ensure_project_root_on_path()
    if any(a in ("-h", "--help", "/?") for a in args):
        print(USAGE)
        return 0
    if "--version" in args:
        from src.version import APP_NAME, APP_VERSION

        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--selftest" in args:
        from src.selftest import run_selftest

        code = run_selftest()
        if "--pause" in args and sys.stdin and sys.stdin.isatty():  # okno otwarte ze skrótu „Sprawdź instalację”
            try:
                input("\nNaciśnij Enter, aby zamknąć okno...")
            except (EOFError, KeyboardInterrupt):
                pass
        elif code:
            _pause_if_launcher()
        return code
    if args:
        print(f"Nieznana opcja: {' '.join(args)}\n\n{USAGE}")
        return 2

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
        if sys.stdin and sys.stdin.isatty():
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
    code = app.return_code or 0
    if code:
        logging.getLogger(__name__).error("Program zakończył się błędem (kod %s).", code)
        print("\nSzczegóły błędu: ~/.matrix_finance/matrix.log")
        _pause_if_launcher()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
