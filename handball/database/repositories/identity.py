from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any, Iterable

from handball.core.authorization import ROLE_PERMISSIONS


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class IdentityRepository:
    """Identidades, papéis e sessões dentro da transação da UnitOfWork."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self.read_only = read_only

    @staticmethod
    def normalize_username(value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized or len(normalized) > 80:
            raise ValueError("Usuário inválido.")
        return normalized

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def has_user_schema(self) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='users'"
        ).fetchone()
        return row is not None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        if not self.has_user_schema():
            return None
        row = self.connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (self.normalize_username(username),),
        ).fetchone()
        return dict(row) if row else None

    def get_teams_by_ids(self, team_ids: Iterable[int]) -> list[dict[str, Any]]:
        """Le teams(id,code,slug,display_name) para os IDs informados, ordenado por id.

        Somente leitura; usada para resolver a identidade visual do time ativo
        a partir de AccessContext.team_ids (nunca a partir de dado do cliente).
        """
        ids = sorted({int(value) for value in team_ids})
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.connection.execute(
            f"SELECT id,code,slug,display_name FROM teams "
            f"WHERE id IN ({placeholders}) AND active=1 ORDER BY id",
            ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_teams(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id,code,slug,display_name,active FROM teams ORDER BY display_name COLLATE NOCASE"
        ).fetchall()
        return [dict(row) for row in rows]

    def create_team(
        self,
        *,
        code: str,
        slug: str,
        display_name: str,
        season_label: str,
        actor_user_id: int,
    ) -> int:
        code = code.strip().upper()
        slug = slug.strip().lower()
        display_name = display_name.strip()
        season_label = season_label.strip()
        if not code or not slug or not display_name or not season_label:
            raise ValueError("Código, slug, nome e temporada do time são obrigatórios.")
        now = now_iso()
        try:
            cursor = self.connection.execute(
                """INSERT INTO teams(code,slug,display_name,active,created_at,updated_at)
                   VALUES(?,?,?,1,?,?)""",
                (code, slug, display_name, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe um time com esse código ou slug.") from exc
        team_id = int(cursor.lastrowid)
        self.connection.execute(
            """INSERT INTO seasons(team_id,label,starts_on,ends_on,active)
               VALUES(?,?,NULL,NULL,1)""",
            (team_id, season_label),
        )
        self.audit_event(
            actor_user_id=actor_user_id,
            action="team.create",
            entity="team",
            target_id=str(team_id),
            origin="admin",
            after={"code": code, "slug": slug, "display_name": display_name, "season_label": season_label},
        )
        return team_id

    def set_team_active(self, team_id: int, active: bool, *, actor_user_id: int) -> None:
        now = now_iso()
        updated = self.connection.execute(
            "UPDATE teams SET active=?,updated_at=? WHERE id=?",
            (1 if active else 0, now, team_id),
        )
        if updated.rowcount != 1:
            raise ValueError("Time inexistente.")
        self.audit_event(
            actor_user_id=actor_user_id,
            action="team.active.update",
            entity="team",
            target_id=str(team_id),
            origin="admin",
            after={"active": bool(active)},
        )

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT u.*, p.full_name, p.display_name
               FROM users u LEFT JOIN people p ON p.id=u.person_id
               WHERE u.id=?""",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def mark_login(self, user_id: int) -> None:
        now = now_iso()
        self.connection.execute(
            "UPDATE users SET last_login_at=?, updated_at=? WHERE id=?",
            (now, now, user_id),
        )

    def access_context_data(self, token: str, *, touch: bool = True) -> dict[str, Any] | None:
        if not self.has_user_schema():
            return None
        row = self.connection.execute(
            """SELECT s.id session_id, s.user_id, s.csrf_token,
                      s.expires_at, s.revoked_at,
                      s.credential_version session_credential_version,
                      u.person_id, u.username, u.active user_active,
                      u.credential_version, u.must_change_password,
                      p.full_name, p.display_name,
                      (SELECT team_member_id FROM player_user_links
                       WHERE user_id=u.id) linked_player_id
               FROM auth_sessions s
               JOIN users u ON u.id=s.user_id
               LEFT JOIN people p ON p.id=u.person_id
               WHERE s.token_hash=?""",
            (self.token_hash(token),),
        ).fetchone()
        if (
            not row
            or row["revoked_at"]
            or not bool(row["user_active"])
            or int(row["session_credential_version"]) != int(row["credential_version"])
            or datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC)
        ):
            return None
        system_roles = {
            str(item[0])
            for item in self.connection.execute(
                "SELECT role_code FROM system_roles WHERE user_id=?",
                (row["user_id"],),
            )
        }
        team_rows = (
            self.connection.execute(
                """SELECT DISTINCT tm.team_id, mr.role_code
                   FROM team_memberships tm
                   JOIN membership_roles mr ON mr.membership_id=tm.id
                   WHERE tm.person_id=? AND tm.status='ACTIVE'
                     AND (tm.valid_from IS NULL OR tm.valid_from<=date('now'))
                     AND (tm.valid_to IS NULL OR tm.valid_to>=date('now'))""",
                (row["person_id"],),
            ).fetchall()
            if row["person_id"]
            else []
        )
        team_roles = {str(item["role_code"]) for item in team_rows}
        permissions: set[str] = set()
        for role in system_roles | team_roles:
            permissions.update(str(permission) for permission in ROLE_PERMISSIONS.get(role, ()))
        if self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='user_permission_grants'"
        ).fetchone():
            permissions.update(
                str(item[0])
                for item in self.connection.execute(
                    "SELECT permission_code FROM user_permission_grants WHERE user_id=?",
                    (row["user_id"],),
                )
            )
        if "sql.admin" in permissions:
            permissions.add("sql.explore")
        if touch and not self.read_only:
            self.connection.execute(
                "UPDATE auth_sessions SET last_seen_at=? WHERE id=?",
                (now_iso(), row["session_id"]),
            )
        result = dict(row)
        result.update(
            system_roles=system_roles,
            team_roles=team_roles,
            team_ids={int(item["team_id"]) for item in team_rows},
            permissions=permissions,
        )
        return result

    def create_session(
        self,
        user_id: int,
        expires_at: str,
        csrf_token: str,
        *,
        user_agent_hash: str | None = None,
    ) -> tuple[str, str]:
        user = self.get_user(user_id)
        if not user or not bool(user["active"]):
            raise ValueError("Conta inativa ou inexistente.")
        token = secrets.token_urlsafe(48)
        session_id = secrets.token_urlsafe(24)
        now = now_iso()
        self.connection.execute(
            """INSERT INTO auth_sessions(
                   id,user_id,token_hash,csrf_token,credential_version,
                   created_at,expires_at,last_seen_at,user_agent_hash
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                user_id,
                self.token_hash(token),
                csrf_token,
                int(user["credential_version"]),
                now,
                expires_at,
                now,
                user_agent_hash,
            ),
        )
        return token, session_id

    def revoke_session_token(self, token: str) -> None:
        if not self.has_user_schema():
            return
        self.connection.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (now_iso(), self.token_hash(token)),
        )

    def revoke_user_sessions(self, user_id: int) -> None:
        self.connection.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now_iso(), user_id),
        )

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT u.id,u.person_id,u.username,u.active,u.must_change_password,
                      u.credential_version,u.last_login_at,u.created_at,u.updated_at,
                      p.full_name,p.display_name,
                      pul.team_member_id linked_player_id
               FROM users u LEFT JOIN people p ON p.id=u.person_id
               LEFT JOIN player_user_links pul ON pul.user_id=u.id
               ORDER BY u.username COLLATE NOCASE"""
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["roles"] = [
                str(role[0])
                for role in self.connection.execute(
                    "SELECT role_code FROM system_roles WHERE user_id=? ORDER BY role_code",
                    (row["id"],),
                )
            ]
            inherited: set[str] = set()
            for role in item["roles"]:
                inherited.update(str(value) for value in ROLE_PERMISSIONS.get(role, ()))
            direct = (
                [
                    str(value[0])
                    for value in self.connection.execute(
                        "SELECT permission_code FROM user_permission_grants WHERE user_id=? ORDER BY permission_code",
                        (row["id"],),
                    )
                ]
                if self.connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='user_permission_grants'"
                ).fetchone()
                else []
            )
            effective = inherited | set(direct)
            if "sql.admin" in effective:
                effective.add("sql.explore")
            item["inherited_permissions"] = sorted(inherited)
            item["direct_permissions"] = direct
            item["effective_permissions"] = sorted(effective)
            result.append(item)
        return result

    def set_permission_grants(
        self,
        user_id: int,
        permissions: Iterable[str],
        *,
        actor_user_id: int,
    ) -> None:
        if not self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='user_permission_grants'"
        ).fetchone():
            raise ValueError(
                "A migração v5 é necessária para permissões individuais."
            )
        normalized = {str(value).strip().casefold() for value in permissions}
        allowed = {"sql.explore", "sql.admin"}
        if not normalized <= allowed:
            raise ValueError("Permissão SQL inválida.")
        if not self.connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise ValueError("Usuário inexistente.")
        before = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT permission_code FROM user_permission_grants WHERE user_id=? ORDER BY permission_code",
                (user_id,),
            )
        ]
        self.connection.execute(
            "DELETE FROM user_permission_grants WHERE user_id=?", (user_id,)
        )
        now = now_iso()
        self.connection.executemany(
            "INSERT INTO user_permission_grants(user_id,permission_code,granted_by_user_id,granted_at) VALUES(?,?,?,?)",
            [(user_id, permission, actor_user_id, now) for permission in sorted(normalized)],
        )
        self.audit_event(
            actor_user_id=actor_user_id,
            action="user.permissions.update",
            entity="user",
            target_id=str(user_id),
            origin="admin",
            before={"direct_permissions": before},
            after={"direct_permissions": sorted(normalized)},
        )

    def list_people_and_players(self) -> dict[str, list[dict[str, Any]]]:
        people = [
            dict(row)
            for row in self.connection.execute(
                """SELECT p.id,p.full_name,p.display_name,p.active,
                          u.id user_id,pul.team_member_id
                   FROM people p LEFT JOIN users u ON u.person_id=p.id
                   LEFT JOIN player_user_links pul ON pul.person_id=p.id
                   ORDER BY p.display_name COLLATE NOCASE"""
            )
        ]
        return {
            "people": people,
            "players": [item for item in people if item["team_member_id"] is not None],
        }

    def available_player_registrations(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT tm.id,tm.name,tm.position
               FROM team_members tm
               JOIN player_user_links pul ON pul.team_member_id=tm.id
               JOIN people p ON p.id=pul.person_id
               WHERE tm.active=1 AND p.active=1 AND pul.user_id IS NULL
               ORDER BY tm.name COLLATE NOCASE"""
        ).fetchall()
        return [dict(row) for row in rows]

    def available_players_for_team(self, team_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT tm.id,tm.name,tm.position
               FROM team_members tm
               JOIN player_user_links pul ON pul.team_member_id=tm.id
               JOIN people p ON p.id=pul.person_id
               JOIN team_memberships tms ON tms.person_id=p.id
               WHERE tm.active=1 AND p.active=1 AND pul.user_id IS NULL
                 AND tms.team_id=? AND tms.status='ACTIVE'
                 AND (tms.valid_from IS NULL OR tms.valid_from<=date('now'))
                 AND (tms.valid_to IS NULL OR tms.valid_to>=date('now'))
               ORDER BY tm.name COLLATE NOCASE""",
            (int(team_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def register_player(
        self, *, team_member_id: int, username: str, password_hash: str
    ) -> int:
        link = self.connection.execute(
            """SELECT pul.person_id,pul.user_id
               FROM player_user_links pul
               JOIN team_members tm ON tm.id=pul.team_member_id
               JOIN people p ON p.id=pul.person_id
               WHERE pul.team_member_id=? AND tm.active=1 AND p.active=1""",
            (int(team_member_id),),
        ).fetchone()
        if link is None or link["user_id"] is not None:
            raise ValueError("Atleta indisponível para cadastro.")
        person_id = int(link["person_id"])
        now = now_iso()
        try:
            cursor = self.connection.execute(
                """INSERT INTO users(person_id,username,password_hash,active,
                       must_change_password,credential_version,created_at,updated_at)
                   VALUES(?,?,?,1,0,1,?,?)""",
                (person_id, self.normalize_username(username), password_hash, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Usuário indisponível para cadastro.") from exc
        user_id = int(cursor.lastrowid)
        updated = self.connection.execute(
            "UPDATE player_user_links SET user_id=? WHERE team_member_id=? AND user_id IS NULL",
            (user_id, int(team_member_id)),
        )
        if updated.rowcount != 1:
            raise ValueError("Atleta indisponível para cadastro.")
        self.connection.execute(
            "INSERT INTO system_roles(user_id,role_code) VALUES(?,'PLAYER')",
            (user_id,),
        )
        self.audit_event(
            actor_user_id=None,
            action="user.self_register",
            entity="user",
            target_id=str(user_id),
            origin="registration",
            after={"team_member_id": int(team_member_id), "roles": ["PLAYER"]},
        )
        return user_id

    def person_id_for_player(self, team_member_id: int) -> int | None:
        row = self.connection.execute(
            "SELECT person_id FROM player_user_links WHERE team_member_id=?",
            (team_member_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def create_person(self, full_name: str, display_name: str | None = None) -> int:
        full_name = full_name.strip()
        display_name = (display_name or full_name).strip()
        if not full_name or not display_name:
            raise ValueError("Nome da pessoa é obrigatório.")
        now = now_iso()
        cursor = self.connection.execute(
            "INSERT INTO people(full_name,display_name,active,created_at,updated_at) VALUES(?,?,1,?,?)",
            (full_name, display_name, now, now),
        )
        return int(cursor.lastrowid)

    def create_user(
        self,
        *,
        person_id: int,
        username: str,
        password_hash: str,
        roles: Iterable[str],
        linked_player_id: int | None,
        actor_user_id: int,
        team_id: int | None = None,
    ) -> int:
        normalized_roles = {str(role).upper() for role in roles}
        if not normalized_roles or not normalized_roles <= {"DEV", "CT", "PLAYER"}:
            raise ValueError("Papéis inválidos.")
        if "PLAYER" in normalized_roles and linked_player_id is None:
            raise ValueError("PLAYER exige vínculo com atleta.")
        if normalized_roles & {"CT", "PLAYER"} and team_id is None:
            raise ValueError("Selecione um time.")
        if self.connection.execute("SELECT 1 FROM users WHERE person_id=?", (person_id,)).fetchone():
            raise ValueError("A pessoa já possui conta.")
        if "PLAYER" in normalized_roles and linked_player_id is not None:
            player_team = self.connection.execute(
                """SELECT 1 FROM player_user_links pul
                   JOIN team_memberships tms ON tms.person_id=pul.person_id
                   WHERE pul.team_member_id=? AND tms.team_id=? AND tms.status='ACTIVE'""",
                (linked_player_id, team_id),
            ).fetchone()
            if player_team is None:
                raise ValueError("O atleta não pertence ao time selecionado.")
        now = now_iso()
        try:
            cursor = self.connection.execute(
                """INSERT INTO users(person_id,username,password_hash,active,
                       must_change_password,credential_version,created_at,updated_at)
                   VALUES(?,?,?,1,0,1,?,?)""",
                (person_id, self.normalize_username(username), password_hash, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username ou pessoa já possui conta.") from exc
        user_id = int(cursor.lastrowid)
        for role in sorted(normalized_roles):
            self.connection.execute(
                "INSERT INTO system_roles(user_id,role_code) VALUES(?,?)",
                (user_id, role),
            )
        if "CT" in normalized_roles:
            team = self.connection.execute(
                "SELECT id FROM teams WHERE id=? AND active=1", (team_id,)
            ).fetchone()
            if team is None:
                raise ValueError("Time inexistente ou inativo.")
            season = self.connection.execute(
                "SELECT id FROM seasons WHERE team_id=? AND active=1 ORDER BY id DESC LIMIT 1",
                (team[0],),
            ).fetchone()
            if season is None:
                raise ValueError("O time selecionado não possui temporada ativa.")
            membership = self.connection.execute(
                """SELECT tm.id FROM team_memberships tm
                   WHERE tm.person_id=? AND tm.team_id=? AND tm.season_id=?""",
                (person_id, team[0], season[0]),
            ).fetchone()
            if membership is None:
                now = now_iso()
                cursor_membership = self.connection.execute(
                    """INSERT INTO team_memberships(
                           person_id,team_id,season_id,status,valid_from,valid_to,
                           created_at,updated_at
                       ) VALUES(?,?,?,'ACTIVE',NULL,NULL,?,?)""",
                    (person_id, team[0], season[0], now, now),
                )
                membership_id = int(cursor_membership.lastrowid)
            else:
                membership_id = int(membership[0])
            self.connection.execute(
                "INSERT OR IGNORE INTO membership_roles(membership_id,role_code) VALUES(?,'CT')",
                (membership_id,),
            )
        if linked_player_id is not None:
            link = self.connection.execute(
                "SELECT person_id,user_id FROM player_user_links WHERE team_member_id=?",
                (linked_player_id,),
            ).fetchone()
            if not link or int(link["person_id"]) != person_id or link["user_id"] is not None:
                raise ValueError("Vínculo de atleta inválido ou já utilizado.")
            self.connection.execute(
                "UPDATE player_user_links SET user_id=? WHERE team_member_id=?",
                (user_id, linked_player_id),
            )
        self.audit_event(
            actor_user_id=actor_user_id,
            action="user.create",
            entity="user",
            target_id=str(user_id),
            origin="admin",
            after={"username": self.normalize_username(username), "roles": sorted(normalized_roles)},
        )
        return user_id

    def set_roles(self, user_id: int, roles: Iterable[str], *, actor_user_id: int) -> None:
        normalized = {str(role).upper() for role in roles}
        if not normalized or not normalized <= {"DEV", "CT", "PLAYER"}:
            raise ValueError("Papéis inválidos.")
        linked = self.connection.execute(
            "SELECT team_member_id FROM player_user_links WHERE user_id=?", (user_id,)
        ).fetchone()
        if "PLAYER" in normalized and linked is None:
            raise ValueError("PLAYER exige vínculo com atleta.")
        before = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT role_code FROM system_roles WHERE user_id=? ORDER BY role_code", (user_id,)
            )
        ]
        self.connection.execute("DELETE FROM system_roles WHERE user_id=?", (user_id,))
        for role in sorted(normalized):
            self.connection.execute(
                "INSERT INTO system_roles(user_id,role_code) VALUES(?,?)", (user_id, role)
            )
        user = self.get_user(user_id)
        if user and user["person_id"] is not None:
            memberships = self.connection.execute(
                "SELECT id FROM team_memberships WHERE person_id=?",
                (user["person_id"],),
            ).fetchall()
            if not memberships and "CT" in normalized:
                raise ValueError(
                    "Pessoa sem vínculo com nenhum time; use a criação de conta com "
                    "seleção de time para o primeiro papel CT."
                )
            for membership in memberships:
                self.connection.execute(
                    "DELETE FROM membership_roles WHERE membership_id=? AND role_code IN('CT','PLAYER')",
                    (membership[0],),
                )
            linked_player = self.connection.execute(
                "SELECT team_member_id FROM player_user_links WHERE user_id=?", (user_id,)
            ).fetchone()
            for role in sorted(normalized & {"CT", "PLAYER"}):
                if role == "PLAYER" and linked_player is None:
                    continue
                if not memberships:
                    raise ValueError("A pessoa não possui vínculo com nenhum time.")
                self.connection.execute(
                    "INSERT OR IGNORE INTO membership_roles(membership_id,role_code) VALUES(?,?)",
                    (memberships[0][0], role),
                )
        self.audit_event(actor_user_id=actor_user_id, action="user.roles.update", entity="user", target_id=str(user_id), origin="admin", before={"roles": before}, after={"roles": sorted(normalized)})

    def deactivate_user(self, user_id: int, *, actor_user_id: int) -> None:
        now = now_iso()
        self.connection.execute(
            "UPDATE users SET active=0,credential_version=credential_version+1,updated_at=? WHERE id=?",
            (now, user_id),
        )
        self.revoke_user_sessions(user_id)
        self.audit_event(actor_user_id=actor_user_id, action="user.deactivate", entity="user", target_id=str(user_id), origin="admin")

    def reset_password(self, user_id: int, password_hash: str, *, actor_user_id: int) -> None:
        now = now_iso()
        self.connection.execute(
            """UPDATE users SET password_hash=?,must_change_password=0,
                   credential_version=credential_version+1,updated_at=? WHERE id=?""",
            (password_hash, now, user_id),
        )
        self.revoke_user_sessions(user_id)
        self.audit_event(actor_user_id=actor_user_id, action="user.password.reset", entity="user", target_id=str(user_id), origin="admin")

    def change_own_password(self, user_id: int, password_hash: str) -> None:
        now = now_iso()
        self.connection.execute(
            """UPDATE users SET password_hash=?,must_change_password=0,
                   credential_version=credential_version+1,updated_at=? WHERE id=?""",
            (password_hash, now, user_id),
        )
        self.revoke_user_sessions(user_id)
        self.audit_event(actor_user_id=user_id, action="user.password.change", entity="user", target_id=str(user_id), origin="self")

    def own_attendance(self, user_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT ts.training_date,ts.is_finalized,ar.confirmation_status,
                      ar.present,ar.updated_at,ce.id calendar_event_id,
                      ce.status calendar_status,
                      CASE WHEN ce.status IN ('CANCELLED','RESCHEDULED') THEN 0
                           ELSE 1 END AS is_eligible
               FROM player_user_links pul
               JOIN attendance_records ar ON ar.member_id=pul.team_member_id
               JOIN training_sessions ts ON ts.id=ar.session_id
               LEFT JOIN calendar_events ce ON ce.attendance_session_id=ts.id
               WHERE pul.user_id=? ORDER BY ts.training_date DESC""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def audit_event(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity: str,
        target_id: str | None,
        origin: str,
        before: Any = None,
        after: Any = None,
        request_id: str | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO security_audit_events(
                   actor_user_id,occurred_at,action,entity,target_id,origin,
                   before_json,after_json,request_id
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                actor_user_id,
                now_iso(),
                action,
                entity,
                target_id,
                origin,
                json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
                request_id,
            ),
        )

    def list_security_audit(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT e.id,e.occurred_at,e.action,e.entity,e.target_id,e.origin,
                      e.before_json,e.after_json,e.request_id,e.actor_user_id,
                      u.username actor_username
               FROM security_audit_events e
               LEFT JOIN users u ON u.id=e.actor_user_id
               ORDER BY e.id DESC LIMIT ?""",
            (max(1, min(limit, 1000)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_security_audit_result(
        self, *, request_id: str, actor_user_id: int
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT after_json FROM security_audit_events
               WHERE request_id=? AND actor_user_id=?
                 AND action='sql.change.execute' AND origin='sql-admin'
               ORDER BY id DESC LIMIT 1""",
            (request_id, actor_user_id),
        ).fetchone()
        if row is None or not row["after_json"]:
            return None
        try:
            payload = json.loads(str(row["after_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
