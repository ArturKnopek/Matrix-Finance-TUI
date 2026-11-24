"""Synchronizacja telefon ↔ komputer przez wspólny folder (symulacja dwóch urządzeń)."""
from __future__ import annotations

import uuid

import pytest

from src.finance import accounts, envelopes, goals, ledger, storage, sync

PASSWORD = "haslo-sync"
YM = "2026-03"


class Devices:
    """Dwie bazy (PC i telefon) w jednym procesie — przełączamy aktywną bazę."""

    def __init__(self) -> None:
        self.pc = uuid.uuid4().hex
        self.phone = uuid.uuid4().hex
        storage.init_user_db(storage.set_active_user_db(self.phone), 0, 0)
        storage.init_user_db(storage.set_active_user_db(self.pc), 1000, 200)

    def use(self, which: str) -> None:
        storage.set_active_user_db(self.pc if which == "pc" else self.phone)


@pytest.fixture()
def devices(user_db, tmp_path):
    d = Devices()
    d.use("pc")
    accounts.add_account("Oszczędnościowe", 500, account_kind="savings")
    with storage.open_user_db(write=True) as conn:
        conn.execute("UPDATE categories SET limit_amount = 800 WHERE name = 'Jedzenie'")
        conn.execute("UPDATE categories SET limit_amount = 200 WHERE name = 'Transport'")
    goals.add_piggy_bank("Wakacje", 3000, "Karta")
    ledger.add_transaction(f"{YM}-01", "Wydatek", "Jedzenie", "Karta", "Lidl", 100, "", True)
    sync.set_sync_setting(sync.SET_PASSWORD, PASSWORD)
    d.folder = tmp_path / "OneDrive" / "MatrixFinance"
    return d


def _balances():
    return {a["name"]: round(float(a["balance"]), 2) for a in accounts.get_accounts_overview()}


def _phone_pull(d: Devices) -> sync.SnapshotImport:
    d.use("phone")
    return sync.import_snapshot_bytes((d.folder / sync.SNAPSHOT_FILE).read_bytes(), PASSWORD)


def _phone_push(d: Devices, name: str = None) -> None:
    d.use("phone")
    (d.folder / (name or sync.ops_file_name())).write_bytes(sync.build_ops_file(PASSWORD))


def test_full_round_trip_phone_and_pc(devices):
    d = devices
    sync.sync_folder_now(d.folder)  # PC: pierwsza migawka
    assert (d.folder / sync.SNAPSHOT_FILE).exists()

    _phone_pull(d)
    assert _balances() == {"Karta": 900.0, "Gotówka": 200.0, "Oszczędnościowe": 500.0}
    goal_id = goals.get_all_piggy_banks()[0]["id"]
    lidl = ledger.fetch_transactions(month_filter=YM)[0]

    # telefon: kilka operacji (od razu widoczne na telefonie)
    exp_uid = sync.new_uid("tx")
    sync.record_op("tx.add", {"uid": exp_uid, "date": f"{YM}-05", "type": "Wydatek", "category": "Jedzenie",
                              "account": "Karta", "shop": "Żabka", "amount": 25.5, "desc": ""})
    sync.record_op("transfer", {"group": sync.new_uid("trf"), "source": "Karta", "target": "Oszczędnościowe",
                                "amount": 100, "date": f"{YM}-06", "note": ""})
    sync.record_op("goal.move", {"uid": sync.new_uid("tx"), "goal_id": goal_id, "goal_name": "Wakacje",
                                 "amount": 50, "account": "Karta", "date": f"{YM}-07"})
    sync.record_op("account.set_balance", {"uid": sync.new_uid("tx"), "account": "Gotówka", "balance": 180,
                                           "date": f"{YM}-08"})
    sync.record_op("envelope.move", {"source": "Transport", "target": "Jedzenie", "ym": YM, "amount": 40})
    sync.record_op("tx.update", {"uid": lidl["tx_uid"], "date": f"{YM}-01", "type": "Wydatek",
                                 "category": "Jedzenie", "account": "Karta", "shop": "Lidl", "amount": 110,
                                 "desc": "poprawka"})
    phone_view = _balances()
    assert phone_view == {"Karta": 900 - 25.5 - 100 - 50 - 10, "Gotówka": 180.0, "Oszczędnościowe": 600.0}
    assert len(sync.pending_ops()) == 6

    # telefon zapisuje plik dwa razy (np. OneDrive nadał nazwę „(1)”) — operacje mają się wykonać raz
    _phone_push(d)
    _phone_push(d, "telefon (1).mfops")

    # komputer w tym czasie też coś dodał
    d.use("pc")
    ledger.add_transaction(f"{YM}-09", "Wydatek", "Transport", "Karta", "Orlen", 60, "", True)
    result = sync.sync_folder_now(d.folder)
    assert len(result.applied) == 6 and not result.rejected
    assert result.processed_files == 2
    assert not list(d.folder.glob("*.mfops"))  # przetworzone pliki przeniesione
    pc_view = _balances()
    assert pc_view == {"Karta": round(900 - 25.5 - 100 - 50 - 10 - 60, 2), "Gotówka": 180.0,
                       "Oszczędnościowe": 600.0}
    assert float(goals.get_piggy_bank_by_id(goal_id)["current_amount"]) == 50
    env = {e["name"]: e for e in envelopes.get_envelope_overview(YM)}
    assert env["Jedzenie"]["adjustment"] == 40 and env["Transport"]["adjustment"] == -40

    # ponowna synchronizacja nie duplikuje
    sync.sync_folder_now(d.folder)
    assert _balances() == pc_view

    # telefon: nowa migawka potwierdza operacje i czyści skrzynkę
    imp = _phone_pull(d)
    assert imp.confirmed == 6 and imp.replayed == 0 and not imp.rejected
    assert sync.pending_ops() == []
    assert _balances() == pc_view
    assert ledger.get_transaction_by_uid(exp_uid)["shop"] == "Żabka"


def test_pending_ops_survive_older_snapshot(devices):
    d = devices
    sync.sync_folder_now(d.folder)
    _phone_pull(d)
    sync.record_op("tx.add", {"uid": sync.new_uid("tx"), "date": f"{YM}-10", "type": "Wydatek",
                              "category": "Jedzenie", "account": "Karta", "shop": "Biedronka", "amount": 30,
                              "desc": ""})
    # telefon wczytuje ponownie tę samą (starą) migawkę — jego operacja nie może zniknąć
    imp = _phone_pull(d)
    assert imp.replayed == 1
    assert _balances()["Karta"] == 870.0
    assert len(sync.pending_ops()) == 1


def test_rejected_operation_is_reported_and_dropped(devices):
    d = devices
    sync.sync_folder_now(d.folder)
    _phone_pull(d)
    goal_id = goals.get_all_piggy_banks()[0]["id"]
    sync.record_op("goal.move", {"uid": sync.new_uid("tx"), "goal_id": goal_id, "goal_name": "Wakacje",
                                 "amount": 20, "account": "Karta", "date": f"{YM}-07"})
    _phone_push(d)
    d.use("pc")
    goals.delete_piggy_bank(goal_id)  # na komputerze cel usunięto
    result = sync.sync_folder_now(d.folder)
    assert len(result.rejected) == 1 and not result.applied
    imp = _phone_pull(d)
    assert len(imp.rejected) == 1 and "Wakacje" in imp.rejected[0]
    assert sync.pending_ops() == []


def test_wrong_password_and_local_settings(devices):
    d = devices
    sync.sync_folder_now(d.folder)
    d.use("phone")
    sync.set_sync_setting(sync.SET_PASSWORD, PASSWORD)
    device = sync.device_id()
    with pytest.raises(sync.SyncError):
        sync.import_snapshot_bytes((d.folder / sync.SNAPSHOT_FILE).read_bytes(), "zle-haslo")
    sync.import_snapshot_bytes((d.folder / sync.SNAPSHOT_FILE).read_bytes(), PASSWORD)
    # ustawienia telefonu (hasło, id urządzenia) nie zostały nadpisane danymi z komputera
    assert sync.get_sync_setting(sync.SET_PASSWORD) == PASSWORD
    assert sync.device_id() == device
    # a hasło komputera nie trafiło do migawki
    from src.finance import data_io

    d.use("pc")
    assert all(not r["key"].startswith("sync_") for r in data_io.export_data_dict()["tables"]["settings"])
    # plik z operacjami zaszyfrowany innym hasłem jest pomijany, nie psuje synchronizacji
    (d.folder / "obcy.mfops").write_bytes(b"x" * 64)
    result = sync.sync_folder_now(d.folder)
    assert result.skipped_files and result.snapshot


def test_strict_checks_on_phone(devices):
    d = devices
    sync.sync_folder_now(d.folder)
    _phone_pull(d)
    with pytest.raises(ValueError):
        sync.record_op("transfer", {"group": sync.new_uid("trf"), "source": "Gotówka", "target": "Karta",
                                    "amount": 5000, "date": f"{YM}-06", "note": ""})
    assert sync.pending_ops() == []  # nieudana operacja nie trafia do skrzynki
    with pytest.raises(ValueError):
        sync.record_op("nieznana", {})


def test_snapshot_only_when_changed(devices):
    d = devices
    first = sync.sync_folder_now(d.folder, only_if_changed=True)
    assert first.snapshot
    assert sync.sync_folder_now(d.folder, only_if_changed=True).snapshot is None  # nic się nie zmieniło
    ledger.add_transaction(f"{YM}-12", "Wydatek", "Jedzenie", "Karta", "Piekarnia", 9, "", True)
    assert sync.sync_folder_now(d.folder, only_if_changed=True).snapshot  # zmiana -> nowa migawka


def test_default_folder_prefers_onedrive_env(monkeypatch, tmp_path):
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    monkeypatch.setenv("OneDrive", str(onedrive))
    assert sync.default_sync_folder() == onedrive / "MatrixFinance"
    assert sync.onedrive_detected()
