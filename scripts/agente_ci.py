"""Agente de leitura para o CI, falando com o gateway compatível com OpenAI.

Deliberadamente sem dependências além da biblioteca padrão: o job não instala
nada e não há versão de SDK para quebrar. O agente responde em texto; quem
publica o comentário é o workflow, então este script nunca recebe token do
GitHub nem permissão de escrita.

Uso: python scripts/agente_ci.py "<pedido>" > resposta.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Um diff grande estoura contexto e cota sem melhorar a revisão. Cortamos com
# aviso explícito em vez de deixar o provedor truncar em silêncio.
MAX_DIFF_CHARS = 60_000
TIMEOUT_SECONDS = 180


def _run(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


def _diff(base_ref: str) -> str:
    if not base_ref:
        return ""
    _run("git", "fetch", "--no-tags", "--depth", "50", "origin", base_ref)
    diff = _run("git", "diff", f"origin/{base_ref}...HEAD")
    if len(diff) > MAX_DIFF_CHARS:
        return (
            diff[:MAX_DIFF_CHARS]
            + f"\n\n[diff truncado em {MAX_DIFF_CHARS} caracteres]\n"
        )
    return diff


def _rules() -> str:
    rules = REPO_ROOT / "AGENTS.md"
    return rules.read_text(encoding="utf-8") if rules.exists() else ""


def _complete(prompt: str, system: str) -> str:
    base_url = os.environ.get("AGENTE_BASE_URL", "http://127.0.0.1:20128/v1")
    api_key = os.environ.get("AGENTE_API_KEY", "")
    model = os.environ.get("AGENTE_MODEL", "")
    if not model:
        raise SystemExit("AGENTE_MODEL não definido.")

    payload = json.dumps(
        {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Nunca ecoar o corpo do erro: pode conter cabeçalho de autorização.
        raise SystemExit(
            f"O gateway respondeu {error.code}. Verifique provedores e cota."
        ) from None
    except urllib.error.URLError:
        raise SystemExit("Gateway inacessível.") from None

    choices = body.get("choices") or []
    if not choices:
        raise SystemExit("O gateway respondeu sem conteúdo.")
    return str(choices[0].get("message", {}).get("content") or "").strip()


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit("Pedido vazio.")
    pedido = sys.argv[1].strip()

    system = (
        "Você revisa um repositório de handball em português do Brasil. "
        "As regras do projeto são a autoridade final e estão abaixo. "
        "Você é SOMENTE LEITURA: não pode alterar arquivos, e deve recusar "
        "pedidos de DDL, migration ou seed citando a regra 13. "
        "Seja específico e cite caminho e linha. Se não souber, diga que não "
        "sabe em vez de supor.\n\n"
        f"=== REGRAS DO PROJETO (AGENTS.md) ===\n{_rules()}"
    )

    diff = _diff(os.environ.get("AGENTE_BASE_REF", ""))
    partes = [f"Pedido de quem chamou:\n{pedido}\n"]
    if diff:
        partes.append(f"\n=== DIFF EM REVISÃO ===\n{diff}")
    else:
        partes.append(
            "\n(Sem diff: o pedido veio de uma issue, não de um pull request.)"
        )

    print(_complete("\n".join(partes), system))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
