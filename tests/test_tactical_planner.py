from __future__ import annotations

from handball.modules.presencas.planner import build_coach_report


def record(
    member_id: int,
    name: str,
    attack: list[str],
    *,
    selected: list[str] | None = None,
    defense: list[str] | None = None,
) -> dict[str, object]:
    return {
        "member_id": member_id,
        "name": name,
        "position": "/".join(attack),
        "attack_positions": attack,
        "defensive_positions": defense or [],
        "training_positions": selected or [],
        "confirmation_status": "CONFIRMED_EARLY",
        "present": None,
    }


def test_twelve_wings_do_not_create_two_complete_six_player_teams() -> None:
    records = [record(index, f"Ponta {index}", ["PE", "PD"]) for index in range(1, 13)]

    report = build_coach_report(records)

    assert report["confirmed_count"] == 12
    assert report["scrimmages"] == []


def test_complete_lineups_do_not_repeat_players_and_report_goalkeeper_rotation() -> None:
    records = []
    member_id = 1
    defenses = (["M1"], ["M1"], ["M2"], ["M2"], ["M3"], ["M3"])
    for team in range(2):
        for position, defense in zip(("PE", "ME", "C", "MD", "PD", "PV"), defenses, strict=True):
            records.append(record(member_id, f"T{team}-{position}", [position], defense=defense))
            member_id += 1
    records.append(record(member_id, "Goleiro", ["GOL"]))

    report = build_coach_report(records)

    option = report["scrimmages"][0]
    assigned = [item["member_id"] for team in option["teams"].values() for item in team]
    assert len(assigned) == len(set(assigned)) == 12
    assert option["goalkeeper_status"] == "ROTATION"
    assert option["complete"] is True
    assert option["defense_coverage"]["A"]["6x0"]["feasible"] is True


def test_selected_training_positions_override_profile_fallback() -> None:
    exercise = {
        "content_id": 10,
        "title": "Finalização de ponta",
        "variants": [{
            "label": "Direita",
            "roles": [{"group": "ATTACK", "label": "Ponta", "count": 1, "attack_positions": ["PD"]}],
        }],
    }
    player = record(1, "Coringa", ["PE", "PD"], selected=["PE"])

    restricted = build_coach_report([player], [exercise])
    fallback = build_coach_report([record(1, "Coringa", ["PE", "PD"])], [exercise])

    assert restricted["executable_exercises"] == []
    assert restricted["near_feasible_exercises"][0]["missing_roles"] == ["Ponta"]
    assert fallback["executable_exercises"][0]["assignments"][0]["assignments"][0]["name"] == "Coringa"


def test_generic_defender_only_fills_roles_that_explicitly_allow_it() -> None:
    generic = record(1, "Defensor", ["C"])
    exercises = [
        {
            "content_id": 1,
            "title": "Defesa livre",
            "variants": [{"label": "Livre", "roles": [{
                "group": "DEFENSE", "label": "Defensor", "count": 1,
                "allow_generic_defender": True,
            }]}],
        },
        {
            "content_id": 2,
            "title": "Primeiro marcador",
            "variants": [{"label": "M1", "roles": [{
                "group": "DEFENSE", "label": "1º marcador", "count": 1,
                "defensive_positions": ["M1"], "allow_generic_defender": False,
            }]}],
        },
    ]

    report = build_coach_report([generic], exercises)

    assert [item["title"] for item in report["executable_exercises"]] == ["Defesa livre"]
    assert report["near_feasible_exercises"][0]["title"] == "Primeiro marcador"
