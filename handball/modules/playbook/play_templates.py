"""Modelos iniciais de jogada: nunca uma quadra vazia.

Coordenadas em metros na meia quadra (origem no centro da linha de gol,
x para a direita de quem ataca, y em direção ao meio da quadra). As defesas
ficam logo fora da área de 6 m, que é formada por um segmento reto de 3 m e
dois quartos de círculo de raio 6 m centrados nas traves (Regra 1 da IHF).

Os nomes do catálogo do time (X, Desdobre, Islândia…) chegam com a formação
contra 6x0 pronta; o movimento é do time e a CT desenha. Só o cruzamento
central ↔ meia direita, conceito clássico, vem com passos de exemplo.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

POST_X = 1.5


def _around_area(side: int, degrees: float, radius: float = 6.4) -> dict[str, float]:
    """Ponto a ``radius`` metros da trave do lado ``side`` (-1 esquerda, 1 direita)."""

    angle = math.radians(degrees)
    x = side * (POST_X + radius * math.cos(angle))
    y = radius * math.sin(angle)
    return {"x": round(x, 2), "y": round(y, 2)}


ATTACK_3_3: list[dict[str, Any]] = [
    {"id": "a-pe", "side": "ATTACK", "position": "PE", "start": {"x": -8.8, "y": 1.6}},
    {"id": "a-me", "side": "ATTACK", "position": "ME", "start": {"x": -5.6, "y": 9.6}},
    {"id": "a-c", "side": "ATTACK", "position": "C", "start": {"x": 0.0, "y": 10.8}},
    {"id": "a-md", "side": "ATTACK", "position": "MD", "start": {"x": 5.6, "y": 9.6}},
    {"id": "a-pd", "side": "ATTACK", "position": "PD", "start": {"x": 8.8, "y": 1.6}},
    {"id": "a-pv", "side": "ATTACK", "position": "PV", "start": {"x": 0.8, "y": 6.6}},
]

GOALKEEPER = {"id": "d-gol", "side": "DEFENSE", "position": "GOL", "start": {"x": 0.0, "y": 0.9}}

DEFENSE_6_0: list[dict[str, Any]] = [
    {"id": "d-m1e", "side": "DEFENSE", "position": "M1", "start": _around_area(-1, 18)},
    {"id": "d-m2e", "side": "DEFENSE", "position": "M2", "start": _around_area(-1, 50)},
    {"id": "d-m3e", "side": "DEFENSE", "position": "M3", "start": _around_area(-1, 80)},
    {"id": "d-m3d", "side": "DEFENSE", "position": "M3", "start": _around_area(1, 80)},
    {"id": "d-m2d", "side": "DEFENSE", "position": "M2", "start": _around_area(1, 50)},
    {"id": "d-m1d", "side": "DEFENSE", "position": "M1", "start": _around_area(1, 18)},
    GOALKEEPER,
]

DEFENSE_5_1: list[dict[str, Any]] = [
    {"id": "d-m1e", "side": "DEFENSE", "position": "M1", "start": _around_area(-1, 18)},
    {"id": "d-m2e", "side": "DEFENSE", "position": "M2", "start": _around_area(-1, 55)},
    {"id": "d-m3", "side": "DEFENSE", "position": "M3", "start": {"x": 0.0, "y": 6.5}},
    {"id": "d-m2d", "side": "DEFENSE", "position": "M2", "start": _around_area(1, 55)},
    {"id": "d-m1d", "side": "DEFENSE", "position": "M1", "start": _around_area(1, 18)},
    {"id": "d-av", "side": "DEFENSE", "position": "AVANCADO", "start": {"x": 0.0, "y": 8.9}},
    GOALKEEPER,
]


def _formation(defense: list[dict[str, Any]] | None, *, system: str | None) -> dict[str, Any]:
    actors = deepcopy(ATTACK_3_3) + deepcopy(defense or [])
    return {
        "court": "HALF",
        "defense_system": system,
        "actors": actors,
        "ball": {"holder": "a-c"},
        "steps": [],
    }


def _cruzamento() -> dict[str, Any]:
    diagram = _formation(DEFENSE_6_0, system="6x0")
    diagram["steps"] = [
        {
            "id": "s1",
            "label": "Central ataca o intervalo",
            "duration_s": 2.0,
            "note": "Central conduz em diagonal para o intervalo entre o 3º e o 2º marcador da direita.",
            "actions": [
                {"type": "DRIBBLE", "actor": "a-c", "to": {"x": 2.6, "y": 8.6}},
                {"type": "MOVE", "actor": "a-md", "to": {"x": 5.0, "y": 10.4}},
            ],
        },
        {
            "id": "s2",
            "label": "Cruzamento C → MD",
            "duration_s": 2.0,
            "note": "Meia direita cruza por trás e recebe na corrida; o pivô fixa o 3º marcador.",
            "actions": [
                {"type": "MOVE", "actor": "a-md", "to": {"x": 0.8, "y": 9.2}, "via": [{"x": 3.2, "y": 10.6}]},
                {"type": "MOVE", "actor": "a-c", "to": {"x": 3.6, "y": 8.0}},
                {"type": "SCREEN", "actor": "a-pv", "target": "d-m3e"},
                {"type": "PASS", "actor": "a-c", "target": "a-md", "at": 0.6},
            ],
        },
        {
            "id": "s3",
            "label": "Finalização",
            "duration_s": 1.5,
            "note": "Arremesso de 9 m no espaço aberto pelo cruzamento.",
            "actions": [
                {"type": "MOVE", "actor": "a-md", "to": {"x": -0.6, "y": 8.2}},
                {"type": "SHOT", "actor": "a-md", "zone": 1, "at": 0.8},
            ],
        },
    ]
    return diagram


def _counterattack() -> dict[str, Any]:
    return {
        "court": "HALF",
        "defense_system": None,
        "actors": [
            {"id": "a-pe", "side": "ATTACK", "position": "PE", "start": {"x": -7.5, "y": 18.5}},
            {"id": "a-c", "side": "ATTACK", "position": "C", "start": {"x": 0.0, "y": 19.0}},
            {"id": "a-pd", "side": "ATTACK", "position": "PD", "start": {"x": 7.5, "y": 18.5}},
            {"id": "d-m2e", "side": "DEFENSE", "position": "M2", "start": {"x": -3.0, "y": 11.0}},
            {"id": "d-m2d", "side": "DEFENSE", "position": "M2", "start": {"x": 3.0, "y": 11.0}},
            GOALKEEPER,
        ],
        "ball": {"holder": "a-c"},
        "steps": [],
    }


def _seven_meters() -> dict[str, Any]:
    return {
        "court": "HALF",
        "defense_system": None,
        "actors": [
            {"id": "a-7m", "side": "ATTACK", "position": "C", "label": "Cobrador", "start": {"x": 0.0, "y": 7.4}},
            GOALKEEPER,
        ],
        "ball": {"holder": "a-7m"},
        "steps": [
            {
                "id": "s1",
                "label": "Tiro de 7 m",
                "duration_s": 1.5,
                "note": "",
                "actions": [{"type": "SHOT", "actor": "a-7m", "zone": 3, "at": 0.6}],
            }
        ],
    }


CATALOG_NAMES = ("X", "Desdobre", "Corrida", "Circulação", "Roda", "Islândia", "Portugal", "Espanha", "Amplitude")


def play_templates() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = [
        {"key": "posicional-6x0", "title": "Ataque posicional × 6x0", "group": "Formações", "diagram": _formation(DEFENSE_6_0, system="6x0")},
        {"key": "posicional-5x1", "title": "Ataque posicional × 5x1", "group": "Formações", "diagram": _formation(DEFENSE_5_1, system="5x1")},
        {"key": "sem-defesa", "title": "Ataque sem defesa", "group": "Formações", "diagram": _formation([GOALKEEPER], system=None)},
        {"key": "contra-ataque", "title": "Contra-ataque 3 × 2", "group": "Situações", "diagram": _counterattack()},
        {"key": "sete-metros", "title": "Tiro de 7 m", "group": "Situações", "diagram": _seven_meters()},
        {"key": "cruzamento", "title": "Cruzamento C → MD × 6x0", "group": "Jogadas principais", "diagram": _cruzamento()},
    ]
    templates.extend(
        {
            "key": f"catalogo-{index}",
            "title": f"{name} × 6x0",
            "group": "Jogadas principais",
            "diagram": _formation(DEFENSE_6_0, system="6x0"),
        }
        for index, name in enumerate(CATALOG_NAMES, start=1)
    )
    return deepcopy(templates)
