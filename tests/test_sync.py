from __future__ import annotations

from attendance.database import AttendanceRepository


def test_sync_is_idempotent_and_rejects_stale_version(tmp_path):
    repo = AttendanceRepository(tmp_path / "presencas.db")
    repo.initialize()
    session = repo.get_or_create_session("2026-07-23")
    session_id = int(session["id"])
    record = repo.get_session_records(session_id)[0]

    operation = {
        "operation_id": "operation-0001",
        "member_id": record["member_id"],
        "base_version": record["version"],
        "confirmation_status": "CONFIRMED_EARLY",
        "present": True,
        "notes": "Confirmado pelo iPhone",
    }
    first = repo.sync_records(session_id, [operation], source="pytest-offline")
    repeated = repo.sync_records(session_id, [operation], source="pytest-offline")

    assert first == repeated
    assert first[0]["status"] == "accepted"
    assert first[0]["record"]["version"] == record["version"] + 1
    assert len(repo.get_audit_log()) == 1

    stale = repo.sync_records(
        session_id,
        [
            {
                **operation,
                "operation_id": "operation-0002",
                "notes": "Edição antiga",
            }
        ],
        source="pytest-offline",
    )
    assert stale[0]["status"] == "conflict"
    assert stale[0]["record"]["notes"] == "Confirmado pelo iPhone"
    assert len(repo.get_audit_log()) == 1


def test_backup_is_consistent(tmp_path):
    original = AttendanceRepository(tmp_path / "original.db")
    original.initialize()
    original.get_or_create_session("2026-07-24")

    backup_path = original.backup_to(tmp_path / "backups" / "copy.db")
    restored = AttendanceRepository(backup_path)

    assert len(restored.list_members(include_inactive=False)) == 19
    assert restored.get_history()


def test_offline_noop_still_advances_version_for_followup_operation(tmp_path):
    repo = AttendanceRepository(tmp_path / "sequence.db")
    repo.initialize()
    session = repo.get_or_create_session("2026-07-26")
    session_id = int(session["id"])
    record = repo.get_session_records(session_id)[0]

    first = repo.sync_records(
        session_id,
        [
            {
                "operation_id": "sequence-0001",
                "member_id": record["member_id"],
                "base_version": record["version"],
                "confirmation_status": record["confirmation_status"],
                "present": False,
                "notes": record["notes"],
            },
            {
                "operation_id": "sequence-0002",
                "member_id": record["member_id"],
                "base_version": record["version"] + 1,
                "confirmation_status": "CONFIRMED_EARLY",
                "present": False,
                "notes": "Segunda edição offline",
            },
        ],
        source="pytest-offline",
    )

    assert [item["status"] for item in first] == ["accepted", "accepted"]
    assert first[0]["changed"] is False
    assert first[1]["record"]["version"] == record["version"] + 2
