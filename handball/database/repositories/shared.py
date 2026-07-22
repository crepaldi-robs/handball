from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")

# Códigos persistidos pelo schema v1. Rótulos e apresentação pertencem ao módulo.
VALID_CONFIRMATION_STATUSES = frozenset(
    {
        "PENDING",
        "CONFIRMED_EARLY",
        "CONFIRMED_LATE",
        "CANCELLED_EARLY",
        "CANCELLED_LATE",
        "NO_RESPONSE",
    }
)

# Bootstrap histórico da instalação inicial. É inserido somente em banco candidato.
INITIAL_MEMBER_ROWS: tuple[tuple[str, str], ...] = (
    ("Arthur", "PD"),
    ("Gabixo", "ME/C"),
    ("João Alma", "ME"),
    ("BDX", "PD/PE"),
    ("Pedrinho", "PD"),
    ("Fumis", "PV"),
    ("Gabigol", "GOL"),
    ("Giovanny", "PE/PV"),
    ("Augusto", "GOL"),
    ("Guido", "PD/PE"),
    ("Luan", "GOL"),
    ("Olsen", "GOL"),
    ("Rafa Pod", "PE"),
    ("Vitinho", "C"),
    ("Isaac", "PV"),
    ("Tom", "C/MD"),
    ("Zampol", "MD/C"),
    ("Guerra", "GOL"),
    ("Sotelo", "PE"),
)


def now_iso() -> str:
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def date_iso(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()
