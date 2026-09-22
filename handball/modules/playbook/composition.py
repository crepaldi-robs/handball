"""Preview de composição manual da prancheta tática — lógica pura, sem I/O.

Fatia 1 de docs/planejamento-treinos/: participantes previstos → prancheta
manual → diagnóstico. Não persiste nada, não sugere/busca automaticamente
(isso depende de decisões ainda abertas — ver DECISOES.md) e não trata
ataque/defesa como dimensões independentes (a persistência dessas dimensões é
DB_MIGRATION, fora do escopo desta fatia). Reaproveita a elegibilidade e a
normalização de participante já usadas por presencas/planner.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from handball.core.positions import ATTACK_POSITION_LABELS, DEFENSIVE_POSITION_LABELS
from handball.modules.presencas.planner import (
    build_assignment_entry,
    expand_roles,
    is_eligible,
    normalize_player,
)

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
METHOD_VERSION = "composition-preview-v1"


def build_participants(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza participantes previstos no formato usado pelo motor de composição.

    A origem de cada participante (confirmado, incluído manualmente) já foi
    decidida por quem monta `records`; este módulo só normaliza posição
    efetiva e camada, sem julgar confirmação.
    """

    return [normalize_player(record) for record in records]


def build_slots(blocks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expande blocos (papéis com contagem) em slots individuais estáveis.

    `slot_id` combina o `block_id` explícito do bloco com o slot posicional
    de `planner.expand_roles`, preservando unicidade entre blocos.
    """

    slots: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("block_id") or "bloco")
        for slot in expand_roles(block.get("roles") or ()):
            slots.append({**slot, "block_id": block_id, "slot_id": f"{block_id}:{slot['slot_id']}"})
    return slots


def apply_manual_assignment(
    slots: Sequence[Mapping[str, Any]],
    participants: Sequence[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aplica a ocupação manual da CT aos slots, sem buscar nem sugerir nada.

    Detecta duplicidade simultânea (mesma pessoa em dois slots) e vaga
    incompatível com a posição do slot; nunca substitui silenciosamente um
    ocupante fixado — o conflito fica explícito no resultado.
    """

    participants_by_id = {int(player["member_id"]): player for player in participants}
    occupied_by: dict[int, list[str]] = {}
    resolved_choice: dict[str, dict[str, Any]] = {}
    for raw in assignments:
        slot_id = str(raw["slot_id"])
        member_id = raw.get("member_id")
        if member_id is not None:
            occupied_by.setdefault(int(member_id), []).append(slot_id)
        resolved_choice[slot_id] = {
            "member_id": int(member_id) if member_id is not None else None,
            "occupant_locked": bool(raw.get("occupant_locked", False)),
        }

    output: list[dict[str, Any]] = []
    for slot in slots:
        slot_id = str(slot["slot_id"])
        choice = resolved_choice.get(slot_id, {"member_id": None, "occupant_locked": False})
        member_id = choice["member_id"]
        entry: dict[str, Any] = {
            "slot_id": slot_id,
            "block_id": slot["block_id"],
            "group": slot["group"],
            "role": slot["label"],
            "attack_positions": list(slot.get("attack_positions") or ()),
            "defensive_positions": list(slot.get("defensive_positions") or ()),
            "occupant_locked": choice["occupant_locked"],
            "member_id": member_id,
            "occupant": None,
            "conflicts": [],
            # Elegíveis para a lista de substituição (UX.md: "clique... abre
            # Substituir ocupante, lista elegível e impedimentos").
            "eligible_member_ids": sorted(
                candidate_id for candidate_id, candidate in participants_by_id.items() if is_eligible(candidate, slot)
            ),
        }
        if member_id is not None:
            player = participants_by_id.get(member_id)
            if player is None:
                entry["conflicts"].append("PARTICIPANT_NOT_AVAILABLE")
            else:
                entry["occupant"] = build_assignment_entry(player, slot)
                if not is_eligible(player, slot):
                    entry["conflicts"].append("INELIGIBLE_POSITION")
                if len(occupied_by.get(member_id, [])) > 1:
                    entry["conflicts"].append("DUPLICATE_OCCUPANT")
        output.append(entry)
    return output


def diagnose(
    resolved: Sequence[Mapping[str, Any]],
    participants: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Cobertura, conflitos e vagas — nunca uma nota única de força.

    "Não avaliado" nunca vira zero; cobertura parcial nunca é certificada
    como equilíbrio (essa comparação fica para a fase de sugestão assistida,
    ainda bloqueada por decisão aberta — ver DECISOES.md).
    """

    coverage_attack = {position: 0 for position in ATTACK_POSITION_LABELS}
    coverage_defense = {position: 0 for position in DEFENSIVE_POSITION_LABELS}
    for player in participants:
        for position in player["effective_attack_positions"]:
            if position in coverage_attack:
                coverage_attack[position] += 1
        for position in player["defensive_positions"]:
            if position in coverage_defense:
                coverage_defense[position] += 1

    conflicts = [
        {"slot_id": item["slot_id"], "block_id": item["block_id"], "reasons": item["conflicts"]}
        for item in resolved
        if item["conflicts"]
    ]
    vacant_slots = [
        {"slot_id": item["slot_id"], "block_id": item["block_id"], "role": item["role"]}
        for item in resolved
        if item["member_id"] is None
    ]

    layer_distribution_by_block: dict[str, dict[str, int]] = {}
    for item in resolved:
        occupant = item["occupant"]
        if occupant is None:
            continue
        block_layers = layer_distribution_by_block.setdefault(item["block_id"], {})
        label = occupant.get("layer_label") if "layer_ordinal" in occupant else "sem camada"
        block_layers[label] = block_layers.get(label, 0) + 1

    has_ranked = any(player["layer_ordinal"] is not None for player in participants)
    data_gaps = [
        {"member_id": player["member_id"], "name": player["name"], "kind": "ATTACK_POSITIONS"}
        for player in participants
        if not player["effective_attack_positions"]
    ]
    # Só aponta lacuna de camada quando a hierarquia já está em uso entre os
    # participantes, igual build_coach_report — evitar alarme quando ninguém
    # do treino foi ranqueado ainda.
    ranking_gaps = [
        {"member_id": player["member_id"], "name": player["name"]}
        for player in participants
        if player["layer_ordinal"] is None
        and set(player["effective_attack_positions"]) - {"GOL"}
        and has_ranked
    ]

    return {
        "coverage": {
            "attack": coverage_attack,
            "defense": coverage_defense,
            "known_participants": len(participants),
        },
        "conflicts": conflicts,
        "vacant_slots": vacant_slots,
        "layer_distribution_by_block": layer_distribution_by_block,
        "data_gaps": data_gaps,
        "ranking_gaps": ranking_gaps,
    }


def build_preview(
    *,
    participant_records: Iterable[Mapping[str, Any]],
    blocks: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """Monta o preview completo de composição manual, sem persistir nada."""

    participants = build_participants(participant_records)
    slots = build_slots(blocks)
    resolved = apply_manual_assignment(slots, participants, assignments)
    diagnostics = diagnose(resolved, participants)
    return {
        "schema_version": 1,
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        "mode": mode,
        "participants": [
            {
                "member_id": player["member_id"],
                "name": player["name"],
                "attack_positions": player["effective_attack_positions"],
                "defensive_positions": player["defensive_positions"],
                "layer_label": player.get("layer_label"),
            }
            for player in participants
        ],
        "slots": resolved,
        "diagnostics": diagnostics,
    }
