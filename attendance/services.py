from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .models import (
    CANCELLED_CODES,
    CONFIRMATION_LABELS,
    CONFIRMED_CODES,
    LABEL_TO_CONFIRMATION,
    PENDING_CODES,
)


def records_to_editor_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for record in records:
        rows.append(
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
        )
    return pd.DataFrame(rows)


def editor_dataframe_to_updates(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for row in dataframe.to_dict(orient="records"):
        label = str(row["Situação da confirmação"])
        updates.append(
            {
                "member_id": int(row["member_id"]),
                "confirmation_status": LABEL_TO_CONFIRMATION[label],
                "present": bool(row["Presente"]),
                "notes": str(row.get("Observação") or ""),
            }
        )
    return updates


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
    names = [
        item["name"] if isinstance(item, dict) else str(item)
        for item in items
    ]
    return ", ".join(names)


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
