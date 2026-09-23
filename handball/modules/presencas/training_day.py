"""Treino do dia: roteiro, filas por posição e coletivo ataque × defesa.

Lógica pura, sem I/O. Recebe os registros da chamada (já com camadas) e os
itens do plano do Playbook ligado ao evento, e devolve o que a quadra precisa:

- exercício = posições com **filas**; todo confirmado entra em alguma fila e
  o rodízio é no sentido horário. Quem não joga nenhuma posição pedida vai
  para a mais próxima pelo handebol clássico, com desempate pela hierarquia;
- coletivo = times. O padrão é *ataque forte × defesa forte*: Time A com o
  melhor ataque, Time B com a melhor defesa (decisão da CT, 23/09/2026);
- goleiro puro fora de exercício sem gol faz trabalho à parte.

Decisões registradas em docs/planejamento-treinos/CHAMADA-TREINO.md.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from handball.core.positions import ATTACK_POSITION_LABELS, DEFENSIVE_POSITION_LABELS

from .domain import CONFIRMED_CODES
from .planner import normalize_player

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
METHOD_VERSION = "training-day-v1"

COURT_POSITIONS = ("PE", "ME", "C", "MD", "PD", "PV")

# Encaixe clássico: para quem não joga a posição pedida, a ordem de
# preferência (1 = mais próxima). Tabela aprovada pela CT em 23/09/2026.
ATTACK_FALLBACK: dict[str, dict[str, int]] = {
    "PE": {"PD": 1, "ME": 2, "PV": 3},
    "PD": {"PE": 1, "MD": 2, "PV": 3},
    "ME": {"MD": 1, "C": 2, "PE": 3},
    "MD": {"ME": 1, "C": 2, "PD": 3},
    "C": {"ME": 1, "MD": 2, "PV": 3},
    "PV": {"C": 1, "ME": 2, "MD": 2, "PE": 3, "PD": 3},
}
DEFENSE_FALLBACK: dict[str, dict[str, int]] = {
    "M1": {"M2": 1, "M3": 2},
    "M2": {"M1": 1, "M3": 1, "AVANCADO": 2},
    "M3": {"AVANCADO": 1, "M2": 2},
    "AVANCADO": {"M3": 1, "M2": 2},
}
_UNFIT = 9

# Sentido horário visto de cima, com o gol no alto da quadra: da ponta
# direita, passando pelo centro, até a ponta esquerda; pivô fecha o giro.
CLOCKWISE_ORDER = ("PD", "MD", "C", "ME", "PE", "PV")

ROTATION_CLOCKWISE = "CLOCKWISE"

SHORT_LABELS = {
    "GOL": "GOL", "PE": "PE", "ME": "ME", "C": "C", "MD": "MD", "PD": "PD", "PV": "PV",
    "M1": "M1", "M2": "M2", "M3": "M3", "AVANCADO": "AV",
}


# ---------------------------------------------------------------------------
# Participantes
# ---------------------------------------------------------------------------


def confirmed_participants(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        normalize_player(record)
        for record in records
        if record.get("confirmation_status") in CONFIRMED_CODES
    ]


def _is_pure_goalkeeper(player: Mapping[str, Any]) -> bool:
    positions = set(player.get("effective_attack_positions") or ())
    return bool(positions) and positions == {"GOL"}


def _line_positions(player: Mapping[str, Any]) -> list[str]:
    return [value for value in player.get("effective_attack_positions") or () if value != "GOL"]


def _attack_rank(player: Mapping[str, Any]) -> int:
    """Ordinal de ataque (maior = mais forte); -1 quando não avaliado.

    Registros antigos só trazem ``layer_ordinal`` (linha); ele vale como
    ataque para quem não é goleiro puro.
    """

    value = player.get("attack_layer_ordinal")
    if value is None and not _is_pure_goalkeeper(player):
        value = player.get("layer_ordinal")
    return int(value) if value is not None else -1


def _defense_rank(player: Mapping[str, Any]) -> int:
    value = player.get("defense_layer_ordinal")
    return int(value) if value is not None else -1


def _goalkeeper_rank(player: Mapping[str, Any]) -> int:
    value = player.get("goalkeeper_layer_ordinal")
    if value is None and _is_pure_goalkeeper(player):
        value = player.get("layer_ordinal")
    return int(value) if value is not None else -1


def _by_hierarchy(players: Iterable[Mapping[str, Any]], rank=_attack_rank) -> list[Mapping[str, Any]]:
    """Mais forte primeiro; não avaliados depois, sem contar como fracos."""

    return sorted(
        players,
        key=lambda player: (rank(player) < 0, -rank(player), _fold(player["name"]), int(player["member_id"])),
    )


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


attack_rank = _attack_rank
defense_rank = _defense_rank
goalkeeper_rank = _goalkeeper_rank


# ---------------------------------------------------------------------------
# Filas de um exercício
# ---------------------------------------------------------------------------


def _distance(positions: Sequence[str], required: Iterable[str], table: Mapping[str, Mapping[str, int]]) -> tuple[int, int, str | None]:
    """(distância, índice da posição de origem, posição de origem).

    Distância 0 = joga a posição pedida. Entre posições de origem empatadas,
    vale a que a pessoa cadastrou primeiro (ordem de preferência do perfil).
    """

    required = list(required)
    best = (_UNFIT, len(positions), None)
    for index, position in enumerate(positions):
        for target in required:
            if position == target:
                candidate = (0, index, position)
            else:
                step = table.get(position, {}).get(target)
                if step is None:
                    continue
                candidate = (step, index, position)
            if candidate[:2] < best[:2]:
                best = candidate
    return best


def _role_fit(player: Mapping[str, Any], role: Mapping[str, Any]) -> tuple[int, int, str | None]:
    group = str(role.get("group") or "NEUTRAL").upper()
    if group == "DEFENSE":
        required = [str(value).upper() for value in role.get("defensive_positions") or ()]
        own = [str(value).upper() for value in player.get("defensive_positions") or ()]
        if not required:
            return (0, 0, None)
        if not own:
            # Marcador genérico cobre qualquer vaga de defesa, sem ser natural.
            return (2, 0, None)
        return _distance(own, required, DEFENSE_FALLBACK)
    required = [str(value).upper() for value in role.get("attack_positions") or () if str(value).upper() != "GOL"]
    own = _line_positions(player)
    if not required:
        return (0, 0, None) if own else (_UNFIT, 0, None)
    return _distance(own, required, ATTACK_FALLBACK)


def _role_label(role: Mapping[str, Any]) -> str:
    label = str(role.get("label") or "").strip()
    if label:
        return label
    positions = list(role.get("attack_positions") or ()) or list(role.get("defensive_positions") or ())
    return " / ".join(SHORT_LABELS.get(str(value), str(value)) for value in positions) or "Todos"


def _clockwise_key(role: Mapping[str, Any], fallback_index: int) -> tuple[int, int]:
    positions = [str(value).upper() for value in role.get("attack_positions") or ()]
    indexes = [CLOCKWISE_ORDER.index(value) for value in positions if value in CLOCKWISE_ORDER]
    return (min(indexes) if indexes else len(CLOCKWISE_ORDER), fallback_index)


def build_queues(players: Sequence[Mapping[str, Any]], roles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Distribui todos os participantes em filas por papel do exercício."""

    roles = [dict(role) for role in roles]
    goalkeeper_roles = [role for role in roles if str(role.get("group") or "").upper() == "GOALKEEPER"]
    attack_roles = [role for role in roles if str(role.get("group") or "NEUTRAL").upper() in {"ATTACK", "NEUTRAL"}]
    defense_roles = [role for role in roles if str(role.get("group") or "").upper() == "DEFENSE"]
    primary = attack_roles or defense_roles
    defense_by_rotation = bool(attack_roles and defense_roles)

    pure_goalkeepers = [player for player in players if _is_pure_goalkeeper(player)]
    line_players = [player for player in players if not _is_pure_goalkeeper(player)]

    queues: list[dict[str, Any]] = []
    for index, role in enumerate(primary):
        queues.append(
            {
                "role": _role_label(role),
                "group": str(role.get("group") or "NEUTRAL").upper(),
                "positions": list(role.get("attack_positions") or role.get("defensive_positions") or ()),
                "simultaneous": max(1, int(role.get("count") or 1)),
                "members": [],
                "_role": role,
                "_order": _clockwise_key(role, index),
            }
        )

    goalkeeper_queue: dict[str, Any] | None = None
    apart: list[dict[str, Any]] = []
    if goalkeeper_roles:
        goalkeeper_queue = {
            "role": "Goleiros",
            "group": "GOALKEEPER",
            "positions": ["GOL"],
            "simultaneous": sum(max(1, int(role.get("count") or 1)) for role in goalkeeper_roles),
            "members": [],
        }
        keepers = _by_hierarchy(pure_goalkeepers, _goalkeeper_rank)
        if not keepers:
            hybrids = [player for player in line_players if "GOL" in (player.get("effective_attack_positions") or ())]
            keepers = _by_hierarchy(hybrids, _goalkeeper_rank)[:1]
            line_players = [player for player in line_players if player not in keepers]
        goalkeeper_queue["members"] = [_queue_member(player, fitted=False, origin="GOL") for player in keepers]
    else:
        apart = [{"member_id": int(player["member_id"]), "name": str(player["name"])} for player in _by_hierarchy(pure_goalkeepers, _goalkeeper_rank)]

    if queues:
        # Hierarquia decide a ordem de escolha: o mais forte fica com a fila
        # mais próxima quando duas empatam.
        for player in _by_hierarchy(line_players):
            ranked = sorted(
                range(len(queues)),
                key=lambda qi: (
                    _role_fit(player, queues[qi]["_role"])[:2],
                    len(queues[qi]["members"]),
                    qi,
                ),
            )
            chosen = queues[ranked[0]]
            distance, _, origin = _role_fit(player, chosen["_role"])
            chosen["members"].append(_queue_member(player, fitted=distance > 0, origin=origin, unfit=distance >= _UNFIT))
        for queue in queues:
            # Estável: dentro de cada grupo segue a ordem da hierarquia.
            queue["members"].sort(key=lambda item: (item["fitted"], item["without_position"]))
    else:
        apart.extend({"member_id": int(player["member_id"]), "name": str(player["name"])} for player in _by_hierarchy(line_players))

    queues.sort(key=lambda queue: queue["_order"])
    for queue in queues:
        queue.pop("_role", None)
        queue.pop("_order", None)

    rotation_labels = [queue["role"] for queue in queues]
    if defense_by_rotation:
        rotation_labels.append("Defesa")
    return {
        "queues": queues,
        "goalkeepers": goalkeeper_queue,
        "defense_rotation": (
            {
                "roles": [_role_label(role) for role in defense_roles],
                "simultaneous": sum(max(1, int(role.get("count") or 1)) for role in defense_roles),
            }
            if defense_by_rotation
            else None
        ),
        "apart": apart,
        "rotation": ROTATION_CLOCKWISE,
        "rotation_order": rotation_labels,
        "alerts": _queue_alerts(queues),
    }


def _queue_member(player: Mapping[str, Any], *, fitted: bool, origin: str | None, unfit: bool = False) -> dict[str, Any]:
    return {
        "member_id": int(player["member_id"]),
        "name": str(player["name"]),
        "fitted": bool(fitted),
        "from_position": origin,
        "without_position": bool(unfit),
    }


def _queue_alerts(queues: Sequence[Mapping[str, Any]]) -> list[str]:
    alerts: list[str] = []
    for queue in queues:
        naturals = [item for item in queue["members"] if not item["fitted"]]
        if not queue["members"]:
            alerts.append(f"Ninguém para {queue['role']}.")
        elif len(queue["members"]) == 1:
            alerts.append(f"Só {queue['members'][0]['name']} em {queue['role']}: sem rodízio nessa fila.")
        elif not naturals:
            alerts.append(f"{queue['role']} só com gente fora da posição.")
    return alerts


# ---------------------------------------------------------------------------
# Papéis de cada item do plano
# ---------------------------------------------------------------------------


def roles_from_diagram(diagram: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Posições dos atores de uma jogada viram os papéis do exercício."""

    attack: dict[str, int] = {}
    defense: dict[str, int] = {}
    goalkeepers = 0
    for actor in diagram.get("actors") or ():
        position = str(actor.get("position") or "").upper()
        side = str(actor.get("side") or "").upper()
        if position == "GOL":
            if side == "DEFENSE":
                goalkeepers += 1
            continue
        if side == "ATTACK" and position in ATTACK_POSITION_LABELS:
            attack[position] = attack.get(position, 0) + 1
        elif side == "DEFENSE" and position in DEFENSIVE_POSITION_LABELS:
            defense[position] = defense.get(position, 0) + 1
    roles: list[dict[str, Any]] = [
        {"group": "ATTACK", "label": ATTACK_POSITION_LABELS[position], "count": count, "attack_positions": [position]}
        for position, count in sorted(attack.items(), key=lambda item: COURT_POSITIONS.index(item[0]))
    ]
    roles.extend(
        {
            "group": "DEFENSE",
            "label": DEFENSIVE_POSITION_LABELS[position],
            "count": count,
            "defensive_positions": [position],
            "allow_generic_defender": True,
        }
        for position, count in sorted(defense.items(), key=lambda item: list(DEFENSIVE_POSITION_LABELS).index(item[0]))
    )
    if goalkeepers:
        roles.append({"group": "GOALKEEPER", "label": "Goleiro", "count": goalkeepers, "attack_positions": ["GOL"]})
    return roles


def _is_collective(item: Mapping[str, Any]) -> bool:
    kind = str(item.get("content_kind") or "").upper()
    return kind == "COLLECTIVE" or _fold(item.get("title")).startswith("coletivo")


def _item_roles(item: Mapping[str, Any], players: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    diagram = item.get("diagram")
    if isinstance(diagram, Mapping) and diagram.get("actors"):
        return roles_from_diagram(diagram), None
    variants = [variant for variant in item.get("variants") or () if variant.get("roles")]
    if not variants:
        return [], None
    # A primeira variante em que toda fila tem gente é a usada; sem nenhuma
    # assim, a primeira cadastrada — o rodízio resolve o resto em quadra.
    for variant in variants:
        roles = list(variant.get("roles") or ())
        attack_like = [role for role in roles if str(role.get("group") or "NEUTRAL").upper() in {"ATTACK", "NEUTRAL"}]
        if all(any(_role_fit(player, role)[0] == 0 for player in players if not _is_pure_goalkeeper(player)) for role in attack_like):
            return roles, str(variant.get("label") or "Padrão")
    return list(variants[0].get("roles") or ()), str(variants[0].get("label") or "Padrão")


# ---------------------------------------------------------------------------
# Coletivo: ataque forte × defesa forte
# ---------------------------------------------------------------------------


def normalized_strength(values: Mapping[int, int]) -> dict[int, float]:
    known = [value for value in values.values() if value >= 0]
    if not known:
        return {key: 0.0 for key in values}
    low, high = min(known), max(known)
    span = high - low
    return {
        key: (0.0 if value < 0 else (1.0 if span == 0 else (value - low) / span))
        for key, value in values.items()
    }


def min_cost_assignment(cost: list[list[int]]) -> list[int]:
    """Atribuição de custo mínimo (matriz quadrada). Devolve coluna por linha."""

    size = len(cost)
    infinity = float("inf")
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for row in range(1, size + 1):
        p[0] = row
        column0 = 0
        minv = [infinity] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column0] = True
            row0 = p[column0]
            delta = infinity
            column1 = 0
            for column in range(1, size + 1):
                if used[column]:
                    continue
                current = cost[row0 - 1][column - 1] - u[row0] - v[column]
                if current < minv[column]:
                    minv[column] = current
                    way[column] = column0
                if minv[column] < delta:
                    delta = minv[column]
                    column1 = column
            for column in range(size + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minv[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assignment = [0] * size
    for column in range(1, size + 1):
        if p[column]:
            assignment[p[column] - 1] = column - 1
    return assignment


_BENCH_COST = 100_000
_VACANCY_COST = 200_000


def build_directed_scrimmage(players: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Time A com o melhor ataque, Time B com a melhor defesa.

    Posição domina: primeiro natural, depois encaixe clássico. Dentro do que
    a posição permite, maximiza força de ataque no A e de defesa no B, cada
    uma na própria escala (normalizada entre os confirmados), sem somar
    ataque com defesa. Não avaliado conta como zero e é sinalizado.
    """

    line = [player for player in players if not _is_pure_goalkeeper(player)]
    keepers = [player for player in players if _is_pure_goalkeeper(player)]
    if len(line) < 2:
        return None
    attack = normalized_strength({int(player["member_id"]): _attack_rank(player) for player in line})
    defense = normalized_strength({int(player["member_id"]): _defense_rank(player) for player in line})
    slots = [(team, position) for team in ("A", "B") for position in COURT_POSITIONS]
    athletes = list(line)
    size = len(athletes) + len(slots)
    cost: list[list[int]] = []
    for player in athletes:
        own = _line_positions(player)
        member_id = int(player["member_id"])
        row: list[int] = []
        for team, position in slots:
            distance = _distance(own, [position], ATTACK_FALLBACK)[0] if own else _UNFIT
            strength = attack[member_id] if team == "A" else defense[member_id]
            row.append(distance * 1_000 - round(strength * 100))
        row.extend([_BENCH_COST] * len(athletes))
        cost.append(row)
    for _ in slots:
        cost.append([_VACANCY_COST] * len(slots) + [0] * len(athletes))
    assert all(len(row) == size for row in cost)
    assignment = min_cost_assignment(cost)

    teams: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    bench_ids: list[int] = []
    for index, player in enumerate(athletes):
        column = assignment[index]
        if column < len(slots):
            team, position = slots[column]
            distance, _, origin = _distance(_line_positions(player), [position], ATTACK_FALLBACK)
            teams[team].append(
                {
                    "position": position,
                    "member_id": int(player["member_id"]),
                    "name": str(player["name"]),
                    "fitted": distance > 0,
                    "from_position": origin,
                    "attack_ranked": _attack_rank(player) >= 0,
                    "defense_ranked": _defense_rank(player) >= 0,
                }
            )
        else:
            bench_ids.append(int(player["member_id"]))
    for team in teams:
        filled = {item["position"] for item in teams[team]}
        teams[team].extend({"position": position, "member_id": None, "name": None, "fitted": False, "from_position": None} for position in COURT_POSITIONS if position not in filled)
        teams[team].sort(key=lambda item: COURT_POSITIONS.index(item["position"]))

    by_id = {int(player["member_id"]): player for player in athletes}
    bench: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    ordered_bench = sorted(bench_ids, key=lambda mid: (-(attack[mid] - defense[mid]), _fold(by_id[mid]["name"])))
    for member_id in ordered_bench:
        prefers = "A" if attack[member_id] >= defense[member_id] else "B"
        other = "B" if prefers == "A" else "A"
        target = prefers if len(bench[prefers]) <= len(bench[other]) else other
        bench[target].append({"member_id": member_id, "name": str(by_id[member_id]["name"])})

    ranked_keepers = _by_hierarchy(keepers, _goalkeeper_rank)
    goalkeepers: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    if len(ranked_keepers) == 1:
        only = {"member_id": int(ranked_keepers[0]["member_id"]), "name": str(ranked_keepers[0]["name"])}
        goalkeepers = {"A": [only], "B": [only]}
        goalkeeper_status = "ROTATION"
    else:
        # A melhor goleira reforça a defesa forte (Time B).
        for index, keeper in enumerate(ranked_keepers):
            goalkeepers["B" if index % 2 == 0 else "A"].append({"member_id": int(keeper["member_id"]), "name": str(keeper["name"])})
        goalkeeper_status = "TWO" if len(ranked_keepers) >= 2 else "NONE"

    unranked = sorted(
        {str(player["name"]) for player in line if _attack_rank(player) < 0 or _defense_rank(player) < 0},
        key=_fold,
    )
    vacancies = sum(1 for team in teams.values() for item in team if item["member_id"] is None)
    return {
        "mode": "DIRECIONADO",
        "label": "Ataque forte × Defesa forte",
        "teams": teams,
        "team_roles": {"A": "Ataque forte", "B": "Defesa forte"},
        "bench": bench,
        "goalkeepers": goalkeepers,
        "goalkeeper_status": goalkeeper_status,
        "vacancies": vacancies,
        "fitted": [
            {"team": team, **item}
            for team, items in teams.items()
            for item in items
            if item["member_id"] is not None and item["fitted"]
        ],
        "unranked": unranked,
    }


# ---------------------------------------------------------------------------
# Treino do dia
# ---------------------------------------------------------------------------


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def build_training_day(
    records: Iterable[Mapping[str, Any]],
    plan_items: Iterable[Mapping[str, Any]] = (),
    *,
    event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    records = list(records)
    players = confirmed_participants(records)
    items = list(plan_items)
    start = _parse_datetime((event or {}).get("starts_at"))
    clock = start
    blocks: list[dict[str, Any]] = []
    scrimmage = build_directed_scrimmage(players)
    for index, item in enumerate(items):
        minutes = item.get("planned_minutes")
        starts_at = clock
        ends_at = clock + timedelta(minutes=int(minutes)) if (clock is not None and minutes) else None
        clock = ends_at
        kind = str(item.get("content_kind") or "CONTENT").upper()
        block: dict[str, Any] = {
            "block_id": f"item-{index + 1}",
            "content_id": int(item["content_id"]) if item.get("content_id") is not None else None,
            "title": str(item.get("title") or "Bloco"),
            "kind": "COLLECTIVE" if _is_collective(item) else ("PLAY" if kind in {"PLAY", "JOGADA"} else ("EXERCISE" if kind == "EXERCISE" else "FREE")),
            "minutes": int(minutes) if minutes else None,
            "starts_at": starts_at.isoformat(timespec="minutes") if starts_at else None,
            "ends_at": ends_at.isoformat(timespec="minutes") if ends_at else None,
            "notes": str(item.get("notes") or ""),
            "variant": None,
            "has_diagram": isinstance(item.get("diagram"), Mapping) and bool(item["diagram"].get("actors")),
        }
        if block["kind"] == "COLLECTIVE":
            block["scrimmage"] = scrimmage
        else:
            roles, variant = _item_roles(item, players)
            block["variant"] = variant
            block["layout"] = build_queues(players, roles) if roles else None
        blocks.append(block)

    has_collective = any(block["kind"] == "COLLECTIVE" for block in blocks)
    by_position: dict[str, list[str]] = {}
    for player in players:
        own = list(player.get("effective_attack_positions") or ())
        key = own[0] if own else "?"
        by_position.setdefault(key, []).append(str(player["name"]))
    alerts: list[str] = []
    for block in blocks:
        for alert in ((block.get("layout") or {}).get("alerts") or ()):
            alerts.append(f"{block['title']}: {alert}")
    return {
        "method_version": METHOD_VERSION,
        "generated_at": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        "event": {
            "id": (event or {}).get("id"),
            "title": (event or {}).get("title"),
            "starts_at": start.isoformat(timespec="minutes") if start else None,
            "location": (event or {}).get("location"),
        },
        "confirmed_count": len(players),
        "has_plan": bool(items),
        "blocks": blocks,
        "scrimmage": scrimmage,
        "show_scrimmage": has_collective or not items,
        "confirmed_by_position": {
            key: sorted(names, key=_fold)
            for key, names in sorted(
                by_position.items(),
                key=lambda entry: (["GOL", *COURT_POSITIONS, "?"].index(entry[0]) if entry[0] in ["GOL", *COURT_POSITIONS, "?"] else 99),
            )
        },
        "alerts": alerts,
    }


def public_training_day(day: Mapping[str, Any]) -> dict[str, Any]:
    """Versão para atletas: mesmo planejamento, sem camadas nem avisos da CT."""

    def strip_scrimmage(scrimmage: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not scrimmage:
            return None
        return {
            "label": scrimmage["label"],
            "team_roles": scrimmage["team_roles"],
            "teams": {
                team: [{"position": item["position"], "name": item["name"]} for item in items]
                for team, items in scrimmage["teams"].items()
            },
            "bench": {team: [item["name"] for item in items] for team, items in scrimmage["bench"].items()},
            "goalkeepers": {team: [item["name"] for item in items] for team, items in scrimmage["goalkeepers"].items()},
        }

    blocks = []
    for block in day.get("blocks") or ():
        layout = block.get("layout")
        public_block = {
            key: block.get(key)
            for key in ("block_id", "content_id", "title", "kind", "minutes", "starts_at", "ends_at", "variant", "has_diagram")
        }
        if layout:
            public_block["layout"] = {
                "queues": [
                    {"role": queue["role"], "positions": queue["positions"], "members": [item["name"] for item in queue["members"]]}
                    for queue in layout["queues"]
                ],
                "goalkeepers": [item["name"] for item in (layout.get("goalkeepers") or {}).get("members", [])],
                "defense_rotation": layout.get("defense_rotation"),
                "apart": [item["name"] for item in layout.get("apart") or ()],
                "rotation_order": layout.get("rotation_order") or [],
            }
        if block.get("kind") == "COLLECTIVE":
            public_block["scrimmage"] = strip_scrimmage(block.get("scrimmage"))
        blocks.append(public_block)
    return {
        "event": day.get("event"),
        "confirmed_count": day.get("confirmed_count"),
        "blocks": blocks,
        "scrimmage": strip_scrimmage(day.get("scrimmage")) if day.get("show_scrimmage") else None,
    }


# ---------------------------------------------------------------------------
# Mensagem do grupo
# ---------------------------------------------------------------------------

_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _clock(value: str | None) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.strftime("%H:%M") if parsed else None


def _queue_text(queue: Mapping[str, Any]) -> str:
    names = ", ".join(
        f"{item['name']}{' (' + SHORT_LABELS.get(str(item['from_position']), str(item['from_position'])) + ')' if item['fitted'] and item['from_position'] else ''}"
        for item in queue["members"]
    )
    return f"{queue['role']}: {names or '—'}"


def _scrimmage_lines(scrimmage: Mapping[str, Any]) -> list[str]:
    lines = [f"   {scrimmage['label']}"]
    for team in ("A", "B"):
        players = " · ".join(
            f"{item['position']} {item['name'] or 'vaga'}"
            + (f" ({SHORT_LABELS.get(str(item['from_position']), item['from_position'])})" if item.get("fitted") and item.get("from_position") else "")
            for item in scrimmage["teams"][team]
        )
        keepers = ", ".join(item["name"] for item in scrimmage["goalkeepers"][team])
        line = f"   Time {team} ({scrimmage['team_roles'][team].lower()}): {players}"
        if keepers:
            line += f" · GOL {keepers}"
        lines.append(line)
        if scrimmage["bench"][team]:
            lines.append(f"     Banco {team}: " + ", ".join(item["name"] for item in scrimmage["bench"][team]))
    if scrimmage.get("goalkeeper_status") == "ROTATION":
        lines.append("   Goleiro único reveza entre os times.")
    return lines


def render_training_message(
    day: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]] = (),
    *,
    training_date: Any = None,
) -> str:
    start = _parse_datetime((day.get("event") or {}).get("starts_at"))
    if start is not None:
        heading = f"🤾 TREINO — {_WEEKDAYS[start.weekday()]} {start.strftime('%d/%m')} · {start.strftime('%Hh%M')}"
    elif training_date is not None:
        heading = f"🤾 TREINO — {training_date.strftime('%d/%m') if hasattr(training_date, 'strftime') else training_date}"
    else:
        heading = "🤾 TREINO"
    location = (day.get("event") or {}).get("location")
    if location:
        heading += f" · {location}"
    lines = [heading]
    pending = sorted(
        (str(record["name"]) for record in records if record.get("confirmation_status") in {"PENDING", "NO_RESPONSE"}),
        key=_fold,
    )
    summary = f"✅ {day.get('confirmed_count', 0)} confirmados"
    if pending:
        summary += f" · ⏳ sem resposta: {', '.join(pending)}"
    lines.append(summary)

    if not day.get("blocks"):
        lines.extend(["", "👥 QUEM VEM"])
        for position, names in (day.get("confirmed_by_position") or {}).items():
            label = "Sem posição" if position == "?" else position
            lines.append(f"• {label}: {', '.join(names)}")

    for number, block in enumerate(day.get("blocks") or (), start=1):
        lines.append("")
        start_text, end_text = _clock(block.get("starts_at")), _clock(block.get("ends_at"))
        timing = f"{start_text}–{end_text} · " if start_text and end_text else (f"{block['minutes']} min · " if block.get("minutes") else "")
        suffix = " (jogada)" if block.get("kind") == "PLAY" else ""
        lines.append(f"{number}) {timing}{block['title']}{suffix}")
        if block.get("kind") == "COLLECTIVE":
            if block.get("scrimmage"):
                lines.extend(_scrimmage_lines(block["scrimmage"]))
            else:
                lines.append("   Coletivo: gente insuficiente para dois times.")
            continue
        layout = block.get("layout")
        if not layout:
            lines.append("   Todos juntos.")
            continue
        if layout["queues"]:
            lines.append("   Rodízio horário: " + " → ".join(layout["rotation_order"]))
        for queue in layout["queues"]:
            lines.append("   " + _queue_text(queue))
        if layout.get("defense_rotation"):
            lines.append(f"   Defesa ({', '.join(layout['defense_rotation']['roles'])}): quem sai do ataque")
        if layout.get("goalkeepers") and layout["goalkeepers"]["members"]:
            lines.append("   Goleiros: " + ", ".join(item["name"] for item in layout["goalkeepers"]["members"]))
        if layout.get("apart"):
            lines.append("   Trabalho à parte: " + ", ".join(item["name"] for item in layout["apart"]))

    if day.get("show_scrimmage") and not any(block.get("kind") == "COLLECTIVE" for block in day.get("blocks") or ()):
        lines.extend(["", "🤾 COLETIVO (sugestão)"])
        if day.get("scrimmage"):
            lines.extend(_scrimmage_lines(day["scrimmage"]))
        else:
            lines.append("   Gente insuficiente para dois times.")

    alerts = list(day.get("alerts") or ())[:2]
    if alerts:
        lines.append("")
        lines.extend(f"⚠️ {alert}" for alert in alerts)
    return "\n".join(lines)
