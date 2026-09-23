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
from handball.modules.presencas.training_day import (
    attack_rank,
    defense_rank,
    goalkeeper_rank,
    min_cost_assignment,
    normalized_strength,
)

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
METHOD_VERSION = "composition-preview-v2"


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
            "origin": str(raw.get("origin") or "MANUAL"),
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
            "origin": choice.get("origin", "MANUAL") if member_id is not None else None,
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


_INELIGIBLE_COST = 1_000_000
_VACANCY_COST = 500_000


def suggest_assignments(
    slots: Sequence[Mapping[str, Any]],
    participants: Sequence[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
    *,
    mode: str,
    block_order: Sequence[str],
) -> list[dict[str, Any]]:
    """Preenche as vagas livres com a sugestão do modo; nunca mexe no que a CT pôs.

    DIRECIONADO (padrão, decisão da CT em 23/09/2026): nos blocos de índice
    par (Time A) pesa a força de ataque, nos de índice ímpar (Time B) a de
    defesa — ataque forte × defesa forte. Vagas de defesa sempre pesam a
    defesa e as de goleiro a hierarquia de goleiros. EQUILIBRADO: preenche por
    posição e depois troca ocupantes da mesma posição entre os pares de times
    enquanto isso aproxima ataque de A e B e defesa de A e B, cada dimensão
    na sua escala. Só entra quem é elegível; sem elegível, a vaga fica
    explícita.
    """

    kept = [dict(item) for item in assignments if item.get("member_id") is not None]
    taken_slots = {str(item["slot_id"]) for item in kept}
    used = {int(item["member_id"]) for item in kept}
    free_slots = [slot for slot in slots if str(slot["slot_id"]) not in taken_slots]
    available = [player for player in participants if int(player["member_id"]) not in used]
    if not free_slots or not available:
        return kept

    ids = [int(player["member_id"]) for player in participants]
    attack = normalized_strength({mid: attack_rank(p) for mid, p in zip(ids, participants)})
    defense = normalized_strength({mid: defense_rank(p) for mid, p in zip(ids, participants)})
    keeper = normalized_strength({mid: goalkeeper_rank(p) for mid, p in zip(ids, participants)})
    block_index = {block_id: index for index, block_id in enumerate(block_order)}

    def strength(player: Mapping[str, Any], slot: Mapping[str, Any]) -> float:
        member_id = int(player["member_id"])
        group = str(slot.get("group") or "NEUTRAL").upper()
        if group == "GOALKEEPER":
            return keeper[member_id]
        if group == "DEFENSE":
            return defense[member_id]
        if mode == "DIRECIONADO" and block_index.get(str(slot.get("block_id")), 0) % 2 == 1:
            return defense[member_id]
        return attack[member_id]

    size = len(available) + len(free_slots)
    cost: list[list[int]] = []
    for player in available:
        row = []
        for slot in free_slots:
            if not is_eligible(player, slot):
                row.append(_INELIGIBLE_COST)
                continue
            # Posição escolhida para o treino antes do perfil; depois força.
            penalty = 0 if player.get("attack_position_source") == "SELECTED" else 20
            weight = 0 if mode == "EQUILIBRADO" else round(strength(player, slot) * 100)
            row.append(penalty - weight)
        row.extend([0] * len(available))
        cost.append(row)
    for _ in free_slots:
        cost.append([_VACANCY_COST] * len(free_slots) + [0] * len(available))
    assert all(len(row) == size for row in cost)
    chosen = min_cost_assignment(cost)

    suggested: list[dict[str, Any]] = []
    for index, player in enumerate(available):
        column = chosen[index]
        if column < len(free_slots) and cost[index][column] < _INELIGIBLE_COST:
            suggested.append(
                {
                    "slot_id": str(free_slots[column]["slot_id"]),
                    "member_id": int(player["member_id"]),
                    "occupant_locked": False,
                    "origin": "SUGGESTED",
                }
            )
    if mode == "EQUILIBRADO":
        suggested = _balance_pairs(suggested, slots, participants, attack, defense, block_order)
    return kept + suggested


def _balance_pairs(
    suggested: list[dict[str, Any]],
    slots: Sequence[Mapping[str, Any]],
    participants: Sequence[Mapping[str, Any]],
    attack: Mapping[int, float],
    defense: Mapping[int, float],
    block_order: Sequence[str],
) -> list[dict[str, Any]]:
    """Troca sugeridos entre Time A e Time B (mesmo papel) enquanto melhora."""

    slot_by_id = {str(slot["slot_id"]): slot for slot in slots}
    by_id = {int(player["member_id"]): player for player in participants}
    pairs = [(block_order[i], block_order[i + 1]) for i in range(0, len(block_order) - 1, 2)]

    def team_of(item: Mapping[str, Any]) -> str:
        return str(slot_by_id[item["slot_id"]]["block_id"])

    def gap(first: str, second: str) -> float:
        totals = {first: [0.0, 0.0], second: [0.0, 0.0]}
        for item in suggested:
            team = team_of(item)
            if team in totals:
                totals[team][0] += attack[item["member_id"]]
                totals[team][1] += defense[item["member_id"]]
        return abs(totals[first][0] - totals[second][0]) + abs(totals[first][1] - totals[second][1])

    for first, second in pairs:
        improved = True
        guard = 0
        while improved and guard < 50:
            improved = False
            guard += 1
            current = gap(first, second)
            for a in [item for item in suggested if team_of(item) == first]:
                for b in [item for item in suggested if team_of(item) == second]:
                    slot_a, slot_b = slot_by_id[a["slot_id"]], slot_by_id[b["slot_id"]]
                    if slot_a["label"].split(" · ")[-1] != slot_b["label"].split(" · ")[-1]:
                        continue
                    if not (is_eligible(by_id[a["member_id"]], slot_b) and is_eligible(by_id[b["member_id"]], slot_a)):
                        continue
                    a["member_id"], b["member_id"] = b["member_id"], a["member_id"]
                    if gap(first, second) + 1e-9 < current:
                        improved = True
                        break
                    a["member_id"], b["member_id"] = b["member_id"], a["member_id"]
                if improved:
                    break
    return suggested


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
    suggest: bool = False,
) -> dict[str, Any]:
    """Monta o preview da prancheta, sem persistir nada.

    Com ``suggest``, as vagas livres chegam preenchidas pela sugestão do modo
    (origem SUGGESTED); o que a CT já pôs ou fixou nunca é trocado.
    """

    blocks = list(blocks)
    participants = build_participants(participant_records)
    slots = build_slots(blocks)
    assignments = list(assignments)
    if suggest:
        assignments = suggest_assignments(
            slots,
            participants,
            assignments,
            mode=mode,
            block_order=[str(block.get("block_id") or "bloco") for block in blocks],
        )
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
