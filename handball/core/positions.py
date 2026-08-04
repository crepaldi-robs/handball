from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


ATTACK_POSITION_LABELS: dict[str, str] = {
    "GOL": "Goleiro",
    "PE": "Ponta esquerda",
    "ME": "Meia esquerda",
    "C": "Central",
    "MD": "Meia direita",
    "PD": "Ponta direita",
    "PV": "Pivô",
}

DEFENSIVE_POSITION_LABELS: dict[str, str] = {
    "M1": "1º marcador",
    "M2": "2º marcador",
    "M3": "3º marcador",
    "AVANCADO": "Avançado",
}

_ATTACK_ALIASES = {
    "GOL": "GOL",
    "GK": "GOL",
    "GOLEIRO": "GOL",
    "GOLEIRA": "GOL",
    "PE": "PE",
    "PONTA ESQUERDA": "PE",
    "ME": "ME",
    "AE": "ME",
    "MEIA ESQUERDA": "ME",
    "ARMADOR ESQUERDO": "ME",
    "C": "C",
    "CENTRAL": "C",
    "ARMADOR CENTRAL": "C",
    "MD": "MD",
    "AD": "MD",
    "MEIA DIREITA": "MD",
    "ARMADOR DIREITO": "MD",
    "PD": "PD",
    "PONTA DIREITA": "PD",
    "PV": "PV",
    "PIV": "PV",
    "PIVO": "PV",
    "PIVOT": "PV",
}


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).upper().strip()


def normalize_attack_position(value: str) -> str | None:
    return _ATTACK_ALIASES.get(_plain(value))


def parse_attack_positions(value: str | Iterable[str]) -> list[str]:
    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values = [part for part in re.split(r"\s*[/,;|]\s*", value) if part.strip()]
    else:
        raw_values = [str(part) for part in value]
    result: list[str] = []
    for raw in raw_values:
        normalized = normalize_attack_position(raw)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_defensive_positions(values: Iterable[str]) -> list[str]:
    aliases = {
        "M1": "M1",
        "1": "M1",
        "1 MARCADOR": "M1",
        "PRIMEIRO MARCADOR": "M1",
        "M2": "M2",
        "2": "M2",
        "2 MARCADOR": "M2",
        "SEGUNDO MARCADOR": "M2",
        "M3": "M3",
        "3": "M3",
        "3 MARCADOR": "M3",
        "TERCEIRO MARCADOR": "M3",
        "AV": "AVANCADO",
        "AVANCADO": "AVANCADO",
    }
    result: list[str] = []
    for value in values:
        normalized = aliases.get(_plain(str(value)))
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def attack_positions_text(values: Iterable[str]) -> str:
    return "/".join(parse_attack_positions(values))
