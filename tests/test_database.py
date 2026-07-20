from __future__ import annotations

from attendance.database import AttendanceRepository


def test_initialization_and_audit(tmp_path):
    repo = AttendanceRepository(tmp_path / "test.db")
    repo.initialize()

    members = repo.list_members(include_inactive=False)
    assert len(members) == 19

    session = repo.get_or_create_session("2026-07-21")
    session_id = int(session["id"])
    records = repo.get_session_records(session_id)
    assert len(records) == 19

    first = records[0]
    changed = repo.save_records(
        session_id,
        [
            {
                "member_id": first["member_id"],
                "confirmation_status": "CONFIRMED_EARLY",
                "present": True,
                "notes": "Teste",
            }
        ],
        source="pytest",
    )
    assert changed == 1

    refreshed = repo.get_session_records(session_id)
    updated = next(
        row for row in refreshed if row["member_id"] == first["member_id"]
    )
    assert updated["confirmation_status"] == "CONFIRMED_EARLY"
    assert updated["present"] == 1
    assert updated["notes"] == "Teste"

    audit = repo.get_audit_log()
    assert len(audit) == 1
    assert audit[0]["source"] == "pytest"


def test_finalize_marks_unchecked_as_absent(tmp_path):
    repo = AttendanceRepository(tmp_path / "test.db")
    repo.initialize()
    session = repo.get_or_create_session("2026-07-22")
    session_id = int(session["id"])

    changed = repo.finalize_session(session_id, source="pytest-finalize")
    assert changed == 19

    records = repo.get_session_records(session_id)
    assert all(record["present"] == 0 for record in records)
    assert repo.get_session(session_id)["is_finalized"] == 1
