from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, ContentSwitcher, DataTable, Input, Label, Select

from src.database import (
    add_account,
    add_category,
    add_piggy_bank,
    add_recurring,
    add_transaction,
    archive_month,
    check_due_payments_count,
    delete_category,
    delete_piggy_bank,
    delete_recurring,
    delete_transaction,
    get_active_month_str,
    get_category_by_id,
    get_piggy_bank_by_id,
    get_recurring_by_id,
    get_setting,
    get_transaction_by_id,
    process_due_payments,
    reset_user_db_hard,
    set_account_balance,
    set_active_month_str,
    set_setting,
    sync_active_month,
    toggle_recurring_pause,
    update_category,
    update_piggy_bank,
    update_piggy_bank_balance,
    update_recurring,
    update_transaction,
)
from src.screens.modal_screen import (
    ChangePasswordModal,
    ConfirmationModal,
    DeleteUserModal,
    ExportBackupModal,
    HelpModal,
)
from src.utils.parsing import parse_amount
from src.utils.ui_tools import money
from src.views.categories_view import CategoriesView
from src.views.category_form_view import CategoryFormView
from src.views.dashboard_view import DashboardView
from src.views.piggy_bank_form_view import PiggyBankFormView
from src.views.piggy_bank_op_view import PiggyBankOperationView
from src.views.piggy_bank_view import PiggyBankView
from src.views.recurring_form_view import RecurringFormView
from src.views.recurring_view import RecurringView
from src.views.reports_view import ReportsView
from src.views.settings_view import SettingsView
from src.views.transaction_form_view import TransactionFormView
from src.views.transactions_view import TransactionsView

APP_VERSION = "1.1"

# (id przycisku menu, id widoku, etykieta, tytuł nagłówka)
MENU = [
    ("nav-pulpit", "view-pulpit", "PULPIT", "PULPIT"),
    ("nav-tranzakcje", "view-tranzakcje", "TRANSAKCJE", "TRANSAKCJE"),
    ("nav-kategorie", "view-kategorie", "KATEGORIE", "KATEGORIE I BUDŻET"),
    ("nav-skarbonki", "view-skarbonki", "SKARBONKI", "CELE OSZCZĘDNOŚCIOWE"),
    ("nav-cykliczne", "view-cykliczne", "CYKLICZNE", "PŁATNOŚCI CYKLICZNE"),
    ("nav-raporty", "view-raporty", "RAPORTY", "RAPORTY"),
    ("nav-ustawienia", "view-ustawienia", "USTAWIENIA", "USTAWIENIA"),
]
MAP_BTN_TO_VIEW = {btn: view for btn, view, _, _ in MENU}
VIEW_TITLES = {view: title for _, view, _, title in MENU}

# formularz -> sekcja menu, do której należy
FORM_PARENT = {
    "view-nowa-tranzakcja": "view-tranzakcje",
    "view-nowa-kategoria": "view-kategorie",
    "view-nowa-skarbonka": "view-skarbonki",
    "view-op-skarbonka": "view-skarbonki",
    "view-nowe-cykliczne": "view-cykliczne",
}
FORM_VIEWS = set(FORM_PARENT)

# Stopka: (id, klawisz, pełna etykieta, krótka etykieta)
FooterSpec = tuple[str, str, str, str]
SAVE_CANCEL: list[FooterSpec] = [
    ("ft-save", "^S", "ZAPISZ", "ZAPISZ"),
    ("ft-cancel", "ESC", "ANULUJ", "ANUL."),
]
FOOTER_SPECS: dict[str, list[FooterSpec]] = {
    "view-pulpit": [
        ("ft-new", "^N", "SZYBKA TRANSAKCJA", "NOWA"),
        ("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW."),
    ],
    "view-tranzakcje": [
        ("ft-new", "^N", "NOWA", "NOWA"),
        ("ft-edit", "^E", "EDYTUJ", "EDYT."),
        ("ft-delete", "^D", "USUŃ", "USUŃ"),
        ("ft-search", "/", "SZUKAJ", "SZUK."),
        ("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW."),
    ],
    "view-kategorie": [
        ("ft-cat-new", "^N", "NOWA", "NOWA"),
        ("ft-cat-edit", "^E", "EDYTUJ", "EDYT."),
        ("ft-cat-delete", "^D", "USUŃ", "USUŃ"),
        ("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW."),
    ],
    "view-skarbonki": [
        ("ft-pig-new", "^N", "NOWY", "NOWY"),
        ("ft-pig-edit", "^E", "EDYTUJ", "EDYT."),
        ("ft-pig-delete", "^D", "USUŃ", "USUŃ"),
        ("ft-pig-deposit", "+", "WPŁAĆ", "WPŁ."),
        ("ft-pig-withdraw", "-", "WYPŁAĆ", "WYP."),
        ("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW."),
    ],
    "view-cykliczne": [
        ("ft-rec-new", "^N", "NOWA", "NOWA"),
        ("ft-rec-edit", "^E", "EDYTUJ", "EDYT."),
        ("ft-rec-delete", "^D", "USUŃ", "USUŃ"),
        ("ft-rec-pause", "^P", "PAUZA / WZNÓW", "PAUZA"),
        ("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW."),
    ],
    "view-raporty": [("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW.")],
    "view-ustawienia": [("ft-refresh", "^R", "ODŚWIEŻ", "ODŚW.")],
    "view-nowa-tranzakcja": SAVE_CANCEL,
    "view-nowa-kategoria": SAVE_CANCEL,
    "view-nowa-skarbonka": SAVE_CANCEL,
    "view-nowe-cykliczne": SAVE_CANCEL,
    "view-op-skarbonka": [("ft-pig-confirm", "^S", "ZATWIERDŹ", "OK"), ("ft-cancel", "ESC", "ANULUJ", "ANUL.")],
}
STATIC_FOOTER: list[FooterSpec] = [
    ("ft-help", "F1", "POMOC", "POMOC"),
    ("ft-logout", "^L", "WYLOGUJ", "WYL."),
    ("ft-exit", "^Q", "WYJŚCIE", "WYJ."),
]
# Kolejność przycisków w stopce (wspólna dla wszystkich widoków)
ALL_DYNAMIC_IDS: list[str] = [
    "ft-new", "ft-cat-new", "ft-pig-new", "ft-rec-new",
    "ft-edit", "ft-cat-edit", "ft-pig-edit", "ft-rec-edit",
    "ft-delete", "ft-cat-delete", "ft-pig-delete", "ft-rec-delete",
    "ft-pig-deposit", "ft-pig-withdraw", "ft-rec-pause", "ft-search",
    "ft-save", "ft-pig-confirm", "ft-cancel", "ft-refresh",
]
assert set(ALL_DYNAMIC_IDS) == {spec[0] for specs in FOOTER_SPECS.values() for spec in specs}

COMPACT_WIDTH = 100  # poniżej tej szerokości menu boczne chowa się automatycznie


def footer_label(key: str, text: str, mode: str = "full") -> Text:
    """Etykieta przycisku stopki: podświetlony klawisz + tekst (mode: full | short | key)."""
    label = Text()
    label.append(key, style="bold #000000 on #00FF41")
    if mode != "key" and text:
        label.append(f" {text}")
    return label


def _spec_text(spec: FooterSpec, mode: str) -> str:
    return spec[2] if mode == "full" else spec[3]


def footer_width(specs: list[FooterSpec], mode: str) -> int:
    # line-pad przycisku (1 + 1) + margin-right 1
    return sum(footer_label(spec[1], _spec_text(spec, mode), mode).cell_len + 3 for spec in specs)


# Kolejne stopnie kompresji stopki: (tryb przycisków widoku, tryb przycisków stałych)
FOOTER_LEVELS = [("full", "full"), ("full", "short"), ("full", "key"), ("short", "key"), ("key", "key")]


class FooterBar(Horizontal):
    """Stopka, która po każdej zmianie swojej szerokości dopasowuje etykiety przycisków."""

    def on_resize(self, event: events.Resize) -> None:
        fit = getattr(self.screen, "_fit_footer", None)
        if callable(fit):
            fit()


class MainDashboard(Screen):
    """Główny ekran aplikacji: menu, nagłówek, przełączane widoki i stopka ze skrótami."""

    BINDINGS = [
        *[Binding(str(i), f"go('{view}')", label, show=False) for i, (_, view, label, _) in enumerate(MENU, 1)],
        Binding("tab", "nav_next", "Następny", show=False),
        Binding("shift+tab", "nav_prev", "Poprzedni", show=False),
        Binding("down", "nav_down", "W dół", show=False),
        Binding("up", "nav_up", "W górę", show=False),
        Binding("enter", "nav_enter", "Wejdź", show=False),
        Binding("escape", "nav_back", "Wstecz", show=False),
        Binding("f1", "help", "Pomoc", show=False),
        Binding("f2", "toggle_sidebar", "Menu", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Menu", show=False),
        Binding("ctrl+r", "refresh_all", "Odśwież", show=False),
        Binding("ctrl+l", "logout", "Wyloguj", show=False),
        Binding("ctrl+q", "exit_app", "Wyjście", show=False),
        Binding("ctrl+n", "ctx('new')", "Nowa", show=False),
        Binding("ctrl+e", "ctx('edit')", "Edytuj", show=False),
        Binding("ctrl+d", "ctx('delete')", "Usuń", show=False),
        Binding("ctrl+p", "ctx('pause')", "Pauza", show=False),
        Binding("ctrl+s", "ctx('save')", "Zapisz", show=False),
        Binding("plus", "ctx('deposit')", "Wpłać", show=False),
        Binding("minus", "ctx('withdraw')", "Wypłać", show=False),
    ]

    # zgodność wsteczna
    MAP_BTN_TO_VIEW = MAP_BTN_TO_VIEW
    MENU_ORDER = [btn for btn, _, _, _ in MENU]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._menu_override: Optional[bool] = None  # None = automatycznie wg szerokości
        self._menu_peek = False  # menu chwilowo otwarte z klawiatury (ESC) w trybie kompaktowym
        self._footer_view = "view-pulpit"
        self._form_return: dict[str, str] = {}
        self._session_user: Optional[str] = None

    # ================================================================ COMPOSE

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar"):
            yield Label("MATRIX FINANCE", id="app-title")
            yield Label(f"v{APP_VERSION}", id="app-version")
            for i, (btn_id, _, label, _) in enumerate(MENU, 1):
                yield Button(f"{i}  {label}", id=btn_id, classes="sidebar-btn")
            yield Label("", classes="spacer")
            yield Label("F2 ukryj/pokaż\nF1 pomoc", id="sidebar-hint")

        with Vertical(id="right-panel"):
            with Horizontal(id="header"):
                yield Label(">>> PULPIT", id="header-title")
                yield Label("", id="header-nav")
                yield Label("", id="header-clock")

            with ContentSwitcher(initial="view-pulpit", id="content-frame"):
                yield DashboardView(id="view-pulpit")
                yield TransactionsView(id="view-tranzakcje")
                yield TransactionFormView(id="view-nowa-tranzakcja")
                yield CategoriesView(id="view-kategorie")
                yield CategoryFormView(id="view-nowa-kategoria")
                yield PiggyBankView(id="view-skarbonki")
                yield PiggyBankFormView(id="view-nowa-skarbonka")
                yield PiggyBankOperationView(id="view-op-skarbonka")
                yield RecurringView(id="view-cykliczne")
                yield RecurringFormView(id="view-nowe-cykliczne")
                yield ReportsView(id="view-raporty")
                yield SettingsView(id="view-ustawienia")

        with FooterBar(id="footer"):
            with Horizontal(id="footer-dynamic"):
                for btn_id in ALL_DYNAMIC_IDS:
                    yield Button("", id=btn_id, classes="footer-btn dynamic")
            yield Label("", classes="footer-spacer")
            with Horizontal(id="footer-static"):
                for btn_id, key, text, _ in STATIC_FOOTER:
                    yield Button(footer_label(key, text), id=btn_id, classes="footer-btn static")

    async def on_mount(self) -> None:
        if not self._ensure_logged_in():
            return
        sync_active_month()
        self._session_user = getattr(self.app, "current_user_id", None)
        self.update_clock()
        self.set_interval(1, self.update_clock)
        self._set_active_sidebar("nav-pulpit")
        self.update_footer("view-pulpit")
        self.call_after_refresh(self._apply_responsive)
        self.call_after_refresh(self._focus_first_menu_button)
        self.call_later(self._check_due_payments)

    def on_screen_resume(self) -> None:
        if not self._ensure_logged_in():
            return
        user = getattr(self.app, "current_user_id", None)
        if user != self._session_user:
            # nowy użytkownik po wylogowaniu -> zaczynamy od pulpitu
            self._session_user = user
            sync_active_month()
            self._switch_to("view-pulpit")
            self.call_later(self._check_due_payments)
        self.call_later(self._refresh_all_views)
        self.call_after_refresh(self._apply_responsive)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive()

    # ============================================================ RESPONSYWNOŚĆ

    def _is_compact(self) -> bool:
        if self._menu_override is not None:
            return not self._menu_override
        if self._menu_peek:
            return False
        return self.size.width < COMPACT_WIDTH

    def _apply_responsive(self) -> None:
        self.set_class(self._is_compact(), "-compact")
        self.update_clock()
        self._update_header_nav()
        self.call_after_refresh(self._fit_footer)

    def action_toggle_sidebar(self) -> None:
        currently_visible = not self._is_compact()
        self._menu_peek = False
        auto_visible = self.size.width >= COMPACT_WIDTH
        target = not currently_visible
        self._menu_override = None if target == auto_visible else target
        self._apply_responsive()
        if target:
            self._focus_active_menu_button()

    def _close_menu_peek(self) -> None:
        if self._menu_peek:
            self._menu_peek = False
            self._apply_responsive()

    def _update_header_nav(self) -> None:
        """W trybie kompaktowym (bez menu) nagłówek pokazuje numery zakładek."""
        try:
            active = self._section_of(self._current_view())
            text = Text()
            for i, (_, view, _, _) in enumerate(MENU, 1):
                style = "bold #000000 on #00FF41" if view == active else "#00AA2B"
                text.append(f" {i} ", style=style)
            text.append("  F2 menu", style="#555555")
            self.query_one("#header-nav", Label).update(text)
        except Exception:
            pass

    def update_clock(self) -> None:
        try:
            now = datetime.now()
            user = getattr(self.app, "current_username", "") or ""
            if self.size.width >= 110:
                text = f"{user} · {now:%Y-%m-%d %H:%M:%S}" if user else f"{now:%Y-%m-%d %H:%M:%S}"
            elif self.size.width >= 70:
                text = f"{now:%d.%m %H:%M:%S}"
            else:
                text = f"{now:%H:%M}"
            self.query_one("#header-clock", Label).update(text)
        except Exception:
            pass

    # ================================================================= STOPKA

    def update_footer(self, view_name: str) -> None:
        """Pokazuje przyciski stopki właściwe dla widoku (bez przebudowy DOM)."""
        self._footer_view = view_name
        visible = {spec[0] for spec in FOOTER_SPECS.get(view_name, [])}
        for btn_id in ALL_DYNAMIC_IDS:
            try:
                self.query_one(f"#{btn_id}", Button).display = btn_id in visible
            except Exception:
                pass
        self._fit_footer()

    def _fit_footer(self) -> None:
        """Dobiera długość etykiet stopki do szerokości okna (pełne -> krótkie -> same klawisze)."""
        try:
            available = self.query_one("#footer").size.width
        except Exception:
            return
        if available <= 0:
            return
        specs = FOOTER_SPECS.get(self._footer_view, [])
        dyn_mode, static_mode = FOOTER_LEVELS[-1]
        for d_mode, s_mode in FOOTER_LEVELS:
            if footer_width(specs, d_mode) + footer_width(STATIC_FOOTER, s_mode) <= available:
                dyn_mode, static_mode = d_mode, s_mode
                break
        changed = False
        for spec, mode in [(sp, dyn_mode) for sp in specs] + [(sp, static_mode) for sp in STATIC_FOOTER]:
            btn = self.query_one(f"#{spec[0]}", Button)
            label = footer_label(spec[1], _spec_text(spec, mode), mode)
            if btn.label.plain != label.plain:
                btn.label = label
                btn.refresh(layout=True)  # zmiana etykiety nie przelicza szerokości automatycznie
                changed = True
        if changed:
            self.query_one("#footer").refresh(layout=True)

    # =============================================================== NAWIGACJA

    def _current_view(self) -> str:
        return self.query_one("#content-frame", ContentSwitcher).current or "view-pulpit"

    @staticmethod
    def _section_of(view: str) -> str:
        return FORM_PARENT.get(view, view)

    def _get_active_view(self) -> Optional[Widget]:
        try:
            return self.query_one(f"#{self._current_view()}")
        except Exception:
            return None

    @staticmethod
    def _is_hidden_widget(widget: Widget) -> bool:
        node: Optional[Widget] = widget
        while node is not None and isinstance(node, Widget):
            if not node.display or not node.visible:
                return True
            node = node.parent  # type: ignore[assignment]
        return False

    def _get_menu_buttons(self) -> list[Button]:
        buttons = []
        for btn_id, _, _, _ in MENU:
            try:
                btn = self.query_one(f"#{btn_id}", Button)
            except Exception:
                continue
            if not self._is_hidden_widget(btn) and not btn.disabled:
                buttons.append(btn)
        return buttons

    def _focused_is_menu_button(self) -> bool:
        return isinstance(self.focused, Button) and self.focused.has_class("sidebar-btn")

    def _focus_first_menu_button(self) -> None:
        self._focus_active_menu_button()

    def _focus_active_menu_button(self) -> None:
        section = self._section_of(self._current_view())
        for btn in self._get_menu_buttons():
            if MAP_BTN_TO_VIEW.get(btn.id or "") == section:
                btn.focus()
                return
        buttons = self._get_menu_buttons()
        if buttons:
            buttons[0].focus()

    def _get_focusable_in_active_view(self) -> list[Widget]:
        view = self._get_active_view()
        if view is None:
            return []
        out = []
        for widget in view.walk_children(Widget):
            if widget.focusable and not self._is_hidden_widget(widget):
                out.append(widget)
        return out

    def _focus_current_content_primary(self) -> None:
        """
        Fokus po wejściu do sekcji:
        - widoki z tabelą -> tabela,
        - formularze (nowa/edycja) -> pierwsze pole,
        - pozostałe (pulpit, raporty, ustawienia) -> sam widok: cyfry 1–7 dalej przełączają
          zakładki, ↑/↓ przewijają, Tab wchodzi w pola.
        """
        view = self._get_active_view()
        if view is None:
            return
        focus_table = getattr(view, "focus_table", None)
        if callable(focus_table):
            focus_table()
            return
        if self._current_view() in FORM_VIEWS:
            for widget in self._get_focusable_in_active_view():
                if isinstance(widget, (Input, Select, Checkbox, Button)):
                    widget.focus()
                    return
        if view.focusable:
            view.focus()

    def _move_focus(self, items: list[Widget], step: int) -> None:
        if not items:
            return
        current = self.focused
        if current not in items:
            items[0 if step > 0 else -1].focus()
            return
        items[(items.index(current) + step) % len(items)].focus()

    def action_nav_next(self) -> None:
        if self._focused_is_menu_button() or self.focused is None:
            self._move_focus(self._get_menu_buttons(), +1)  # type: ignore[arg-type]
        else:
            self._move_focus(self._get_focusable_in_active_view(), +1)

    def action_nav_prev(self) -> None:
        if self._focused_is_menu_button() or self.focused is None:
            self._move_focus(self._get_menu_buttons(), -1)  # type: ignore[arg-type]
        else:
            self._move_focus(self._get_focusable_in_active_view(), -1)

    def action_nav_down(self) -> None:
        self._nav_vertical(+1)

    def action_nav_up(self) -> None:
        self._nav_vertical(-1)

    def _nav_vertical(self, step: int) -> None:
        """↑/↓: w menu – kolejna pozycja; w formularzu – kolejne pole; w pulpicie – przewijanie."""
        if self._focused_is_menu_button():
            self._move_focus(self._get_menu_buttons(), step)  # type: ignore[arg-type]
            return
        focused = self.focused
        if isinstance(focused, (Input, Checkbox, Button)):
            self._move_focus(self._get_focusable_in_active_view(), step)
            return
        view = self._get_active_view()
        if view is not None and hasattr(view, "scroll_relative"):
            view.scroll_relative(y=step * 3, animate=False)

    def action_nav_enter(self) -> None:
        if self.focused is None:
            self._focus_active_menu_button()

    def action_nav_back(self) -> None:
        """ESC: anuluj formularz; w innym wypadku przejdź do menu (w trybie kompaktowym je pokaż)."""
        if self._current_view() in FORM_VIEWS:
            self.run_worker(self._handle_action("ft-cancel"), exclusive=True)
            return
        if self._is_compact():
            self._menu_peek = True
            self._apply_responsive()
            self.call_after_refresh(self._focus_active_menu_button)
            return
        if self._focused_is_menu_button():
            self._close_menu_peek()
            self.call_after_refresh(self._focus_current_content_primary)
            return
        self._focus_active_menu_button()

    def action_help(self) -> None:
        self.app.push_screen(HelpModal())

    def _set_header(self, text: str) -> None:
        self.query_one("#header-title", Label).update(f">>> {text}")

    def _set_active_sidebar(self, btn_id: str) -> None:
        for b_id, _, _, _ in MENU:
            try:
                self.query_one(f"#{b_id}", Button).set_class(b_id == btn_id, "active")
            except Exception:
                pass

    def _switch_to(self, view_name: str, header: Optional[str] = None) -> None:
        self.query_one("#content-frame", ContentSwitcher).current = view_name
        section = self._section_of(view_name)
        btn_id = next((b for b, v, _, _ in MENU if v == section), None)
        if btn_id:
            self._set_active_sidebar(btn_id)
        self._set_header(header or VIEW_TITLES.get(view_name, view_name.upper()))
        self.update_footer(view_name)
        self._update_header_nav()

    async def _go_view(self, view_name: str, header: Optional[str] = None) -> None:
        self._switch_to(view_name, header)

    async def action_go(self, view_name: str) -> None:
        btn_id = next((b for b, v, _, _ in MENU if v == view_name), None)
        if btn_id:
            self._trigger_sidebar_button(btn_id)

    def _trigger_sidebar_button(self, btn_id: str, focus_content: bool = True) -> None:
        target_view = MAP_BTN_TO_VIEW.get(btn_id)
        if not target_view:
            return
        self._menu_peek = False
        self._switch_to(target_view)
        self._safe_load(f"#{target_view}")
        self._apply_responsive()
        if focus_content:
            self.call_after_refresh(self._focus_current_content_primary)

    # ================================================================== DANE

    def _safe_load(self, view_css_id: str) -> None:
        try:
            view = self.query_one(view_css_id)
            if hasattr(view, "load_data"):
                view.load_data()
        except Exception as e:
            logging.exception(f"Błąd ładowania widoku {view_css_id}: {e}")

    def _refresh_all_views(self) -> None:
        for _, view, _, _ in MENU:
            self._safe_load(f"#{view}")

    _refresh_after_login = _refresh_all_views

    def _ensure_logged_in(self) -> bool:
        if not getattr(self.app, "current_user_id", None):
            self.notify("Sesja wygasła.", severity="warning")
            if hasattr(self.app, "clear_session"):
                self.app.clear_session()
            self.app.switch_screen("login")
            return False
        return True

    def _check_due_payments(self) -> None:
        try:
            due_count = check_due_payments_count()
        except Exception as e:
            logging.exception(f"Błąd sprawdzania płatności cyklicznych: {e}")
            return
        if due_count <= 0:
            return

        def on_answer(result) -> None:
            confirmed, _ = result if result else (False, False)
            if not confirmed:
                return
            processed = process_due_payments()
            self.notify(f"Zaksięgowano {processed} zaległych płatności cyklicznych.", severity="information")
            self._refresh_all_views()

        self.app.push_screen(
            ConfirmationModal(f"Znaleziono zaległe płatności cykliczne: {due_count}.\nZaksięgować je teraz?",
                              show_checkbox=False),
            on_answer,
        )

    @staticmethod
    def _code(prefix: str, x) -> str:
        return f"{prefix}{int(x):06d}" if x else f"{prefix}------"

    def _tx_code_from_id(self, x) -> str:
        return self._code("TX", x)

    def _ct_code_from_id(self, x) -> str:
        return self._code("CT", x)

    def _pb_code_from_id(self, x) -> str:
        return self._code("PB", x)

    def _rr_code_from_id(self, x) -> str:
        return self._code("RR", x)

    # ======================================================= ZDARZENIA / AKCJE

    def on_input_submitted(self, event: Input.Submitted) -> None:
        view = self._current_view()
        if view in FORM_VIEWS:
            btn_id = "ft-pig-confirm" if view == "view-op-skarbonka" else "ft-save"
            self.run_worker(self._handle_action(btn_id), exclusive=True)
        elif view == "view-tranzakcje" and event.input.id == "trans-search":
            self.query_one("#view-tranzakcje", TransactionsView).focus_table()
        elif view == "view-ustawienia":
            target = {
                "set-year": "btn-set-month",
                "set-bal-value": "btn-set-balance",
                "set-new-account": "btn-add-account",
                "set-new-account-balance": "btn-add-account",
            }.get(event.input.id or "")
            if target:
                self.run_worker(self._handle_action(target), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        edit_action = self._ctx_map("edit")
        if edit_action:
            self.run_worker(self._handle_action(edit_action), exclusive=True)

    def action_exit_app(self) -> None:
        self.app.exit()

    def action_logout(self) -> None:
        self.run_worker(self._handle_action("ft-logout"), exclusive=True)

    def action_refresh_all(self) -> None:
        self.run_worker(self._handle_action("ft-refresh"), exclusive=True)

    def action_ctx(self, action: str) -> None:
        btn_id = self._ctx_map(action)
        if btn_id:
            self.run_worker(self._handle_action(btn_id), exclusive=True)

    # zgodność wsteczna ze starymi nazwami akcji
    def action_ctx_new(self) -> None:
        self.action_ctx("new")

    def action_ctx_edit(self) -> None:
        self.action_ctx("edit")

    def action_ctx_delete(self) -> None:
        self.action_ctx("delete")

    def action_ctx_pause(self) -> None:
        self.action_ctx("pause")

    def action_ctx_save(self) -> None:
        self.action_ctx("save")

    def _ctx_map(self, action: str) -> str:
        v = self._current_view()
        if action == "save":
            if v == "view-op-skarbonka":
                return "ft-pig-confirm"
            return "ft-save" if v in FORM_VIEWS else ""
        if action == "cancel":
            return "ft-cancel" if v in FORM_VIEWS else ""
        table = {
            "new": {"view-pulpit": "ft-new", "view-tranzakcje": "ft-new", "view-kategorie": "ft-cat-new",
                    "view-skarbonki": "ft-pig-new", "view-cykliczne": "ft-rec-new"},
            "edit": {"view-tranzakcje": "ft-edit", "view-kategorie": "ft-cat-edit",
                     "view-skarbonki": "ft-pig-edit", "view-cykliczne": "ft-rec-edit"},
            "delete": {"view-tranzakcje": "ft-delete", "view-kategorie": "ft-cat-delete",
                       "view-skarbonki": "ft-pig-delete", "view-cykliczne": "ft-rec-delete"},
            "pause": {"view-cykliczne": "ft-rec-pause"},
            "deposit": {"view-skarbonki": "ft-pig-deposit"},
            "withdraw": {"view-skarbonki": "ft-pig-withdraw"},
        }
        return table.get(action, {}).get(v, "")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self._handle_action(event.button.id or "", event.button)

    # ---------------------------------------------------------------- helpers

    async def _open_form(self, form_id: str, header: str, focus_id: str,
                         prepare: Callable[[Widget], None]) -> None:
        origin = self._current_view()
        if origin not in FORM_VIEWS:
            self._form_return[form_id] = origin
        form = self.query_one(f"#{form_id}")
        prepare(form)
        self._switch_to(form_id, header)
        self.call_after_refresh(lambda: self.query_one(f"#{focus_id}").focus())

    async def _close_form(self, form_id: str) -> None:
        target = self._form_return.pop(form_id, FORM_PARENT.get(form_id, "view-pulpit"))
        self._switch_to(target)
        self.call_after_refresh(self._focus_current_content_primary)

    def _confirm_delete(self, message: str, on_confirm: Callable[[], None]) -> None:
        def handler(result) -> None:
            confirmed, dont_ask = result if result else (False, False)
            if not confirmed:
                return
            if dont_ask:
                set_setting("skip_delete_confirm", "1")
            try:
                on_confirm()
            except Exception as e:
                logging.exception(f"Błąd usuwania: {e}")
                self.notify(f"Błąd usuwania: {e}", severity="error")

        if get_setting("skip_delete_confirm") == "1":
            handler((True, False))
        else:
            self.app.push_screen(ConfirmationModal(message, True), handler)

    def _selected(self, view_id: str, getter: str) -> Optional[str]:
        view = self.query_one(f"#{view_id}")
        return getattr(view, getter)()

    # ------------------------------------------------------------ dispatcher

    async def _handle_action(self, btn_id: str, btn_obj: Optional[Button] = None) -> None:
        if not btn_id:
            return
        try:
            await self._dispatch(btn_id)
        except Exception as e:
            logging.exception(f"Błąd akcji {btn_id}: {e}")
            self.notify(f"Błąd: {e}", severity="error")

    async def _dispatch(self, btn_id: str) -> None:
        current_view = self._current_view()

        if btn_id in MAP_BTN_TO_VIEW:
            self._trigger_sidebar_button(btn_id)
            return

        # ================== TRANSAKCJE ==================
        if btn_id == "ft-new":
            await self._open_form("view-nowa-tranzakcja", "NOWA TRANSAKCJA", "input-amount",
                                  lambda f: f.reset_form())
            return

        if btn_id == "ft-search":
            self._switch_to("view-tranzakcje")
            self.query_one("#view-tranzakcje", TransactionsView).action_focus_search()
            return

        if btn_id == "ft-edit":
            t_id = self._selected("view-tranzakcje", "get_selected_transaction_id")
            if not t_id:
                self.notify("Zaznacz transakcję!", severity="warning")
                return
            data = get_transaction_by_id(int(t_id))
            if data:
                def prepare(form):
                    form.reset_form()
                    form.load_existing_data(data)
                await self._open_form("view-nowa-tranzakcja", f"EDYCJA {self._tx_code_from_id(t_id)}",
                                      "input-amount", prepare)
            return

        if btn_id == "ft-delete":
            t_id = self._selected("view-tranzakcje", "get_selected_transaction_id")
            if not t_id:
                self.notify("Zaznacz transakcję!", severity="warning")
                return
            code = self._tx_code_from_id(t_id)

            def do_delete() -> None:
                delete_transaction(int(t_id))
                self.notify(f"Usunięto transakcję {code}.")
                self._refresh_all_views()

            self._confirm_delete(f"Usunąć transakcję {code}?\nSaldo konta zostanie skorygowane.", do_delete)
            return

        # ================== KATEGORIE ==================
        if btn_id == "ft-cat-new":
            await self._open_form("view-nowa-kategoria", "NOWA KATEGORIA", "cat-input-name",
                                  lambda f: f.reset_form())
            return

        if btn_id == "ft-cat-edit":
            c_id = self._selected("view-kategorie", "get_selected_category_id")
            if not c_id:
                self.notify("Zaznacz kategorię!", severity="warning")
                return
            data = get_category_by_id(int(c_id))
            if data:
                def prepare(form):
                    form.reset_form()
                    form.load_existing_data(data)
                await self._open_form("view-nowa-kategoria", f"EDYCJA {self._ct_code_from_id(c_id)}",
                                      "cat-input-name", prepare)
            return

        if btn_id == "ft-cat-delete":
            c_id = self._selected("view-kategorie", "get_selected_category_id")
            if not c_id:
                self.notify("Zaznacz kategorię!", severity="warning")
                return
            code = self._ct_code_from_id(c_id)

            def do_delete() -> None:
                delete_category(int(c_id))
                self.notify(f"Usunięto kategorię {code}.")
                self._refresh_all_views()

            self._confirm_delete(f"Usunąć kategorię {code}?\nTransakcje zostaną bez kategorii.", do_delete)
            return

        # ================== SKARBONKI ==================
        if btn_id == "ft-pig-new":
            await self._open_form("view-nowa-skarbonka", "NOWY CEL", "piggy-input-name", lambda f: f.reset_form())
            return

        if btn_id == "ft-pig-edit":
            p_id = self._selected("view-skarbonki", "get_selected_piggy_id")
            if not p_id:
                self.notify("Wybierz cel!", severity="warning")
                return
            data = get_piggy_bank_by_id(int(p_id))
            if data:
                def prepare(form):
                    form.reset_form()
                    form.load_existing_data(data)
                await self._open_form("view-nowa-skarbonka", f"EDYCJA {self._pb_code_from_id(p_id)}",
                                      "piggy-input-name", prepare)
            return

        if btn_id in ("ft-pig-deposit", "ft-pig-withdraw"):
            p_id = self._selected("view-skarbonki", "get_selected_piggy_id")
            if not p_id:
                self.notify("Wybierz cel!", severity="warning")
                return
            data = get_piggy_bank_by_id(int(p_id))
            name = data["name"] if data else "Nieznany cel"
            op_type = "deposit" if btn_id == "ft-pig-deposit" else "withdraw"
            header = "WPŁATA NA CEL" if op_type == "deposit" else "WYPŁATA Z CELU"
            await self._open_form("view-op-skarbonka", header, "pig-op-amount",
                                  lambda f: f.setup_operation(p_id, name, op_type))
            return

        if btn_id == "ft-pig-confirm":
            op_view = self.query_one("#view-op-skarbonka", PiggyBankOperationView)
            amount, account, is_reg = op_view.get_data()
            if amount is None:
                self.notify("Podaj poprawną kwotę i konto!", severity="error")
                return
            change = amount if op_view.operation_type == "deposit" else -amount
            update_piggy_bank_balance(int(op_view.target_piggy_id), change, account, bool(is_reg))
            verb = "Wpłacono" if change > 0 else "Wypłacono"
            self.notify(f"{verb} {money(amount)} ({op_view.target_piggy_name}).")
            self._refresh_all_views()
            await self._close_form("view-op-skarbonka")
            return

        if btn_id == "ft-pig-delete":
            p_id = self._selected("view-skarbonki", "get_selected_piggy_id")
            if not p_id:
                self.notify("Zaznacz cel!", severity="warning")
                return
            code = self._pb_code_from_id(p_id)
            piggy = get_piggy_bank_by_id(int(p_id))
            current = float(piggy["current_amount"] or 0.0) if piggy else 0.0
            msg = f"Usunąć cel {code}?"
            if current > 0:
                msg += f"\n{money(current)} wróci na konto {piggy['account_type']}."

            def do_delete() -> None:
                refunded = delete_piggy_bank(int(p_id))
                extra = f" Zwrócono {money(refunded)}." if refunded else ""
                self.notify(f"Usunięto cel {code}.{extra}")
                self._refresh_all_views()

            self._confirm_delete(msg, do_delete)
            return

        # ================== CYKLICZNE ==================
        if btn_id == "ft-rec-new":
            await self._open_form("view-nowe-cykliczne", "NOWE ZLECENIE", "rec-input-name",
                                  lambda f: f.reset_form())
            return

        if btn_id == "ft-rec-edit":
            r_id = self._selected("view-cykliczne", "get_selected_recurring_id")
            if not r_id:
                self.notify("Zaznacz płatność!", severity="warning")
                return
            data = get_recurring_by_id(int(r_id))
            if data:
                await self._open_form("view-nowe-cykliczne", f"EDYCJA {self._rr_code_from_id(r_id)}",
                                      "rec-input-name", lambda f: f.load_existing_data(data))
            return

        if btn_id == "ft-rec-pause":
            r_id = self._selected("view-cykliczne", "get_selected_recurring_id")
            if not r_id:
                self.notify("Zaznacz płatność!", severity="warning")
                return
            active = toggle_recurring_pause(int(r_id))
            self.notify(f"{self._rr_code_from_id(r_id)} → {'AKTYWNA' if active else 'WSTRZYMANA'}")
            self._refresh_all_views()
            return

        if btn_id == "ft-rec-delete":
            r_id = self._selected("view-cykliczne", "get_selected_recurring_id")
            if not r_id:
                self.notify("Zaznacz płatność!", severity="warning")
                return
            code = self._rr_code_from_id(r_id)

            def do_delete() -> None:
                ok, msg = delete_recurring(int(r_id))
                if not ok:
                    self.notify(f"Błąd: {msg}", severity="error")
                    return
                self.notify(f"Usunięto zlecenie {code}.")
                self._refresh_all_views()

            self._confirm_delete(f"Usunąć zlecenie {code}?", do_delete)
            return

        # ================== ZAPISZ / ANULUJ ==================
        if btn_id == "ft-save":
            await self._save_current_form(current_view)
            return

        if btn_id == "ft-cancel":
            if current_view in FORM_VIEWS:
                await self._close_form(current_view)
            return

        # ================== SYSTEM ==================
        if btn_id == "ft-exit":
            self.app.exit()
            return

        if btn_id == "ft-help":
            self.action_help()
            return

        if btn_id == "ft-logout":
            if hasattr(self.app, "clear_session"):
                self.app.clear_session()
            self.app.switch_screen("login")
            return

        if btn_id == "ft-refresh":
            count = process_due_payments()
            if count > 0:
                self.notify(f"Zaksięgowano {count} płatności cyklicznych.", severity="information")
            self._refresh_all_views()
            self.notify("Odświeżono dane.")
            return

        # ================== RAPORTY ==================
        if btn_id == "btn-archive":
            ym = self.query_one("#view-raporty", ReportsView).get_selected_ym()

            def on_archive(result) -> None:
                confirmed, _ = result if result else (False, False)
                if not confirmed:
                    return
                count = archive_month(ym)
                self.notify(f"Zarchiwizowano {count} transakcji z {ym}.")
                self._refresh_all_views()

            self.app.push_screen(
                ConfirmationModal(f"Przenieść transakcje z {ym} do archiwum?\n"
                                  "Znikną z listy, ale zostaną w podsumowaniach.", show_checkbox=False),
                on_archive,
            )
            return

        # ================== USTAWIENIA ==================
        if btn_id == "btn-set-month":
            view_set = self.query_one("#view-ustawienia")
            y = view_set.query_one("#set-year", Input).value.strip()
            m = view_set.query_one("#set-month", Select).value
            if len(y) != 4 or not y.isdigit() or m in (None, Select.BLANK):
                self.notify("Podaj poprawny rok (RRRR) i wybierz miesiąc!", severity="warning")
                return
            new_ym = f"{y}-{m}"
            set_active_month_str(new_ym)
            self.notify(f"Miesiąc roboczy: {new_ym}", severity="information")
            self._refresh_all_views()
            return

        if btn_id == "btn-set-balance":
            view_set = self.query_one("#view-ustawienia")
            account = view_set.query_one("#set-bal-account", Select).value
            value = parse_amount(view_set.query_one("#set-bal-value", Input).value)
            if account in (None, Select.BLANK) or value is None:
                self.notify("Wybierz konto i podaj poprawną kwotę!", severity="error")
                return
            set_account_balance(str(account), value)
            self.notify(f"Saldo konta {account}: {money(value)}")
            self._refresh_all_views()
            return

        if btn_id == "btn-add-account":
            view_set = self.query_one("#view-ustawienia")
            name_input = view_set.query_one("#set-new-account", Input)
            bal_input = view_set.query_one("#set-new-account-balance", Input)
            opening = parse_amount(bal_input.value) if bal_input.value.strip() else 0.0
            if opening is None:
                self.notify("Błędne saldo początkowe!", severity="error")
                return
            ok, msg = add_account(name_input.value, opening_balance=opening)
            if not ok:
                self.notify(msg, severity="error")
                return
            self.notify(f"Dodano konto: {name_input.value.strip()}")
            name_input.value = ""
            bal_input.value = ""
            self._refresh_all_views()
            return

        if btn_id == "btn-delete-user":
            view_set = self.query_one("#view-ustawienia")
            sel_user_id = view_set.query_one("#sel-user-delete", Select).value
            if sel_user_id in (None, Select.BLANK):
                self.notify("Wybierz użytkownika do usunięcia!", severity="warning")
                return
            target_username = getattr(view_set, "_user_label_by_id", {}).get(sel_user_id, "Nieznany")
            cu_name = getattr(self.app, "current_username", "")
            cu_id = getattr(self.app, "current_user_id", "")

            def on_user_deleted(result) -> None:
                if result == "self":
                    if hasattr(self.app, "clear_session"):
                        self.app.clear_session()
                    self.notify("Usunięto Twoje konto. Wylogowano.", severity="information")
                    self.app.switch_screen("login")
                elif result:
                    self._safe_load("#view-ustawienia")

            self.app.push_screen(DeleteUserModal(str(sel_user_id), target_username, cu_name, cu_id),
                                 on_user_deleted)
            return

        if btn_id == "btn-change-pass":
            cu_id = getattr(self.app, "current_user_id", None)
            cu_name = getattr(self.app, "current_username", None)
            if cu_id:
                self.app.push_screen(ChangePasswordModal(cu_name, cu_id))
            return

        if btn_id == "btn-export-backup":
            self.app.push_screen(ExportBackupModal(getattr(self.app, "current_username", "")))
            return

        if btn_id == "btn-reset-db":
            def confirm_reset(result) -> None:
                confirmed, _ = result if result else (False, False)
                if not confirmed:
                    return
                reset_user_db_hard()
                self.notify("Dane zostały wyczyszczone.", severity="warning")
                self._refresh_all_views()

            self.app.push_screen(
                ConfirmationModal("CZY NA PEWNO WYCZYŚCIĆ WSZYSTKIE DANE?\n"
                                  "Transakcje, kategorie, cele i zlecenia znikną bezpowrotnie!",
                                  show_checkbox=False),
                confirm_reset,
            )
            return

    async def _save_current_form(self, current_view: str) -> None:
        if current_view == "view-nowa-tranzakcja":
            form = self.query_one("#view-nowa-tranzakcja", TransactionFormView)
            data, error = form.get_data_and_validate()
            if error:
                self.notify(error, severity="error")
                return
            args = (data["date"], data["type"], data["category"], data["account"], data["shop"],
                    data["amount"], data["desc"], data["is_reg"])
            if form.editing_id:
                update_transaction(form.editing_id, *args)
                self.notify(f"Zaktualizowano {self._tx_code_from_id(form.editing_id)}.")
            else:
                add_transaction(*args)
                note = "" if data["date"].startswith(get_active_month_str()) else \
                    f" (data {data['date']} — poza miesiącem roboczym)"
                self.notify(f"Dodano transakcję: {money(data['amount'])}.{note}")

        elif current_view == "view-nowa-kategoria":
            form = self.query_one("#view-nowa-kategoria", CategoryFormView)
            data, error = form.get_data_and_validate()
            if error:
                self.notify(error, severity="error")
                return
            if form.editing_id:
                ok, msg = update_category(form.editing_id, data["name"], data["limit"])
            else:
                ok, msg = add_category(data["name"], data["limit"])
            if not ok:
                self.notify(msg, severity="error")
                return
            self.notify("Zapisano kategorię.")

        elif current_view == "view-nowa-skarbonka":
            form = self.query_one("#view-nowa-skarbonka", PiggyBankFormView)
            data, error = form.get_data_and_validate()
            if error:
                self.notify(error, severity="error")
                return
            if form.editing_id:
                ok, msg = update_piggy_bank(form.editing_id, data["name"], data["target"], data["account"])
            else:
                ok, msg = add_piggy_bank(data["name"], data["target"], data["account"])
            if not ok:
                self.notify(msg, severity="error")
                return
            self.notify("Zapisano cel.")

        elif current_view == "view-nowe-cykliczne":
            form = self.query_one("#view-nowe-cykliczne", RecurringFormView)
            data, error = form.get_data_and_validate()
            if error:
                self.notify(error, severity="error")
                return
            args = (data["name"], data["amount"], data["type"], data["category"], data["account"],
                    data["cycle"], data["start_date"], data["is_registered"], data["piggy_id"])
            if form.editing_id:
                ok, msg = update_recurring(form.editing_id, *args)
            else:
                ok, msg = add_recurring(*args)
            if not ok:
                self.notify(msg, severity="error")
                return
            self.notify("Zapisano płatność cykliczną.")
            due = check_due_payments_count()
            if due:
                self.call_later(self._check_due_payments)
        else:
            return

        self._refresh_all_views()
        await self._close_form(current_view)
