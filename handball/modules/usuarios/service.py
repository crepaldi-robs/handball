from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from handball.core.authorization import AccessContext
from handball.core.organization import ORGANIZATION
from handball.database.contracts import UnitOfWorkFactoryContract


class IdentityService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactoryContract) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._hasher = PasswordHasher()

    def me(self, context: AccessContext) -> dict[str, Any]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            user = unit_of_work.identity.get_user(context.user_id)
        if user is None:
            raise KeyError("Usuário não encontrado.")
        return {
            "user_id": context.user_id,
            "person_id": context.person_id,
            "username": context.username,
            "display_name": context.display_name,
            "system_roles": sorted(context.system_roles),
            "team_roles": sorted(context.team_roles),
            "permissions": sorted(str(value) for value in context.permissions),
            "team_ids": sorted(context.team_ids),
            "linked_player_id": context.linked_player_id,
            "must_change_password": context.must_change_password,
            "organization": {
                "code": ORGANIZATION.code,
                "slug": ORGANIZATION.slug,
                "display_name": ORGANIZATION.display_name,
            },
        }

    def own_attendance(self, context: AccessContext) -> list[dict[str, Any]]:
        if context.linked_player_id is None:
            raise ValueError("A conta não está vinculada a um atleta.")
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.own_attendance(context.user_id)

    def own_report(self, context: AccessContext) -> dict[str, Any]:
        rows = self.own_attendance(context)
        eligible_rows = [row for row in rows if row.get("is_eligible", 1)]
        eligible = len(eligible_rows)
        confirmations = sum(row["confirmation_status"] != "PENDING" for row in eligible_rows)
        present = sum(row["present"] == 1 for row in eligible_rows)
        absent = sum(row["present"] == 0 for row in eligible_rows)
        pending = sum(row["present"] is None for row in eligible_rows)
        monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"eligible": 0, "present": 0})
        for row in eligible_rows:
            month = str(row["training_date"])[:7]
            monthly[month]["eligible"] += 1
            monthly[month]["present"] += int(row["present"] == 1)
        evolution = [
            {"month": month, **values, "attendance_rate": round(values["present"] / values["eligible"], 4) if values["eligible"] else None}
            for month, values in sorted(monthly.items())
        ]
        return {
            "period": {
                "from": min((row["training_date"] for row in rows), default=None),
                "to": max((row["training_date"] for row in rows), default=None),
            },
            "eligible_trainings": eligible,
            "confirmations": confirmations,
            "presences": present,
            "absences": absent,
            "pending": pending,
            "attendance_rate": round(present / (present + absent), 4) if present + absent else None,
            "monthly_evolution": evolution,
            "history": rows,
            "completeness": {
                "complete": pending == 0,
                "message": "Todos os treinos foram apurados." if pending == 0 else f"{pending} treino(s) ainda não apurado(s).",
            },
        }

    def list_users(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.list_users()

    def options(self) -> dict[str, list[dict[str, Any]]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.list_people_and_players()

    def security_audit(self, limit: int) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.list_security_audit(limit)

    def create_user(self, body: Any, actor: AccessContext) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            person_id = body.person_id
            if body.linked_player_id is not None:
                linked_person = unit_of_work.identity.person_id_for_player(body.linked_player_id)
                if linked_person is None:
                    raise ValueError("Atleta não possui vínculo de pessoa.")
                if person_id is not None and person_id != linked_person:
                    raise ValueError("Pessoa e atleta não correspondem.")
                person_id = linked_person
            if person_id is None:
                if not body.full_name:
                    raise ValueError("Informe uma pessoa existente ou um nome.")
                person_id = unit_of_work.identity.create_person(body.full_name, body.display_name)
            user_id = unit_of_work.identity.create_user(
                person_id=person_id,
                username=body.username,
                password_hash=self._hasher.hash(body.temporary_password),
                roles=body.roles,
                linked_player_id=body.linked_player_id,
                actor_user_id=actor.user_id,
            )
            return unit_of_work.identity.get_user(user_id) or {"id": user_id}

    def set_roles(self, user_id: int, roles: list[str], actor: AccessContext) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.set_roles(user_id, roles, actor_user_id=actor.user_id)

    def deactivate(self, user_id: int, actor: AccessContext) -> None:
        if user_id == actor.user_id:
            raise ValueError("Não é permitido desativar a própria conta nesta operação.")
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.deactivate_user(user_id, actor_user_id=actor.user_id)

    def revoke(self, user_id: int, actor: AccessContext) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.revoke_user_sessions(user_id)
            unit_of_work.identity.audit_event(actor_user_id=actor.user_id, action="auth.sessions.revoke", entity="user", target_id=str(user_id), origin="admin")

    def reset_password(self, user_id: int, temporary_password: str, actor: AccessContext) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.reset_password(user_id, self._hasher.hash(temporary_password), actor_user_id=actor.user_id)

    def change_own_password(self, context: AccessContext, current_password: str, new_password: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            user = unit_of_work.identity.get_user(context.user_id)
            if user is None:
                raise ValueError("Usuário inexistente.")
            try:
                valid = self._hasher.verify(str(user["password_hash"]), current_password)
            except (VerifyMismatchError, InvalidHashError):
                valid = False
            if not valid:
                raise ValueError("Senha atual inválida.")
            unit_of_work.identity.change_own_password(context.user_id, self._hasher.hash(new_password))
