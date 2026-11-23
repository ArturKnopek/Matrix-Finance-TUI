"""
Auto-oszczędzanie — reguły uruchamiane przy każdym zapisanym wpływie/wydatku.

Tryby (`mode`):
    income_percent – X% każdego DOCHODU na koncie źródłowym trafia do celu/na konto,
    roundup        – każdy WYDATEK zaokrąglany w górę do pełnych N zł, różnica jest odkładana
                     (jak „zaokrąglenia” w Revolut).

Cel reguły (`target_kind`): "account" (nazwa konta) albo "goal" (id celu).
Reguła nie wykona się, gdy na koncie źródłowym brakuje środków.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.finance.storage import now_iso, open_user_db

MODES = {
    "income_percent": "% każdego wpływu",
    "roundup": "Zaokrąglanie wydatków",
}
log = logging.getLogger(__name__)


def get_autosave_rules(source_account: Optional[str] = None) -> List[sqlite3.Row]:
    query = "SELECT * FROM autosave_rules"
    params: Tuple[Any, ...] = ()
    if source_account:
        query += " WHERE source_account = ?"
        params = (source_account,)
    with open_user_db() as conn:
        return conn.execute(query + " ORDER BY id", params).fetchall()


def get_autosave_rule(rule_id: int):
    with open_user_db() as conn:
        return conn.execute("SELECT * FROM autosave_rules WHERE id = ?", (rule_id,)).fetchone()


def _validate(mode: str, value: float, source: str, target_kind: str, target: str) -> Optional[str]:
    if mode not in MODES:
        return "Nieznany tryb reguły."
    if mode == "income_percent" and not (0 < value <= 100):
        return "Procent musi być z zakresu 0–100."
    if mode == "roundup" and value <= 0:
        return "Krok zaokrąglenia musi być większy od zera."
    if target_kind not in ("account", "goal"):
        return "Cel reguły musi być kontem albo celem oszczędnościowym."
    if target_kind == "account" and target == source:
        return "Konto docelowe musi być inne niż źródłowe."
    return None


def save_autosave_rule(source_account: str, mode: str, value: float, target_kind: str, target: str,
                       name: str = "", is_active: bool = True, rule_id: Optional[int] = None) -> Tuple[bool, str]:
    error = _validate(mode, float(value), source_account, target_kind, str(target))
    if error:
        return False, error
    with open_user_db(write=True) as conn:
        if rule_id:
            conn.execute(
                "UPDATE autosave_rules SET name=?, source_account=?, mode=?, value=?, target_kind=?, target=?, "
                "is_active=? WHERE id=?",
                (name, source_account, mode, float(value), target_kind, str(target), int(is_active), rule_id))
        else:
            conn.execute(
                "INSERT INTO autosave_rules (name, source_account, mode, value, target_kind, target, is_active, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, source_account, mode, float(value), target_kind, str(target), int(is_active), now_iso()))
    return True, ""


def delete_autosave_rule(rule_id: int) -> None:
    with open_user_db(write=True) as conn:
        conn.execute("DELETE FROM autosave_rules WHERE id = ?", (rule_id,))


def toggle_autosave_rule(rule_id: int) -> bool:
    with open_user_db(write=True) as conn:
        row = conn.execute("SELECT is_active FROM autosave_rules WHERE id = ?", (rule_id,)).fetchone()
        if not row:
            return False
        new = 0 if int(row[0]) else 1
        conn.execute("UPDATE autosave_rules SET is_active = ? WHERE id = ?", (new, rule_id))
        return bool(new)


def compute_autosave_amount(mode: str, value: float, t_type: str, amount: float) -> float:
    """Ile odłożyć dla danego wpisu (0 = reguła nie dotyczy)."""
    amount = abs(float(amount))
    if mode == "income_percent" and t_type == "Dochód":
        return round(amount * float(value) / 100.0, 2)
    if mode == "roundup" and t_type == "Wydatek" and value > 0:
        rounded = math.ceil(round(amount / value, 6)) * value
        return round(rounded - amount, 2)
    return 0.0


def describe_rule(rule: Any) -> str:
    r = dict(rule)
    if r["mode"] == "income_percent":
        how = f"{float(r['value']):g}% każdego wpływu"
    else:
        how = f"zaokrąglaj wydatki do {float(r['value']):g} zł"
    return f"{r['source_account']}: {how}"


def apply_autosave_rules(conn: sqlite3.Connection, account: str, t_type: str, amount: float, day: str,
                         source_label: str = "") -> List[Dict[str, Any]]:
    """Wykonuje pasujące reguły w ramach przekazanej transakcji SQL. Zwraca listę wykonanych odłożeń."""
    from src.finance.accounts import _transfer
    from src.finance.goals import move_goal_funds
    from src.finance.ledger import account_balance_in

    done: List[Dict[str, Any]] = []
    rules = conn.execute("SELECT * FROM autosave_rules WHERE is_active = 1 AND source_account = ?",
                         (account,)).fetchall()
    for rule in rules:
        save = compute_autosave_amount(rule["mode"], rule["value"], t_type, amount)
        if save <= 0:
            continue
        if account_balance_in(conn, account) + 1e-9 < save:
            log.info("Auto-oszczędzanie pominięte (brak środków): %s", describe_rule(rule))
            continue
        note = f"[AUTO] {describe_rule(rule)}" + (f" · {source_label}" if source_label else "")
        try:
            if rule["target_kind"] == "goal":
                move_goal_funds(conn, int(rule["target"]), save, account, day, note)
            else:
                if not conn.execute("SELECT 1 FROM accounts WHERE name=? AND is_active=1",
                                    (rule["target"],)).fetchone():
                    continue
                _transfer(conn, account, rule["target"], save, day, note, group_prefix="auto")
            done.append({"rule_id": rule["id"], "amount": save, "target": rule["target"]})
        except ValueError as e:
            log.info("Auto-oszczędzanie pominięte: %s", e)
    return done


def autosave_total_in_month(ym: str) -> float:
    """Ile odłożono automatycznie w miesiącu (po stronie konta źródłowego)."""
    with open_user_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE date LIKE ? AND description LIKE '[AUTO]%' "
            "AND entry_subtype IN ('transfer_out', 'goal_out')", (f"{ym}%",)).fetchone()
    return float(row[0] or 0.0)
