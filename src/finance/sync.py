"""
Synchronizacja telefon ↔ komputer przez plik (np. w folderze OneDrive).

Zasada („komputer = baza główna”):

    KOMPUTER                                   TELEFON
    ─────────                                  ───────
    MatrixFinance.mfsync  ───── OneDrive ────▶ wczytuje migawkę (pełne dane)
    (zaszyfrowana migawka wszystkich danych       + ponownie stosuje swoje operacje,
     + lista zastosowanych operacji telefonu)     których komputer jeszcze nie ma

    stosuje operacje (każdą tylko raz) ◀────── telefon-XXXX.mfops
                                                (zaszyfrowana lista operacji:
                                                 wydatki, przelewy, korekty…)

* Telefon zapisuje każdą swoją zmianę jako OPERACJĘ (z unikalnym id) w „skrzynce
  nadawczej” (tabela sync_outbox) i od razu stosuje ją u siebie.
* Komputer przy synchronizacji czyta wszystkie pliki *.mfops z folderu, stosuje
  operacje, których jeszcze nie zna (tabela sync_applied), i zapisuje nową migawkę.
  Przetworzone pliki trafiają do podfolderu „przetworzone”.
* Telefon po wczytaniu migawki usuwa ze skrzynki operacje potwierdzone przez
  komputer (zastosowane albo odrzucone), a pozostałe stosuje ponownie — nic nie ginie,
  nawet jeśli plik z operacjami zostanie zapisany kilka razy (np. „telefon (1).mfops”).
* Oba pliki są szyfrowane hasłem synchronizacji (AES/Fernet, klucz z PBKDF2).

Operacje odwołują się do stałych identyfikatorów: tx_uid transakcji, group_id
przelewu, nazw kont i kopert oraz id celów (z migawki, więc wspólnych dla obu urządzeń).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.finance import accounts as acc_api
from src.finance import envelopes as env_api
from src.finance import goals as goals_api
from src.finance import ledger
from src.finance.storage import get_setting_in, now_iso, open_user_db, set_setting_in
from src.utils.crypto_utils import decrypt_bytes, encrypt_bytes, write_atomic

log = logging.getLogger(__name__)

SNAPSHOT_FILE = "MatrixFinance.mfsync"
OPS_SUFFIX = ".mfops"
PROCESSED_DIR = "przetworzone"
SNAPSHOT_FORMAT = "matrix-finance-sync"
OPS_FORMAT = "matrix-finance-ops"
SYNC_VERSION = 1
KEEP_PROCESSED_FILES = 30
APPLIED_IN_SNAPSHOT = 5000  # tyle ostatnich identyfikatorów operacji trafia do migawki

# ustawienia tego urządzenia (nie wędrują z danymi — patrz data_io.LOCAL_SETTING_PREFIXES)
SET_FOLDER = "sync_folder"
SET_PASSWORD = "sync_password"
SET_AUTO = "sync_auto"
SET_LAST = "sync_last"
SET_LAST_INFO = "sync_last_info"
SET_DEVICE_ID = "sync_device_id"
SET_SNAPSHOT_ID = "sync_snapshot_id"
SET_SNAPSHOT_AT = "sync_snapshot_at"
SET_DATA_HASH = "sync_data_hash"


class SyncError(Exception):
    """Błąd synchronizacji z komunikatem dla użytkownika."""


# =============================================================================
# Ustawienia
# =============================================================================

def get_sync_setting(key: str, default: str = "") -> str:
    with open_user_db() as conn:
        return get_setting_in(conn, key, default)


def set_sync_setting(key: str, value: Any) -> None:
    with open_user_db(write=True) as conn:
        set_setting_in(conn, key, value)


def default_sync_folder() -> Path:
    """Folder w OneDrive (Windows: zmienne OneDrive / OneDriveConsumer / OneDriveCommercial)."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(var, "").strip()
        if root and Path(root).is_dir():
            return Path(root) / "MatrixFinance"
    for name in ("OneDrive", "OneDrive - Personal"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate / "MatrixFinance"
    return Path.home() / "OneDrive" / "MatrixFinance"


def onedrive_detected() -> bool:
    return default_sync_folder().parent.is_dir()


def device_id() -> str:
    did = get_sync_setting(SET_DEVICE_ID)
    if not did:
        did = uuid.uuid4().hex[:12]
        set_sync_setting(SET_DEVICE_ID, did)
    return did


# =============================================================================
# Operacje
# =============================================================================

def new_uid(prefix: str = "m") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _category_id(name: str) -> int:
    with open_user_db() as conn:
        row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if not row:
        raise ValueError(f"Nie ma koperty „{name}”.")
    return int(row[0])


def _goal_id(data: Dict[str, Any]) -> int:
    with open_user_db() as conn:
        if data.get("goal_id") is not None:
            row = conn.execute("SELECT id FROM piggy_banks WHERE id = ?", (int(data["goal_id"]),)).fetchone()
            if row:
                return int(row[0])
        row = conn.execute("SELECT id FROM piggy_banks WHERE name = ?", (data.get("goal_name") or "",)).fetchone()
    if not row:
        raise ValueError(f"Nie ma celu „{data.get('goal_name') or data.get('goal_id')}”.")
    return int(row[0])


def _row_id_by_uid(uid: str) -> Optional[int]:
    row = ledger.get_transaction_by_uid(uid)
    return int(row["id"]) if row else None


def _op_tx_add(d: Dict[str, Any], strict: bool) -> None:
    if _row_id_by_uid(d["uid"]):
        return  # już jest (operacja zastosowana wcześniej)
    ledger.add_transaction(d["date"], d["type"], d.get("category"), d["account"], d.get("shop") or "",
                           float(d["amount"]), d.get("desc") or "", True, tx_uid=d["uid"])


def _op_tx_update(d: Dict[str, Any], strict: bool) -> None:
    t_id = _row_id_by_uid(d["uid"])
    if not t_id:
        raise ValueError("Edytowana transakcja nie istnieje (została usunięta?).")
    ledger.update_transaction(t_id, d["date"], d["type"], d.get("category"), d["account"], d.get("shop") or "",
                              float(d["amount"]), d.get("desc") or "", True)


def _op_tx_delete(d: Dict[str, Any], strict: bool) -> None:
    t_id = _row_id_by_uid(d["uid"])
    if t_id:
        ledger.delete_transaction(t_id)


def _op_transfer(d: Dict[str, Any], strict: bool) -> None:
    if _row_id_by_uid(f"{d['group']}:out"):
        return
    acc_api.transfer_between_accounts(d["source"], d["target"], float(d["amount"]), d["date"], d.get("note") or "",
                                      check_funds=strict, group_id=d["group"])


def _op_goal_move(d: Dict[str, Any], strict: bool) -> None:
    if _row_id_by_uid(d["uid"]):
        return
    p_id = _goal_id(d)
    with open_user_db(write=True) as conn:
        goals_api.move_goal_funds(conn, p_id, float(d["amount"]), d["account"], d["date"], d.get("note") or "",
                                  check_funds=strict, tx_uid=d["uid"])


def _op_goal_set(d: Dict[str, Any], strict: bool) -> None:
    goals_api.set_goal_amount(_goal_id(d), float(d["amount"]))


def _op_account_set_balance(d: Dict[str, Any], strict: bool) -> None:
    if _row_id_by_uid(d["uid"]):
        return
    acc_api.set_account_balance(d["account"], float(d["balance"]), d.get("note") or "Korekta salda (telefon)",
                                d.get("date"), tx_uid=d["uid"])


def _op_envelope_adjust(d: Dict[str, Any], strict: bool) -> None:
    env_api.adjust_envelope(_category_id(d["category"]), d["ym"], float(d["amount"]), d.get("note") or "")


def _op_envelope_set(d: Dict[str, Any], strict: bool) -> None:
    env_api.set_envelope_remaining(_category_id(d["category"]), d["ym"], float(d["remaining"]), d.get("note") or "")


def _op_envelope_move(d: Dict[str, Any], strict: bool) -> None:
    src, dst = _category_id(d["source"]), _category_id(d["target"])
    if strict:
        env_api.move_between_envelopes(src, dst, d["ym"], float(d["amount"]))
    else:  # u komputera mogło być już mniej w kopercie — przesunięcie i tak wykonujemy
        amount = float(d["amount"])
        env_api.adjust_envelope(src, d["ym"], -amount, f"Przesunięcie do: {d['target']}")
        env_api.adjust_envelope(dst, d["ym"], amount, f"Przesunięcie z: {d['source']}")


OPERATIONS: Dict[str, Tuple[str, Callable[[Dict[str, Any], bool], None]]] = {
    "tx.add": ("Nowa transakcja", _op_tx_add),
    "tx.update": ("Edycja transakcji", _op_tx_update),
    "tx.delete": ("Usunięcie transakcji", _op_tx_delete),
    "transfer": ("Przelew", _op_transfer),
    "goal.move": ("Wpłata/wypłata z celu", _op_goal_move),
    "goal.set": ("Korekta celu", _op_goal_set),
    "account.set_balance": ("Korekta salda", _op_account_set_balance),
    "envelope.adjust": ("Korekta koperty", _op_envelope_adjust),
    "envelope.set_remaining": ("Korekta koperty", _op_envelope_set),
    "envelope.move": ("Przesunięcie między kopertami", _op_envelope_move),
}


def make_op(op: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if op not in OPERATIONS:
        raise ValueError(f"Nieznana operacja: {op}")
    return {"id": new_uid("op"), "ts": now_iso(), "op": op, "data": data}


def apply_op(op: Dict[str, Any], strict: bool = True) -> None:
    """Stosuje operację. strict=True: pełne sprawdzenia (np. brak środków); False: przy odtwarzaniu."""
    entry = OPERATIONS.get(op.get("op", ""))
    if not entry:
        raise ValueError(f"Nieznana operacja: {op.get('op')}")
    entry[1](op.get("data") or {}, strict)


def describe_op(op: Dict[str, Any]) -> str:
    d = op.get("data") or {}
    label = OPERATIONS.get(op.get("op", ""), (op.get("op", "?"), None))[0]
    details = []
    if "amount" in d:
        details.append(f"{float(d['amount']):.2f} zł".replace(".", ","))
    for key in ("shop", "category", "account", "source", "target", "goal_name"):
        if d.get(key):
            details.append(str(d[key]))
    return f"{label}: " + " · ".join(details[:3]) if details else label


# =============================================================================
# Telefon: skrzynka nadawcza
# =============================================================================

def record_op(op_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Telefon: stosuje operację lokalnie (ze sprawdzeniami) i odkłada ją do wysłania."""
    op = make_op(op_name, data)
    apply_op(op, strict=True)
    with open_user_db(write=True) as conn:
        conn.execute("INSERT INTO sync_outbox (op_id, ts, op, data) VALUES (?, ?, ?, ?)",
                     (op["id"], op["ts"], op["op"], json.dumps(op["data"], ensure_ascii=False)))
    return op


def pending_ops() -> List[Dict[str, Any]]:
    with open_user_db() as conn:
        rows = conn.execute("SELECT * FROM sync_outbox ORDER BY ts, rowid").fetchall()
    return [{"id": r["op_id"], "ts": r["ts"], "op": r["op"], "data": json.loads(r["data"])} for r in rows]


def build_ops_file(password: str, device_name: str = "Telefon") -> bytes:
    payload = {"format": OPS_FORMAT, "version": SYNC_VERSION, "device_id": device_id(), "device_name": device_name,
               "created_at": now_iso(), "ops": pending_ops()}
    return encrypt_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), _require_password(password))


def ops_file_name() -> str:
    return f"telefon-{device_id()[:6]}{OPS_SUFFIX}"


@dataclass
class SnapshotImport:
    created_at: str = ""
    confirmed: int = 0
    replayed: int = 0
    rejected: List[str] = field(default_factory=list)  # opisy operacji odrzuconych przez komputer
    failed: List[str] = field(default_factory=list)  # nie dały się ponownie zastosować (zostają w skrzynce)


def import_snapshot_bytes(raw: bytes, password: str) -> SnapshotImport:
    """Telefon: wczytuje migawkę z komputera i ponownie stosuje niepotwierdzone operacje."""
    from src.finance.data_io import import_data_dict

    payload = _decrypt_json(raw, password, SNAPSHOT_FORMAT)
    meta = payload["sync"]
    applied: Dict[str, str] = meta.get("applied") or {}
    rejected_msgs: Dict[str, str] = meta.get("rejected") or {}
    result = SnapshotImport(created_at=meta.get("created_at", ""))
    outbox = pending_ops()
    import_data_dict(payload)
    still_pending = []
    for op in outbox:
        status = applied.get(op["id"])
        if status == "ok":
            result.confirmed += 1
        elif status == "rejected":
            result.rejected.append(f"{describe_op(op)} — {rejected_msgs.get(op['id'], 'odrzucona')}")
        else:
            still_pending.append(op)
    with open_user_db(write=True) as conn:
        for op in outbox:
            if op not in still_pending:
                conn.execute("DELETE FROM sync_outbox WHERE op_id = ?", (op["id"],))
    for op in still_pending:  # jeszcze nie dotarły do komputera — muszą być widoczne na telefonie
        try:
            apply_op(op, strict=False)
            result.replayed += 1
        except ValueError as e:
            result.failed.append(f"{describe_op(op)} — {e}")
    with open_user_db(write=True) as conn:
        set_setting_in(conn, SET_SNAPSHOT_ID, meta.get("snapshot_id", ""))
        set_setting_in(conn, SET_SNAPSHOT_AT, meta.get("created_at", ""))
        set_setting_in(conn, SET_LAST, now_iso())
    return result


# =============================================================================
# Komputer: migawka + stosowanie operacji z telefonu
# =============================================================================

@dataclass
class SyncResult:
    folder: Path
    snapshot: Optional[Path] = None
    applied: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)
    processed_files: int = 0

    def summary(self) -> str:
        parts = []
        if self.applied:
            parts.append(f"z telefonu: {len(self.applied)} operacji")
        if self.rejected:
            parts.append(f"odrzucono: {len(self.rejected)}")
        if self.skipped_files:
            parts.append(f"pominięte pliki: {len(self.skipped_files)}")
        parts.append("migawka zapisana" if self.snapshot else "bez zmian")
        return " · ".join(parts)


def build_snapshot_bytes(password: str) -> bytes:
    from src.finance.data_io import export_data_dict
    from src.version import APP_VERSION

    payload = export_data_dict()
    with open_user_db() as conn:
        rows = conn.execute("SELECT op_id, status, message FROM sync_applied ORDER BY applied_at DESC LIMIT ?",
                            (APPLIED_IN_SNAPSHOT,)).fetchall()
    payload["sync"] = {
        "format": SNAPSHOT_FORMAT, "version": SYNC_VERSION, "snapshot_id": uuid.uuid4().hex,
        "created_at": now_iso(), "device": "PC", "app_version": APP_VERSION,
        "applied": {r["op_id"]: r["status"] for r in rows},
        "rejected": {r["op_id"]: r["message"] or "" for r in rows if r["status"] == "rejected"},
    }
    return encrypt_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), _require_password(password))


def apply_ops_payload(payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Komputer: stosuje operacje z pliku telefonu (każdą tylko raz). Zwraca (zastosowane, odrzucone)."""
    applied, rejected = [], []
    device = str(payload.get("device_id") or "?")
    with open_user_db() as conn:
        known = {r[0] for r in conn.execute("SELECT op_id FROM sync_applied").fetchall()}
    for op in sorted(payload.get("ops") or [], key=lambda o: o.get("ts", "")):
        if not op.get("id") or op["id"] in known:
            continue
        status, message = "ok", ""
        try:
            apply_op(op, strict=False)
            applied.append(describe_op(op))
        except Exception as e:  # operacja odrzucona — telefon dostanie informację w migawce
            status, message = "rejected", str(e)
            rejected.append(f"{describe_op(op)} — {e}")
            log.warning("Odrzucono operację z telefonu %s: %s", op.get("op"), e)
        with open_user_db(write=True) as conn:
            conn.execute("INSERT OR REPLACE INTO sync_applied (op_id, device, op, status, message, applied_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (op["id"], device, op.get("op"), status, message, now_iso()))
        known.add(op["id"])
    return applied, rejected


def data_fingerprint() -> str:
    from src.finance.data_io import export_data_dict

    return hashlib.sha256(json.dumps(export_data_dict()["tables"], sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()


def sync_folder_now(folder: Optional[Path] = None, password: Optional[str] = None,
                    only_if_changed: bool = False) -> SyncResult:
    """
    Komputer: pełna synchronizacja z folderem (OneDrive).
    only_if_changed=True: migawka zapisywana tylko, gdy dane się zmieniły (mniej wysyłania przez OneDrive).
    """
    folder = Path(folder or get_sync_setting(SET_FOLDER) or default_sync_folder()).expanduser()
    password = _require_password(password if password is not None else get_sync_setting(SET_PASSWORD))
    folder.mkdir(parents=True, exist_ok=True)
    result = SyncResult(folder=folder)
    processed = folder / PROCESSED_DIR
    for path in sorted(folder.glob(f"*{OPS_SUFFIX}"), key=lambda p: p.stat().st_mtime):
        try:
            payload = _decrypt_json(path.read_bytes(), password, OPS_FORMAT)
        except (SyncError, OSError) as e:
            result.skipped_files.append(f"{path.name}: {e}")
            continue
        applied, rejected = apply_ops_payload(payload)
        result.applied += applied
        result.rejected += rejected
        processed.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            shutil.move(str(path), str(processed / f"{stamp}_{path.name}"))
        except OSError:
            pass  # np. plik jeszcze synchronizowany — następnym razem zostanie pominięty (operacje znane)
        result.processed_files += 1
    _trim_processed(processed)
    snapshot = folder / SNAPSHOT_FILE
    fingerprint = data_fingerprint()
    unchanged = (only_if_changed and snapshot.exists() and not result.processed_files
                 and fingerprint == get_sync_setting(SET_DATA_HASH))
    if not unchanged:
        write_atomic(snapshot, build_snapshot_bytes(password))
        result.snapshot = snapshot
        with open_user_db(write=True) as conn:
            set_setting_in(conn, SET_DATA_HASH, fingerprint)
            set_setting_in(conn, SET_LAST, now_iso())
            set_setting_in(conn, SET_LAST_INFO, result.summary())
    return result


def _trim_processed(processed: Path) -> None:
    if not processed.is_dir():
        return
    files = sorted(processed.glob(f"*{OPS_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_PROCESSED_FILES:]:
        try:
            old.unlink()
        except OSError:
            pass


def is_configured() -> bool:
    return bool(get_sync_setting(SET_PASSWORD))


def auto_enabled() -> bool:
    return is_configured() and get_sync_setting(SET_AUTO, "1") == "1"


# =============================================================================
# Pomocnicze
# =============================================================================

def _require_password(password: Optional[str]) -> str:
    if not password:
        raise SyncError("Ustaw hasło synchronizacji (to samo na komputerze i telefonie).")
    return password


def _decrypt_json(raw: bytes, password: str, expected_format: str) -> Dict[str, Any]:
    try:
        data = json.loads(decrypt_bytes(raw, _require_password(password)).decode("utf-8"))
    except SyncError:
        raise
    except Exception:
        raise SyncError("Nie udało się odczytać pliku — złe hasło synchronizacji albo uszkodzony plik.")
    fmt = (data.get("sync") or {}).get("format") if expected_format == SNAPSHOT_FORMAT else data.get("format")
    if fmt != expected_format:
        raise SyncError("To nie jest plik synchronizacji Matrix Finance.")
    if int(((data.get("sync") or data).get("version")) or 0) > SYNC_VERSION:
        raise SyncError("Plik pochodzi z nowszej wersji programu — zaktualizuj aplikację.")
    return data


def today() -> str:
    return date.today().isoformat()


def format_stamp(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return "—"


__all__: Iterable[str] = [
    "SyncError", "SyncResult", "SnapshotImport", "OPERATIONS", "record_op", "apply_op", "make_op", "pending_ops",
    "build_ops_file", "ops_file_name", "import_snapshot_bytes", "build_snapshot_bytes", "apply_ops_payload",
    "sync_folder_now", "default_sync_folder", "onedrive_detected", "device_id", "describe_op", "new_uid",
]
