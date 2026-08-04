from __future__ import annotations

from datetime import UTC, datetime

from handball.database.maintenance import (
    execute_legacy_training_removal,
    preview_legacy_training_removal,
)
from handball.database.migrations import verify_database
from tests.test_users_authorization import make_v2


TARGET_DATES = ("2026-07-23", "2026-07-24", "2026-07-27")


def _seed_legacy_sessions(manager) -> list[int]:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with manager.unit_of_work() as unit_of_work:
        member_id = int(
            unit_of_work.connection.execute("SELECT id FROM team_members ORDER BY id LIMIT 1").fetchone()[0]
        )
        result: list[int] = []
        for index, training_date in enumerate(TARGET_DATES):
            session_id = int(
                unit_of_work.connection.execute(
                    """INSERT INTO training_sessions(training_date,notes,is_finalized,created_at,updated_at)
                       VALUES(?, '', 0, ?, ?)""",
                    (training_date, now, now),
                ).lastrowid
            )
            record_id = int(
                unit_of_work.connection.execute(
                    """INSERT INTO attendance_records(
                           session_id,member_id,confirmation_status,present,notes,version,updated_at
                       ) VALUES(?,?,?,NULL,'',1,?)""",
                    (session_id, member_id, "CONFIRMED_EARLY" if index == 1 else "PENDING", now),
                ).lastrowid
            )
            unit_of_work.connection.execute(
                """INSERT INTO attendance_audit_log(
                       session_id,member_id,old_confirmation_status,new_confirmation_status,
                       old_present,new_present,old_notes,new_notes,changed_at,source
                   ) VALUES(?,?,NULL,?,NULL,NULL,NULL,'',?,'legacy-test')""",
                (session_id, member_id, "CONFIRMED_EARLY" if index == 1 else "PENDING", now),
            )
            assert record_id > 0
            result.append(session_id)
    return result


def test_legacy_training_removal_is_previewed_backed_up_audited_and_verified(tmp_path):
    _, manager, _ = make_v2(tmp_path)
    session_ids = _seed_legacy_sessions(manager)
    fingerprint_before = manager.logical_fingerprint()

    preview = preview_legacy_training_removal(manager, dates=TARGET_DATES)
    assert preview["session_count"] == 3
    assert preview["attendance_records"] == 3
    assert preview["attendance_audit_rows"] == 3
    assert manager.logical_fingerprint() == fingerprint_before

    result = execute_legacy_training_removal(manager, dates=TARGET_DATES, actor_username="bob")
    assert result["deleted_sessions"] == 3
    assert (manager.backup_dir / result["backup_id"]).is_file()
    assert verify_database(manager.db_path)["ok"] is True
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE id IN (?,?,?)", session_ids
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM attendance_records WHERE session_id IN (?,?,?)", session_ids
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM attendance_audit_log WHERE session_id IN (?,?,?)", session_ids
        ).fetchone()[0] == 0
        audit = connection.execute(
            "SELECT action,origin FROM security_audit_events WHERE request_id=?",
            (result["request_id"],),
        ).fetchone()
    assert tuple(audit) == ("maintenance.legacy_training.remove", "maintenance-script")

    replay = execute_legacy_training_removal(manager, dates=TARGET_DATES, actor_username="bob")
    assert replay["replayed"] is True
    assert replay["request_id"] == result["request_id"]
