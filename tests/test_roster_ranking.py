from __future__ import annotations

from math import ceil, log2

import pytest

from handball.modules.elenco.ranking import (
    apply_answer,
    choose_representative,
    max_questions,
    next_probe,
    question_text,
    start_interval,
)


def _insert(layers: list[list[str]], athlete: str, value_of: dict[str, int]) -> int:
    """Simula uma inserção completa e devolve o número de perguntas feitas.

    ``layers`` é a lista de camadas do mais fraco (ordinal 0) para o mais
    forte; ``value_of`` é o "nível verdadeiro" que a CT usa para responder.
    """

    questions = 0
    lo, hi = start_interval(len(layers))
    while True:
        mid = next_probe(lo, hi)
        if mid is None:
            layers.insert(lo, [athlete])
            return questions
        reference = layers[mid][0]
        questions += 1
        if value_of[athlete] == value_of[reference]:
            outcome = "EQUAL"
        elif value_of[athlete] > value_of[reference]:
            outcome = "BETTER"
        else:
            outcome = "WORSE"
        action, value = apply_answer(lo, hi, mid, outcome)
        if action == "JOIN_LAYER":
            layers[value].append(athlete)
            return questions
        lo, hi = value


def test_first_athlete_needs_no_question_and_creates_layer_zero() -> None:
    layers: list[list[str]] = []
    assert _insert(layers, "a", {"a": 5}) == 0
    assert layers == [["a"]]


def test_equal_answer_merges_athletes_into_the_same_layer() -> None:
    layers: list[list[str]] = []
    values = {"a": 5, "b": 5, "c": 5}
    for athlete in values:
        _insert(layers, athlete, values)
    assert layers == [["a", "b", "c"]]


def test_empty_interval_creates_layers_below_between_and_above() -> None:
    layers: list[list[str]] = []
    values = {"meio": 50, "pior": 10, "melhor": 90, "entre": 70}
    for athlete in ("meio", "pior", "melhor", "entre"):
        _insert(layers, athlete, values)
    assert layers == [["pior"], ["meio"], ["entre"], ["melhor"]]


def test_question_count_never_exceeds_binary_search_bound() -> None:
    values = {f"a{i}": i for i in range(40)}
    layers: list[list[str]] = []
    for athlete, _ in sorted(values.items(), key=lambda item: hash(item[0])):
        bound = max_questions(len(layers))
        assert _insert(layers, athlete, values) <= bound
    # Todos com níveis distintos: uma camada por atleta, na ordem certa.
    assert [member for layer in layers for member in layer] == [
        f"a{i}" for i in range(40)
    ]


def test_max_questions_matches_information_bound() -> None:
    assert max_questions(0) == 0
    for layer_count in range(1, 200):
        assert max_questions(layer_count) == ceil(log2(layer_count + 1))


def test_shared_layers_cost_fewer_questions_than_total_order() -> None:
    # 16 atletas em 2 níveis: o teto por atleta fica em ceil(log2(3)) = 2
    # perguntas depois que as duas camadas existem.
    values = {f"a{i}": i % 2 for i in range(16)}
    layers: list[list[str]] = []
    total = sum(_insert(layers, athlete, values) for athlete in values)
    assert len(layers) == 2
    assert total <= 2 + 2 * 14


def test_apply_answer_rejects_unknown_outcome() -> None:
    with pytest.raises(ValueError):
        apply_answer(0, 4, 2, "MAYBE")


def test_next_probe_signals_new_layer_on_empty_interval() -> None:
    assert next_probe(2, 2) is None
    assert next_probe(3, 2) is None
    assert next_probe(0, 4) == 2


def test_choose_representative_is_deterministic_and_never_the_subject() -> None:
    members = [
        {"member_id": 1, "name": "Bia", "active": True, "comparisons_count": 2},
        {"member_id": 2, "name": "Ana", "active": True, "comparisons_count": 2},
        {"member_id": 3, "name": "Caio", "active": True, "comparisons_count": 9},
    ]
    chosen = choose_representative(members, subject_member_id=3)
    # O próprio sujeito (mais ancorado) fica de fora; empate resolve por nome.
    assert chosen is not None and chosen["member_id"] == 2
    assert choose_representative(members[:1], subject_member_id=1) is None


def test_choose_representative_prefers_active_members() -> None:
    members = [
        {"member_id": 1, "name": "Ana", "active": False, "comparisons_count": 9},
        {"member_id": 2, "name": "Bia", "active": True, "comparisons_count": 0},
    ]
    chosen = choose_representative(members, subject_member_id=99)
    assert chosen is not None and chosen["member_id"] == 2


def test_question_text_is_in_portuguese_and_names_both_athletes() -> None:
    text = question_text("Ana", "Bia")
    assert "Ana" in text and "Bia" in text
    assert "mesmo nível" in text
