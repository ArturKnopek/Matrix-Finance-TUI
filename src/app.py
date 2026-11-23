import sys
from pathlib import Path

from textual.app import App

from src.screens.login import LoginScreen
from src.screens.main_dashboard import MainDashboard
from src.screens.welcome import WelcomeScreen


class MatrixApp(App):
    TITLE = "Matrix Finance"
    SUB_TITLE = "Budget App"

    # --- FIX DLA PYINSTALLER (Aby widział style w pliku exe) ---
    if getattr(sys, "frozen", False):
        BASE_PATH = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        BASE_PATH = Path(__file__).resolve().parent.parent
    CSS_PATH = str(BASE_PATH / "assets" / "tui_style.tcss")

    # Paleta poleceń Textual zajmowała Ctrl+P (skrót „Pauza” w płatnościach cyklicznych)
    ENABLE_COMMAND_PALETTE = False

    # Klasy breakpointów ustawiane automatycznie na każdym ekranie (patrz tui_style.tcss)
    HORIZONTAL_BREAKPOINTS = [(0, "-w-xs"), (60, "-w-sm"), (100, "-w-md"), (150, "-w-lg")]
    VERTICAL_BREAKPOINTS = [(0, "-h-xs"), (24, "-h-sm"), (32, "-h-md"), (45, "-h-lg")]

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
        self.push_screen("welcome")

    def clear_session(self) -> None:
        self.current_user_id = None
        self.current_username = None
        from src.database import clear_active_user_db

        clear_active_user_db()
