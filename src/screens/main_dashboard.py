from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, ContentSwitcher, Label, Input, DataTable, Select

# --- WIDOKI ---
from src.screens.modal_screen import ConfirmationModal, DeleteUserModal, ChangePasswordModal
from src.views.dashboard_view import DashboardView
from src.views.transactions_view import TransactionsView
from src.views.transaction_form_view import TransactionFormView
from src.views.categories_view import CategoriesView
from src.views.category_form_view import CategoryFormView
from src.views.piggy_bank_view import PiggyBankView
from src.views.piggy_bank_form_view import PiggyBankFormView
from src.views.piggy_bank_op_view import PiggyBankOperationView
from src.views.recurring_view import RecurringView
from src.views.recurring_form_view import RecurringFormView
from src.views.reports_view import ReportsView
from src.views.settings_view import SettingsView

# --- BAZA ---
from src.database import (
    add_transaction, get_transaction_by_id, update_transaction, delete_transaction,
    add_category, get_category_by_id, update_category, delete_category,
    add_recurring, get_recurring_by_id, update_recurring, delete_recurring, toggle_recurring_pause,
    check_due_payments_count, process_due_payments,
    add_piggy_bank, get_piggy_bank_by_id, update_piggy_bank, delete_piggy_bank, update_piggy_bank_balance,
    archive_month, get_setting, set_setting, set_active_month_str, set_account_balance, reset_user_db_hard,
)
from src.screens.modal_screen import ConfirmationModal, DeleteUserModal, ChangePasswordModal, ExportBackupModal

class MainDashboard(Screen):
    """
    Główny ekran aplikacji.
    """

    BINDINGS = [
        ("1", "go('view-pulpit')", "Pulpit"),
        ("2", "go('view-tranzakcje')", "Transakcje"),
        ("3", "go('view-kategorie')", "Kategorie"),
        ("4", "go('view-skarbonki')", "Skarbonki"),
        ("5", "go('view-cykliczne')", "Cykliczne"),
        ("6", "go('view-raporty')", "Raporty"),
        ("7", "go('view-ustawienia')", "Ustawienia"),
        ("up", "menu_up", "Góra"),
        ("down", "menu_down", "Dół"),
        ("ctrl+r", "refresh_all", "Odśwież"),
        ("ctrl+l", "logout", "Wyloguj"),
        ("ctrl+q", "exit_app", "Wyjście"),
        ("ctrl+n", "ctx_new", "Nowa"),
        ("ctrl+e", "ctx_edit", "Edytuj"),
        ("ctrl+d", "ctx_delete", "Usuń"),
        ("ctrl+p", "ctx_pause", "Pauza"),
        ("ctrl+s", "ctx_save", "Zapisz"),
        ("escape", "ctx_cancel", "Anuluj"),
    ]

    MAP_BTN_TO_VIEW = {
        "nav-pulpit": "view-pulpit",
        "nav-tranzakcje": "view-tranzakcje",
        "nav-kategorie": "view-kategorie",
        "nav-skarbonki": "view-skarbonki",
        "nav-cykliczne": "view-cykliczne",
        "nav-raporty": "view-raporty",
        "nav-ustawienia": "view-ustawienia",
    }

    MENU_ORDER = list(MAP_BTN_TO_VIEW.keys())

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar"):
            yield Label("BUDGET APP v1.0", id="app-title")
            yield Label("", classes="menu-spacer")
            yield Button("[1] PULPIT", id="nav-pulpit", classes="sidebar-btn active")
            yield Button("[2] TRANZAKCJE", id="nav-tranzakcje", classes="sidebar-btn")
            yield Button("[3] KATEGORIE", id="nav-kategorie", classes="sidebar-btn")
            yield Button("[4] SKARBONKI", id="nav-skarbonki", classes="sidebar-btn")
            yield Button("[5] CYKLICZNE", id="nav-cykliczne", classes="sidebar-btn")
            yield Button("[6] RAPORTY", id="nav-raporty", classes="sidebar-btn")
            yield Button("[7] USTAWIENIA", id="nav-ustawienia", classes="sidebar-btn")
            yield Label("", classes="spacer")

        with Vertical(id="right-panel"):
            with Horizontal(id="header"):
                yield Label(">>> PULPIT GŁÓWNY", id="header-title")
                yield Label("...", id="header-clock")

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

        with Horizontal(id="footer"):
            with Horizontal(id="footer-dynamic"): pass
            yield Label("", classes="footer-spacer")
            with Horizontal(id="footer-static"):
                yield Button("\[L] WYLOGUJ", id="ft-logout", classes="footer-btn static")
                yield Button("\[Q] WYJŚCIE", id="ft-exit", classes="footer-btn static")

    async def on_mount(self) -> None:
        if not self._ensure_logged_in(): return
        from src.database import sync_active_month
        sync_active_month()
        self.update_clock()
        self.set_interval(1, self.update_clock)
        self.call_later(self._refresh_after_login)
        await self.update_footer("view-pulpit")

        try:
            due_count = check_due_payments_count()
            if due_count > 0:
                def check_recurring_response(result):
                    is_confirmed, _ = result if result else (False, False)
                    if not is_confirmed: return
                    processed = process_due_payments()
                    self.notify(f"Przetworzono {processed} zaległych płatności!", severity="information")
                    self._refresh_after_login()

                self.app.push_screen(
                    ConfirmationModal(f"Znaleziono {due_count} zaległych płatności. Dodać je?", show_checkbox=False),
                    check_recurring_response,
                )
        except Exception as e:
            logging.error(f"Błąd na starcie: {e}")

    def on_screen_resume(self) -> None:
        if not self._ensure_logged_in(): return
        self.call_later(self._refresh_after_login)

    def update_clock(self) -> None:
        self.query_one("#header-clock").update(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    async def update_footer(self, view_name: str) -> None:
        dynamic_container = self.query_one("#footer-dynamic")
        await dynamic_container.query(".dynamic").remove()

        btn_refresh = Button("\[R] ODŚWIEŻ", id="ft-refresh", classes="footer-btn dynamic")

        if view_name == "view-pulpit":
            await dynamic_container.mount(Button("\[N] SZYBKA TRANZAKCJA", id="ft-new", classes="footer-btn dynamic"),
                                          btn_refresh)
        elif view_name == "view-tranzakcje":
            await dynamic_container.mount(Button("\[N] NOWA", id="ft-new", classes="footer-btn dynamic"),
                                          Button("\[E] EDYTUJ", id="ft-edit", classes="footer-btn dynamic"),
                                          Button("\[D] USUŃ", id="ft-delete", classes="footer-btn dynamic"),
                                          btn_refresh)
        elif view_name == "view-nowa-tranzakcja":
            await dynamic_container.mount(Button("\[S] ZAPISZ", id="ft-save", classes="footer-btn dynamic"),
                                          Button("\[ESC] ANULUJ", id="ft-cancel", classes="footer-btn dynamic"))
        elif view_name == "view-kategorie":
            await dynamic_container.mount(Button("\[N] NOWA", id="ft-cat-new", classes="footer-btn dynamic"),
                                          Button("\[E] EDYTUJ", id="ft-cat-edit", classes="footer-btn dynamic"),
                                          Button("\[D] USUŃ", id="ft-cat-delete", classes="footer-btn dynamic"),
                                          btn_refresh)
        elif view_name == "view-nowa-kategoria":
            await dynamic_container.mount(Button("\[S] ZAPISZ", id="ft-save", classes="footer-btn dynamic"),
                                          Button("\[ESC] ANULUJ", id="ft-cancel", classes="footer-btn dynamic"))
        elif view_name == "view-skarbonki":
            await dynamic_container.mount(Button("\[N] NOWY", id="ft-pig-new", classes="footer-btn dynamic"),
                                          Button("\[E] EDYTUJ", id="ft-pig-edit", classes="footer-btn dynamic"),
                                          Button("\[D] USUŃ", id="ft-pig-delete", classes="footer-btn dynamic"),
                                          Button("\[+] WPŁAĆ", id="ft-pig-deposit", classes="footer-btn dynamic"),
                                          Button("\[-] WYPŁAĆ", id="ft-pig-withdraw", classes="footer-btn dynamic"),
                                          btn_refresh)
        elif view_name == "view-nowa-skarbonka":
            await dynamic_container.mount(Button("\[S] ZAPISZ", id="ft-save", classes="footer-btn dynamic"),
                                          Button("\[ESC] ANULUJ", id="ft-cancel", classes="footer-btn dynamic"))
        elif view_name == "view-op-skarbonka":
            await dynamic_container.mount(Button("\[S] ZATWIERDŹ", id="ft-pig-confirm", classes="footer-btn dynamic"),
                                          Button("\[ESC] ANULUJ", id="ft-cancel", classes="footer-btn dynamic"))
        elif view_name == "view-cykliczne":
            await dynamic_container.mount(Button("\[N] NOWA", id="ft-rec-new", classes="footer-btn dynamic"),
                                          Button("\[E] EDYTUJ", id="ft-rec-edit", classes="footer-btn dynamic"),
                                          Button("\[D] USUŃ", id="ft-rec-delete", classes="footer-btn dynamic"),
                                          Button("\[P] PAUZA", id="ft-rec-pause", classes="footer-btn dynamic"),
                                          btn_refresh)
        elif view_name == "view-nowe-cykliczne":
            await dynamic_container.mount(Button("\[S] ZAPISZ", id="ft-save", classes="footer-btn dynamic"),
                                          Button("\[ESC] ANULUJ", id="ft-cancel", classes="footer-btn dynamic"))
        else:
            await dynamic_container.mount(btn_refresh)

    def _current_view(self) -> str:
        return self.query_one("#content-frame").current

    def _safe_load(self, view_css_id: str) -> None:
        try:
            v = self.query_one(view_css_id)
            if hasattr(v, "load_data"):
                v.load_data()
        except Exception as e:
            logging.error(f"Błąd _safe_load w {view_css_id}: {e}")

    def _strip_shortcut(self, text: str) -> str:
        text = (text or "").strip()
        if text.startswith("[") and "]" in text: return text.split("]", 1)[1].strip()
        return text

    def _set_header(self, text: str) -> None:
        self.query_one("#header-title").update(f">>> {self._strip_shortcut(text)}")

    def _set_active_sidebar(self, btn_id: str) -> None:
        try:
            self.query(".sidebar-btn").remove_class("active")
            self.query_one(f"#{btn_id}").add_class("active")
        except Exception:
            pass

    def _active_sidebar_index(self) -> int:
        for i, bid in enumerate(self.MENU_ORDER):
            try:
                if "active" in self.query_one(f"#{bid}").classes: return i
            except Exception:
                pass
        return 0

    async def _go_view(self, view_name: str, header: Optional[str] = None) -> None:
        self.query_one("#content-frame").current = view_name
        if header: self._set_header(header)
        await self.update_footer(view_name)

    def _refresh_after_login(self) -> None:
        for vid in ("#view-pulpit", "#view-tranzakcje", "#view-kategorie", "#view-skarbonki", "#view-cykliczne",
                    "#view-raporty", "#view-ustawienia"):
            self._safe_load(vid)

    def _ensure_logged_in(self) -> bool:
        if not getattr(self.app, "current_user_id", None):
            self.notify("Sesja wygasła.", severity="warning")
            if hasattr(self.app, "clear_session"): self.app.clear_session()
            self.app.switch_screen("login")
            return False
        return True

    @staticmethod
    def _tx_code_from_id(x) -> str:
        return f"TX{int(x):06d}" if x else "TX------"

    @staticmethod
    def _ct_code_from_id(x) -> str:
        return f"CT{int(x):06d}" if x else "CT------"

    @staticmethod
    def _pb_code_from_id(x) -> str:
        return f"PB{int(x):06d}" if x else "PB------"

    @staticmethod
    def _rr_code_from_id(x) -> str:
        return f"RR{int(x):06d}" if x else "RR------"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        v = self._current_view()
        forms = ("view-nowa-tranzakcja", "view-nowa-kategoria", "view-nowa-skarbonka", "view-op-skarbonka",
                 "view-nowe-cykliczne")
        if v in forms:
            btn_id = "ft-pig-confirm" if v == "view-op-skarbonka" else "ft-save"
            self.run_worker(self._handle_action(btn_id), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        edit_action = self._ctx_map("edit")
        if edit_action:
            self.run_worker(self._handle_action(edit_action), exclusive=True)

    def action_menu_up(self) -> None:
        idx = max(0, self._active_sidebar_index() - 1)
        self.call_later(self._trigger_sidebar_button, self.MENU_ORDER[idx])

    def action_menu_down(self) -> None:
        idx = min(len(self.MENU_ORDER) - 1, self._active_sidebar_index() + 1)
        self.call_later(self._trigger_sidebar_button, self.MENU_ORDER[idx])

    async def action_go(self, view_name: str) -> None:
        btn_id = {v: k for k, v in self.MAP_BTN_TO_VIEW.items()}.get(view_name)
        if btn_id:
            self._set_active_sidebar(btn_id)
            self._trigger_sidebar_button(btn_id)

    def _trigger_sidebar_button(self, btn_id: str) -> None:
        target_view = self.MAP_BTN_TO_VIEW.get(btn_id)
        if not target_view: return

        self._set_active_sidebar(btn_id)
        try:
            self._set_header(f"{self.query_one(f'#{btn_id}', Button).label.plain.upper()} GŁÓWNY")
        except Exception:
            pass

        self.query_one("#content-frame").current = target_view
        self._safe_load(f"#{target_view}")

        try:
            self.query_one(f"#{target_view}").focus()
        except Exception:
            pass

        self.run_worker(self.update_footer(target_view), exclusive=True)

    def action_exit_app(self) -> None:
        self.app.exit()

    def action_logout(self) -> None:
        self.run_worker(self._handle_action("ft-logout"), exclusive=True)

    def action_refresh_all(self) -> None:
        self.run_worker(self._handle_action("ft-refresh"), exclusive=True)

    def action_ctx_new(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("new")), exclusive=True)

    def action_ctx_edit(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("edit")), exclusive=True)

    def action_ctx_delete(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("delete")), exclusive=True)

    def action_ctx_pause(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("pause")), exclusive=True)

    def action_ctx_save(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("save")), exclusive=True)

    def action_ctx_cancel(self) -> None:
        self.run_worker(self._handle_action(self._ctx_map("cancel")), exclusive=True)

    def _ctx_map(self, action: str) -> str:
        v = self._current_view()
        if action in ("save", "cancel"):
            if v in ("view-nowa-tranzakcja", "view-nowa-kategoria", "view-nowa-skarbonka",
                     "view-nowe-cykliczne"): return "ft-save" if action == "save" else "ft-cancel"
            if v == "view-op-skarbonka": return "ft-pig-confirm" if action == "save" else "ft-cancel"
            return ""
        if action == "new": return {"view-tranzakcje": "ft-new", "view-kategorie": "ft-cat-new",
                                    "view-skarbonki": "ft-pig-new", "view-cykliczne": "ft-rec-new",
                                    "view-pulpit": "ft-new"}.get(v, "")
        if action == "edit": return {"view-tranzakcje": "ft-edit", "view-kategorie": "ft-cat-edit",
                                     "view-skarbonki": "ft-pig-edit", "view-cykliczne": "ft-rec-edit"}.get(v, "")
        if action == "delete": return {"view-tranzakcje": "ft-delete", "view-kategorie": "ft-cat-delete",
                                       "view-skarbonki": "ft-pig-delete", "view-cykliczne": "ft-rec-delete"}.get(v, "")
        if action == "pause" and v == "view-cykliczne": return "ft-rec-pause"
        return ""

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        await self._handle_action(event.button.id, event.button)

    async def _handle_action(self, btn_id: str, btn_obj: Optional[Button] = None) -> None:
        if not btn_id: return
        current_view = self._current_view()

        if btn_id in self.MAP_BTN_TO_VIEW:
            self._trigger_sidebar_button(btn_id)
            return

        # ================== TRANSAKCJE ==================
        if btn_id == "ft-new":
            form = self.query_one("#view-nowa-tranzakcja")
            form.reset_form()
            await self._go_view("view-nowa-tranzakcja", "NOWA TRANSAKCJA")
            self.query_one("#input-date").focus()
            return

        if btn_id == "ft-edit":
            try:
                view = self.query_one("#view-tranzakcje")
                t_id = view.get_selected_transaction_id()
                if not t_id:
                    self.notify("Zaznacz transakcję!", severity="warning")
                    return
                data = get_transaction_by_id(int(t_id))
                if data:
                    form = self.query_one("#view-nowa-tranzakcja")
                    form.reset_form()
                    form.load_existing_data(data)
                    await self._go_view("view-nowa-tranzakcja", f"EDYCJA {self._tx_code_from_id(t_id)}")
                    self.query_one("#input-date").focus()
            except Exception as e:
                logging.error(f"Błąd edycji: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-delete":
            try:
                view = self.query_one("#view-tranzakcje")
                t_id = view.get_selected_transaction_id()
                if not t_id: return self.notify("Zaznacz transakcję!", severity="warning")
                tx_code = self._tx_code_from_id(t_id)

                def do_delete_trans(result):
                    is_confirmed, dont_ask = result if result else (False, False)
                    if not is_confirmed: return
                    if dont_ask: set_setting("skip_delete_confirm", "1")
                    delete_transaction(int(t_id))
                    self.notify(f"Usunięto transakcję {tx_code}!")
                    self._refresh_after_login()

                if get_setting("skip_delete_confirm") == "1":
                    do_delete_trans((True, False))
                else:
                    self.app.push_screen(ConfirmationModal(f"Usunąć {tx_code}?", True), do_delete_trans)
            except Exception as e:
                logging.error(f"Błąd usuwania transakcji: {e}")
            return

        # ================== KATEGORIE ==================
        if btn_id == "ft-cat-new":
            form = self.query_one("#view-nowa-kategoria")
            form.reset_form()
            await self._go_view("view-nowa-kategoria", "NOWA KATEGORIA")
            self.query_one("#cat-input-name").focus()
            return

        if btn_id == "ft-cat-edit":
            try:
                view = self.query_one("#view-kategorie")
                c_id = view.get_selected_category_id()
                if not c_id: return self.notify("Zaznacz kategorię!", severity="warning")
                data = get_category_by_id(int(c_id))
                if data:
                    form = self.query_one("#view-nowa-kategoria")
                    form.reset_form()
                    form.load_existing_data(data)
                    await self._go_view("view-nowa-kategoria", f"EDYCJA {self._ct_code_from_id(c_id)}")
                    self.query_one("#cat-input-name").focus()
            except Exception as e:
                logging.error(f"Błąd edycji kat: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-cat-delete":
            try:
                view = self.query_one("#view-kategorie")
                c_id = view.get_selected_category_id()
                if not c_id: return self.notify("Zaznacz kategorię!", severity="warning")
                ct_code = self._ct_code_from_id(c_id)

                def do_delete_cat(result):
                    is_confirmed, dont_ask = result if result else (False, False)
                    if not is_confirmed: return
                    if dont_ask: set_setting("skip_delete_confirm", "1")
                    delete_category(int(c_id))
                    self.notify(f"Usunięto kategorię {ct_code}!")
                    self._safe_load("#view-kategorie")

                if get_setting("skip_delete_confirm") == "1":
                    do_delete_cat((True, False))
                else:
                    self.app.push_screen(ConfirmationModal(f"Usunąć kategorię {ct_code}?", True), do_delete_cat)
            except Exception as e:
                logging.error(f"Błąd usuwania kat: {e}")
            return

        # ================== SKARBONKI ==================
        if btn_id == "ft-pig-new":
            form = self.query_one("#view-nowa-skarbonka")
            form.reset_form()
            await self._go_view("view-nowa-skarbonka", "NOWY CEL")
            self.query_one("#piggy-input-name").focus()
            return

        if btn_id == "ft-pig-edit":
            try:
                view = self.query_one("#view-skarbonki")
                p_id = view.get_selected_piggy_id()
                if not p_id: return self.notify("Wybierz cel!", severity="warning")
                data = get_piggy_bank_by_id(int(p_id))
                if data:
                    form = self.query_one("#view-nowa-skarbonka")
                    form.reset_form()
                    form.load_existing_data(data)
                    await self._go_view("view-nowa-skarbonka", f"EDYCJA {self._pb_code_from_id(p_id)}")
                    self.query_one("#piggy-input-name").focus()
            except Exception as e:
                logging.error(f"Błąd edycji piggy: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id in ("ft-pig-deposit", "ft-pig-withdraw"):
            try:
                view = self.query_one("#view-skarbonki")
                p_id = view.get_selected_piggy_id()
                if not p_id: return self.notify("Wybierz skarbonkę!", severity="warning")
                data = get_piggy_bank_by_id(p_id)
                p_name = data["name"] if data else "Nieznany cel"
                op_type = "deposit" if btn_id == "ft-pig-deposit" else "withdraw"
                op_view = self.query_one("#view-op-skarbonka")
                op_view.setup_operation(p_id, p_name, op_type)
                await self._go_view("view-op-skarbonka", "OPERACJA FINANSOWA")
                self.query_one("#pig-op-amount").focus()
            except Exception as e:
                logging.error(f"Błąd operacji piggy: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-pig-confirm":
            try:
                op_view = self.query_one("#view-op-skarbonka")
                amount, account, is_reg = op_view.get_data()
                if amount is None: return self.notify("Podaj poprawną kwotę!", severity="error")
                final_change = amount if op_view.operation_type == "deposit" else -amount

                update_piggy_bank_balance(op_view.target_piggy_id, final_change, account, is_reg)
                self.notify("Operacja udana!" if is_reg else "Zaktualizowano stan skarbonki.")
                self._refresh_after_login()
                await self._go_view("view-skarbonki", "SKARBONKI GŁÓWNY")
            except Exception as e:
                logging.error(f"Błąd confirm piggy: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-pig-delete":
            try:
                view = self.query_one("#view-skarbonki")
                p_id = view.get_selected_piggy_id()
                if not p_id: return self.notify("Zaznacz cel!", severity="warning")
                pb_code = self._pb_code_from_id(p_id)

                def do_delete_piggy(result):
                    is_confirmed, dont_ask = result if result else (False, False)
                    if not is_confirmed: return
                    if dont_ask: set_setting("skip_delete_confirm", "1")
                    delete_piggy_bank(int(p_id))
                    self.notify(f"Usunięto cel {pb_code}!")
                    self._safe_load("#view-skarbonki")

                if get_setting("skip_delete_confirm") == "1":
                    do_delete_piggy((True, False))
                else:
                    self.app.push_screen(ConfirmationModal(f"Usunąć {pb_code}?", True), do_delete_piggy)
            except Exception as e:
                logging.error(f"Błąd usunięcia piggy: {e}")
            return

        # ================== CYKLICZNE ==================
        if btn_id == "ft-rec-new":
            form = self.query_one("#view-nowe-cykliczne")
            form.reset_form()
            await self._go_view("view-nowe-cykliczne", "NOWE ZLECENIE")
            self.query_one("#rec-input-type").focus()
            return

        if btn_id == "ft-rec-edit":
            try:
                view = self.query_one("#view-cykliczne")
                r_id = view.get_selected_recurring_id()
                if not r_id: return self.notify("Zaznacz płatność!", severity="warning")
                data = get_recurring_by_id(int(r_id))
                if data:
                    form = self.query_one("#view-nowe-cykliczne")
                    form.load_existing_data(data)
                    await self._go_view("view-nowe-cykliczne", f"EDYCJA {self._rr_code_from_id(r_id)}")
                    self.query_one("#rec-input-type").focus()
            except Exception as e:
                logging.error(f"Błąd edycji rec: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-rec-pause":
            try:
                view = self.query_one("#view-cykliczne")
                r_id = view.get_selected_recurring_id()
                if not r_id: return self.notify("Zaznacz płatność!", severity="warning")
                new_status = toggle_recurring_pause(int(r_id))
                self.notify(f"{self._rr_code_from_id(r_id)} → status: {'AKTYWNA' if new_status else 'WSTRZYMANA'}")
                view.load_data()
            except Exception as e:
                logging.error(f"Błąd pauzy rec: {e}")
                self.notify(f"Błąd: {e}", severity="error")
            return

        if btn_id == "ft-rec-delete":
            try:
                view = self.query_one("#view-cykliczne")
                r_id = view.get_selected_recurring_id()
                if not r_id: return self.notify("Zaznacz płatność!", severity="warning")
                rr_code = self._rr_code_from_id(r_id)

                def do_delete_rec(result):
                    is_confirmed, dont_ask = result if result else (False, False)
                    if not is_confirmed: return
                    if dont_ask: set_setting("skip_delete_confirm", "1")
                    ok, msg = delete_recurring(int(r_id))
                    if not ok: return self.notify(f"Błąd: {msg}", severity="error")
                    self.notify(f"Usunięto {rr_code}!")
                    view.load_data()

                if get_setting("skip_delete_confirm") == "1":
                    do_delete_rec((True, False))
                else:
                    self.app.push_screen(ConfirmationModal(f"Usunąć {rr_code}?", True), do_delete_rec)
            except Exception as e:
                logging.error(f"Błąd usuwania rec: {e}")
            return

        # ================== ZAPISZ / ANULUJ ==================
        if btn_id == "ft-save":
            try:
                if current_view == "view-nowa-tranzakcja":
                    form = self.query_one("#view-nowa-tranzakcja")
                    data, error = form.get_data_and_validate()
                    if error: return self.notify(error, severity="error")

                    if form.editing_id:
                        update_transaction(form.editing_id, data["date"], data["type"], data["category"],
                                           data["account"], data["shop"], data["amount"], data["desc"], data["is_reg"])
                        self.notify(f"Zaktualizowano {self._tx_code_from_id(form.editing_id)}!")
                    else:
                        add_transaction(data["date"], data["type"], data["category"], data["account"], data["shop"],
                                        data["amount"], data["desc"], data["is_reg"])
                        self.notify("Dodano nową transakcję!")

                    self._refresh_after_login()
                    await self._go_view("view-tranzakcje", "TRANZAKCJE GŁÓWNY")

                elif current_view == "view-nowa-kategoria":
                    form = self.query_one("#view-nowa-kategoria")
                    data, error = form.get_data_and_validate()
                    if error: return self.notify(error, severity="error")
                    if form.editing_id:
                        success, msg = update_category(form.editing_id, data["name"], data["limit"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify(f"Zaktualizowano {self._ct_code_from_id(form.editing_id)}!")
                    else:
                        success, msg = add_category(data["name"], data["limit"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify("Dodano nową kategorię!")
                    self._safe_load("#view-kategorie")
                    await self._go_view("view-kategorie", "KATEGORIE GŁÓWNY")

                elif current_view == "view-nowa-skarbonka":
                    form = self.query_one("#view-nowa-skarbonka")
                    data, error = form.get_data_and_validate()
                    if error: return self.notify(error, severity="error")
                    if form.editing_id:
                        success, msg = update_piggy_bank(form.editing_id, data["name"], data["target"], data["account"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify(f"Zaktualizowano {self._pb_code_from_id(form.editing_id)}!")
                    else:
                        success, msg = add_piggy_bank(data["name"], data["target"], data["account"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify("Dodano nowy cel!")
                    self._safe_load("#view-skarbonki")
                    await self._go_view("view-skarbonki", "SKARBONKI GŁÓWNY")

                elif current_view == "view-nowe-cykliczne":
                    form = self.query_one("#view-nowe-cykliczne")
                    data, error = form.get_data_and_validate()
                    if error: return self.notify(error, severity="error")
                    if form.editing_id:
                        success, msg = update_recurring(form.editing_id, data["name"], data["amount"], data["type"],
                                                        data["category"], data["account"], data["cycle"],
                                                        data["start_date"], data["is_registered"], data["piggy_id"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify(f"Zaktualizowano {self._rr_code_from_id(form.editing_id)}!")
                    else:
                        success, msg = add_recurring(data["name"], data["amount"], data["type"], data["category"],
                                                     data["account"], data["cycle"], data["start_date"],
                                                     data["is_registered"], data["piggy_id"])
                        if not success: return self.notify(msg, severity="error")
                        self.notify("Dodano płatność cykliczną!")
                    self._safe_load("#view-cykliczne")
                    await self._go_view("view-cykliczne", "PŁATNOŚCI CYKLICZNE")

            except Exception as e:
                logging.error(f"BŁĄD ZAPISU: {e}")
                self.notify(f"BŁĄD ZAPISU: {e}", severity="error")
            return

        if btn_id == "ft-cancel":
            if current_view == "view-nowa-tranzakcja":
                await self._go_view("view-tranzakcje", "TRANZAKCJE GŁÓWNY")
            elif current_view == "view-nowa-kategoria":
                await self._go_view("view-kategorie", "KATEGORIE GŁÓWNY")
            elif current_view in ("view-nowa-skarbonka", "view-op-skarbonka"):
                await self._go_view("view-skarbonki", "SKARBONKI GŁÓWNY")
            elif current_view == "view-nowe-cykliczne":
                await self._go_view("view-cykliczne", "PŁATNOŚCI CYKLICZNE")
            else:
                await self._go_view("view-pulpit", "PULPIT GŁÓWNY")
            return

        # ================== SYSTEM I RAPORTY ==================
        if btn_id == "ft-exit": self.app.exit(); return
        if btn_id == "ft-logout":
            if hasattr(self.app, "clear_session"): self.app.clear_session()
            self.app.switch_screen("login")
            return
        if btn_id == "ft-refresh":
            self.notify("Odświeżanie...")
            try:
                count = process_due_payments()
                if count > 0: self.notify(f"Przetworzono {count} cyklicznych!", severity="information")
            except Exception as e:
                logging.error(f"Błąd manualnego odświeżania: {e}")
            self._refresh_after_login()
            return

        if btn_id == "btn-gen-report":
            try:
                self.query_one("#view-raporty").update_report()
                self.notify("Raport wygenerowany!")
            except Exception as e:
                logging.error(f"Błąd raportu: {e}")
                self.notify("Błąd raportu.", severity="error")
            return

        # ================== USTAWIENIA ==================
        if btn_id == "btn-set-month":
            try:
                view_set = self.query_one("#view-ustawienia")
                y = view_set.query_one("#set-year", Input).value.strip()
                m = view_set.query_one("#set-month", Select).value

                if not y or len(y) != 4 or not m or m == Select.BLANK:
                    self.notify("Podaj poprawny rok (YYYY) i wybierz miesiąc!", severity="warning")
                    return

                new_ym = f"{y}-{m}"
                set_active_month_str(new_ym)

                self.notify(f"Miesiąc roboczy zmieniony na: {new_ym}", severity="information")
                self._refresh_after_login()
            except Exception as e:
                logging.error(f"Błąd zmiany miesiąca: {e}")
                self.notify(f"Błąd zmiany miesiąca: {e}", severity="error")
            return

        if btn_id == "btn-delete-user":
            try:
                view_set = self.query_one("#view-ustawienia")
                sel_user_id = view_set.query_one("#sel-user-delete", Select).value
                if not sel_user_id or sel_user_id == Select.BLANK:
                    self.notify("Wybierz użytkownika do usunięcia!", severity="warning")
                    return

                target_username = getattr(view_set, "_user_label_by_id", {}).get(sel_user_id, "Nieznany")
                cu_name = getattr(self.app, "current_username", "")
                cu_id = getattr(self.app, "current_user_id", "")

                def on_user_deleted(result):
                    if result:
                        self._safe_load("#view-ustawienia")

                self.app.push_screen(DeleteUserModal(str(sel_user_id), target_username, cu_name, cu_id),
                                     on_user_deleted)
            except Exception as e:
                logging.error(f"Błąd wywoływania modalu usuwania usera: {e}")
            return

        if btn_id == "btn-change-pass":
            try:
                cu_id = getattr(self.app, "current_user_id", None)
                cu_name = getattr(self.app, "current_username", None)
                if not cu_id: return
                self.app.push_screen(ChangePasswordModal(cu_name, cu_id))
            except Exception as e:
                logging.error(f"Błąd wywoływania modalu zmiany hasła: {e}")
            return

        if btn_id == "btn-set-balance":
            try:
                c = float(self.query_one("#set-bal-card").value.replace(",", "."))
                g = float(self.query_one("#set-bal-cash").value.replace(",", "."))
                set_account_balance("Karta", c)
                set_account_balance("Gotówka", g)
                self.notify("Saldo zaktualizowane!")
                self._safe_load("#view-pulpit")
            except Exception as e:
                logging.error(f"Błąd zmiany salda: {e}")
                self.notify("Błąd kwoty!", severity="error")
            return
        if btn_id == "btn-export-backup":
            try:
                cu_name = getattr(self.app, "current_username", "")
                self.app.push_screen(ExportBackupModal(cu_name))
            except Exception as e:
                logging.error(f"Błąd modalu eksportu: {e}")
            return
        # Opcjonalny przycisk resetu bazy (dodany dla kompletności Ustawień)
        if btn_id == "btn-reset-db":
            try:
                def confirm_reset(result):
                    is_confirmed, _ = result if result else (False, False)
                    if not is_confirmed: return
                    reset_user_db_hard()
                    self.notify("Baza danych zresetowana!", severity="warning")
                    self._refresh_after_login()

                self.app.push_screen(
                    ConfirmationModal("CZY NA PEWNO CHCESZ ZRESETOWAĆ DANE? (Wszystkie transakcje znikną!)",
                                      show_checkbox=False),
                    confirm_reset
                )
            except Exception as e:
                logging.error(f"Błąd wywoływania modalu resetowania bazy: {e}")
            return