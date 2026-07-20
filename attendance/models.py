from __future__ import annotations

CONFIRMATION_LABELS: dict[str, str] = {
    "PENDING": "Pendente",
    "CONFIRMED_EARLY": "Confirmou com mais de 24h",
    "CONFIRMED_LATE": "Confirmou dentro de 24h",
    "CANCELLED_EARLY": "Desmarcou com mais de 24h",
    "CANCELLED_LATE": "Desmarcou dentro de 24h",
    "NO_RESPONSE": "Sem resposta",
}

CONFIRMATION_OPTIONS: list[str] = list(CONFIRMATION_LABELS.values())

LABEL_TO_CONFIRMATION: dict[str, str] = {
    label: code for code, label in CONFIRMATION_LABELS.items()
}

CONFIRMED_CODES = {"CONFIRMED_EARLY", "CONFIRMED_LATE"}
CANCELLED_CODES = {"CANCELLED_EARLY", "CANCELLED_LATE"}
PENDING_CODES = {"PENDING", "NO_RESPONSE"}

INITIAL_MEMBERS: tuple[tuple[str, str], ...] = (
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
