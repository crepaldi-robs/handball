from __future__ import annotations

from handball.modules.presencas.training_day import (
    build_directed_scrimmage,
    build_queues,
    build_training_day,
    confirmed_participants,
    public_training_day,
    render_training_message,
    roles_from_diagram,
)


def record(
    member_id: int,
    name: str,
    attack: list[str],
    *,
    defense: list[str] | None = None,
    attack_layer: int | None = None,
    defense_layer: int | None = None,
    goalkeeper_layer: int | None = None,
    status: str = "CONFIRMED_EARLY",
) -> dict[str, object]:
    item: dict[str, object] = {
        "member_id": member_id,
        "name": name,
        "attack_positions": attack,
        "defensive_positions": defense or [],
        "training_positions": [],
        "confirmation_status": status,
    }
    if attack_layer is not None:
        item["attack_layer_ordinal"] = attack_layer
        item["layer_ordinal"] = attack_layer
    if defense_layer is not None:
        item["defense_layer_ordinal"] = defense_layer
    if goalkeeper_layer is not None:
        item["goalkeeper_layer_ordinal"] = goalkeeper_layer
        item["layer_ordinal"] = goalkeeper_layer
    return item


def role(label: str, positions: list[str], *, group: str = "ATTACK", count: int = 1) -> dict[str, object]:
    if group == "DEFENSE":
        return {"group": group, "label": label, "count": count, "defensive_positions": positions}
    return {"group": group, "label": label, "count": count, "attack_positions": positions}


def queue_names(layout: dict, label: str) -> list[str]:
    queue = next(item for item in layout["queues"] if item["role"] == label)
    return [member["name"] for member in queue["members"]]


def test_everyone_enters_a_queue_and_out_of_position_uses_classic_fit() -> None:
    players = confirmed_participants(
        [
            record(1, "Carla", ["C"]),
            record(2, "Mel", ["ME"]),
            record(3, "Pati", ["PE"]),
            record(4, "Rita", ["PD"]),
            record(5, "Vivi", ["PV"]),
        ]
    )
    layout = build_queues(players, [role("Central", ["C"]), role("Meia direita", ["MD"])])

    assigned = [member["name"] for queue in layout["queues"] for member in queue["members"]]
    assert sorted(assigned) == ["Carla", "Mel", "Pati", "Rita", "Vivi"]
    # ME → MD é a 1ª opção; PD → MD a 2ª; PV → C a 1ª; PE não tem C nem MD
    # na tabela e cai na fila mais curta, sinalizado como sem posição.
    assert queue_names(layout, "Meia direita")[:2] == ["Mel", "Rita"]
    # Natural vem antes de quem foi encaixado.
    assert queue_names(layout, "Central")[:2] == ["Carla", "Vivi"]
    fitted = {member["name"]: member for queue in layout["queues"] for member in queue["members"]}
    assert fitted["Mel"]["fitted"] is True and fitted["Mel"]["from_position"] == "ME"
    assert fitted["Pati"]["without_position"] is True


def test_hierarchy_breaks_ties_between_equally_close_queues() -> None:
    # Pivô vai para ME ou MD com a mesma distância: o mais forte escolhe
    # primeiro e o empate seguinte vai para a fila mais curta.
    players = confirmed_participants(
        [
            record(1, "Forte", ["PV"], attack_layer=3),
            record(2, "Fraca", ["PV"], attack_layer=0),
        ]
    )
    layout = build_queues(players, [role("Meia esquerda", ["ME"]), role("Meia direita", ["MD"])])

    assert queue_names(layout, "Meia esquerda") == ["Forte"]
    assert queue_names(layout, "Meia direita") == ["Fraca"]


def test_goalkeeper_works_apart_when_exercise_has_no_goal() -> None:
    players = confirmed_participants([record(1, "Lara", ["GOL"]), record(2, "Carla", ["C"])])

    without_goal = build_queues(players, [role("Central", ["C"])])
    with_goal = build_queues(players, [role("Central", ["C"]), role("Goleiro", ["GOL"], group="GOALKEEPER")])

    assert [item["name"] for item in without_goal["apart"]] == ["Lara"]
    assert without_goal["goalkeepers"] is None
    assert [item["name"] for item in with_goal["goalkeepers"]["members"]] == ["Lara"]
    assert with_goal["apart"] == []


def test_defense_roles_are_filled_by_rotation_when_exercise_also_has_attack() -> None:
    players = confirmed_participants([record(1, "Carla", ["C"], defense=["M2"]), record(2, "Mel", ["MD"])])

    layout = build_queues(players, [role("Central", ["C"]), role("Meia direita", ["MD"]), role("Defensores", [], group="DEFENSE", count=2)])

    assert layout["defense_rotation"] == {"roles": ["Defensores"], "simultaneous": 2}
    assert layout["rotation"] == "CLOCKWISE"
    assert layout["rotation_order"] == ["Meia direita", "Central", "Defesa"]


def test_defense_only_exercise_uses_defensive_positions() -> None:
    players = confirmed_participants(
        [record(1, "Duda", ["C"], defense=["M3"]), record(2, "Eva", ["PE"], defense=["AVANCADO"])]
    )
    layout = build_queues(players, [role("3º marcador", ["M3"], group="DEFENSE"), role("Avançado", ["AVANCADO"], group="DEFENSE")])

    assert queue_names(layout, "3º marcador") == ["Duda"]
    assert queue_names(layout, "Avançado") == ["Eva"]


def _two_teams_roster() -> list[dict[str, object]]:
    records = []
    member_id = 1
    for position in ("PE", "ME", "C", "MD", "PD", "PV"):
        # Em cada posição: um atacante forte (defesa fraca) e um defensor
        # forte (ataque fraco).
        records.append(record(member_id, f"Atq-{position}", [position], attack_layer=3, defense_layer=0))
        records.append(record(member_id + 1, f"Def-{position}", [position], attack_layer=0, defense_layer=3))
        member_id += 2
    records.append(record(90, "Lara", ["GOL"], goalkeeper_layer=2))
    records.append(record(91, "Mari", ["GOL"], goalkeeper_layer=0))
    return records


def test_directed_scrimmage_puts_best_attack_in_a_and_best_defense_in_b() -> None:
    scrimmage = build_directed_scrimmage(confirmed_participants(_two_teams_roster()))

    assert scrimmage is not None
    assert {item["name"] for item in scrimmage["teams"]["A"]} == {f"Atq-{p}" for p in ("PE", "ME", "C", "MD", "PD", "PV")}
    assert {item["name"] for item in scrimmage["teams"]["B"]} == {f"Def-{p}" for p in ("PE", "ME", "C", "MD", "PD", "PV")}
    assert [item["name"] for item in scrimmage["goalkeepers"]["B"]] == ["Lara"]
    assert scrimmage["vacancies"] == 0
    assert scrimmage["fitted"] == []
    assert scrimmage["unranked"] == []


def test_directed_scrimmage_prefers_position_over_strength_and_flags_unranked() -> None:
    records = _two_teams_roster()
    records.append(record(50, "Nova", ["PE"]))
    scrimmage = build_directed_scrimmage(confirmed_participants(records))

    placed = [item["name"] for team in scrimmage["teams"].values() for item in team]
    assert len(placed) == len(set(placed)) == 12
    bench = [item["name"] for team in scrimmage["bench"].values() for item in team]
    assert bench == ["Nova"]
    assert scrimmage["unranked"] == ["Nova"]


def test_short_roster_leaves_explicit_vacancies() -> None:
    scrimmage = build_directed_scrimmage(confirmed_participants([record(1, "A", ["C"]), record(2, "B", ["PV"]), record(3, "C", ["ME"])]))

    assert scrimmage["vacancies"] == 9
    assert all(item["member_id"] is None or item["name"] for team in scrimmage["teams"].values() for item in team)


def test_training_day_follows_plan_order_times_and_collective() -> None:
    records = _two_teams_roster() + [record(99, "Zé", ["C"], status="PENDING")]
    items = [
        {"content_id": 1, "title": "Aquecimento", "content_kind": "CONTENT", "planned_minutes": 15},
        {
            "content_id": 2,
            "title": "Cruzamento",
            "content_kind": "EXERCISE",
            "planned_minutes": 20,
            "variants": [{"label": "Base", "roles": [role("Central", ["C"]), role("Meia direita", ["MD"])]}],
        },
        {"content_id": 3, "title": "Coletivo final", "content_kind": "CONTENT", "planned_minutes": 30},
    ]
    day = build_training_day(records, items, event={"id": 7, "starts_at": "2026-09-24T19:00:00-03:00", "location": "Ginásio"})

    assert [block["kind"] for block in day["blocks"]] == ["FREE", "EXERCISE", "COLLECTIVE"]
    assert [block["starts_at"][11:16] for block in day["blocks"]] == ["19:00", "19:15", "19:35"]
    assert day["blocks"][1]["variant"] == "Base"
    assert day["blocks"][2]["scrimmage"]["team_roles"] == {"A": "Ataque forte", "B": "Defesa forte"}

    message = render_training_message(day, records)
    assert message.startswith("🤾 TREINO — qui 24/09 · 19h00 · Ginásio")
    assert "⏳ sem resposta: Zé" in message
    assert "2) 19:15–19:35 · Cruzamento" in message
    assert "Rodízio horário: Meia direita → Central" in message
    assert "Trabalho à parte: Lara, Mari" in message
    assert "Time A (ataque forte)" in message
    # Nada da auditoria do algoritmo vai para o grupo.
    for noise in ("VIABILIDADE", "Robustez", "Camada", "COMBINAÇÕES", "Excedentes"):
        assert noise not in message


def test_without_plan_message_lists_who_comes_and_suggests_collective() -> None:
    records = _two_teams_roster()
    day = build_training_day(records, [], event=None)
    message = render_training_message(day, records)

    assert "👥 QUEM VEM" in message
    assert "• GOL: Lara, Mari" in message
    assert "🤾 COLETIVO (sugestão)" in message


def test_play_diagram_actors_become_queues() -> None:
    diagram = {
        "actors": [
            {"id": "a1", "side": "ATTACK", "position": "C"},
            {"id": "a2", "side": "ATTACK", "position": "MD"},
            {"id": "d1", "side": "DEFENSE", "position": "M2"},
            {"id": "g", "side": "DEFENSE", "position": "GOL"},
        ]
    }
    roles = roles_from_diagram(diagram)
    assert [(item["group"], item["label"]) for item in roles] == [
        ("ATTACK", "Central"),
        ("ATTACK", "Meia direita"),
        ("DEFENSE", "2º marcador"),
        ("GOALKEEPER", "Goleiro"),
    ]
    day = build_training_day(
        _two_teams_roster(),
        [{"content_id": 5, "title": "X", "content_kind": "PLAY", "planned_minutes": 10, "diagram": diagram}],
    )
    block = day["blocks"][0]
    assert block["kind"] == "PLAY" and block["has_diagram"] is True
    assert block["layout"]["goalkeepers"]["members"][0]["name"] == "Lara"


def test_public_view_hides_layers_and_ct_alerts() -> None:
    records = _two_teams_roster()
    day = build_training_day(records, [{"content_id": 3, "title": "Coletivo", "planned_minutes": 30}])
    public = public_training_day(day)

    text = repr(public)
    assert "layer" not in text and "unranked" not in text and "alerts" not in text
    assert public["blocks"][0]["scrimmage"]["teams"]["A"][0]["name"]
