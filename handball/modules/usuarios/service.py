from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from handball.core.authorization import AccessContext, require_team_access
from handball.core.organization import CURRENT_SEASON_LABEL, ORGANIZATION
from handball.core.team_theme import team_theme
from handball.database.contracts import UnitOfWorkFactoryContract

logger = logging.getLogger(__name__)


def _current_presence_streak(eligible_rows: list[dict[str, Any]]) -> int:
    """Presenças seguidas até o último treino apurado, do mais recente para trás.

    Treino ainda não apurado (present is None) não zera a sequência — ele
    simplesmente ainda não aconteceu para efeito de contagem. Uma ausência
    zera.
    """
    streak = 0
    for row in sorted(eligible_rows, key=lambda item: str(item["training_date"]), reverse=True):
        if row["present"] is None:
            continue
        if row["present"] != 1:
            break
        streak += 1
    return streak


def _initials(display_name: str) -> str:
    """Duas letras a partir do nome do time, para o cartão do cadastro.

    Não usa o monograma do tema de propósito: o monograma é ativo de marca e
    /login não carrega marca de time nenhuma.
    """
    words = [word for word in display_name.split() if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


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
            "must_change_password": False,
            "organization": {
                "code": ORGANIZATION.code,
                "slug": ORGANIZATION.slug,
                "display_name": ORGANIZATION.display_name,
            },
        }

    def resolve_active_team_view(self, context: AccessContext) -> dict[str, Any]:
        """Resolve a identidade organizacional e visual do time ativo da sessão.

        O slug nunca vem do cliente: sempre parte de context.team_ids, que o
        backend calcula a partir de team_memberships ativas (ver
        docs/design-system/AUDIT.md §11). Usuário sem time (Caso D) ou time
        sem tema cadastrado/inativo (Caso E) caem no tema neutro sem quebrar a
        renderização. Quando a sessão tem mais de um time vinculado, o
        provisório é escolher o de menor id, de forma determinística — não há
        hoje seletor de time ativo nem armazenamento persistente da escolha;
        isso é limitação conhecida e documentada em
        docs/design-system/ARCHITECTURE.md (Caso C), não decidida aqui.
        """
        team_row: dict[str, Any] | None = None
        if context.team_ids:
            with self._unit_of_work_factory(read_only=True) as unit_of_work:
                teams = unit_of_work.identity.get_teams_by_ids(context.team_ids)
            if teams:
                team_row = teams[0]
            else:
                logger.warning(
                    "Sessão do usuário %s tem team_ids sem linha ativa correspondente em 'teams'; "
                    "usando tema neutro.",
                    context.user_id,
                )
        identity = team_theme(team_row["slug"] if team_row else None)
        organization = (
            {"code": team_row["code"], "slug": team_row["slug"], "display_name": team_row["display_name"]}
            if team_row is not None
            else {"code": None, "slug": identity.slug, "display_name": identity.display_name}
        )
        return {"organization": organization, "team_theme": identity.to_dict()}

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
            # Próximo treino ainda não apurado, para o cartão de ação da tela
            # "Seu relatório". Sai das linhas que já foram carregadas — nenhuma
            # consulta a mais e, principalmente, nenhuma data inventada: se não
            # houver treino aberto à frente, o cartão simplesmente não aparece.
            "next_training": next(
                (
                    {
                        "training_date": row["training_date"],
                        "confirmation_status": row["confirmation_status"],
                    }
                    for row in sorted(eligible_rows, key=lambda item: str(item["training_date"]))
                    if row["present"] is None
                    and not row.get("is_finalized")
                    and str(row["training_date"]) >= date.today().isoformat()
                ),
                None,
            ),
            "streak": _current_presence_streak(eligible_rows),
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

    def available_player_registrations(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.available_player_registrations()

    def registration_teams(self) -> list[dict[str, Any]]:
        """Times oferecíveis no cadastro do /login, com o elenco livre de cada um.

        Alimenta o passo 1 do assistente de criação de conta. Só entra time
        ativo; time ativo sem nenhum atleta livre aparece na lista como
        indisponível ("Em breve") em vez de sumir, para o visitante entender
        que o time existe e o problema é outro.

        Não devolve cor, logotipo nem tema: /login é a Camada 1 neutra e o
        nome do time aqui é *dado escolhível*, não identidade da página (ver
        docs/design-system/ARCHITECTURE.md §Camada 1). O tema pós-login
        continua saindo de resolve_active_team_view, nunca deste formulário.
        """
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            teams = [team for team in unit_of_work.identity.list_teams() if team["active"]]
            return [
                {
                    "id": int(team["id"]),
                    "display_name": str(team["display_name"]),
                    "initials": _initials(str(team["display_name"])),
                    "players": unit_of_work.identity.available_players_for_team(int(team["id"])),
                }
                for team in teams
            ]

    def list_teams(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.list_teams()

    def create_team(self, body: Any, actor: AccessContext) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            team_id = unit_of_work.identity.create_team(
                code=body.code,
                slug=body.slug,
                display_name=body.display_name,
                season_label=body.season_label or CURRENT_SEASON_LABEL,
                actor_user_id=actor.user_id,
            )
        return {"id": team_id}

    def set_team_active(self, team_id: int, active: bool, actor: AccessContext) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.set_team_active(team_id, active, actor_user_id=actor.user_id)

    def available_players_for_team(self, team_id: int) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.identity.available_players_for_team(team_id)

    def create_player_account_as_ct(self, body: Any, actor: AccessContext) -> dict[str, Any]:
        require_team_access(body.team_id, actor)
        if not body.temporary_password:
            raise ValueError("A senha não pode ficar vazia.")
        with self._unit_of_work_factory() as unit_of_work:
            person_id = unit_of_work.identity.person_id_for_player(body.team_member_id)
            if person_id is None:
                raise ValueError("Atleta não possui vínculo de pessoa.")
            user_id = unit_of_work.identity.create_user(
                person_id=person_id,
                username=body.username,
                password_hash=self._hasher.hash(body.temporary_password),
                roles=["PLAYER"],
                linked_player_id=body.team_member_id,
                team_id=body.team_id,
                actor_user_id=actor.user_id,
            )
            return unit_of_work.identity.get_user(user_id) or {"id": user_id}

    def register_player(
        self,
        *,
        team_member_id: int,
        username: str,
        password: str,
        team_id: int | None = None,
    ) -> int:
        """Cria a conta do atleta e a vincula ao seu perfil no elenco.

        `team_id` é o time escolhido no passo 1 do assistente. Ele chega do
        formulário, então é tratado como entrada não confiável: só serve para
        *restringir* a lista de atletas aceitáveis, conferida contra o banco
        aqui. Nada de tema, permissão ou vínculo é derivado dele — o vínculo
        real continua vindo de player_user_links, e o tema de
        resolve_active_team_view depois do login.
        """
        if not password:
            raise ValueError("A senha não pode ficar vazia.")
        with self._unit_of_work_factory() as unit_of_work:
            if team_id is not None:
                active_team_ids = {
                    int(team["id"])
                    for team in unit_of_work.identity.list_teams()
                    if team["active"]
                }
                if int(team_id) not in active_team_ids:
                    raise ValueError("Time indisponível para cadastro.")
                allowed = {
                    int(player["id"])
                    for player in unit_of_work.identity.available_players_for_team(int(team_id))
                }
                if int(team_member_id) not in allowed:
                    raise ValueError("Atleta indisponível para cadastro neste time.")
            return unit_of_work.identity.register_player(
                team_member_id=team_member_id,
                username=username,
                password_hash=self._hasher.hash(password),
            )

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
                team_id=body.team_id,
                actor_user_id=actor.user_id,
            )
            return unit_of_work.identity.get_user(user_id) or {"id": user_id}

    def set_roles(self, user_id: int, roles: list[str], actor: AccessContext) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.set_roles(user_id, roles, actor_user_id=actor.user_id)

    def set_permission_grants(
        self, user_id: int, permissions: list[str], actor: AccessContext
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity.set_permission_grants(
                user_id, permissions, actor_user_id=actor.user_id
            )

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
