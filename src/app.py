import sys
from pathlib import Path
from textual.app import App

from src.screens.login import LoginScreen
from src.screens.welcome import WelcomeScreen
from src.screens.main_dashboard import MainDashboard


class MatrixApp(App):
    TITLE = "Matrix Finance"
    SUB_TITLE = "Budget App"

    # --- FIX DLA PYINSTALLER (Aby widział style w pliku exe) ---
    if getattr(sys, 'frozen', False):
        # Jeśli uruchamiamy jako skompilowany EXE
        BASE_PATH = Path(sys._MEIPASS)
    else:
        # Jeśli uruchamiamy normalnie z Pythona
        BASE_PATH = Path(__file__).resolve().parent.parent

    # Ścieżka do stylów
    CSS_PATH = str(BASE_PATH / "assets" / "tui_style.tcss")
    # -----------------------------------------------------------

    SCREENS = {
        "welcome": WelcomeScreen,
        "login": LoginScreen,
        "main_dashboard": MainDashboard,
    }

    def __init__(self, *args, app_config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.app_config = app_config or {}
        self.current_user_id: str | None = None
        self.current_username: str | None = None

    def set_current_user(self, user_id: str, username: str) -> None:
        self.current_user_id = user_id
        self.current_username = username

    def on_ready(self) -> None:
        # Pierwszy ekran -> push_screen (stos jest pusty)
        self.push_screen("welcome")

    def clear_session(self) -> None:
        self.current_user_id = None
        self.current_username = None

        # ważne: odpinamy bazę użytkownika (wracamy do guest)
        from src.database import clear_active_user_db
        clear_active_user_db()