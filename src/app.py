import logging
import sys
from pathlib import Path
from typing import Optional

from textual.app import App

from src.screens.login import LoginScreen
from src.screens.main_dashboard import MainDashboard
from src.screens.welcome import WelcomeScreen
from src.ui.theme import DEFAULT_THEME, THEMES, all_textual_themes, set_palette, theme_id


class MatrixApp(App):
    TITLE = "Matrix Finance"
    SUB_TITLE = "Budżet domowy i oszczędzanie kopertowe"

    # --- PyInstaller: style w pliku .exe ---
    if getattr(sys, "frozen", False):
        BASE_PATH = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        BASE_PATH = Path(__file__).resolve().parent.parent
    CSS_PATH = str(BASE_PATH / "assets" / "tui_style.tcss")

    # Paleta poleceń Textual zajmowała Ctrl+P (pauza zleceń)
    ENABLE_COMMAND_PALETTE = False

    # Klasy breakpointów ustawiane automatycznie na ekranach (patrz tui_style.tcss)
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
        self.current_user_id: Optional[str] = None
        self.current_username: Optional[str] = None
        self.vault = None  # src.core.vault.DataVault, gdy dane są szyfrowane na dysku
        for theme in all_textual_themes():
            self.register_theme(theme)
        self.apply_theme(self._saved_theme(), save=False)

    @staticmethod
    def _saved_theme() -> str:
        try:
            from src.finance.storage import get_setting

            return get_setting("ui_theme", DEFAULT_THEME)
        except Exception:
            return DEFAULT_THEME

    def apply_theme(self, name: str, save: bool = True) -> None:
        """Przełącza motyw (CSS + kolory rysowane w Pythonie)."""
        name = name if name in THEMES else DEFAULT_THEME
        set_palette(name)
        self.theme = theme_id(name)
        if save:
            from src.finance.storage import set_setting

            set_setting("ui_theme", name)
        refresh = getattr(self.screen, "refresh_theme", None) if self.is_running else None
        if callable(refresh):
            refresh()

    @property
    def animations_enabled(self) -> bool:
        try:
            from src.finance.storage import get_setting

            return get_setting("ui_animations", "1") == "1"
        except Exception:
            return True

    def set_current_user(self, user_id: str, username: str) -> None:
        self.current_user_id = user_id
        self.current_username = username

    def on_ready(self) -> None:
        self.push_screen("welcome")

    def close_vault(self) -> None:
        """Zapisuje i zamyka zaszyfrowaną sesję (dane znikają z pamięci)."""
        if self.vault is not None:
            try:
                self.vault.close()
            except Exception as e:
                logging.error("Błąd zapisu zaszyfrowanej bazy: %s", e)
            self.vault = None

    def clear_session(self) -> None:
        self.close_vault()
        self.current_user_id = None
        self.current_username = None
        from src.finance.storage import clear_active_user_db

        clear_active_user_db()
