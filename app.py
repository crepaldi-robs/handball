from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from attendance import AttendanceRepository
from attendance.models import CONFIRMATION_LABELS, CONFIRMATION_OPTIONS
from attendance.services import (
    build_coach_message,
    editor_dataframe_to_updates,
    history_to_dataframe,
    records_to_editor_dataframe,
    summarize_records,
)

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = Path(
    os.environ.get(
        "ATTENDANCE_DB_PATH",
        ROOT_DIR / "data" / "presencas.db",
    )
)

st.set_page_config(
    page_title="Registro Oficial de Presenças",
    page_icon="✓",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.8rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

repo = AttendanceRepository(DB_PATH)
repo.initialize()

st.title("Registro Oficial de Presenças")
st.caption(
    "Confirmação prévia e presença real são registradas separadamente. "
    "Toda alteração fica gravada no histórico de auditoria."
)

with st.sidebar:
    st.header("Treino")
    selected_date = st.date_input(
        "Data do treino",
        value=date.today() + timedelta(days=1),
        format="DD/MM/YYYY",
    )
    st.caption(f"Banco de dados: `{DB_PATH}`")

session = repo.get_or_create_session(selected_date)
session_id = int(session["id"])
records = repo.get_session_records(session_id)
summary = summarize_records(records)

metrics = st.columns(4)
metrics[0].metric("Confirmados", len(summary["confirmed"]))
metrics[1].metric("Pendentes", len(summary["pending"]))
metrics[2].metric("Desmarcaram", len(summary["cancelled"]))
metrics[3].metric("Presentes marcados", len(summary["present"]))

if session["is_finalized"]:
    st.success("Chamada encerrada: atletas não marcados foram registrados como ausentes.")
else:
    st.info("Chamada aberta: caixas desmarcadas ainda não contam automaticamente como ausência.")

tab_call, tab_summary, tab_history, tab_roster, tab_audit = st.tabs(
    [
        "Chamada",
        "Resumo para o técnico",
        "Histórico",
        "Elenco",
        "Auditoria",
    ]
)

with tab_call:
    editor_df = records_to_editor_dataframe(records)

    edited_df = st.data_editor(
        editor_df,
        hide_index=True,
        use_container_width=True,
        key=f"attendance_editor_{session_id}",
        disabled=["member_id", "Nome", "Posição"],
        column_config={
            "member_id": None,
            "Nome": st.column_config.TextColumn("Nome", width="medium"),
            "Posição": st.column_config.TextColumn("Posição", width="small"),
            "Situação da confirmação": st.column_config.SelectboxColumn(
                "Situação da confirmação",
                options=CONFIRMATION_OPTIONS,
                required=True,
                width="large",
            ),
            "Presente": st.column_config.CheckboxColumn(
                "Presente",
                help="Marque apenas quem efetivamente compareceu ao treino.",
                default=False,
                width="small",
            ),
            "Observação": st.column_config.TextColumn(
                "Observação",
                help="Ex.: lesionado, chegou atrasado, treinou parcialmente.",
                width="large",
            ),
        },
    )

    button_save, button_finalize, button_reopen = st.columns([1, 1, 1])

    with button_save:
        if st.button("Salvar alterações", type="primary", use_container_width=True):
            updates = editor_dataframe_to_updates(edited_df)
            changed = repo.save_records(session_id, updates, source="streamlit")
            st.success(f"Registro salvo. {changed} atleta(s) tiveram alteração.")
            st.rerun()

    with button_finalize:
        if not session["is_finalized"]:
            if st.button(
                "Encerrar chamada",
                use_container_width=True,
                help="Todos os atletas ainda não apurados serão marcados como ausentes.",
            ):
                changed = repo.finalize_session(session_id, source="streamlit-finalize")
                st.success(
                    f"Chamada encerrada. {changed} atleta(s) foram marcados como ausentes."
                )
                st.rerun()

    with button_reopen:
        if session["is_finalized"]:
            if st.button("Reabrir chamada", use_container_width=True):
                repo.reopen_session(session_id)
                st.warning("Chamada reaberta para correções.")
                st.rerun()

    session_notes = st.text_area(
        "Observações gerais do treino",
        value=session["notes"] or "",
        placeholder="Ex.: treino reduzido, quadra alterada, foco técnico específico.",
    )
    if st.button("Salvar observações gerais"):
        repo.update_session_notes(session_id, session_notes)
        st.success("Observações gerais salvas.")

    refreshed_records = repo.get_session_records(session_id)
    current_export = history_to_dataframe(
        [
            {
                "training_date": selected_date.isoformat(),
                "is_finalized": session["is_finalized"],
                "name": item["name"],
                "position": item["position"],
                "confirmation_status": item["confirmation_status"],
                "present": item["present"],
                "notes": item["notes"],
                "updated_at": item["updated_at"],
            }
            for item in refreshed_records
        ]
    )
    st.download_button(
        "Baixar CSV deste treino",
        data=current_export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"presencas_{selected_date.isoformat()}.csv",
        mime="text/csv",
    )

with tab_summary:
    current_session = repo.get_session(session_id)
    current_records = repo.get_session_records(session_id)
    message = build_coach_message(
        selected_date,
        current_records,
        is_finalized=bool(current_session["is_finalized"]),
    )
    st.text_area(
        "Mensagem pronta para copiar",
        value=message,
        height=430,
    )
    st.caption(
        "No celular ou no computador, selecione o texto acima e copie para o grupo ou para o técnico."
    )

with tab_history:
    history = repo.get_history()
    history_df = history_to_dataframe(history)

    if history_df.empty:
        st.info("Ainda não há registros históricos.")
    else:
        available_dates = sorted(
            history_df["Data do treino"].unique().tolist(),
            reverse=True,
        )
        selected_history_dates = st.multiselect(
            "Filtrar datas",
            options=available_dates,
            default=available_dates[:5],
        )
        filtered_df = history_df
        if selected_history_dates:
            filtered_df = history_df[
                history_df["Data do treino"].isin(selected_history_dates)
            ]

        st.dataframe(filtered_df, hide_index=True, use_container_width=True)
        st.download_button(
            "Baixar histórico completo em CSV",
            data=history_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="historico_completo_presencas.csv",
            mime="text/csv",
        )

with tab_roster:
    st.subheader("Elenco cadastrado")
    members = repo.list_members(include_inactive=True)
    members_df = pd.DataFrame(
        [
            {
                "member_id": member["id"],
                "Nome": member["name"],
                "Posição": member["position"],
                "Ativo": bool(member["active"]),
            }
            for member in members
        ]
    )

    edited_members = st.data_editor(
        members_df,
        hide_index=True,
        use_container_width=True,
        key="members_editor",
        disabled=["member_id", "Nome"],
        column_config={
            "member_id": None,
            "Nome": st.column_config.TextColumn("Nome"),
            "Posição": st.column_config.TextColumn("Posição"),
            "Ativo": st.column_config.CheckboxColumn("Ativo"),
        },
    )

    if st.button("Salvar alterações do elenco"):
        for row in edited_members.to_dict(orient="records"):
            repo.update_member(
                int(row["member_id"]),
                position=str(row["Posição"]),
                active=bool(row["Ativo"]),
            )
        st.success("Elenco atualizado.")
        st.rerun()

    with st.form("add_member_form", clear_on_submit=True):
        st.markdown("#### Adicionar atleta")
        new_name = st.text_input("Nome")
        new_position = st.text_input("Posição", placeholder="Ex.: GOL, PD/PE")
        submitted = st.form_submit_button("Adicionar ao elenco")
        if submitted:
            try:
                repo.add_member(new_name, new_position)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(f"{new_name.strip()} adicionado ao elenco.")
                st.rerun()

with tab_audit:
    audit = repo.get_audit_log(limit=1000)
    if not audit:
        st.info("Nenhuma alteração registrada na auditoria.")
    else:
        audit_rows = []
        for item in audit:
            old_status = item["old_confirmation_status"]
            new_status = item["new_confirmation_status"]

            def presence_label(value: int | None) -> str:
                if value == 1:
                    return "Presente"
                if value == 0:
                    return "Ausente"
                return "Não apurado"

            audit_rows.append(
                {
                    "Alterado em": item["changed_at"],
                    "Data do treino": item["training_date"],
                    "Atleta": item["name"],
                    "Posição": item["position"],
                    "Confirmação anterior": (
                        CONFIRMATION_LABELS.get(old_status, "")
                        if old_status
                        else ""
                    ),
                    "Nova confirmação": (
                        CONFIRMATION_LABELS.get(new_status, "")
                        if new_status
                        else ""
                    ),
                    "Presença anterior": presence_label(item["old_present"]),
                    "Nova presença": presence_label(item["new_present"]),
                    "Origem": item["source"],
                }
            )

        audit_df = pd.DataFrame(audit_rows)
        st.dataframe(audit_df, hide_index=True, use_container_width=True)
        st.download_button(
            "Baixar auditoria em CSV",
            data=audit_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="auditoria_presencas.csv",
            mime="text/csv",
        )
