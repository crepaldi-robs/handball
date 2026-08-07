from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from handball.database.contracts import UnitOfWorkFactoryContract

from .ranking import (
    RANK_SCOPES,
    SCOPE_LABELS,
    apply_answer,
    choose_representative,
    max_questions,
    next_probe,
    question_text,
    start_interval,
)

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")

_SEMESTER_PATTERN = re.compile(r"^(\d{4})\.(1|2)$")

_DRIFT_MESSAGE = "As camadas mudaram; recomece o ranqueamento deste atleta."

# Um sexteto de linha completo define o corte titular×reserva: as camadas mais
# fortes entram inteiras até somarem seis atletas de linha ativos.
_STARTER_LINE_TARGET = 6


def layer_label(ordinal: int) -> str:
    return f"Camada {int(ordinal) + 1}"


def semester_bounds(label: str | None = None) -> dict[str, str]:
    """Recorte simples de semestre civil: AAAA.1 = jan–jun, AAAA.2 = jul–dez."""

    if label:
        match = _SEMESTER_PATTERN.match(label.strip())
        if match is None:
            raise ValueError("Semestre inválido. Use o formato AAAA.1 ou AAAA.2.")
        year, half = int(match.group(1)), int(match.group(2))
    else:
        today = datetime.now(LOCAL_TIMEZONE).date()
        year, half = today.year, 1 if today.month <= 6 else 2
    if half == 1:
        starts_on, ends_on = date(year, 1, 1), date(year, 6, 30)
    else:
        starts_on, ends_on = date(year, 7, 1), date(year, 12, 31)
    return {
        "label": f"{year}.{half}",
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat(),
    }


class RosterService:
    """Caso de uso da gestão de elenco: cadastro, hierarquia e métricas."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactoryContract) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    # ------------------------------------------------------------------
    # Cadastro (delegado ao repositório de presenças, dono do SQL de membros)
    # ------------------------------------------------------------------

    def members(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            members = unit_of_work.attendance.list_members(include_inactive=True)
            rankings = unit_of_work.roster.rankings_by_member()
        return self._members_with_layers(members, rankings)

    def add_member(
        self, name: str, position: str, *, attack_positions: Iterable[str] | None = None,
        defensive_positions: Iterable[str] | None = None, actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.add_member(
                name, position, attack_positions=attack_positions,
                defensive_positions=defensive_positions, actor_user_id=actor_user_id,
            )
            members = unit_of_work.attendance.list_members(include_inactive=True)
            rankings = unit_of_work.roster.rankings_by_member()
        return self._members_with_layers(members, rankings)

    def update_member(
        self,
        member_id: int,
        *,
        position: str,
        active: bool,
        attack_positions: Iterable[str] | None = None,
        defensive_positions: Iterable[str] | None = None,
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.update_member(
                member_id,
                position=position,
                active=active,
                attack_positions=attack_positions,
                defensive_positions=defensive_positions,
                actor_user_id=actor_user_id,
            )
            members = unit_of_work.attendance.list_members(include_inactive=True)
            rankings = unit_of_work.roster.rankings_by_member()
        return self._members_with_layers(members, rankings)

    @staticmethod
    def _members_with_layers(
        members: list[dict[str, Any]], rankings: dict[int, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        for member in members:
            member_scopes = rankings.get(int(member["id"]), {})
            member["layers"] = {
                scope: {
                    "ordinal": info["layer_ordinal"],
                    "label": layer_label(info["layer_ordinal"]),
                }
                for scope, info in member_scopes.items()
            }
        return members

    # ------------------------------------------------------------------
    # Hierarquia em camadas
    # ------------------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            roster = unit_of_work.roster
            available = roster.is_available()
            names = self._member_names(unit_of_work)
            scopes: dict[str, Any] = {}
            for scope in RANK_SCOPES:
                layers = roster.list_layers(scope)
                for layer in layers:
                    layer["label"] = layer_label(layer["ordinal"])
                session = roster.active_session(scope)
                scopes[scope] = {
                    "label": SCOPE_LABELS[scope],
                    "layers": layers,
                    "pending": roster.pending_members(scope),
                    "active_session": (
                        self._session_payload(unit_of_work, session, names)
                        if session is not None
                        else None
                    ),
                }
        return {"available": available, "scopes": scopes}

    def start_ranking(
        self, *, scope: str, member_id: int, rerank: bool, actor_user_id: int
    ) -> dict[str, Any]:
        if scope not in RANK_SCOPES:
            raise ValueError("Escopo de hierarquia inválido.")
        with self._unit_of_work_factory() as unit_of_work:
            roster = unit_of_work.roster
            if not roster.is_available():
                raise RuntimeError(
                    "O banco ainda não recebeu a atualização de hierarquia do elenco."
                )
            members = unit_of_work.attendance.list_members(include_inactive=True)
            member = next(
                (item for item in members if int(item["id"]) == int(member_id)), None
            )
            if member is None:
                raise KeyError("Atleta não encontrado.")
            if not bool(member["active"]):
                raise ValueError("Atleta inativo não entra na hierarquia.")
            positions = list(member.get("attack_positions") or ())
            if scope == "GOALKEEPER" and "GOL" not in positions:
                raise ValueError("Este atleta não tem a posição de goleiro cadastrada.")
            if scope == "LINE" and not any(value != "GOL" for value in positions):
                raise ValueError("Este atleta não tem posição de linha cadastrada.")
            existing = roster.assignment_for_member(member_id, scope)
            if rerank and existing is None:
                raise ValueError("Este atleta ainda não tem camada para re-ranquear.")
            if not rerank and existing is not None:
                raise ValueError(
                    "Este atleta já tem camada. Use o re-ranqueamento para mudá-la."
                )
            if roster.active_session(scope) is not None:
                raise ValueError(
                    "Já existe um ranqueamento em andamento neste escopo. "
                    "Conclua ou cancele antes de iniciar outro."
                )
            if rerank and existing is not None:
                own_layer = next(
                    layer
                    for layer in roster.list_layers(scope)
                    if layer["layer_id"] == existing["layer_id"]
                )
                if len(own_layer["members"]) == 1:
                    # Camada unitária não pode servir de referência contra o
                    # próprio atleta: sai agora (com compactação) e o atleta é
                    # reinserido do zero; cancelar deixa-o visível na fila.
                    roster.remove_assignment_and_compact(
                        member_id, scope, actor_user_id=actor_user_id
                    )

            layer_count = roster.layer_count(scope)
            lo, hi = start_interval(layer_count)
            probe = next_probe(lo, hi)
            if probe is None:
                new_layer_id = roster.insert_layer_at(
                    scope, lo, actor_user_id=actor_user_id
                )
                roster.assign_member(
                    member_id, scope, new_layer_id, actor_user_id=actor_user_id
                )
                session = roster.create_session(
                    scope=scope,
                    subject_member_id=member_id,
                    is_rerank=rerank,
                    lo_ordinal=lo,
                    hi_ordinal=hi,
                    pending_reference_member_id=None,
                    created_by_user_id=actor_user_id,
                    status="COMPLETED",
                    result_layer_id=new_layer_id,
                )
                return self._completed_payload(
                    session["session_id"], ordinal=lo, created_new_layer=True, asked=0
                )
            reference = self._representative_at(roster, scope, probe, member_id)
            session = roster.create_session(
                scope=scope,
                subject_member_id=member_id,
                is_rerank=rerank,
                lo_ordinal=lo,
                hi_ordinal=hi,
                pending_reference_member_id=int(reference["member_id"]),
                created_by_user_id=actor_user_id,
            )
            names = self._member_names(unit_of_work)
            return self._session_payload(unit_of_work, session, names)

    def answer(
        self,
        session_id: str,
        *,
        reference_member_id: int,
        outcome: str,
        actor_user_id: int,
    ) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            roster = unit_of_work.roster
            session = roster.get_session(session_id)
            if session is None:
                raise KeyError("Ranqueamento não encontrado.")
            if session["status"] != "ACTIVE":
                raise ValueError("Este ranqueamento já foi concluído ou cancelado.")
            scope = session["scope"]
            subject_id = session["subject_member_id"]
            lo, hi = session["lo_ordinal"], session["hi_ordinal"]
            layer_count = roster.layer_count(scope)
            if hi > layer_count:
                raise ValueError(_DRIFT_MESSAGE)
            if session["pending_reference_member_id"] != int(reference_member_id):
                raise ValueError(_DRIFT_MESSAGE)
            probe = next_probe(lo, hi)
            if probe is None:
                raise ValueError(_DRIFT_MESSAGE)
            probe_layer = roster.layer_by_ordinal(scope, probe)
            if probe_layer is None:
                raise ValueError(_DRIFT_MESSAGE)
            names = self._member_names(unit_of_work)
            roster.record_comparison(
                session_id=session_id,
                scope=scope,
                subject_member_id=subject_id,
                reference_member_id=int(reference_member_id),
                question=question_text(
                    names.get(subject_id, f"#{subject_id}"),
                    names.get(int(reference_member_id), f"#{reference_member_id}"),
                ),
                outcome=outcome,
                actor_user_id=actor_user_id,
            )
            asked = self._asked_count(roster, session_id, subject_id)
            action, value = apply_answer(lo, hi, probe, outcome)
            if action == "JOIN_LAYER":
                target_ordinal = int(value)
                target_ordinal = self._remove_old_assignment(
                    roster, session, target_ordinal, actor_user_id
                )
                layer = roster.layer_by_ordinal(scope, target_ordinal)
                if layer is None:
                    raise ValueError(_DRIFT_MESSAGE)
                roster.assign_member(
                    subject_id, scope, layer["layer_id"], actor_user_id=actor_user_id
                )
                roster.complete_session(session_id, result_layer_id=layer["layer_id"])
                return self._completed_payload(
                    session_id,
                    ordinal=target_ordinal,
                    created_new_layer=False,
                    asked=asked,
                )
            new_lo, new_hi = value
            if new_lo >= new_hi:
                insert_ordinal = self._remove_old_assignment(
                    roster, session, int(new_lo), actor_user_id
                )
                new_layer_id = roster.insert_layer_at(
                    scope, insert_ordinal, actor_user_id=actor_user_id
                )
                roster.assign_member(
                    subject_id, scope, new_layer_id, actor_user_id=actor_user_id
                )
                roster.complete_session(session_id, result_layer_id=new_layer_id)
                return self._completed_payload(
                    session_id,
                    ordinal=insert_ordinal,
                    created_new_layer=True,
                    asked=asked,
                )
            next_mid = next_probe(new_lo, new_hi)
            assert next_mid is not None
            reference = self._representative_at(roster, scope, next_mid, subject_id)
            roster.save_session_interval(
                session_id,
                lo_ordinal=new_lo,
                hi_ordinal=new_hi,
                pending_reference_member_id=int(reference["member_id"]),
            )
            updated = roster.get_session(session_id)
            assert updated is not None
            return self._session_payload(unit_of_work, updated, names)

    def cancel(self, session_id: str) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            roster = unit_of_work.roster
            session = roster.get_session(session_id)
            if session is None:
                raise KeyError("Ranqueamento não encontrado.")
            if session["status"] != "ACTIVE":
                raise ValueError("Este ranqueamento já foi concluído ou cancelado.")
            roster.cancel_session(session_id)
        return {"session_id": session_id, "status": "CANCELLED"}

    def save_refinement(
        self,
        layer_id: int,
        *,
        position: str,
        member_ids: list[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.roster.replace_refinements(
                layer_id, position, member_ids, actor_user_id=actor_user_id
            )
        return self.overview()

    # ------------------------------------------------------------------
    # Métricas de presença
    # ------------------------------------------------------------------

    def metrics(self, semester: str | None = None) -> dict[str, Any]:
        bounds = semester_bounds(semester)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            roster = unit_of_work.roster
            members = unit_of_work.attendance.list_members(include_inactive=True)
            rankings = roster.rankings_by_member()
            presence = roster.presence_metrics(bounds["starts_on"], bounds["ends_on"])
            sessions_considered = roster.finalized_sessions_count(
                bounds["starts_on"], bounds["ends_on"]
            )
            line_layers = roster.list_layers("LINE")
            goalkeeper_layers = roster.list_layers("GOALKEEPER")

        def group_totals(member_ids: Iterable[int]) -> dict[str, Any]:
            ids = sorted(set(member_ids))
            presents = sum(presence.get(mid, {}).get("presents", 0) for mid in ids)
            records = sum(presence.get(mid, {}).get("records", 0) for mid in ids)
            return {
                "members": ids,
                "presents": presents,
                "records": records,
                "rate": round(presents / records, 3) if records else None,
            }

        athletes = []
        for member in sorted(members, key=lambda item: str(item["name"]).casefold()):
            member_id = int(member["id"])
            stats = presence.get(member_id, {"presents": 0, "records": 0})
            member_scopes = rankings.get(member_id, {})
            primary = member_scopes.get("LINE") or member_scopes.get("GOALKEEPER")
            athletes.append(
                {
                    "member_id": member_id,
                    "name": str(member["name"]),
                    "active": bool(member["active"]),
                    "layer_label": (
                        layer_label(primary["layer_ordinal"]) if primary else None
                    ),
                    "presents": stats["presents"],
                    "records": stats["records"],
                    "rate": (
                        round(stats["presents"] / stats["records"], 3)
                        if stats["records"]
                        else None
                    ),
                }
            )

        layers_metrics = []
        for scope, layers in (("LINE", line_layers), ("GOALKEEPER", goalkeeper_layers)):
            for layer in layers:
                totals = group_totals(item["member_id"] for item in layer["members"])
                layers_metrics.append(
                    {
                        "scope": scope,
                        "ordinal": layer["ordinal"],
                        "label": layer_label(layer["ordinal"]),
                        **totals,
                    }
                )

        starter_ids: set[int] = set()
        line_starters: list[int] = []
        for layer in line_layers:  # já vem da mais forte para a mais fraca
            active_ids = [
                item["member_id"] for item in layer["members"] if item["active"]
            ]
            if not active_ids:
                continue
            line_starters.extend(active_ids)
            if len(line_starters) >= _STARTER_LINE_TARGET:
                break
        starter_ids.update(line_starters)
        for layer in goalkeeper_layers:
            active_ids = [
                item["member_id"] for item in layer["members"] if item["active"]
            ]
            if active_ids:
                starter_ids.update(active_ids)
                break

        active_ids = {int(member["id"]) for member in members if bool(member["active"])}
        ranked_ids = {member_id for member_id in rankings if member_id in active_ids}
        reserve_ids = ranked_ids - starter_ids
        unranked_ids = active_ids - ranked_ids

        return {
            "semester": bounds,
            "sessions_considered": sessions_considered,
            "athletes": athletes,
            "layers": layers_metrics,
            "starters_vs_reserves": {
                "definition": (
                    "Titulares = atletas das camadas de linha mais fortes cujo "
                    "acumulado atinge 6 jogadores (a camada que cruza a marca "
                    "entra inteira) + a camada mais forte de goleiros. Quem não "
                    "foi ranqueado fica em grupo próprio."
                ),
                "starters": group_totals(starter_ids),
                "reserves": group_totals(reserve_ids),
                "unranked": group_totals(unranked_ids),
            },
        }

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    @staticmethod
    def _member_names(unit_of_work: Any) -> dict[int, str]:
        return {
            int(member["id"]): str(member["name"])
            for member in unit_of_work.attendance.list_members(include_inactive=True)
        }

    @staticmethod
    def _representative_at(
        roster: Any, scope: str, ordinal: int, subject_member_id: int
    ) -> dict[str, Any]:
        layer = next(
            (
                item
                for item in roster.list_layers(scope)
                if item["ordinal"] == int(ordinal)
            ),
            None,
        )
        if layer is None:
            raise ValueError(_DRIFT_MESSAGE)
        reference = choose_representative(
            layer["members"], subject_member_id=subject_member_id
        )
        if reference is None:
            raise ValueError(_DRIFT_MESSAGE)
        return dict(reference)

    @staticmethod
    def _remove_old_assignment(
        roster: Any, session: dict[str, Any], target_ordinal: int, actor_user_id: int
    ) -> int:
        """No re-rank, tira o atleta da camada antiga antes de resolver o alvo.

        Se a camada antiga esvaziar e sair, os ordinais acima dela descem um
        degrau — o alvo calculado pela busca precisa acompanhar.
        """

        if not session["is_rerank"]:
            return target_ordinal
        removal = roster.remove_assignment_and_compact(
            session["subject_member_id"],
            session["scope"],
            actor_user_id=actor_user_id,
        )
        if removal and removal["layer_deleted"] and removal["ordinal"] < target_ordinal:
            return target_ordinal - 1
        return target_ordinal

    @staticmethod
    def _asked_count(roster: Any, session_id: str, subject_member_id: int) -> int:
        return sum(
            1
            for item in roster.list_comparisons(subject_member_id=subject_member_id)
            if str(item["session_id"]) == str(session_id)
        )

    def _session_payload(
        self, unit_of_work: Any, session: dict[str, Any], names: dict[int, str]
    ) -> dict[str, Any]:
        roster = unit_of_work.roster
        subject_id = session["subject_member_id"]
        reference_id = session["pending_reference_member_id"]
        asked = self._asked_count(roster, session["session_id"], subject_id)
        remaining_layers = roster.layer_count(session["scope"])
        return {
            "status": "ASKING",
            "session_id": session["session_id"],
            "scope": session["scope"],
            "is_rerank": session["is_rerank"],
            "question": {
                "subject": {
                    "member_id": subject_id,
                    "name": names.get(subject_id, f"#{subject_id}"),
                },
                "reference": {
                    "member_id": reference_id,
                    "name": names.get(reference_id, f"#{reference_id}"),
                },
                "text": question_text(
                    names.get(subject_id, f"#{subject_id}"),
                    names.get(reference_id, f"#{reference_id}"),
                ),
            },
            "result": None,
            "progress": {
                "asked": asked,
                "max_questions": max_questions(remaining_layers),
            },
        }

    @staticmethod
    def _completed_payload(
        session_id: str, *, ordinal: int, created_new_layer: bool, asked: int
    ) -> dict[str, Any]:
        return {
            "status": "COMPLETED",
            "session_id": session_id,
            "question": None,
            "result": {
                "layer_ordinal": int(ordinal),
                "layer_label": layer_label(ordinal),
                "created_new_layer": created_new_layer,
            },
            "progress": {"asked": asked, "max_questions": asked},
        }
