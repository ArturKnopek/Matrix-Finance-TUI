"""
Ekran główny: menu (9 zakładek), nagłówek z przełącznikiem miesiąca, widoki, stopka ze skrótami.

Stopka i skróty kontekstowe pochodzą z `ACTIONS` aktywnego widoku (src/views/base.py).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, ContentSwitcher, Label

from src.finance.accounts import settle_matured_deposits
from src.finance.analytics import SearchHit
from src.finance.recurring import check_due_payments_count, process_due_payments
from src.finance.storage import get_active_month_str, set_active_month_str, shift_active_month, sync_active_month
from src.screens.modals import HelpDialog, SearchDialog
from src.ui.dialogs import ConfirmDialog
from src.ui.theme import palette
from src.views.accounts_view import AccountsView
from src.views.automation_view import AutomationView
from src.views.base import DataChanged, OpenView, ViewAction
from src.views.calendar_view import MONTHS_PL, CalendarView
from src.views.dashboard_view import DashboardView
from src.views.envelopes_view import EnvelopesView
from src.views.goals_view import GoalsView
from src.views.reports_view import ReportsView
from src.views.settings_view import SettingsView
from src.views.transactions_view import TransactionsView

from src.version import APP_VERSION  # noqa: E402

# (id widoku, klasa, etykieta w menu)
MENU = [
    ("view-dashboard", DashboardView, "PULPIT"),
    ("view-transactions", TransactionsView, "TRANSAKCJE"),
    ("view-envelopes", EnvelopesView, "KOPERTY"),
    ("view-accounts", AccountsView, "KONTA"),
    ("view-goals", GoalsView, "CELE"),
    ("view-automation", AutomationView, "AUTOMATY"),
    ("view-calendar", CalendarView, "KALENDARZ"),
    ("view-reports", ReportsView, "RAPORTY"),
    ("view-settings", SettingsView, "USTAWIENIA"),
]
VIEW_IDS = [v for v, _, _ in MENU]
STATIC_FOOTER = [ViewAction("help", "F1", "POMOC", "POMOC"), ViewAction("search", "^F", "SZUKAJ", "SZUK."),
                 ViewAction("logout", "^L", "WYLOGUJ", "WYL."), ViewAction("exit", "^Q", "WYJŚCIE", "WYJ.")]
FOOTER_LEVELS = [("full", "full"), ("full", "short"), ("full", "key"), ("short", "key"), ("key", "key")]
COMPACT_WIDTH = 100
SEAL_INTERVAL_S = 120
SEARCH_TARGETS = {"transaction": "view-transactions", "account": "view-accounts", "envelope": "view-envelopes",
                  "goal": "view-goals", "recurring": "view-automation"}


def footer_label(action: ViewAction, mode: str = "full") -> Text:
    p = palette()
    label = Text()
    label.append(action.key, style=f"bold {p.on_accent} on {p.accent}")
    if mode != "key":
        label.append(" " + (action.label if mode == "full" else action.short))
    return label


def footer_width(actions: List[ViewAction], mode: str) -> int:
    return sum(footer_label(a, mode).cell_len + 2 for a in actions)  # line-pad 1 + 1


class FooterBar(Horizontal):
    """Stopka dopasowująca etykiety do swojej szerokości."""

    def on_resize(self, event: events.Resize) -> None:
        fit = getattr(self.screen, "_fit_footer", None)
        if callable(fit):
            fit()


class MainDashboard(Screen):
    BINDINGS = [
        *[Binding(str(i), f"go('{view}')", label, show=False) for i, (view, _, label) in enumerate(MENU, 1)],
        Binding("left_square_bracket", "shift_month(-1)", "Poprzedni miesiąc", show=False),
        Binding("right_square_bracket", "shift_month(1)", "Następny miesiąc", show=False),
        Binding("ctrl+f", "search", "Szukaj", show=False),
        Binding("ctrl+t", "key('^T')", "Przelew", show=False),
        Binding("ctrl+n", "key('^N')", "Nowy", show=False),
        Binding("ctrl+e", "key('^E')", "Edytuj", show=False),
        Binding("ctrl+d", "key('^D')", "Usuń", show=False),
        Binding("ctrl+p", "key('^P')", "Pauza", show=False),
        Binding("plus", "key('+')", "Wpłata", show=False),
        Binding("minus", "key('-')", "Wypłata", show=False),
        Binding("tab", "nav_next", show=False),
        Binding("shift+tab", "nav_prev", show=False),
        Binding("down", "nav_down", show=False),
        Binding("up", "nav_up", show=False),
        Binding("escape", "nav_back", show=False),
        Binding("f1", "help", "Pomoc", show=False),
        Binding("f2", "toggle_sidebar", "Menu", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Menu", show=False),
        Binding("ctrl+r", "refresh_all", "Odśwież", show=False),
        Binding("ctrl+y", "sync_now", "Synchronizuj", show=False),
        Binding("ctrl+l", "logout", "Wyloguj", show=False),
        Binding("ctrl+q", "exit_app", "Wyjście", show=False),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._menu_override: Optional[bool] = None
        self._menu_peek = False
        self._session_user: Optional[str] = None
        self._footer_actions: List[ViewAction] = []

    # ================================================================ COMPOSE

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar"):
            yield Label("MATRIX FINANCE", id="app-title")
            yield Label(f"budżet · koperty · v{APP_VERSION}", id="app-version")
            for i, (view_id, _, label) in enumerate(MENU, 1):
                yield Button(f"{i}  {label}", id=f"nav-{view_id}", classes="sidebar-btn")
            yield Label("", classes="spacer")
            yield Label("F2 menu · F1 pomoc\n^F szukaj · [ ] miesiąc", id="sidebar-hint")

        with Vertical(id="right-panel"):
            with Horizontal(id="header"):
                yield Label("", id="header-title")
                yield Button("◀", id="month-prev", classes="month-btn")
                yield Label("", id="header-month")
                yield Button("▶", id="month-next", classes="month-btn")
                yield Label("", id="header-nav")
                yield Label("", id="header-clock")
            with ContentSwitcher(initial="view-dashboard", id="content-frame"):
                for view_id, cls, _ in MENU:
                    yield cls(id=view_id)

        with FooterBar(id="footer"):
            with Horizontal(id="footer-dynamic"):
                for view_id, cls, _ in MENU:
                    for action in cls.ACTIONS:
                        yield Button(footer_label(action), id=f"ft-{view_id}-{action.name}",
                                     classes="footer-btn dynamic")
            yield Label("", classes="footer-spacer")
            with Horizontal(id="footer-static"):
                for action in STATIC_FOOTER:
                    yield Button(footer_label(action), id=f"ft-static-{action.name}", classes="footer-btn static")

    async def on_mount(self) -> None:
        if not self._ensure_logged_in():
            return
        sync_active_month()
        self._session_user = getattr(self.app, "current_user_id", None)
        self.set_interval(1, self.update_clock)
        self.set_interval(SEAL_INTERVAL_S, self._periodic_save)
        self._sync_error_shown = False
        self._switch_to("view-dashboard")
        self.call_after_refresh(self._apply_responsive)
        self.call_after_refresh(self._focus_active_menu_button)
        self.call_later(self._startup_checks)

    def on_screen_resume(self) -> None:
        if not self._ensure_logged_in():
            return
        user = getattr(self.app, "current_user_id", None)
        if user != self._session_user:
            self._session_user = user
            sync_active_month()
            self._switch_to("view-dashboard")
            self.call_later(self._startup_checks)
        self.call_later(self.refresh_all_views)
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
        self._update_header()
        self.call_after_refresh(self._fit_footer)

    def action_toggle_sidebar(self) -> None:
        visible = not self._is_compact()
        self._menu_peek = False
        auto_visible = self.size.width >= COMPACT_WIDTH
        target = not visible
        self._menu_override = None if target == auto_visible else target
        self._apply_responsive()
        if target:
            self._focus_active_menu_button()

    def update_clock(self) -> None:
        try:
            now = datetime.now()
            user = getattr(self.app, "current_username", "") or ""
            lock = "⚿ " if getattr(self.app, "vault", None) is not None else ""
            if self.size.width >= 120:
                text = f"{lock}{user} · {now:%H:%M:%S}"
            elif self.size.width >= 80:
                text = f"{lock}{now:%H:%M:%S}"
            else:
                text = f"{now:%H:%M}"
            self.query_one("#header-clock", Label).update(text)
        except Exception:
            pass

    def _update_header(self) -> None:
        p = palette()
        view = self._current_view()
        title = next((cls.TITLE for v, cls, _ in MENU if v == view), "")
        header = Text(f"› {title}", style=f"bold {p.accent}")
        try:
            from src.finance.accounts import opening_mode

            if opening_mode():  # przypomnienie: zmiany sald bez historii
                header.append("  ⚑ STAN POCZĄTKOWY", style=f"bold {p.on_accent} on {p.warning}")
        except Exception:
            pass
        self.query_one("#header-title", Label).update(header)
        y, m = map(int, get_active_month_str().split("-"))
        month = f"{MONTHS_PL[m - 1]} {y}" if self.size.width >= 110 else f"{m:02d}.{y}"
        self.query_one("#header-month", Label).update(Text(month, style=f"bold {p.text}"))
        nav = Text()
        for i, view_id in enumerate(VIEW_IDS, 1):
            nav.append(f"{i}", style=f"bold {p.on_accent} on {p.accent}" if view_id == view else p.accent_dim)
        self.query_one("#header-nav", Label).update(nav)

    # ================================================================= STOPKA

    def _update_footer(self, view_id: str) -> None:
        cls = next(c for v, c, _ in MENU if v == view_id)
        self._footer_actions = list(cls.ACTIONS)
        visible = {f"ft-{view_id}-{a.name}" for a in cls.ACTIONS}
        for btn in self.query(".footer-btn.dynamic").results(Button):
            btn.display = btn.id in visible
        self._fit_footer(force=True)

    def _fit_footer(self, force: bool = False) -> None:
        try:
            available = self.query_one("#footer").size.width
        except Exception:
            return
        if available <= 0:
            return
        dyn_mode, static_mode = FOOTER_LEVELS[-1]
        for d_mode, s_mode in FOOTER_LEVELS:
            # -1: odstęp między grupami przycisków zajmuje co najmniej jedną kolumnę
            if footer_width(self._footer_actions, d_mode) + footer_width(STATIC_FOOTER, s_mode) <= available - 1:
                dyn_mode, static_mode = d_mode, s_mode
                break
        view_id = self._current_view()
        pairs = [(f"ft-{view_id}-{a.name}", a, dyn_mode) for a in self._footer_actions] + \
                [(f"ft-static-{a.name}", a, static_mode) for a in STATIC_FOOTER]
        changed = False
        for btn_id, action, mode in pairs:
            btn = self.query_one(f"#{btn_id}", Button)
            label = footer_label(action, mode)
            if force or btn.label.plain != label.plain:
                # Textual porównuje etykiety tylko po tekście (bez kolorów) — przy zmianie motywu ta sama
                # treść w innych kolorach nie odświeżyłaby przycisku, więc najpierw czyścimy etykietę.
                btn.label = ""
                btn.label = label
                btn.refresh(layout=True)
                changed = True
        if changed:
            self.query_one("#footer").refresh(layout=True)

    def refresh_theme(self) -> None:
        """Po zmianie motywu: kolory rysowane w Pythonie (stopka, nagłówek, widoki).
        Stopka innych zakładek odświeża się przy przejściu na nie (_update_footer -> _fit_footer(force=True))."""
        self._fit_footer(force=True)
        self._update_header()
        self.refresh_all_views()

    # =============================================================== NAWIGACJA

    def _current_view(self) -> str:
        return self.query_one("#content-frame", ContentSwitcher).current or "view-dashboard"

    def _active_view(self) -> Any:
        return self.query_one(f"#{self._current_view()}")

    def _switch_to(self, view_id: str) -> None:
        self.query_one("#content-frame", ContentSwitcher).current = view_id
        for v in VIEW_IDS:
            self.query_one(f"#nav-{v}", Button).set_class(v == view_id, "active")
        self._update_footer(view_id)
        self._update_header()

    def action_go(self, view_id: str, focus_content: bool = True) -> None:
        self._menu_peek = False
        self._switch_to(view_id)
        self._load_view(view_id)
        self._apply_responsive()
        if focus_content:
            self.call_after_refresh(self._focus_content)

    def _focus_content(self) -> None:
        view = self._active_view()
        if hasattr(view, "focus_primary"):
            view.focus_primary()

    @staticmethod
    def _is_hidden(widget: Widget) -> bool:
        node: Any = widget
        while isinstance(node, Widget):
            if not node.display or not node.visible:
                return True
            node = node.parent
        return False

    def _menu_buttons(self) -> List[Widget]:
        return [b for b in self.query(".sidebar-btn").results(Button) if not self._is_hidden(b)]

    def _focused_is_menu(self) -> bool:
        return isinstance(self.focused, Button) and self.focused.has_class("sidebar-btn")

    def _focus_active_menu_button(self) -> None:
        try:
            btn = self.query_one(f"#nav-{self._current_view()}", Button)
            if not self._is_hidden(btn):
                btn.focus()
        except Exception:
            pass

    def _view_focusables(self) -> List[Widget]:
        return [w for w in self._active_view().walk_children(Widget) if w.focusable and not self._is_hidden(w)]

    def _move_focus(self, items: List[Widget], step: int) -> None:
        if not items:
            return
        current = self.focused
        if current not in items:
            items[0 if step > 0 else -1].focus()
        else:
            items[(items.index(current) + step) % len(items)].focus()

    def action_nav_next(self) -> None:
        self._move_focus(self._menu_buttons() if self._focused_is_menu() else self._view_focusables(), 1)

    def action_nav_prev(self) -> None:
        self._move_focus(self._menu_buttons() if self._focused_is_menu() else self._view_focusables(), -1)

    def action_nav_down(self) -> None:
        if self._focused_is_menu():
            self._move_focus(self._menu_buttons(), 1)
        elif self.focused is not None:
            self._move_focus(self._view_focusables(), 1)

    def action_nav_up(self) -> None:
        if self._focused_is_menu():
            self._move_focus(self._menu_buttons(), -1)
        elif self.focused is not None:
            self._move_focus(self._view_focusables(), -1)

    def action_nav_back(self) -> None:
        if self._focused_is_menu():
            self._menu_peek = False
            self._apply_responsive()
            self.call_after_refresh(self._focus_content)
            return
        if self._is_compact():
            self._menu_peek = True
            self._apply_responsive()
        self.call_after_refresh(self._focus_active_menu_button)

    # ================================================================= MIESIĄC

    def action_shift_month(self, delta: int) -> None:
        month = shift_active_month(int(delta))
        self.refresh_all_views()
        self.notify(f"Miesiąc roboczy: {month}", timeout=1.5)

    def action_set_month(self, ym: str) -> None:
        set_active_month_str(ym)
        self.refresh_all_views()

    # =================================================================== AKCJE

    def action_key(self, key_label: str) -> None:
        view = self._active_view()
        for action in getattr(view, "ACTIONS", []):
            if action.key == key_label:
                view.run_view_action(action.name)
                return
        if key_label == "^T":
            from src.ui.forms import TransferDialog

            view.open_dialog(TransferDialog())
        elif key_label == "^N":
            from src.ui.forms import TransactionDialog

            view.open_dialog(TransactionDialog())

    def action_help(self) -> None:
        self.app.push_screen(HelpDialog())

    def action_search(self) -> None:
        views = [SearchHit("view", v, label.capitalize(), f"zakładka {i}")
                 for i, (v, _, label) in enumerate(MENU, 1)]

        def on_pick(hit: Optional[SearchHit]) -> None:
            if not hit:
                return
            if hit.kind == "view":
                self.action_go(hit.ref)
                return
            if hit.kind == "transaction":
                from src.finance.ledger import get_transaction_by_id

                row = get_transaction_by_id(int(hit.ref))
                if row and not str(row["date"]).startswith(get_active_month_str()):
                    set_active_month_str(str(row["date"])[:7])
                    self.refresh_all_views()
            target = SEARCH_TARGETS.get(hit.kind)
            if target:
                self.action_go(target)
                self._active_view().select_ref(hit.ref)

        self.app.push_screen(SearchDialog(views), on_pick)

    def action_refresh_all(self) -> None:
        count = process_due_payments()
        settled = settle_matured_deposits()
        self.refresh_all_views()
        parts = ["Odświeżono."]
        if count:
            parts.append(f"Zaksięgowano zleceń: {count}.")
        parts.extend(settled)
        self.notify(" ".join(parts))

    def action_logout(self, after_delete: bool = False) -> None:
        if hasattr(self.app, "clear_session"):
            self.app.clear_session()
        self.app.switch_screen("login")

    def action_exit_app(self) -> None:
        self.app.exit()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("nav-"):
            self.action_go(bid[4:])
        elif bid == "month-prev":
            self.action_shift_month(-1)
        elif bid == "month-next":
            self.action_shift_month(1)
        elif bid.startswith("ft-static-"):
            {"help": self.action_help, "search": self.action_search, "logout": self.action_logout,
             "exit": self.action_exit_app}[bid[len("ft-static-"):]]()
        elif bid.startswith("ft-view-"):
            prefix = f"ft-{self._current_view()}-"
            if bid.startswith(prefix):
                self._active_view().run_view_action(bid[len(prefix):])

    def on_data_table_row_selected(self, event: Any) -> None:
        view = self._active_view()
        if view.has_view_action("edit"):
            view.run_view_action("edit")

    # ================================================================== DANE

    def on_data_changed(self, event: DataChanged) -> None:
        if event.message:
            self.notify(event.message, severity=event.severity)
        self.refresh_all_views()
        if event.check_due:
            self.call_later(self._check_due_payments)

    def on_open_view(self, event: OpenView) -> None:
        self.action_go(event.view_id)
        if event.select is not None:
            self._active_view().select_ref(event.select)

    def _load_view(self, view_id: str) -> None:
        try:
            self.query_one(f"#{view_id}").load_data()
        except Exception as e:
            logging.exception("Błąd ładowania widoku %s: %s", view_id, e)

    def refresh_all_views(self) -> None:
        with self.app.batch_update():
            for view_id in VIEW_IDS:
                self._load_view(view_id)
        self._update_header()

    _refresh_all_views = refresh_all_views

    def _ensure_logged_in(self) -> bool:
        if not getattr(self.app, "current_user_id", None):
            if hasattr(self.app, "clear_session"):
                self.app.clear_session()
            self.app.switch_screen("login")
            return False
        return True

    def _periodic_save(self) -> None:
        self._auto_sync()
        self._seal_vault()

    def _auto_sync(self) -> None:
        """Synchronizacja z telefonem (OneDrive) w tle: przy starcie, co 2 minuty i przy wyjściu."""
        from src.finance import sync

        try:
            if not sync.auto_enabled():
                return
            result = sync.sync_folder_now(only_if_changed=True)
        except Exception as e:
            if not getattr(self, "_sync_error_shown", False):
                self._sync_error_shown = True
                self.notify(f"Synchronizacja z telefonem: {e}", severity="warning", timeout=8)
            logging.warning("Automatyczna synchronizacja: %s", e)
            return
        self._sync_error_shown = False
        self._after_sync(result, quiet=True)

    def _after_sync(self, result: Any, quiet: bool = False) -> None:
        if result.applied or result.rejected:
            self.refresh_all_views()
        if result.rejected:
            self.notify("Odrzucone operacje z telefonu:\n" + "\n".join(result.rejected[:5]), severity="warning",
                        timeout=12)
        if result.applied:
            self.notify(f"Z telefonu: {len(result.applied)} operacji\n" + "\n".join(result.applied[:5]),
                        timeout=8)
        elif not quiet:
            self.notify(f"Synchronizacja: {result.summary()}\n{result.folder}", timeout=6)

    def action_sync_now(self) -> None:
        from src.finance import sync

        if not sync.is_configured():
            from src.screens.modals import SyncSettingsDialog

            self._active_view().open_dialog(SyncSettingsDialog())
            return
        try:
            result = sync.sync_folder_now()
        except Exception as e:
            self.notify(f"Synchronizacja nie powiodła się: {e}", severity="error", timeout=10)
            return
        self._after_sync(result)

    def _seal_vault(self) -> None:
        vault = getattr(self.app, "vault", None)
        if vault is not None:
            try:
                vault.seal()
            except Exception as e:
                logging.error("Nie udało się zapisać zaszyfrowanej bazy: %s", e)

    def _startup_checks(self) -> None:
        self._auto_sync()  # najpierw operacje z telefonu
        settled = settle_matured_deposits()
        if settled:
            self.notify("Rozliczono lokaty: " + " ".join(settled), timeout=8)
            self.refresh_all_views()
        self._check_due_payments()

    def _check_due_payments(self) -> None:
        try:
            due = check_due_payments_count()
        except Exception as e:
            logging.exception("Błąd sprawdzania zleceń: %s", e)
            return
        if due <= 0:
            return

        def on_answer(result: Any) -> None:
            if result and result[0]:
                processed = process_due_payments()
                self.post_message(DataChanged(f"Zaksięgowano {processed} zaległych płatności cyklicznych."))

        self.app.push_screen(ConfirmDialog(f"Zaległe płatności cykliczne: {due}.\nZaksięgować je teraz?",
                                           title="ZLECENIA CYKLICZNE", yes="ZAKSIĘGUJ", no="PÓŹNIEJ"), on_answer)
