from __future__ import annotations

from handball.modules.playbook.composition import build_preview


def record(
    member_id: int,
    name: str,
    attack: list[str],
    *,
    defense: list[str] | None = None,
    layer_ordinal: int | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "member_id": member_id,
        "name": name,
        "attack_positions": attack,
        "defensive_positions": defense or [],
        "training_positions": [],
    }
    if layer_ordinal is not None:
        item["layer_ordinal"] = layer_ordinal
        item["layer_label"] = f"Camada {layer_ordinal + 1}"
    return item


def block(block_id: str, roles: list[dict[str, object]]) -> dict[str, object]:
    return {"block_id": block_id, "label": block_id, "roles": roles}


def role(group: str, label: str, *, count: int = 1, attack: list[str] | None = None, defense: list[str] | None = None, allow_generic_defender: bool = False) -> dict[str, object]:
    return {
        "group": group,
        "label": label,
        "count": count,
        "attack_positions": attack or [],
        "defensive_positions": defense or [],
        "allow_generic_defender": allow_generic_defender,
    }


def test_unknown_layer_is_never_reported_as_zero() -> None:
    participants = [record(1, "Sem camada", ["PE"])]
    blocks = [block("bloco", [role("ATTACK", "Ponta", attack=["PE"])])]
    assignments = [{"slot_id": "bloco:0:0", "member_id": 1, "occupant_locked": False}]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    occupant = preview["slots"][0]["occupant"]
    assert "layer_ordinal" not in occupant
    assert preview["diagnostics"]["ranking_gaps"] == []


def test_ties_share_the_same_layer_label_in_distribution() -> None:
    participants = [
        record(1, "A", ["PE"], layer_ordinal=2),
        record(2, "B", ["PD"], layer_ordinal=2),
    ]
    blocks = [block("bloco", [role("ATTACK", "Ponta E", attack=["PE"]), role("ATTACK", "Ponta D", attack=["PD"])])]
    assignments = [
        {"slot_id": "bloco:0:0", "member_id": 1},
        {"slot_id": "bloco:1:0", "member_id": 2},
    ]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    assert preview["diagnostics"]["layer_distribution_by_block"]["bloco"] == {"Camada 3": 2}


def test_strong_and_weak_layers_are_distinguished_not_collapsed() -> None:
    participants = [
        record(1, "Forte", ["PE"], layer_ordinal=4),
        record(2, "Fraco", ["PD"], layer_ordinal=0),
    ]
    blocks = [block("bloco", [role("ATTACK", "Ponta E", attack=["PE"]), role("ATTACK", "Ponta D", attack=["PD"])])]
    assignments = [
        {"slot_id": "bloco:0:0", "member_id": 1},
        {"slot_id": "bloco:1:0", "member_id": 2},
    ]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    distribution = preview["diagnostics"]["layer_distribution_by_block"]["bloco"]
    assert distribution == {"Camada 5": 1, "Camada 1": 1}


def test_goalkeeper_slot_requires_gol_position() -> None:
    participants = [record(1, "Linha", ["PE"]), record(2, "Goleiro", ["GOL"])]
    blocks = [block("bloco", [role("GOALKEEPER", "Gol", attack=["GOL"])])]

    ineligible = build_preview(
        participant_records=participants,
        blocks=blocks,
        assignments=[{"slot_id": "bloco:0:0", "member_id": 1}],
        mode="EQUILIBRADO",
    )
    assert "INELIGIBLE_POSITION" in ineligible["slots"][0]["conflicts"]

    eligible = build_preview(
        participant_records=participants,
        blocks=blocks,
        assignments=[{"slot_id": "bloco:0:0", "member_id": 2}],
        mode="EQUILIBRADO",
    )
    assert eligible["slots"][0]["conflicts"] == []


def test_hybrid_goalkeeper_can_fill_line_or_goalkeeper_slot() -> None:
    hybrid = record(1, "Híbrido", ["GOL", "PV"])
    blocks = [block("bloco", [role("GOALKEEPER", "Gol", attack=["GOL"]), role("ATTACK", "Pivô", attack=["PV"])])]

    as_goalkeeper = build_preview(
        participant_records=[hybrid],
        blocks=blocks,
        assignments=[{"slot_id": "bloco:0:0", "member_id": 1}],
        mode="EQUILIBRADO",
    )
    assert as_goalkeeper["slots"][0]["conflicts"] == []

    as_pivot = build_preview(
        participant_records=[hybrid],
        blocks=blocks,
        assignments=[{"slot_id": "bloco:1:0", "member_id": 1}],
        mode="EQUILIBRADO",
    )
    assert as_pivot["slots"][1]["conflicts"] == []


def test_two_goalkeepers_both_resolve_without_conflict() -> None:
    participants = [record(1, "G1", ["GOL"]), record(2, "G2", ["GOL"])]
    blocks = [block("bloco", [role("GOALKEEPER", "Gol", attack=["GOL"], count=2)])]
    assignments = [
        {"slot_id": "bloco:0:0", "member_id": 1},
        {"slot_id": "bloco:0:1", "member_id": 2},
    ]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    assert all(slot["conflicts"] == [] for slot in preview["slots"])


def test_zero_goalkeepers_leaves_slot_vacant_not_silently_filled() -> None:
    participants = [record(1, "Linha", ["PE"])]
    blocks = [block("bloco", [role("GOALKEEPER", "Gol", attack=["GOL"])])]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=[], mode="EQUILIBRADO")

    assert preview["diagnostics"]["vacant_slots"] == [{"slot_id": "bloco:0:0", "block_id": "bloco", "role": "Gol"}]


def test_duplicate_occupant_in_two_slots_is_an_explicit_conflict() -> None:
    participants = [record(1, "Duplicado", ["PE", "PD"])]
    blocks = [block("bloco", [role("ATTACK", "Ponta E", attack=["PE"]), role("ATTACK", "Ponta D", attack=["PD"])])]
    assignments = [
        {"slot_id": "bloco:0:0", "member_id": 1},
        {"slot_id": "bloco:1:0", "member_id": 1},
    ]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    assert all("DUPLICATE_OCCUPANT" in slot["conflicts"] for slot in preview["slots"])


def test_incompatible_fixation_is_reported_not_silently_moved() -> None:
    participants = [record(1, "Pivô", ["PV"])]
    blocks = [block("bloco", [role("ATTACK", "Ponta", attack=["PE"])])]
    assignments = [{"slot_id": "bloco:0:0", "member_id": 1, "occupant_locked": True}]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    slot = preview["slots"][0]
    assert slot["occupant_locked"] is True
    assert slot["member_id"] == 1
    assert "INELIGIBLE_POSITION" in slot["conflicts"]


def test_last_minute_removal_after_fixation_is_explicit_not_silent_swap() -> None:
    # O participante foi removido (ex.: falta de última hora) mas o
    # assignment ainda referencia o antigo ocupante — não deve inventar um
    # substituto silenciosamente.
    participants: list[dict[str, object]] = []
    blocks = [block("bloco", [role("ATTACK", "Ponta", attack=["PE"])])]
    assignments = [{"slot_id": "bloco:0:0", "member_id": 1, "occupant_locked": True}]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=assignments, mode="EQUILIBRADO")

    slot = preview["slots"][0]
    assert slot["member_id"] == 1
    assert slot["occupant"] is None
    assert "PARTICIPANT_NOT_AVAILABLE" in slot["conflicts"]


def test_coverage_counts_known_positions_and_never_fabricates_zero_for_unknown() -> None:
    participants = [record(1, "A", ["PE"]), record(2, "B", [])]
    blocks = [block("bloco", [role("ATTACK", "Ponta", attack=["PE"])])]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=[], mode="EQUILIBRADO")

    coverage = preview["diagnostics"]["coverage"]
    assert coverage["attack"]["PE"] == 1
    assert coverage["known_participants"] == 2
    assert preview["diagnostics"]["data_gaps"] == [{"member_id": 2, "name": "B", "kind": "ATTACK_POSITIONS"}]


def test_generic_defender_only_fills_slot_that_allows_it() -> None:
    # Papel defensivo sem posição específica exigida: só assim
    # allow_generic_defender entra em jogo (posição específica exigida
    # sempre rejeita quem não tem nenhuma posição defensiva registrada).
    generic = record(1, "Genérico", ["PE"], defense=[])
    blocks = [block("bloco", [role("DEFENSE", "Marcador")])]

    without_allow = build_preview(
        participant_records=[generic],
        blocks=blocks,
        assignments=[{"slot_id": "bloco:0:0", "member_id": 1}],
        mode="EQUILIBRADO",
    )
    assert "INELIGIBLE_POSITION" in without_allow["slots"][0]["conflicts"]

    blocks_allowed = [block("bloco", [role("DEFENSE", "Marcador", allow_generic_defender=True)])]
    with_allow = build_preview(
        participant_records=[generic],
        blocks=blocks_allowed,
        assignments=[{"slot_id": "bloco:0:0", "member_id": 1}],
        mode="EQUILIBRADO",
    )
    assert with_allow["slots"][0]["conflicts"] == []


def test_eligible_member_ids_lists_candidates_for_the_substitute_picker() -> None:
    participants = [record(1, "Ponta", ["PE"]), record(2, "Pivô", ["PV"])]
    blocks = [block("bloco", [role("ATTACK", "Ponta esquerda", attack=["PE"])])]

    preview = build_preview(participant_records=participants, blocks=blocks, assignments=[], mode="EQUILIBRADO")

    assert preview["slots"][0]["eligible_member_ids"] == [1]
    assert [item["member_id"] for item in preview["participants"]] == [1, 2]


def test_mode_is_echoed_back_without_running_any_automatic_search() -> None:
    preview = build_preview(
        participant_records=[record(1, "A", ["PE"])],
        blocks=[block("bloco", [role("ATTACK", "Ponta", attack=["PE"])])],
        assignments=[],
        mode="DIRECIONADO",
    )

    assert preview["mode"] == "DIRECIONADO"
    assert preview["method_version"]
    assert preview["schema_version"] == 1


def _ranked(member_id: int, name: str, position: str, *, attack: int, defense: int) -> dict[str, object]:
    item = record(member_id, name, [position])
    item["attack_layer_ordinal"] = attack
    item["layer_ordinal"] = attack
    item["defense_layer_ordinal"] = defense
    return item


def _team_blocks() -> list[dict[str, object]]:
    return [
        block("time-a", [role("ATTACK", "Time A · Central", attack=["C"]), role("ATTACK", "Time A · Pivô", attack=["PV"])]),
        block("time-b", [role("ATTACK", "Time B · Central", attack=["C"]), role("ATTACK", "Time B · Pivô", attack=["PV"])]),
    ]


def _occupants(preview: dict) -> dict[str, str]:
    names = {item["member_id"]: item["name"] for item in preview["participants"]}
    return {slot["slot_id"]: names.get(slot["member_id"]) for slot in preview["slots"]}


def test_board_starts_with_strong_attack_against_strong_defense() -> None:
    participants = [
        _ranked(1, "Atq C", "C", attack=3, defense=0),
        _ranked(2, "Def C", "C", attack=0, defense=3),
        _ranked(3, "Atq PV", "PV", attack=3, defense=0),
        _ranked(4, "Def PV", "PV", attack=0, defense=3),
    ]
    preview = build_preview(participant_records=participants, blocks=_team_blocks(), assignments=[], mode="DIRECIONADO", suggest=True)

    occupants = _occupants(preview)
    assert occupants == {"time-a:0:0": "Atq C", "time-a:1:0": "Atq PV", "time-b:0:0": "Def C", "time-b:1:0": "Def PV"}
    assert {slot["origin"] for slot in preview["slots"]} == {"SUGGESTED"}
    assert preview["diagnostics"]["conflicts"] == []


def test_suggestion_never_moves_what_the_ct_placed_and_leaves_ineligible_slots_vacant() -> None:
    participants = [
        _ranked(1, "Atq C", "C", attack=3, defense=0),
        _ranked(2, "Def C", "C", attack=0, defense=3),
        _ranked(3, "Atq PV", "PV", attack=3, defense=0),
    ]
    manual = [{"slot_id": "time-a:0:0", "member_id": 2, "occupant_locked": True}]
    preview = build_preview(participant_records=participants, blocks=_team_blocks(), assignments=manual, mode="DIRECIONADO", suggest=True)

    occupants = _occupants(preview)
    assert occupants["time-a:0:0"] == "Def C"
    assert occupants["time-b:0:0"] == "Atq C"
    assert occupants["time-a:1:0"] == "Atq PV"
    assert occupants["time-b:1:0"] is None  # ninguém mais joga de pivô
    origins = {slot["slot_id"]: slot["origin"] for slot in preview["slots"]}
    assert origins["time-a:0:0"] == "MANUAL" and origins["time-b:0:0"] == "SUGGESTED"
    assert [item["slot_id"] for item in preview["diagnostics"]["vacant_slots"]] == ["time-b:1:0"]


def test_balanced_suggestion_splits_strength_between_teams() -> None:
    participants = [
        _ranked(1, "Forte C", "C", attack=3, defense=3),
        _ranked(2, "Fraca C", "C", attack=0, defense=0),
        _ranked(3, "Forte PV", "PV", attack=3, defense=3),
        _ranked(4, "Fraca PV", "PV", attack=0, defense=0),
    ]
    preview = build_preview(participant_records=participants, blocks=_team_blocks(), assignments=[], mode="EQUILIBRADO", suggest=True)

    occupants = _occupants(preview)
    team_a = {occupants["time-a:0:0"], occupants["time-a:1:0"]}
    assert team_a in ({"Forte C", "Fraca PV"}, {"Fraca C", "Forte PV"})


def test_without_suggest_flag_the_board_stays_manual() -> None:
    participants = [_ranked(1, "Atq C", "C", attack=3, defense=0)]
    preview = build_preview(participant_records=participants, blocks=_team_blocks(), assignments=[], mode="DIRECIONADO")

    assert all(slot["member_id"] is None for slot in preview["slots"])
