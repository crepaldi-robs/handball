"""Consulta Claude Pro e Antigravity apenas como pareceristas de planejamento.

Os processos rodam em um diretório vazio e ignorado, sem o repositório como
diretório de trabalho. Nenhum deles recebe ferramentas de leitura ou escrita.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class PlannerResult:
    planner: str
    ok: bool
    answer: str
    error: str


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_root() -> Path:
    configured = os.environ.get("HANDBALL_AGENT_RUNTIME")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = Path(os.environ["LOCALAPPDATA"])
    digest = hashlib.sha256(
        str(_project_root()).casefold().encode("utf-8")
    ).hexdigest()[:12]
    return local_app_data / "cpx" / digest


def _first_existing(candidates: Sequence[str | Path]) -> Path | None:
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
    return None


def find_claude() -> Path | None:
    from_path = shutil.which("claude")
    candidates: list[str | Path] = []
    if from_path:
        candidates.append(from_path)
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates.extend(
        glob.glob(
            str(
                local_app_data
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "Anthropic.ClaudeCode_*"
                / "claude.exe"
            )
        )
    )
    return _first_existing(candidates)


def find_antigravity() -> Path | None:
    from_path = shutil.which("agy")
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates: list[str | Path] = []
    if from_path:
        candidates.append(from_path)
    candidates.extend(
        [
            local_app_data / "agy" / "bin" / "agy.exe",
            local_app_data / "Programs" / "antigravity" / "agy.exe",
        ]
    )
    return _first_existing(candidates)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    exact_blocklist = {
        "CODEX_HOME",
        "DATA_DIR",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "STORAGE_ENCRYPTION_KEY",
    }
    secret_markers = (
        "API_KEY",
        "ACCESS_TOKEN",
        "AUTH_TOKEN",
        "OAUTH_TOKEN",
        "SECRET",
        "PASSWORD",
        "CREDENTIAL",
    )
    for key in list(child_env):
        upper = key.upper()
        if (
            upper in exact_blocklist
            or upper.startswith("OMNIROUTE_")
            or any(marker in upper for marker in secret_markers)
        ):
            child_env.pop(key, None)

    return subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        creationflags=CREATE_NO_WINDOW,
        env=child_env,
    )


def _clean(text: str) -> str:
    return ANSI_RE.sub("", text).strip()


def _bounded_prompt(user_prompt: str) -> str:
    prompt = user_prompt.strip()
    if not prompt:
        raise ValueError("A sintese de planejamento esta vazia.")
    if len(prompt) > 30_000:
        raise ValueError("A sintese excede 30.000 caracteres.")
    return f"""\
Você é um parecerista técnico de planejamento. Não tem acesso ao repositório,
não deve executar ferramentas e não deve propor que credenciais sejam copiadas.
Avalie a síntese abaixo quanto a correção, riscos, lacunas, sequência de
implementação e testes. Responda em português do Brasil, com recomendações
concretas e concisas.

SÍNTESE:
{prompt}
"""


def consult_claude(prompt: str, cwd: Path, timeout_seconds: int) -> PlannerResult:
    executable = find_claude()
    if executable is None:
        return PlannerResult("claude", False, "", "Claude Code não encontrado.")
    command = [
        str(executable),
        "-p",
        prompt,
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--safe-mode",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    try:
        completed = _run(command, cwd=cwd, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        return PlannerResult("claude", False, "", "Tempo limite excedido.")

    if completed.returncode != 0:
        error = _clean(completed.stderr or completed.stdout)
        return PlannerResult("claude", False, "", error or "Falha sem mensagem.")

    raw = _clean(completed.stdout)
    try:
        payload = json.loads(raw)
        answer = str(payload.get("result") or payload.get("response") or "").strip()
    except json.JSONDecodeError:
        answer = raw
    if not answer:
        return PlannerResult("claude", False, "", "Resposta vazia.")
    return PlannerResult("claude", True, answer, "")


def consult_antigravity(
    prompt: str, cwd: Path, timeout_seconds: int
) -> PlannerResult:
    executable = find_antigravity()
    if executable is None:
        return PlannerResult(
            "antigravity", False, "", "Antigravity CLI (agy) não encontrado."
        )
    command = [
        str(executable),
        "--mode",
        "plan",
        "--sandbox",
        "--print-timeout",
        f"{timeout_seconds}s",
        "-p",
        prompt,
    ]
    try:
        completed = _run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds + 10,
        )
    except subprocess.TimeoutExpired:
        return PlannerResult("antigravity", False, "", "Tempo limite excedido.")

    answer = _clean(completed.stdout)
    if completed.returncode != 0:
        error = _clean(completed.stderr or completed.stdout)
        return PlannerResult(
            "antigravity", False, "", error or "Falha sem mensagem."
        )
    if not answer:
        return PlannerResult("antigravity", False, "", "Resposta vazia.")
    return PlannerResult("antigravity", True, answer, "")


def check_installations(cwd: Path) -> list[PlannerResult]:
    results: list[PlannerResult] = []

    claude = find_claude()
    if claude is None:
        results.append(PlannerResult("claude", False, "", "Executável ausente."))
    else:
        completed = _run(
            [str(claude), "auth", "status", "--json"],
            cwd=cwd,
            timeout_seconds=20,
        )
        ok = completed.returncode == 0
        detail = _clean(completed.stdout if ok else completed.stderr)
        if ok:
            try:
                auth = json.loads(detail)
                detail = json.dumps(
                    {
                        "loggedIn": bool(auth.get("loggedIn")),
                        "authMethod": auth.get("authMethod"),
                        "apiProvider": auth.get("apiProvider"),
                        "subscriptionType": auth.get("subscriptionType"),
                    },
                    ensure_ascii=False,
                )
            except json.JSONDecodeError:
                detail = "Claude autenticado; formato de status não reconhecido."
        results.append(PlannerResult("claude", ok, detail if ok else "", detail if not ok else ""))

    antigravity = find_antigravity()
    if antigravity is None:
        results.append(
            PlannerResult("antigravity", False, "", "Executável agy ausente.")
        )
    else:
        completed = _run(
            [str(antigravity), "--version"],
            cwd=cwd,
            timeout_seconds=20,
        )
        ok = completed.returncode == 0
        detail = _clean(completed.stdout if ok else completed.stderr)
        results.append(
            PlannerResult(
                "antigravity",
                ok,
                detail if ok else "",
                detail if not ok else "",
            )
        )

    return results


def _print_markdown(results: Sequence[PlannerResult]) -> None:
    for result in results:
        print(f"## {result.planner}")
        print()
        if result.ok:
            print(result.answer)
        else:
            print(f"FALHA: {result.error}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--planejador",
        choices=("todos", "claude", "antigravity"),
        default="todos",
    )
    parser.add_argument("--prompt")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--formato", choices=("markdown", "json"), default="json")
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sandbox = _runtime_root() / "planner-sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    if args.check:
        results = check_installations(sandbox)
    else:
        raw_prompt = args.prompt if args.prompt is not None else sys.stdin.read()
        try:
            prompt = _bounded_prompt(raw_prompt)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        results = []
        if args.planejador in {"todos", "claude"}:
            results.append(consult_claude(prompt, sandbox, args.timeout))
        if args.planejador in {"todos", "antigravity"}:
            results.append(consult_antigravity(prompt, sandbox, args.timeout))

    if args.formato == "json":
        print(
            json.dumps(
                [asdict(result) for result in results],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_markdown(results)

    return 0 if results and all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
