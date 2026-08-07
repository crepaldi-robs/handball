"""Inserção de um atleta na hierarquia de camadas com o mínimo de perguntas.

A hierarquia não é uma ordem total entre pessoas: várias podem dividir a mesma
camada, e a única garantia é que toda a camada de ordinal N é pior que toda a
camada N+1. Cada atleta novo é posicionado por busca binária sobre a lista de
camadas: a CT responde "melhor", "pior" ou "mesmo nível" contra um representante
da camada do meio, o que custa no máximo ceil(log2(k+1)) perguntas para k
camadas — a resposta "mesmo nível" encerra cedo e é o que agrupa atletas.
"""
from __future__ import annotations

from math import ceil, log2
from typing import Any, Mapping, Sequence

RANK_SCOPES = ("LINE", "GOALKEEPER")
SCOPE_LABELS = {"LINE": "Linha", "GOALKEEPER": "Goleiros"}

OUTCOME_BETTER = "BETTER"
OUTCOME_WORSE = "WORSE"
OUTCOME_EQUAL = "EQUAL"
VALID_OUTCOMES = frozenset({OUTCOME_BETTER, OUTCOME_WORSE, OUTCOME_EQUAL})


def start_interval(layer_count: int) -> tuple[int, int]:
    """Intervalo inicial [lo, hi) de ordinais onde o atleta ainda pode cair."""

    return (0, max(0, int(layer_count)))


def next_probe(lo: int, hi: int) -> int | None:
    """Ordinal da próxima camada a comparar; None quando o intervalo esvaziou.

    Intervalo vazio significa que nenhuma camada existente serve: o atleta
    ganha uma camada nova no ordinal ``lo`` (cobre abaixo de todas, entre duas
    e acima de todas).
    """

    if lo >= hi:
        return None
    return (lo + hi) // 2


def apply_answer(lo: int, hi: int, mid: int, outcome: str) -> tuple[str, Any]:
    """Aplica a resposta da CT, do ponto de vista do atleta sendo inserido."""

    if outcome not in VALID_OUTCOMES:
        raise ValueError("Resposta de comparação inválida.")
    if outcome == OUTCOME_EQUAL:
        return ("JOIN_LAYER", mid)
    if outcome == OUTCOME_BETTER:
        return ("CONTINUE", (mid + 1, hi))
    return ("CONTINUE", (lo, mid))


def max_questions(layer_count: int) -> int:
    """Teto de perguntas da busca binária para ``layer_count`` camadas."""

    if layer_count <= 0:
        return 0
    return ceil(log2(layer_count + 1))


def choose_representative(
    members: Sequence[Mapping[str, Any]], *, subject_member_id: int
) -> Mapping[str, Any] | None:
    """Representante determinístico de uma camada para a pergunta da CT.

    Prefere quem já respondeu mais comparações (âncora mais estável) e
    desempata por nome; o próprio atleta sendo (re)ranqueado nunca representa
    a camada, e inativos só entram na falta de ativos.
    """

    candidates = [
        member
        for member in members
        if int(member["member_id"]) != int(subject_member_id)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda member: (
            not bool(member.get("active", True)),
            -int(member.get("comparisons_count", 0)),
            str(member.get("name", "")).casefold(),
        ),
    )[0]


def question_text(subject_name: str, reference_name: str) -> str:
    return (
        f"Quem é melhor em quadra: {subject_name} ou {reference_name}? "
        "(ou são do mesmo nível)"
    )
