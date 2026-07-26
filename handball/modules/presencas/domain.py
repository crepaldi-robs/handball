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


def _names_with_pos(records: list[dict[str, Any]]) -> str:
    if not records:
        return "nenhum"
    return ", ".join(
        f"{r['name']} ({r['position']})" if r.get("position") else r["name"]
        for r in records
    )


def classify_position_categories(position: str) -> list[str]:
    pos_upper = (position or "").upper().strip()
    if not pos_upper:
        return ["Outros / Não informada"]

    categories = []
    tokens = [
        t.strip()
        for t in pos_upper.replace("/", " ")
        .replace("-", " ")
        .replace(",", " ")
        .split()
        if t.strip()
    ]

    # 1. Goleiros
    if any(
        t in ["GOL", "GK", "GOLEIRO", "GOLEIRA", "GOLEIROS"] or "GOLEIR" in t
        for t in tokens
    ):
        categories.append("Goleiros")

    # 2. Pontas
    if any(
        t
        in [
            "PE",
            "PD",
            "PONTA",
            "PONTAS",
            "EXTREMO",
            "EXTREMOS",
            "WING",
            "WINGS",
        ]
        or "PONTA" in t
        for t in tokens
    ):
        categories.append("Pontas")

    # 3. Meias / Armadores
    if any(
        t
        in [
            "ME",
            "MD",
            "C",
            "AE",
            "AD",
            "MEIA",
            "MEIAS",
            "ARMADOR",
            "ARMADORES",
            "CENTRAL",
            "CENTRAIS",
            "BACK",
            "BACKS",
        ]
        or "ARMAD" in t
        or "MEIA" in t
        for t in tokens
    ):
        categories.append("Meias / Armadores")

    # 4. Pivôs
    if any(
        t in ["PV", "PIV", "PIVÔ", "PIVO", "PIVOTS", "PIVOT"] or "PIV" in t
        for t in tokens
    ):
        categories.append("Pivôs")

    if not categories:
        categories.append("Outros / Não informada")

    return categories


def build_tactical_insights(
    goleiros: list[dict[str, Any]],
    pontas: list[dict[str, Any]],
    meias: list[dict[str, Any]],
    pivos: list[dict[str, Any]],
    total_confirmed: int,
) -> list[str]:
    insights = []

    # 1. Goleiros (Foco Especial)
    if len(goleiros) == 0:
        insights.append(
            "🚨 GOLEIROS (0): Nenhum goleiro confirmado! Urgente convocar goleiro convidado para o treino."
        )
    elif len(goleiros) == 1:
        names_str = _names(goleiros)
        insights.append(
            f"⚠️ GOLEIROS (1): Apenas 1 goleiro confirmado ({names_str}). Recomenda-se chamar 1 goleiro convidado para garantir rotatividade nos arremessos."
        )
    else:
        insights.append(
            f"✅ GOLEIROS ({len(goleiros)}): Boa cobertura de goleiros para revezamento e trabalho coletivo."
        )

    # 2. Meias / Armadores
    if len(meias) == 0:
        insights.append(
            "🚨 ARMAÇÃO (0): Nenhum meia/armador confirmado! Treino tático comprometido. Cobrar confirmação urgente dos armadores."
        )
    elif len(meias) == 1:
        names_str = _names(meias)
        insights.append(
            f"⚠️ ARMAÇÃO (1): Apenas 1 meia/armador confirmado ({names_str})! Repensar o treino tático de armação ou pedir confirmação urgente aos meias pendentes."
        )
    else:
        insights.append(
            f"✅ ARMAÇÃO ({len(meias)}): {len(meias)} meias/armadores disponíveis para condução tática."
        )

    # 3. Pontas
    if len(pontas) >= 4 or (total_confirmed <= 8 and len(pontas) >= 3):
        insights.append(
            f"⚡ PONTAS ({len(pontas)}): Alto volume de pontas confirmados! Excelente oportunidade para focar em rotinas de finalização de ponta, transição rápida e contra-ataques."
        )
    elif len(pontas) <= 1 and total_confirmed >= 6:
        insights.append(
            f"⚠️ PONTAS ({len(pontas)}): Poucos pontas confirmados. Adaptar trabalhos de ponta ou combinar com meias/pivôs."
        )
    elif len(pontas) > 0:
        insights.append(
            f"✅ PONTAS ({len(pontas)}): {len(pontas)} ponta(s) confirmado(s)."
        )

    # 4. Pivôs
    if len(pivos) == 0 and total_confirmed >= 6:
        insights.append(
            "⚠️ PIVÔS (0): Nenhum pivô confirmado. Adaptar jogadas de bloqueio e 2 vs 2 na linha de 6 metros."
        )
    elif len(pivos) > 0:
        insights.append(
            f"✅ PIVÔS ({len(pivos)}): {len(pivos)} pivô(s) confirmado(s)."
        )

    # 5. Tamanho do Elenco / Planejamento Geral
    if total_confirmed == 0:
        insights.append(
            "ℹ️ ELENCO (0): Nenhum atleta confirmado até o momento. Cobrar confirmações do grupo."
        )
    elif total_confirmed < 8:
        insights.append(
            f"ℹ️ ELENCO REDUZIDO ({total_confirmed} atletas): Recomendado focar em técnica individual, fundamentos, arremessos e físico."
        )
    elif total_confirmed < 12:
        insights.append(
            f"ℹ️ ELENCO INTERMEDIÁRIO ({total_confirmed} atletas): Treino tático setorial ideal (meio-quadra / 4x4 / 5x5)."
        )
    else:
        insights.append(
            f"ℹ️ ELENCO CHEIO ({total_confirmed} atletas): Condição ideal para coletivo 6x6 e simulado de jogo."
        )

    return insights


def build_coach_message(
    training_date: date,
    records: list[dict[str, Any]],
    *,
    is_finalized: bool,
) -> str:
    summary = summarize_records(records)
    status = summary["by_status"]
    confirmed_records = summary["confirmed"]

    goleiros, pontas, meias, pivos, outros = [], [], [], [], []
    for r in confirmed_records:
        cats = classify_position_categories(r.get("position", ""))
        if "Goleiros" in cats:
            goleiros.append(r)
        if "Pontas" in cats:
            pontas.append(r)
        if "Meias / Armadores" in cats:
            meias.append(r)
        if "Pivôs" in cats:
            pivos.append(r)
        if "Outros / Não informada" in cats:
            outros.append(r)

    date_str = (
        training_date.strftime("%d/%m/%Y")
        if isinstance(training_date, date)
        else str(training_date)
    )

    lines = [
        f"📋 RELATÓRIO PRÉ-TREINO — {date_str}",
        "",
        "📊 RESUMO DE CONFIRMAÇÃO",
        f"• Confirmados ({len(confirmed_records)}):",
        f"  - Antecipados (>24h): {_names(status['CONFIRMED_EARLY'])}",
        f"  - Em cima da hora (<24h): {_names(status['CONFIRMED_LATE'])}",
        "",
        f"• Pendentes / Sem resposta ({len(summary['pending'])}):",
        f"  - Pendentes: {_names(status['PENDING'])}",
        f"  - Sem resposta: {_names(status['NO_RESPONSE'])}",
        "",
        f"• Desmarcaram / Ausentes previstos ({len(summary['cancelled'])}):",
        f"  - Antecipados (>24h): {_names(status['CANCELLED_EARLY'])}",
        f"  - Em cima da hora (<24h): {_names(status['CANCELLED_LATE'])}",
        "",
        f"📌 ANÁLISE DE ELENCO CONFIRMADO POR POSIÇÃO ({len(confirmed_records)} atletas)",
        f"• 🧤 Goleiros ({len(goleiros)}): {_names_with_pos(goleiros)}",
        f"• ⚡ Pontas ({len(pontas)}): {_names_with_pos(pontas)}",
        f"• 🎯 Meias / Armadores ({len(meias)}): {_names_with_pos(meias)}",
        f"• 🤾 Pivôs ({len(pivos)}): {_names_with_pos(pivos)}",
    ]
    if outros:
        lines.append(f"• 📋 Outros ({len(outros)}): {_names_with_pos(outros)}")

    lines.extend(
        [
            "",
            "💡 INSIGHTS E RECOMENDAÇÕES PARA O TREINO",
        ]
    )

    insights = build_tactical_insights(
        goleiros, pontas, meias, pivos, len(confirmed_records)
    )
    for ins in insights:
        lines.append(f"• {ins}")

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
