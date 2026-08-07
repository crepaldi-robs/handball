from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from handball.core.positions import parse_attack_positions

from .shared import now_iso

RANK_SCOPES = ("LINE", "GOALKEEPER")

# Deslocamento temporário usado ao renumerar ordinais: o UPDATE direto de
# ordinal+1 violaria UNIQUE(scope,ordinal) no meio da varredura do SQLite.
_ORDINAL_SHIFT = 1_000_000

_UNAVAILABLE_MESSAGE = (
    "O banco ainda não recebeu a atualização de hierarquia do elenco."
)


class RosterRepository:
    """SQL da hierarquia do elenco, sempre dentro da conexão da UnitOfWork."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self.read_only = read_only

    def _table_exists(self, table: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def is_available(self) -> bool:
        return self._table_exists("rank_layers")

    def _require_available(self) -> None:
        if not self.is_available():
            raise RuntimeError(_UNAVAILABLE_MESSAGE)

    def _security_audit(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_id: str,
        before_json: str | None = None,
        after_json: str | None = None,
    ) -> None:
        if not self._table_exists("security_audit_events"):
            return
        self.connection.execute(
            """INSERT INTO security_audit_events(
                   actor_user_id,occurred_at,action,entity,target_id,origin,
                   before_json,after_json,request_id
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                actor_user_id,
                now_iso(),
                action,
                "roster_ranking",
                target_id,
                "ui",
                before_json,
                after_json,
                None,
            ),
        )

    # ------------------------------------------------------------------
    # Leituras
    # ------------------------------------------------------------------

    def _member_attack_positions(self, member_ids: Iterable[int]) -> dict[int, list[str]]:
        ids = sorted({int(value) for value in member_ids})
        if not ids:
            return {}
        result: dict[int, list[str]] = {member_id: [] for member_id in ids}
        placeholders = ",".join("?" for _ in ids)
        if self._table_exists("member_attack_positions"):
            for row in self.connection.execute(
                f"SELECT member_id,position FROM member_attack_positions WHERE member_id IN ({placeholders}) ORDER BY member_id,ordinal",
                tuple(ids),
            ).fetchall():
                result[int(row["member_id"])].append(str(row["position"]))
            return result
        for row in self.connection.execute(
            f"SELECT id,position FROM team_members WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall():
            result[int(row["id"])] = parse_attack_positions(str(row["position"] or ""))
        return result

    def _comparison_counts(self, scope: str) -> dict[int, int]:
        counts: dict[int, int] = {}
        for row in self.connection.execute(
            """SELECT member_id, COUNT(*) AS total FROM (
                   SELECT subject_member_id AS member_id FROM rank_comparisons WHERE scope=?
                   UNION ALL
                   SELECT reference_member_id AS member_id FROM rank_comparisons WHERE scope=?
               ) GROUP BY member_id""",
            (scope, scope),
        ).fetchall():
            counts[int(row["member_id"])] = int(row["total"])
        return counts

    def list_layers(self, scope: str) -> list[dict[str, Any]]:
        if not self.is_available():
            return []
        comparison_counts = self._comparison_counts(scope)
        layers: list[dict[str, Any]] = []
        for layer_row in self.connection.execute(
            "SELECT id,scope,ordinal,created_at,updated_at FROM rank_layers WHERE scope=? ORDER BY ordinal DESC",
            (scope,),
        ).fetchall():
            layer_id = int(layer_row["id"])
            members = [
                {
                    "member_id": int(row["id"]),
                    "name": str(row["name"]),
                    "active": bool(row["active"]),
                    "comparisons_count": comparison_counts.get(int(row["id"]), 0),
                }
                for row in self.connection.execute(
                    """SELECT m.id,m.name,m.active
                       FROM member_layer_assignments a JOIN team_members m ON m.id=a.member_id
                       WHERE a.layer_id=? ORDER BY m.name COLLATE NOCASE""",
                    (layer_id,),
                ).fetchall()
            ]
            attack_by_member = self._member_attack_positions(
                item["member_id"] for item in members
            )
            for item in members:
                item["attack_positions"] = attack_by_member.get(item["member_id"], [])
            refinements: dict[str, list[int]] = {}
            for row in self.connection.execute(
                "SELECT position,member_id FROM layer_position_refinements WHERE layer_id=? ORDER BY position,refine_ordinal",
                (layer_id,),
            ).fetchall():
                refinements.setdefault(str(row["position"]), []).append(int(row["member_id"]))
            layers.append(
                {
                    "layer_id": layer_id,
                    "scope": str(layer_row["scope"]),
                    "ordinal": int(layer_row["ordinal"]),
                    "members": members,
                    "refinements": refinements,
                }
            )
        return layers

    def pending_members(self, scope: str) -> list[dict[str, Any]]:
        if not self.is_available():
            return []
        rows = self.connection.execute(
            """SELECT m.id,m.name FROM team_members m
               WHERE m.active=1 AND NOT EXISTS (
                   SELECT 1 FROM member_layer_assignments a
                   WHERE a.member_id=m.id AND a.scope=?
               ) ORDER BY m.name COLLATE NOCASE""",
            (scope,),
        ).fetchall()
        attack_by_member = self._member_attack_positions(int(row["id"]) for row in rows)
        pending: list[dict[str, Any]] = []
        for row in rows:
            member_id = int(row["id"])
            positions = attack_by_member.get(member_id, [])
            if scope == "GOALKEEPER":
                eligible = "GOL" in positions
            else:
                eligible = any(position != "GOL" for position in positions)
            if eligible:
                pending.append(
                    {
                        "member_id": member_id,
                        "name": str(row["name"]),
                        "attack_positions": positions,
                    }
                )
        return pending

    def layer_count(self, scope: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM rank_layers WHERE scope=?", (scope,)
        ).fetchone()
        return int(row[0])

    def layer_by_ordinal(self, scope: str, ordinal: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT id,scope,ordinal FROM rank_layers WHERE scope=? AND ordinal=?",
            (scope, int(ordinal)),
        ).fetchone()
        if row is None:
            return None
        return {"layer_id": int(row["id"]), "scope": str(row["scope"]), "ordinal": int(row["ordinal"])}

    def assignment_for_member(self, member_id: int, scope: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT a.layer_id,l.ordinal FROM member_layer_assignments a
               JOIN rank_layers l ON l.id=a.layer_id
               WHERE a.member_id=? AND a.scope=?""",
            (int(member_id), scope),
        ).fetchone()
        if row is None:
            return None
        return {"layer_id": int(row["layer_id"]), "ordinal": int(row["ordinal"])}

    # ------------------------------------------------------------------
    # Sessões de ranqueamento
    # ------------------------------------------------------------------

    def _session_dict(self, row: Any) -> dict[str, Any]:
        return {
            "session_id": str(row["id"]),
            "scope": str(row["scope"]),
            "subject_member_id": int(row["subject_member_id"]),
            "is_rerank": bool(row["is_rerank"]),
            "lo_ordinal": int(row["lo_ordinal"]),
            "hi_ordinal": int(row["hi_ordinal"]),
            "pending_reference_member_id": (
                int(row["pending_reference_member_id"])
                if row["pending_reference_member_id"] is not None
                else None
            ),
            "status": str(row["status"]),
            "result_layer_id": (
                int(row["result_layer_id"]) if row["result_layer_id"] is not None else None
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def active_session(self, scope: str) -> dict[str, Any] | None:
        if not self.is_available():
            return None
        row = self.connection.execute(
            "SELECT * FROM rank_sessions WHERE scope=? AND status='ACTIVE'", (scope,)
        ).fetchone()
        return self._session_dict(row) if row is not None else None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        self._require_available()
        row = self.connection.execute(
            "SELECT * FROM rank_sessions WHERE id=?", (str(session_id),)
        ).fetchone()
        return self._session_dict(row) if row is not None else None

    def create_session(
        self,
        *,
        scope: str,
        subject_member_id: int,
        is_rerank: bool,
        lo_ordinal: int,
        hi_ordinal: int,
        pending_reference_member_id: int | None,
        created_by_user_id: int,
        status: str = "ACTIVE",
        result_layer_id: int | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        session_id = uuid4().hex
        now = now_iso()
        try:
            self.connection.execute(
                """INSERT INTO rank_sessions(
                       id,scope,subject_member_id,is_rerank,lo_ordinal,hi_ordinal,
                       pending_reference_member_id,status,result_layer_id,
                       created_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    scope,
                    int(subject_member_id),
                    int(bool(is_rerank)),
                    int(lo_ordinal),
                    int(hi_ordinal),
                    pending_reference_member_id,
                    status,
                    result_layer_id,
                    int(created_by_user_id),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "Já existe um ranqueamento em andamento neste escopo. "
                "Conclua ou cancele antes de iniciar outro."
            ) from error
        session = self.get_session(session_id)
        assert session is not None
        return session

    def save_session_interval(
        self,
        session_id: str,
        *,
        lo_ordinal: int,
        hi_ordinal: int,
        pending_reference_member_id: int | None,
    ) -> None:
        self.connection.execute(
            """UPDATE rank_sessions
               SET lo_ordinal=?,hi_ordinal=?,pending_reference_member_id=?,updated_at=?
               WHERE id=? AND status='ACTIVE'""",
            (
                int(lo_ordinal),
                int(hi_ordinal),
                pending_reference_member_id,
                now_iso(),
                str(session_id),
            ),
        )

    def complete_session(self, session_id: str, *, result_layer_id: int) -> None:
        self.connection.execute(
            """UPDATE rank_sessions
               SET status='COMPLETED',result_layer_id=?,pending_reference_member_id=NULL,updated_at=?
               WHERE id=?""",
            (int(result_layer_id), now_iso(), str(session_id)),
        )

    def cancel_session(self, session_id: str) -> None:
        self.connection.execute(
            """UPDATE rank_sessions
               SET status='CANCELLED',pending_reference_member_id=NULL,updated_at=?
               WHERE id=? AND status='ACTIVE'""",
            (now_iso(), str(session_id)),
        )

    def record_comparison(
        self,
        *,
        session_id: str,
        scope: str,
        subject_member_id: int,
        reference_member_id: int,
        question: str,
        outcome: str,
        actor_user_id: int,
    ) -> None:
        self.connection.execute(
            """INSERT INTO rank_comparisons(
                   session_id,scope,subject_member_id,reference_member_id,
                   question,outcome,answered_at,actor_user_id
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(session_id),
                scope,
                int(subject_member_id),
                int(reference_member_id),
                question,
                outcome,
                now_iso(),
                int(actor_user_id),
            ),
        )

    def list_comparisons(self, *, subject_member_id: int | None = None) -> list[dict[str, Any]]:
        if not self.is_available():
            return []
        sql = (
            "SELECT session_id,scope,subject_member_id,reference_member_id,"
            "question,outcome,answered_at,actor_user_id FROM rank_comparisons"
        )
        params: tuple[Any, ...] = ()
        if subject_member_id is not None:
            sql += " WHERE subject_member_id=?"
            params = (int(subject_member_id),)
        sql += " ORDER BY id"
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # Escritas de camada e atribuição
    # ------------------------------------------------------------------

    def insert_layer_at(self, scope: str, ordinal: int, *, actor_user_id: int) -> int:
        self._require_available()
        now = now_iso()
        self.connection.execute(
            "UPDATE rank_layers SET ordinal=ordinal+?,updated_at=? WHERE scope=? AND ordinal>=?",
            (_ORDINAL_SHIFT, now, scope, int(ordinal)),
        )
        self.connection.execute(
            "UPDATE rank_layers SET ordinal=ordinal-? WHERE scope=? AND ordinal>=?",
            (_ORDINAL_SHIFT - 1, scope, _ORDINAL_SHIFT),
        )
        cursor = self.connection.execute(
            "INSERT INTO rank_layers(scope,ordinal,created_at,updated_at) VALUES(?,?,?,?)",
            (scope, int(ordinal), now, now),
        )
        layer_id = int(cursor.lastrowid)
        self._security_audit(
            actor_user_id=actor_user_id,
            action="ranking.layer.create",
            target_id=f"layer:{layer_id}",
            after_json=json.dumps({"scope": scope, "ordinal": int(ordinal)}, ensure_ascii=False),
        )
        return layer_id

    def assign_member(
        self, member_id: int, scope: str, layer_id: int, *, actor_user_id: int
    ) -> None:
        self._require_available()
        layer = self.connection.execute(
            "SELECT scope,ordinal FROM rank_layers WHERE id=?", (int(layer_id),)
        ).fetchone()
        if layer is None:
            raise KeyError("Camada não encontrada.")
        if str(layer["scope"]) != scope:
            raise ValueError("A camada pertence a outro escopo da hierarquia.")
        previous = self.assignment_for_member(member_id, scope)
        self.connection.execute(
            """INSERT INTO member_layer_assignments(
                   member_id,scope,layer_id,assigned_at,assigned_by_user_id
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(member_id,scope) DO UPDATE SET
                   layer_id=excluded.layer_id,
                   assigned_at=excluded.assigned_at,
                   assigned_by_user_id=excluded.assigned_by_user_id""",
            (int(member_id), scope, int(layer_id), now_iso(), int(actor_user_id)),
        )
        self._security_audit(
            actor_user_id=actor_user_id,
            action="ranking.assign",
            target_id=f"{int(member_id)}:{scope}",
            before_json=json.dumps(
                {"layer_ordinal": previous["ordinal"] if previous else None},
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {"layer_ordinal": int(layer["ordinal"])}, ensure_ascii=False
            ),
        )

    def remove_assignment_and_compact(
        self, member_id: int, scope: str, *, actor_user_id: int
    ) -> dict[str, Any] | None:
        self._require_available()
        previous = self.assignment_for_member(member_id, scope)
        if previous is None:
            return None
        layer_id = previous["layer_id"]
        self.connection.execute(
            "DELETE FROM member_layer_assignments WHERE member_id=? AND scope=?",
            (int(member_id), scope),
        )
        self.connection.execute(
            "DELETE FROM layer_position_refinements WHERE layer_id=? AND member_id=?",
            (layer_id, int(member_id)),
        )
        remaining = self.connection.execute(
            "SELECT COUNT(*) FROM member_layer_assignments WHERE layer_id=?",
            (layer_id,),
        ).fetchone()
        layer_deleted = int(remaining[0]) == 0
        if layer_deleted:
            self.connection.execute("DELETE FROM rank_layers WHERE id=?", (layer_id,))
            now = now_iso()
            self.connection.execute(
                "UPDATE rank_layers SET ordinal=ordinal+?,updated_at=? WHERE scope=? AND ordinal>?",
                (_ORDINAL_SHIFT, now, scope, previous["ordinal"]),
            )
            self.connection.execute(
                "UPDATE rank_layers SET ordinal=ordinal-? WHERE scope=? AND ordinal>=?",
                (_ORDINAL_SHIFT + 1, scope, _ORDINAL_SHIFT),
            )
        self._security_audit(
            actor_user_id=actor_user_id,
            action="ranking.unassign",
            target_id=f"{int(member_id)}:{scope}",
            before_json=json.dumps(
                {"layer_ordinal": previous["ordinal"]}, ensure_ascii=False
            ),
            after_json=json.dumps(
                {"layer_ordinal": None, "layer_deleted": layer_deleted},
                ensure_ascii=False,
            ),
        )
        return {**previous, "layer_deleted": layer_deleted}

    def replace_refinements(
        self,
        layer_id: int,
        position: str,
        member_ids: Iterable[int],
        *,
        actor_user_id: int,
    ) -> None:
        self._require_available()
        ordered = [int(value) for value in member_ids]
        if len(set(ordered)) != len(ordered):
            raise ValueError("A ordem de refino não pode repetir atleta.")
        layer = self.connection.execute(
            "SELECT scope,ordinal FROM rank_layers WHERE id=?", (int(layer_id),)
        ).fetchone()
        if layer is None:
            raise KeyError("Camada não encontrada.")
        layer_members = {
            int(row["member_id"])
            for row in self.connection.execute(
                "SELECT member_id FROM member_layer_assignments WHERE layer_id=?",
                (int(layer_id),),
            ).fetchall()
        }
        outsiders = [value for value in ordered if value not in layer_members]
        if outsiders:
            raise ValueError("Só atletas da própria camada entram no refino.")
        attack_by_member = self._member_attack_positions(ordered)
        without_position = [
            value for value in ordered if position not in attack_by_member.get(value, [])
        ]
        if without_position:
            raise ValueError(
                "Só atletas com a posição selecionada entram no refino dessa posição."
            )
        before_rows = self.connection.execute(
            "SELECT member_id FROM layer_position_refinements WHERE layer_id=? AND position=? ORDER BY refine_ordinal",
            (int(layer_id), position),
        ).fetchall()
        self.connection.execute(
            "DELETE FROM layer_position_refinements WHERE layer_id=? AND position=?",
            (int(layer_id), position),
        )
        now = now_iso()
        self.connection.executemany(
            """INSERT INTO layer_position_refinements(
                   layer_id,position,member_id,refine_ordinal,updated_at,updated_by_user_id
               ) VALUES(?,?,?,?,?,?)""",
            [
                (int(layer_id), position, member_id, ordinal, now, int(actor_user_id))
                for ordinal, member_id in enumerate(ordered)
            ],
        )
        self._security_audit(
            actor_user_id=actor_user_id,
            action="ranking.refinement.update",
            target_id=f"layer:{int(layer_id)}:{position}",
            before_json=json.dumps(
                {"member_ids": [int(row["member_id"]) for row in before_rows]},
                ensure_ascii=False,
            ),
            after_json=json.dumps({"member_ids": ordered}, ensure_ascii=False),
        )

    # ------------------------------------------------------------------
    # Consultas agregadas para planner e métricas
    # ------------------------------------------------------------------

    def rankings_by_member(self) -> dict[int, dict[str, Any]]:
        """Camada e refino de cada atleta, por escopo, em uma leitura só.

        Formato: {member_id: {scope: {"layer_id", "layer_ordinal", "layer_size",
        "refinements": {position: {"refine_ordinal", "peers"}}}}}. Banco não
        migrado devolve {} e o chamador segue sem hierarquia.
        """

        if not self.is_available():
            return {}
        layer_sizes: dict[int, int] = {}
        for row in self.connection.execute(
            "SELECT layer_id,COUNT(*) AS total FROM member_layer_assignments GROUP BY layer_id"
        ).fetchall():
            layer_sizes[int(row["layer_id"])] = int(row["total"])
        refinement_peers: dict[tuple[int, str], int] = {}
        for row in self.connection.execute(
            "SELECT layer_id,position,COUNT(*) AS total FROM layer_position_refinements GROUP BY layer_id,position"
        ).fetchall():
            refinement_peers[(int(row["layer_id"]), str(row["position"]))] = int(row["total"])
        refinements_by_member: dict[tuple[int, int], dict[str, dict[str, int]]] = {}
        for row in self.connection.execute(
            "SELECT layer_id,position,member_id,refine_ordinal FROM layer_position_refinements"
        ).fetchall():
            key = (int(row["member_id"]), int(row["layer_id"]))
            refinements_by_member.setdefault(key, {})[str(row["position"])] = {
                "refine_ordinal": int(row["refine_ordinal"]),
                "peers": refinement_peers[(int(row["layer_id"]), str(row["position"]))],
            }
        result: dict[int, dict[str, Any]] = {}
        for row in self.connection.execute(
            """SELECT a.member_id,a.scope,a.layer_id,l.ordinal
               FROM member_layer_assignments a JOIN rank_layers l ON l.id=a.layer_id"""
        ).fetchall():
            member_id = int(row["member_id"])
            layer_id = int(row["layer_id"])
            result.setdefault(member_id, {})[str(row["scope"])] = {
                "layer_id": layer_id,
                "layer_ordinal": int(row["ordinal"]),
                "layer_size": layer_sizes.get(layer_id, 0),
                "refinements": refinements_by_member.get((member_id, layer_id), {}),
            }
        return result

    def finalized_sessions_count(self, start_date_iso: str, end_date_iso: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM training_sessions WHERE is_finalized=1 AND training_date BETWEEN ? AND ?",
            (start_date_iso, end_date_iso),
        ).fetchone()
        return int(row[0])

    def presence_metrics(self, start_date_iso: str, end_date_iso: str) -> dict[int, dict[str, int]]:
        metrics: dict[int, dict[str, int]] = {}
        for row in self.connection.execute(
            """SELECT r.member_id,
                      SUM(CASE WHEN r.present=1 THEN 1 ELSE 0 END) AS presents,
                      COUNT(*) AS records
               FROM attendance_records r
               JOIN training_sessions s ON s.id=r.session_id
               WHERE s.is_finalized=1 AND s.training_date BETWEEN ? AND ?
               GROUP BY r.member_id""",
            (start_date_iso, end_date_iso),
        ).fetchall():
            metrics[int(row["member_id"])] = {
                "presents": int(row["presents"] or 0),
                "records": int(row["records"]),
            }
        return metrics
