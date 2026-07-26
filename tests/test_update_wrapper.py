from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = PROJECT_ROOT / "atualizar-aplicativo.ps1"


def read_wrapper() -> str:
    return WRAPPER.read_text(encoding="utf-8", errors="strict")


def test_wrapper_defaults_to_app_only_and_exposes_only_explicit_modes():
    script = read_wrapper()

    assert '[ValidateSet("APP_ONLY", "DB_MIGRATION")]' in script
    assert '[string]$Modo = "APP_ONLY"' in script
    assert "Assert-Administrator" in script
    assert "Assert-PowerShell7" in script


def test_wrapper_validates_before_updating_and_updates_before_migrating():
    script = read_wrapper()

    validation = script.index("Invoke-ProjectValidation `")
    update = script.index("& $UpdateScript -InstallRoot $InstallRoot")
    plan = script.index("$plan = Get-DatabaseMigrationPlan `")
    apply = script.index("& $MigrationScript `", plan)

    assert validation < update < plan < apply
    assert "& $TestScript" in script
    assert "-m compileall -q app.py attendance handball tests" in script
    assert '@("diff", "--check")' in script
    assert '@("diff", "--cached", "--check")' in script


def test_wrapper_preserves_database_flow_contracts():
    script = read_wrapper()

    assert "-ExpectedPlanSha256 $planSha256" in script
    assert "$planSha256 -notmatch '^[0-9a-f]{64}$'" in script
    assert '"adopt-baseline", "migrate"' in script
    assert "Nenhuma escrita de migração foi iniciada." in script

    forbidden = (
        "sqlite3",
        "init-database",
        "Copy-Item",
        "Move-Item",
        "Remove-Item",
        "git commit",
        "git reset",
        "git clean",
    )
    for item in forbidden:
        assert item not in script


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 indisponível")
def test_wrapper_has_no_powershell_parser_errors():
    pwsh = shutil.which("pwsh")
    assert pwsh is not None

    escaped_path = str(WRAPPER).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, (
        f"{WRAPPER.name}: {completed.stdout}\n{completed.stderr}"
    )
