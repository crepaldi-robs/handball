"""Politica deterministica para separar planejamento pago e execucao gratuita.

O Codex envia um objeto JSON por stdin antes de cada ferramenta local. Modelos
gratuitos do OmniRoute podem executar ferramentas, exceto criar novos agentes.
Qualquer outro modelo pode apenas coordenar os perfis free_* aprovados.
"""

from __future__ import annotations

import json
import sys
from typing import Any


FREE_MODELS = frozenset({"auto/coding:free"})
APPROVED_FREE_AGENTS = frozenset(
    {
        "free_explorer",
        "free_peer_coordinator",
        "free_reviewer",
        "free_tester",
        "free_worker",
    }
)

# Ferramentas que nao leem nem alteram o workspace. A lista inclui os nomes
# usados pelas versoes atuais e anteriores do coordenador multiagente.
PAID_COORDINATION_TOOLS = frozenset(
    {
        "followup_task",
        "get_goal",
        "interrupt_agent",
        "list_agents",
        "close_agent",
        "request_user_input",
        "send_message",
        "update_goal",
        "update_plan",
        "wait_agent",
        # Formato namespace+nome emitido pelo Codex TUI atual.
        "collaborationfollowup_task",
        "collaborationget_goal",
        "collaborationinterrupt_agent",
        "collaborationlist_agents",
        "collaborationrequest_user_input",
        "collaborationsend_message",
        "collaborationupdate_goal",
        "collaborationupdate_plan",
        "collaborationwait_agent",
    }
)

AGENT_TOOL_NAMES = frozenset(
    {
        "agent",
        "spawn_agent",
        # O Codex TUI atual envia ferramentas com o namespace concatenado.
        "collaborationagent",
        "collaborationspawn_agent",
    }
)
AGENT_TYPE_KEYS = (
    "agent_type",
    "profile",
    "subagent_type",
    "agent_name",
    "task_name",
    "name",
)
AGENT_MODEL_KEYS = ("model", "model_name")
AGENT_PROVIDER_KEYS = ("model_provider", "provider")


def _deny(reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _requested_agent(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in AGENT_TYPE_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize(value)
    return None


def _explicit_agent_setting(
    tool_input: Any,
    keys: tuple[str, ...],
) -> str | None:
    """Busca overrides diretos ou dentro de um objeto config do spawn."""
    if not isinstance(tool_input, dict):
        return None
    containers = [tool_input]
    nested_config = tool_input.get("config")
    if isinstance(nested_config, dict):
        containers.append(nested_config)
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize(value)
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        _deny(f"Hook recebeu JSON invalido: {exc}")
        return 0

    model = _normalize(event.get("model"))
    tool_name = _normalize(event.get("tool_name"))
    # As ferramentas de equipe aparecem em formatos diferentes conforme a
    # superfície do Codex (TUI, API ou namespace legado):
    # ``collaborationspawn_agent`` e ``multi_agent_v1wait_agent`` são exemplos.
    # Reduza somente esses prefixos conhecidos para aplicar uma única política.
    for prefix in ("multi_agent_v1", "collaboration"):
        if tool_name.startswith(prefix):
            tool_name = tool_name[len(prefix):]
            break
    tool_input = event.get("tool_input")

    if tool_name in AGENT_TOOL_NAMES:
        if model in FREE_MODELS:
            _deny(
                "Executores gratuitos nao podem criar outros agentes. "
                "A coordenacao pertence ao planner principal."
            )
            return 0

        requested = _requested_agent(tool_input)
        if requested in APPROVED_FREE_AGENTS:
            explicit_model = _explicit_agent_setting(tool_input, AGENT_MODEL_KEYS)
            if explicit_model is not None and explicit_model not in FREE_MODELS:
                _deny(
                    "Override de modelo recusado: perfis free_* so podem usar "
                    "auto/coding:free."
                )
                return 0

            explicit_provider = _explicit_agent_setting(
                tool_input,
                AGENT_PROVIDER_KEYS,
            )
            if (
                explicit_provider is not None
                and explicit_provider != "omniroute_project"
            ):
                _deny(
                    "Override de provedor recusado: perfis free_* so podem usar "
                    "omniroute_project."
                )
                return 0
            return 0

        allowed = ", ".join(sorted(APPROVED_FREE_AGENTS))
        _deny(
            "O planner pago so pode criar perfis gratuitos aprovados. "
            f"Recebido: {requested or 'nao identificado'}. Permitidos: {allowed}."
        )
        return 0

    if model in FREE_MODELS:
        return 0

    if tool_name in PAID_COORDINATION_TOOLS:
        return 0

    _deny(
        "Politica do projeto: modelos pagos planejam e coordenam; leitura, "
        "escrita, comandos e testes devem ser delegados a um agente free_* "
        "roteado por auto/coding:free no OmniRoute."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
