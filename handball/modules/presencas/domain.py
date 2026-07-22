from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


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


def records_to_editor_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Mantém a transformação tabular histórica sem acoplar persistência."""

    return pd.DataFrame(
        [
            {
                "member_id": int(record["member_id"]),
                "Nome": record["name"],
                "Posição": record["position"],
                "Situação da confirmação": CONFIRMATION_LABELS[
                    record["confirmation_status"]
                ],
                "Presente": record["present"] == 1,
                "Observação": record["notes"] or "",
            }
            for record in records
        ]
    )


def editor_dataframe_to_updates(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    """Converte a tabela editável para comandos de domínio tipados por código."""

    return [
        {
            "member_id": int(row["member_id"]),
            "confirmation_status": LABEL_TO_CONFIRMATION[
                str(row["Situação da confirmação"])
            ],
            "present": bool(row["Presente"]),
            "notes": str(row.get("Observação") or ""),
        }
        for row in dataframe.to_dict(orient="records")
    ]


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = [r for r in records if r["confirmation_status"] in CONFIRMED_CODES]
    pending = [r for r in records if r["confirmation_status"] in PENDING_CODES]
    cancelled = [r for r in records if r["confirmation_status"] in CANCELLED_CODES]
    present = [r for r in records if r["present"] == 1]
    absent = [r for r in records if r["present"] == 0]
    unknown_presence = [r for r in records if r["present"] is None]
    by_status: dict[str, list[str]] = {
        code: [
            r["name"]
            for r in records
            if r["confirmation_status"] == code
        ]
        for code in CONFIRMATION_LABELS
    }
    return {
        "confirmed": confirmed,
        "pending": pending,
        "cancelled": cancelled,
        "present": present,
        "absent": absent,
        "unknown_presence": unknown_presence,
        "by_status": by_status,
    }


def _names(items: list[dict[str, Any]] | list[str]) -> str:
    if not items:
        return "nenhum"
    return ", ".join(
        item["name"] if isinstance(item, dict) else str(item)
        for item in items
    )


def build_coach_message(
    training_date: date,
    records: list[dict[str, Any]],
    *,
    is_finalized: bool,
) -> str:
    summary = summarize_records(records)
    status = summary["by_status"]
    lines = [
        f"Treino de {training_date.strftime('%d/%m/%Y')}",
        "",
        f"Confirmados: {len(summary['confirmed'])}",
        f"• Mais de 24h: {_names(status['CONFIRMED_EARLY'])}",
        f"• Dentro de 24h: {_names(status['CONFIRMED_LATE'])}",
        "",
        f"Pendentes/sem resposta: {len(summary['pending'])}",
        f"• Pendentes: {_names(status['PENDING'])}",
        f"• Sem resposta: {_names(status['NO_RESPONSE'])}",
        "",
        f"Desmarcaram: {len(summary['cancelled'])}",
        f"• Mais de 24h: {_names(status['CANCELLED_EARLY'])}",
        f"• Dentro de 24h: {_names(status['CANCELLED_LATE'])}",
    ]
    if is_finalized:
        lines.extend(
            [
                "",
                f"Presença real: {len(summary['present'])} presentes",
                f"• Presentes: {_names(summary['present'])}",
                f"• Ausentes: {_names(summary['absent'])}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Presença real: chamada ainda não encerrada.",
                f"• Presentes já marcados: {_names(summary['present'])}",
            ]
        )
    return "\n".join(lines)


def history_to_dataframe(history: list[dict[str, Any]]) -> pd.DataFrame:
    if not history:
        return pd.DataFrame()

    rows = []
    for item in history:
        present_value = item["present"]
        if present_value == 1:
            presence_label = "Presente"
        elif present_value == 0:
            presence_label = "Ausente"
        else:
            presence_label = "Não apurado"
        rows.append(
            {
                "Data do treino": item["training_date"],
                "Nome": item["name"],
                "Posição": item["position"],
                "Confirmação": CONFIRMATION_LABELS[item["confirmation_status"]],
                "Presença real": presence_label,
                "Observação": item["notes"] or "",
                "Treino encerrado": "Sim" if item["is_finalized"] else "Não",
                "Atualizado em": item["updated_at"],
            }
        )
    return pd.DataFrame(rows)
