from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
RUN_SCRIPT = SCRIPTS_ROOT / "run-server.ps1"
SETUP_SCRIPT = SCRIPTS_ROOT / "setup.ps1"
BACKUP_SCRIPT = SCRIPTS_ROOT / "backup-server.ps1"
RESET_SCRIPT = SCRIPTS_ROOT / "reset-password.ps1"
MIGRATION_SCRIPT = SCRIPTS_ROOT / "migrate-database.ps1"
MAINTENANCE_SCRIPTS = (
    RUN_SCRIPT,
    BACKUP_SCRIPT,
    RESET_SCRIPT,
    MIGRATION_SCRIPT,
)


def read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def main_after_lock(script: str) -> str:
    marker = "$LockStream = Enter-MaintenanceLock"
    assert marker in script
    return script[script.index(marker) :]


def test_application_cli_namespace_is_centralized_in_handball():
    scripts = {
        path.name: read_script(path)
        for path in SCRIPTS_ROOT.glob("*.ps1")
    }

    for name, script in scripts.items():
        assert "attendance.cli" not in script, name
    assert "-m handball.cli init `" in scripts[SETUP_SCRIPT.name]
    assert "-m handball.cli init-database `" in scripts[SETUP_SCRIPT.name]


def test_backup_reset_and_migration_resolve_state_only_after_lock():
    for path in (BACKUP_SCRIPT, RESET_SCRIPT, MIGRATION_SCRIPT):
        script = read_script(path)
        main = main_after_lock(script)
        lock_index = main.index("$LockStream = Enter-MaintenanceLock")
        root_index = main.index("$ResolvedInstallRoot = Resolve-ExactInstallRoot")
        release_index = main.index("$Release = Resolve-ActiveRelease")

        assert lock_index < root_index < release_index, path.name
        assert '".maintenance.lock"' in script, path.name
        assert "[IO.FileShare]::None" in script, path.name
        assert "-AllowBackupPointer" not in main, path.name


def test_run_server_fails_closed_and_uses_only_fixed_environment():
    script = read_script(RUN_SCRIPT)

    assert "-AllowBackupPointer" not in script
    assert '$Release.Kind -cne "release"' in script
    assert "Assert-PersistentConfiguration" in script
    assert '"data\\presencas.db"' in script
    assert '"data\\app-config.json"' in script
    assert '"backups"' in script
    assert "ATTENDANCE_DB_PATH" not in script
    assert "ATTENDANCE_BACKUP_DIR" not in script

    clear_index = script.index('Where-Object { $_.Name -like "ATTENDANCE_*" }')
    config_index = script.index("$env:ATTENDANCE_CONFIG_PATH = $ConfigPath")
    release_index = script.index("$env:ATTENDANCE_RELEASE_ID = $Release.ReleaseId")
    marker_index = script.index("$env:ATTENDANCE_MAINTENANCE_FILE = $MaintenanceFile")
    bytecode_index = script.index('$env:PYTHONDONTWRITEBYTECODE = "1"')
    launch_index = script.index("& $Release.PythonPath -m uvicorn")
    assert clear_index < config_index < launch_index
    assert clear_index < release_index < launch_index
    assert clear_index < marker_index < launch_index
    assert clear_index < bytecode_index < launch_index
    assert "Assert-ReleasePointerUnchanged" in script
    assert script.rindex("Assert-ReleasePointerUnchanged") < launch_index


def test_guard_runtime_is_manifest_authenticated_and_python_is_isolated():
    for path in (BACKUP_SCRIPT, RESET_SCRIPT, MIGRATION_SCRIPT):
        script = read_script(path)
        assert '$opsRoot = Join-Path $Root "ops"' in script, path.name
        assert 'Join-Path $opsRoot "ops-manifest.json"' in script, path.name
        assert 'Join-Path $opsRoot "database-guard.py"' in script, path.name
        assert "[int]$manifest.format -ne 1" in script, path.name
        assert "[int]$manifest.protocol -ne 1" in script, path.name
        assert '"ops/database-guard.py"' in script, path.name
        assert "guard_python_path" in script, path.name
        assert "guard_python_sha256" in script, path.name
        assert "[IO.Path]::IsPathFullyQualified($pythonValue)" in script, path.name
        assert "Get-FileHash -LiteralPath $guardPath" in script, path.name
        assert "Get-FileHash -LiteralPath $pythonPath" in script, path.name
        assert "$Runtime.PythonPath -I -S $Runtime.GuardPath" in script, path.name


def test_backup_uses_only_guard_and_validates_published_regular_file():
    script = read_script(BACKUP_SCRIPT)

    assert "attendance.cli" not in script
    assert '"backup",' in script
    assert '"--expected-backup-root", $BackupRoot' in script
    assert "Assert-BackupArtifact -Path $destination" in script
    assert "$item.Attributes -band [IO.FileAttributes]::ReparsePoint" in script
    assert "$item.Length -ne [long]$Result.backup_bytes" in script
    assert "Get-FileHash -LiteralPath $Path -Algorithm SHA256" in script
    assert 'foreach ($suffix in @("-journal", "-wal", "-shm"))' in script
    assert "guard_sha256" in script
    assert "guard_python_sha256" in script


def test_reset_marker_has_owner_and_failure_keeps_service_closed():
    script = read_script(RESET_SCRIPT)

    assert "$maximumAttempts = 900" in script
    assert "[IO.FileMode]::CreateNew" in script
    assert '-Operation "PASSWORD_RESET"' in script
    assert "owner_token = $Token" in script
    assert "Read-OwnedMaintenanceMarker" in script
    assert "Remove-OwnedMaintenanceMarker" in script
    assert "[IO.File]::Move($Path, $retiredPath, $false)" in script
    assert "Set-Content" not in script
    assert 'Stop-ScheduledTask -TaskName "CrepaldiHandball"' in script
    assert 'Start-ScheduledTask -TaskName "CrepaldiHandball"' in script
    assert "Wait-ExpectedReadiness" in script
    assert "Assert-ReleasePointerUnchanged" in script
    assert '"manutenção preservado.' in script
    assert "Nenhum restore do banco foi executado" in script

    start_index = script.index('Start-ScheduledTask -TaskName "CrepaldiHandball"')
    pointer_index = script.rfind("Assert-ReleasePointerUnchanged", 0, start_index)
    assert pointer_index >= 0


def test_reset_and_migration_allowlist_the_scheduled_task_actions():
    reset = read_script(RESET_SCRIPT)
    migration = read_script(MIGRATION_SCRIPT)

    assert "function Assert-ServerTaskAction" in reset
    assert "não está na allowlist operacional" in reset
    assert '"app\\scripts\\run-server.ps1"' in reset

    assert "function Assert-ScheduledTaskAction" in migration
    assert "não está na allowlist operacional" in migration
    assert '[ValidateSet("run-server.ps1", "backup-server.ps1")]' in migration
    assert '-TaskName "CrepaldiHandball"' in migration
    assert '-TaskName "CrepaldiHandballBackup"' in migration


def test_migration_has_explicit_plan_action_allowlists():
    script = read_script(MIGRATION_SCRIPT)

    for action in (
        "none",
        "adopt-baseline",
        "migrate",
        "blocked",
        "bootstrap-required",
    ):
        assert f'"{action}"' in script
    assert '$WritableActions = @("adopt-baseline", "migrate")' in script
    assert "$PlanningActions -cnotcontains $action" in script
    assert "$WritableActions -cnotcontains $action" in script
    assert "action fora da allowlist" in script


def test_migration_uses_guard_for_baseline_backup_and_recovery():
    script = read_script(MIGRATION_SCRIPT)

    assert '"verify",' in script
    assert '"fingerprint",' in script
    assert '"backup",' in script
    assert '"--expected-fingerprint", $StoppedFingerprint' in script
    assert "Assert-BackupArtifact" in script
    assert "Assert-CliBackupArtifact" in script
    assert "migration-guard-v$fromVersion-to-v$toVersion" in script
    assert "migration-cli-v$fromVersion-to-v$toVersion" in script
    assert "Get-GuardFingerprint" in script[script.index("catch {") :]
    assert "Nenhum restore automático foi feito" in script
    assert "handball.cli restore" not in script
    assert "Copy-Item" not in script

    guard_backup = script.index("$guardBackupResult = Invoke-GuardJson")
    write_gate = script.index("$WriteGateEntered = $true")
    cli_apply = script.index('-Command "database-migrate"', write_gate)
    assert guard_backup < write_gate < cli_apply


def test_migration_cli_is_restricted_to_plan_and_apply_commands():
    script = read_script(MIGRATION_SCRIPT)

    assert '[ValidateSet("database-plan", "database-migrate")]' in script
    assert '-Command "database-plan"' in script
    assert '-Command "database-migrate"' in script
    assert '"--backup-path", $CliBackupPath' in script
    assert "--expected-plan-sha256" in script
    assert "--expected-fingerprint" in script
    assert "init-database" not in script
    assert "fingerprint-database" not in script
    assert "verify-database" not in script


def test_migration_marker_schema_and_pointer_gate_restart():
    script = read_script(MIGRATION_SCRIPT)

    assert "[IO.FileMode]::CreateNew" in script
    assert 'operation = "DB_MIGRATION"' in script
    assert "owner_token = $Token" in script
    assert "Set-Content" not in script
    assert "SchemaMinimum" in script
    assert "SchemaMaximum" in script
    assert "Assert-ReleaseSupportsSchema" in script

    main_start = script.index('Start-ScheduledTask -TaskName "CrepaldiHandball"')
    pointer_check = script.rfind("Assert-ReleasePointerUnchanged", 0, main_start)
    marker_check = script.rfind("Read-OwnedMaintenanceMarker", 0, main_start)
    assert pointer_check >= 0
    assert marker_check >= 0
    assert pointer_check < main_start
    assert marker_check < main_start


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 indisponível")
def test_maintenance_scripts_have_no_powershell_parser_errors():
    pwsh = shutil.which("pwsh")
    assert pwsh is not None

    for path in MAINTENANCE_SCRIPTS:
        escaped_path = str(path).replace("'", "''")
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
            f"{path.name}: {completed.stdout}\n{completed.stderr}"
        )
