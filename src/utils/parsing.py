"""
Parsowanie danych wpisywanych przez użytkownika (daty, kwoty).

Daty (parse_user_date):
    ""            -> dziś
    "dziś"/"d"    -> dziś,  "wczoraj"/"w" -> wczoraj
    "12"          -> 12. dzień miesiąca bazowego (miesiąc roboczy)
    "12.05", "12-05", "12/05"          -> 12 maja roku bazowego
    "12.05.2026", "12-05-2026"         -> pełna data
    "2026-05-12"                        -> ISO

Kwoty (parse_amount):
    "12,50", "1 200,50", "1200.5" oraz proste działania: "12.5+3*2", "(10+5)/3"
"""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

_DATE_SPLIT = re.compile(r"[.\-/]")


def _base_year_month(base_ym: Optional[str]) -> Tuple[int, int]:
    if base_ym:
        try:
            y, m = base_ym.split("-")[:2]
            return int(y), int(m)
        except (ValueError, AttributeError):
            pass
    today = date.today()
    return today.year, today.month


def parse_user_date(raw: str, base_ym: Optional[str] = None, today: Optional[date] = None) -> Optional[str]:
    """Zwraca datę w formacie YYYY-MM-DD albo None, jeśli nie da się jej odczytać."""
    today = today or date.today()
    text = (raw or "").strip().lower()

    if text in ("", "dziś", "dzis", "d", "today"):
        return today.isoformat()
    if text in ("wczoraj", "w", "yesterday"):
        return (today - timedelta(days=1)).isoformat()

    base_year, base_month = _base_year_month(base_ym)
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        parts = [p for p in _DATE_SPLIT.split(text) if p != ""]
        if not parts or not all(p.isdigit() for p in parts):
            return None
        if len(parts) == 1 and len(parts[0]) <= 2:
            return date(base_year, base_month, int(parts[0])).isoformat()
        if len(parts) == 2:
            return date(base_year, int(parts[1]), int(parts[0])).isoformat()
        if len(parts) == 3:
            day, month, year = (int(p) for p in parts)
            if year < 100:
                year += 2000
            return date(year, month, day).isoformat()
    except ValueError:
        return None
    return None


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("Niedozwolone wyrażenie")


def parse_amount(raw: str) -> Optional[float]:
    """Zwraca kwotę zaokrągloną do groszy albo None przy błędzie."""
    text = (raw or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not text or len(text) > 64:
        return None
    if not re.fullmatch(r"[0-9.+\-*/()]+", text):
        return None
    try:
        value = _eval_node(ast.parse(text, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError, RecursionError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return round(value, 2)


AMOUNT_RESTRICT = r"^[0-9.,+\-*/() ]*$"
