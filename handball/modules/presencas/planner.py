from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from handball.core.positions import ATTACK_POSITION_LABELS, DEFENSIVE_POSITION_LABELS

from .domain import CONFIRMED_CODES


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
COURT_POSITIONS = ("PE", "ME", "C", "MD", "PD", "PV")
DEFENSE_SYSTEMS: dict[str, tuple[str, ...]] = {
    "6x0": ("M1", "M1", "M2", "M2", "M3", "M3"),
    "5x1": ("M1", "M1", "M2", "M2", "M3", "AVANCADO"),
}


def _player(record: Mapping[str, Any]) -> dict[str, Any]:
    selected = [str(value) for value in record.get("training_positions") or ()]
    profile = [str(value) for value in record.get("attack_positions") or ()]
    effective = selected or profile
    defensive = [str(value) for value in record.get("defensive_positions") or ()]
    layer_ordinal = record.get("layer_ordinal")
    return {
        "member_id": int(record["member_id"]),
        "name": str(record["name"]),
        "effective_attack_positions": effective,
        "attack_position_source": "SELECTED" if selected else ("PROFILE_DEFAULT" if profile else "INCOMPLETE"),
        "defensive_positions": defensive,
        "defensive_generic": not defensive,
        "layer_ordinal": int(layer_ordinal) if layer_ordinal is not None else None,
        "layer_label": record.get("layer_label"),
        "layer_refine_bonus": dict(record.get("layer_refine_bonus") or {}),
    }


def _expand_roles(roles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for role_index, raw in enumerate(roles):
        count = max(1, min(int(raw.get("count") or 1), 40))
        role = {
            "group": str(raw.get("group") or "NEUTRAL").upper(),
            "label": str(raw.get("label") or f"Papel {role_index + 1}").strip(),
            "attack_positions": [str(value).upper() for value in raw.get("attack_positions") or ()],
            "defensive_positions": [str(value).upper() for value in raw.get("defensive_positions") or ()],
            "allow_generic_defender": bool(raw.get("allow_generic_defender", False)),
        }
        for ordinal in range(count):
            slots.append({**role, "slot_id": f"{role_index}:{ordinal}"})
    return slots


def _eligible(player: Mapping[str, Any], slot: Mapping[str, Any]) -> bool:
    group = str(slot["group"])
    attack_required = set(slot.get("attack_positions") or ())
    defense_required = set(slot.get("defensive_positions") or ())
    attack = set(player.get("effective_attack_positions") or ())
    defense = set(player.get("defensive_positions") or ())
    if group == "GOALKEEPER" and "GOL" not in attack:
        return False
    if group == "ATTACK" and not attack:
        return False
    if group == "DEFENSE":
        if defense_required:
            if not defense.intersection(defense_required):
                return False
        elif not defense and not bool(player.get("defensive_generic")):
            return False
    if attack_required and not attack.intersection(attack_required):
        return False
    if defense_required and not defense.intersection(defense_required):
        return False
    if group == "DEFENSE" and player.get("defensive_generic") and not slot.get("allow_generic_defender"):
        return False
    return True


def _assignment_penalty(assignments: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> int:
    penalty = 0
    for player, slot in assignments:
        if player.get("attack_position_source") != "SELECTED" and slot["group"] in {"ATTACK", "GOALKEEPER"}:
            penalty += 20
        if player.get("defensive_generic") and slot["group"] == "DEFENSE":
            penalty += 10
        penalty += max(0, len(player.get("effective_attack_positions") or ()) - 1)
        penalty += max(0, len(player.get("defensive_positions") or ()) - 1)
    return penalty


def _refine_bonus(player: Mapping[str, Any], slot: Mapping[str, Any]) -> int:
    bonuses = player.get("layer_refine_bonus") or {}
    for position in slot.get("attack_positions") or ():
        if position in bonuses:
            return int(bonuses[position])
    return 0


def enumerate_assignments(
    players: list[dict[str, Any]], roles: Iterable[Mapping[str, Any]], *, limit: int = 3
) -> list[dict[str, Any]]:
    slots = _expand_roles(roles)
    candidates = {
        str(slot["slot_id"]): [player for player in players if _eligible(player, slot)]
        for slot in slots
    }
    ordered = sorted(slots, key=lambda slot: (len(candidates[str(slot["slot_id"])]), str(slot["slot_id"])))
    results: list[tuple[int, tuple[int, ...], list[tuple[dict[str, Any], dict[str, Any]]]]] = []

    def visit(index: int, used: set[int], current: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        if len(results) >= max(limit * 8, 24):
            return
        if index == len(ordered):
            ids = tuple(int(player["member_id"]) for player, _ in current)
            results.append((_assignment_penalty(current), ids, list(current)))
            return
        slot = ordered[index]
        available = sorted(
            candidates[str(slot["slot_id"])],
            key=lambda player: (
                player.get("attack_position_source") != "SELECTED",
                len(player.get("effective_attack_positions") or ()),
                int(player["member_id"]),
            ),
        )
        for player in available:
            member_id = int(player["member_id"])
            if member_id in used:
                continue
            used.add(member_id)
            current.append((player, slot))
            visit(index + 1, used, current)
            current.pop()
            used.remove(member_id)

    visit(0, set(), [])
    unique: set[tuple[tuple[str, int], ...]] = set()
    output: list[dict[str, Any]] = []
    for penalty, _, assignments in sorted(results, key=lambda item: (item[0], item[1])):
        normalized = tuple(sorted((str(slot["slot_id"]), int(player["member_id"])) for player, slot in assignments))
        if normalized in unique:
            continue
        unique.add(normalized)
        output.append(
            {
                "penalty": penalty,
                "assignments": [
                    _assignment_entry(player, slot)
                    for player, slot in sorted(assignments, key=lambda item: str(item[1]["slot_id"]))
                ],
            }
        )
        if len(output) >= limit:
            break
    return output


def _assignment_entry(player: Mapping[str, Any], slot: Mapping[str, Any]) -> dict[str, Any]:
    entry = {
        "member_id": int(player["member_id"]),
        "name": player["name"],
        "group": slot["group"],
        "role": slot["label"],
        "attack_positions": player["effective_attack_positions"],
        "defensive_positions": player["defensive_positions"],
        "position_source": player["attack_position_source"],
    }
    # Campos de camada são aditivos: sem hierarquia registrada, o payload
    # continua idêntico ao histórico.
    if player.get("layer_ordinal") is not None:
        ordinal = int(player["layer_ordinal"])
        entry["layer_ordinal"] = ordinal
        entry["layer_label"] = str(player.get("layer_label") or f"Camada {ordinal + 1}")
        entry["layer_refine_bonus"] = _refine_bonus(player, slot)
    return entry


def _layer_balance(teams: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    """Equilíbrio de camadas entre dois times de um coletivo.

    Peso primário: soma de (ordinal da camada + 1) por time — camada mais forte
    pesa mais; quem não tem camada pesa zero. Desempate: soma dos bônus de
    refino posicional das posições efetivamente ocupadas. A penalidade cresce
    com a diferença entre os times, então 0 é o equilíbrio perfeito.
    """

    weights: dict[str, int] = {}
    refine_totals: dict[str, int] = {}
    breakdown: dict[str, dict[str, Any]] = {}
    ranked_athletes = 0
    for team, assignments in teams.items():
        weight = 0
        refine_total = 0
        by_layer: dict[str, int] = {}
        for item in assignments:
            ordinal = item.get("layer_ordinal")
            if ordinal is None:
                by_layer["sem camada"] = by_layer.get("sem camada", 0) + 1
                continue
            ranked_athletes += 1
            weight += int(ordinal) + 1
            refine_total += int(item.get("layer_refine_bonus", 0))
            label = str(item.get("layer_label") or f"Camada {int(ordinal) + 1}")
            by_layer[label] = by_layer.get(label, 0) + 1
        weights[team] = weight
        refine_totals[team] = refine_total
        breakdown[team] = {
            "weight": weight,
            "refine_bonus": refine_total,
            "by_layer": by_layer,
        }
    ordered_teams = sorted(weights)
    if len(ordered_teams) == 2:
        first, second = ordered_teams
        penalty = abs(weights[first] - weights[second]) * 100 + abs(
            refine_totals[first] - refine_totals[second]
        )
    else:
        penalty = 0
    return {
        "penalty": penalty,
        "teams": breakdown,
        "ranked_athletes": ranked_athletes,
    }


def _maximum_partial(players: list[dict[str, Any]], roles: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    slots = _expand_roles(roles)
    match: dict[int, dict[str, Any]] = {}

    def augment(slot: dict[str, Any], seen: set[int]) -> bool:
        for player in sorted(players, key=lambda item: int(item["member_id"])):
            member_id = int(player["member_id"])
            if member_id in seen or not _eligible(player, slot):
                continue
            seen.add(member_id)
            occupied = match.get(member_id)
            if occupied is None or augment(occupied, seen):
                match[member_id] = slot
                return True
        return False

    for slot in sorted(slots, key=lambda item: str(item["slot_id"])):
        augment(slot, set())
    matched_ids = {str(slot["slot_id"]) for slot in match.values()}
    missing = [slot for slot in slots if str(slot["slot_id"]) not in matched_ids]
    return {
        "filled": len(match),
        "total": len(slots),
        "missing_roles": [slot["label"] for slot in missing],
    }


def _defense_coverage(lineup: list[dict[str, Any]]) -> dict[str, Any]:
    players = [
        {
            "member_id": item["member_id"],
            "name": item["name"],
            "effective_attack_positions": item["attack_positions"],
            "attack_position_source": item["position_source"],
            "defensive_positions": item["defensive_positions"],
            "defensive_generic": not item["defensive_positions"],
        }
        for item in lineup
    ]
    result: dict[str, Any] = {}
    for system, positions in DEFENSE_SYSTEMS.items():
        roles = [
            {"group": "DEFENSE", "label": DEFENSIVE_POSITION_LABELS[position], "count": 1, "defensive_positions": [position]}
            for position in positions
        ]
        assignments = enumerate_assignments(players, roles, limit=1)
        result[system] = {"feasible": bool(assignments), "assignment": assignments[0]["assignments"] if assignments else []}
    return result


def _full_scrimmages(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles = []
    for team in ("A", "B"):
        roles.extend(
            {"group": "ATTACK", "label": f"Time {team} · {ATTACK_POSITION_LABELS[position]}", "count": 1, "attack_positions": [position]}
            for position in COURT_POSITIONS
        )
    lineups = enumerate_assignments(players, roles, limit=12)
    enriched = []
    for lineup in lineups:
        line_member_ids = {int(item["member_id"]) for item in lineup["assignments"]}
        goalkeepers = sorted(
            [
                player for player in players
                if "GOL" in player["effective_attack_positions"] and int(player["member_id"]) not in line_member_ids
            ],
            key=lambda player: int(player["member_id"]),
        )
        teams: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
        for assignment in lineup["assignments"]:
            teams["A" if assignment["role"].startswith("Time A") else "B"].append(assignment)
        defense = {team: _defense_coverage(items) for team, items in teams.items()}
        defense_score = sum(int(data[system]["feasible"]) for data in defense.values() for system in DEFENSE_SYSTEMS)
        enriched.append(
            {
                "teams": teams,
                "goalkeepers": [{"member_id": item["member_id"], "name": item["name"]} for item in goalkeepers[:2]],
                "goalkeeper_status": "TWO" if len(goalkeepers) >= 2 else ("ROTATION" if len(goalkeepers) == 1 else "NONE"),
                "complete": bool(goalkeepers),
                "defense_coverage": defense,
                "penalty": lineup["penalty"],
                "defense_score": defense_score,
                "layer_balance": _layer_balance(teams),
            }
        )
    # Viabilidade posicional continua dominante; o equilíbrio por camada só
    # reordena entre as escalações posicionais já enumeradas.
    return sorted(
        enriched,
        key=lambda item: (
            -item["defense_score"],
            item["penalty"],
            item["layer_balance"]["penalty"],
        ),
    )[:3]


def build_coach_report(
    records: list[dict[str, Any]], exercises: Iterable[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    confirmed = [_player(record) for record in records if record.get("confirmation_status") in CONFIRMED_CODES]
    attack_counts = Counter(position for player in confirmed for position in player["effective_attack_positions"])
    defense_counts = Counter(position for player in confirmed for position in player["defensive_positions"])
    executable: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    critical: dict[int, set[str]] = {}
    for exercise in exercises:
        for variant in exercise.get("variants") or ():
            roles = variant.get("roles") or ()
            assignments = enumerate_assignments(confirmed, roles, limit=3)
            item = {
                "content_id": int(exercise["content_id"]),
                "title": str(exercise["title"]),
                "variant": str(variant.get("label") or "Padrão"),
                "assignments": assignments,
            }
            if assignments:
                executable.append(item)
                for slot in _expand_roles(roles):
                    eligible = [player for player in confirmed if _eligible(player, slot)]
                    if len(eligible) == 1:
                        critical.setdefault(int(eligible[0]["member_id"]), set()).add(str(slot["label"]))
            else:
                partial = _maximum_partial(confirmed, roles)
                near.append({**item, **partial})
    near.sort(key=lambda item: (item["total"] - item["filled"], item["title"], item["variant"]))
    scrimmages = _full_scrimmages(confirmed)
    max_complete_line_teams = 0
    for team_count in range(1, len(confirmed) // len(COURT_POSITIONS) + 1):
        roles = [
            {"group": "ATTACK", "label": f"Time {team + 1} · {ATTACK_POSITION_LABELS[position]}", "count": 1, "attack_positions": [position]}
            for team in range(team_count)
            for position in COURT_POSITIONS
        ]
        partial = _maximum_partial(confirmed, roles)
        if partial["filled"] != partial["total"]:
            break
        max_complete_line_teams = team_count
    two_team_roles = [
        {"group": "ATTACK", "label": f"Time {team} · {ATTACK_POSITION_LABELS[position]}", "count": 1, "attack_positions": [position]}
        for team in ("A", "B") for position in COURT_POSITIONS
    ]
    cancellation_resilient = 0
    if max_complete_line_teams >= 2:
        for removed in confirmed:
            partial = _maximum_partial(
                [player for player in confirmed if player["member_id"] != removed["member_id"]],
                two_team_roles,
            )
            if partial["filled"] == partial["total"]:
                cancellation_resilient += 1
            else:
                critical.setdefault(int(removed["member_id"]), set()).add("manutenção dos dois sextetos")
    for position in COURT_POSITIONS:
        eligible = [player for player in confirmed if position in player["effective_attack_positions"]]
        if len(eligible) == 1:
            critical.setdefault(int(eligible[0]["member_id"]), set()).add(ATTACK_POSITION_LABELS[position])
    used = {
        int(assignment["member_id"])
        for exercise in executable
        for solution in exercise["assignments"][:1]
        for assignment in solution["assignments"]
    }
    if scrimmages:
        used.update(
            int(item["member_id"])
            for assignments in scrimmages[0]["teams"].values()
            for item in assignments
        )
        used.update(int(item["member_id"]) for item in scrimmages[0]["goalkeepers"])
    return {
        "generated_at": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        "confirmed_count": len(confirmed),
        "position_coverage": {
            "attack": {position: attack_counts.get(position, 0) for position in ATTACK_POSITION_LABELS},
            "defense": {position: defense_counts.get(position, 0) for position in DEFENSIVE_POSITION_LABELS},
            "generic_defenders": sum(int(player["defensive_generic"]) for player in confirmed),
        },
        "scrimmages": scrimmages,
        "max_complete_line_teams": max_complete_line_teams,
        "attack_balance": [
            {
                "position": position,
                "available": attack_counts.get(position, 0),
                "demand_for_two_teams": 2,
                "delta": attack_counts.get(position, 0) - 2,
                "substitution_capacity": max(0, attack_counts.get(position, 0) - 1),
            }
            for position in COURT_POSITIONS
        ],
        "robustness": {
            "scrimmage_alternatives": len(scrimmages),
            "executable_variants": len(executable),
            "athletes_whose_cancellation_preserves_two_teams": cancellation_resilient,
        },
        "executable_exercises": executable,
        "near_feasible_exercises": near[:3],
        "critical_athletes": [
            {"member_id": member_id, "name": next(player["name"] for player in confirmed if player["member_id"] == member_id), "roles": sorted(roles)}
            for member_id, roles in sorted(critical.items())
        ],
        "data_gaps": [
            {"member_id": player["member_id"], "name": player["name"], "kind": "ATTACK_POSITIONS"}
            for player in confirmed if not player["effective_attack_positions"]
        ],
        # Só aponta lacuna de camada quando a hierarquia já está em uso entre
        # os confirmados, e só para atletas de linha — o coletivo balanceado
        # divide a linha; goleiro tem hierarquia própria fora deste aviso.
        "ranking_gaps": [
            {"member_id": player["member_id"], "name": player["name"]}
            for player in confirmed
            if player["layer_ordinal"] is None
            and set(player["effective_attack_positions"]) - {"GOL"}
            and any(item["layer_ordinal"] is not None for item in confirmed)
        ],
        "unallocated_athletes": [
            {"member_id": player["member_id"], "name": player["name"]}
            for player in confirmed if int(player["member_id"]) not in used
        ],
    }


def render_coach_report(report: Mapping[str, Any]) -> str:
    lines = ["", "🧩 VIABILIDADE POSICIONAL"]
    attack = report["position_coverage"]["attack"]
    lines.append("• Ataque: " + ", ".join(f"{position} {attack[position]}" for position in ATTACK_POSITION_LABELS))
    defense = report["position_coverage"]["defense"]
    lines.append("• Defesa: " + ", ".join(f"{position} {defense[position]}" for position in DEFENSIVE_POSITION_LABELS))
    lines.append(f"• Marcadores genéricos: {report['position_coverage']['generic_defenders']}")
    lines.append(f"• Máximo de sextetos de linha completos: {report['max_complete_line_teams']}")
    if report["max_complete_line_teams"] >= 2:
        lines.append(f"• Robustez a uma desistência: {report['robustness']['athletes_whose_cancellation_preserves_two_teams']} atleta(s) poderiam sair sem desmontar os dois sextetos.")
    shortages = [item for item in report["attack_balance"] if item["delta"] < 0]
    surpluses = [item for item in report["attack_balance"] if item["delta"] > 0]
    lines.append("• Gargalos para dois times: " + (", ".join(f"{item['position']} ({item['available']}/2)" for item in shortages) or "nenhum"))
    lines.append("• Excedentes posicionais: " + (", ".join(f"{item['position']} (+{item['delta']})" for item in surpluses) or "nenhum"))
    lines.extend(["", "🤾 COMBINAÇÕES DE COLETIVO"])
    if not report["scrimmages"]:
        lines.append("• Não é possível montar dois sextetos posicionais completos.")
    for index, option in enumerate(report["scrimmages"], start=1):
        keeper = {"TWO": "dois goleiros", "ROTATION": "um goleiro em revezamento", "NONE": "sem goleiro; não é coletivo completo"}[option["goalkeeper_status"]]
        lines.append(f"• Opção {index} — {keeper}")
        for team, assignments in option["teams"].items():
            names = ", ".join(f"{item['role'].split(' · ', 1)[1]}: {item['name']}" for item in assignments)
            systems = ", ".join(system for system, data in option["defense_coverage"][team].items() if data["feasible"]) or "sem sistema defensivo estruturado completo"
            lines.append(f"  - Time {team}: {names}. Defesa: {systems}.")
        balance = option.get("layer_balance") or {}
        if balance.get("ranked_athletes"):
            lines.append("  - Equilíbrio por camada: " + _layer_balance_summary(balance))
    lines.extend(["", "🏋️ POSSIBILIDADES DE EXERCÍCIO"])
    if not report["executable_exercises"]:
        lines.append("• Nenhum exercício publicado do Playbook fecha com o elenco confirmado.")
    for exercise in report["executable_exercises"]:
        lines.append(f"• {exercise['title']} — {exercise['variant']}")
        for index, solution in enumerate(exercise["assignments"], start=1):
            names = ", ".join(f"{item['role']}: {item['name']}" for item in solution["assignments"])
            lines.append(f"  - Combinação {index}: {names}")
    if report["near_feasible_exercises"]:
        lines.extend(["", "🟡 EXERCÍCIOS QUASE VIÁVEIS"])
        for item in report["near_feasible_exercises"]:
            lines.append(f"• {item['title']} — {item['variant']}: faltam {', '.join(item['missing_roles'])}.")
    if report["critical_athletes"]:
        lines.extend(["", "🔑 ATLETAS CRÍTICOS"])
        for item in report["critical_athletes"]:
            lines.append(f"• {item['name']}: única opção para {', '.join(item['roles'])}.")
    if report["data_gaps"]:
        lines.extend(["", "⚠️ CADASTROS INCOMPLETOS"])
        lines.append("• Sem posição ofensiva reconhecida: " + ", ".join(item["name"] for item in report["data_gaps"]))
    if report.get("ranking_gaps"):
        lines.extend(["", "🏷️ ATLETAS SEM CAMADA"])
        lines.append("• Ainda fora da hierarquia: " + ", ".join(item["name"] for item in report["ranking_gaps"]))
    if report["unallocated_athletes"]:
        lines.extend(["", "🪑 CONFIRMADOS NÃO ALOCADOS NA PRIMEIRA OPÇÃO"])
        lines.append("• " + ", ".join(item["name"] for item in report["unallocated_athletes"]))
    return "\n".join(lines)


def _layer_balance_summary(balance: Mapping[str, Any]) -> str:
    teams = balance.get("teams") or {}
    team_names = sorted(teams)
    labels: set[str] = set()
    for team in team_names:
        labels.update((teams[team].get("by_layer") or {}).keys())

    def label_order(label: str) -> tuple[int, int]:
        if label.startswith("Camada "):
            try:
                return (0, -int(label.split(" ", 1)[1]))
            except ValueError:
                return (1, 0)
        return (2, 0)

    parts = []
    for label in sorted(labels, key=label_order):
        counts = "×".join(
            str((teams[team].get("by_layer") or {}).get(label, 0)) for team in team_names
        )
        parts.append(f"{label} {counts}")
    return " · ".join(parts) + "."


def confirmed_player_profiles(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Perfis de posição dos registros confirmados, no formato que enumerate_assignments espera.

    Reaproveitado pelo Playbook (filtro "fecha com os confirmados") para não
    duplicar a leitura de posição efetiva que build_coach_report já faz.
    """
    return [_player(record) for record in records if record.get("confirmation_status") in CONFIRMED_CODES]


def exercise_fit(players: list[dict[str, Any]], variants: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Para cada variante de um exercício, diz se fecha com os jogadores informados.

    Mesmo cálculo de enumerate_assignments/_maximum_partial já usado em
    build_coach_report — aqui só reempacotado por variante, sem novo dado.
    """
    results: list[dict[str, Any]] = []
    for variant in variants:
        roles = variant.get("roles") or ()
        label = str(variant.get("label") or "Padrão")
        if enumerate_assignments(players, roles, limit=1):
            results.append({"variant": label, "fits": True, "fits_with": len(players)})
        else:
            partial = _maximum_partial(players, roles)
            results.append({"variant": label, "fits": False, "missing_roles": partial["missing_roles"]})
    return results
