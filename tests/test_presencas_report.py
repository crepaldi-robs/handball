from datetime import date
from handball.modules.presencas.domain import (
    build_coach_message,
    classify_position_categories,
    build_tactical_insights,
)


def test_classify_position_categories():
    assert classify_position_categories("GOL") == ["Goleiros"]
    assert classify_position_categories("PE/PV") == ["Pontas", "Pivôs"]
    assert classify_position_categories("ME/C") == ["Meias / Armadores"]
    assert classify_position_categories("PD") == ["Pontas"]
    assert classify_position_categories("Ponta Esquerda") == ["Pontas"]
    assert classify_position_categories("Armador Central") == ["Meias / Armadores"]
    assert classify_position_categories("Goleiro Convidado") == ["Goleiros"]
    assert classify_position_categories("") == ["Outros / Não informada"]


def test_build_coach_message_report():
    records = [
        # Goleiro
        {"member_id": 1, "name": "Gabigol", "position": "GOL", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        # Pontas
        {"member_id": 2, "name": "Arthur", "position": "PD", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        {"member_id": 3, "name": "Rafa Pod", "position": "PE", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        {"member_id": 4, "name": "BDX", "position": "PD/PE", "confirmation_status": "CONFIRMED_LATE", "present": 0},
        {"member_id": 5, "name": "Sotelo", "position": "PE", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        # Meias
        {"member_id": 6, "name": "João Alma", "position": "ME", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        # Pivôs
        {"member_id": 7, "name": "Fumis", "position": "PV", "confirmation_status": "CONFIRMED_EARLY", "present": 0},
        # Pendente
        {"member_id": 8, "name": "Gabixo", "position": "ME/C", "confirmation_status": "PENDING", "present": 0},
        # Ausente
        {"member_id": 9, "name": "Pedrinho", "position": "PD", "confirmation_status": "CANCELLED_EARLY", "present": 0},
    ]

    msg = build_coach_message(
        date(2026, 7, 26),
        records,
        is_finalized=False,
    )

    assert "📋 RELATÓRIO PRÉ-TREINO — 26/07/2026" in msg
    assert "📊 RESUMO DE CONFIRMAÇÃO" in msg
    assert "Confirmados (7)" in msg
    assert "Pendentes / Sem resposta (1)" in msg
    assert "Desmarcaram / Ausentes previstos (1)" in msg
    assert "📌 ANÁLISE DE ELENCO CONFIRMADO POR POSIÇÃO (7 atletas)" in msg
    assert "🧤 Goleiros (1): Gabigol (GOL)" in msg
    assert "⚡ Pontas (4): Arthur (PD), Rafa Pod (PE), BDX (PD/PE), Sotelo (PE)" in msg
    assert "🎯 Meias / Armadores (1): João Alma (ME)" in msg
    assert "🤾 Pivôs (1): Fumis (PV)" in msg
    assert "💡 INSIGHTS E RECOMENDAÇÕES PARA O TREINO" in msg
    assert "Apenas 1 goleiro confirmado" in msg
    assert "Apenas 1 meia/armador confirmado" in msg
    assert "Alto volume de pontas confirmados" in msg
