from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
GUARD_SCRIPT = PROJECT_ROOT / "handball" / "database" / "guard.py"
BACKUP_SCRIPT = SCRIPTS_ROOT / "backup-server.ps1"
RESET_SCRIPT = SCRIPTS_ROOT / "reset-password.ps1"
MIGRATION_SCRIPT = SCRIPTS_ROOT / "migrate-database.ps1"
POWERSHELL_SCRIPTS = (BACKUP_SCRIPT, RESET_SCRIPT, MIGRATION_SCRIPT)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _main_lock_precedes_release_and_config(script: str) -> None:
    lock = script.index("$LockStream = Enter-MaintenanceLock")
    release = script.index("$Release = Resolve-ActiveRelease", lock)
    config = script.index("$ConfigPath =", release)
    assert lock < release < config


def test_guard_cli_exposes_explicit_path_binding_and_fingerprint_format():
    script = _read(GUARD_SCRIPT)

    assert script.count('add_argument("--expected-database-path")') == 3
    assert 'backup_parser.add_argument("--expected-backup-root")' in script
    assert 'FINGERPRINT_FORMAT = "crepaldi-handball-logical-sqlite/v1"' in script
    assert '"fingerprint_format": FINGERPRINT_FORMAT' in script
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in script
    assert 'getattr(path, "is_junction", None)' in script
    assert '"database_path_mismatch"' in script
    assert '"backup_destination_outside_root"' in script


def test_every_operational_guard_call_is_isolated_from_site_packages():
    backup = _read(BACKUP_SCRIPT)
    reset = _read(RESET_SCRIPT)
    migration = _read(MIGRATION_SCRIPT)

    for script in (backup, reset, migration):
        assert "& $Runtime.PythonPath -I -S $Runtime.GuardPath @Arguments 2>&1" in script
        assert "& $Runtime.PythonPath $Runtime.GuardPath @Arguments 2>&1" not in script

    # As CLIs da aplicação continuam usando o ambiente do release.
    assert "& $Release.PythonPath -m handball.cli reset-password `" in reset
    assert "$output = @(& $Python -m handball.cli $Command @Arguments 2>&1)" in migration


def test_backup_is_lock_first_release_only_and_path_bound():
    script = _read(BACKUP_SCRIPT)
    _main_lock_precedes_release_and_config(script)

    assert '$Release.Kind -cne "release"' in script
    assert "-AllowBackupPointer" not in script
    assert '"--expected-database-path", $DbPath' in script
    assert '"--expected-backup-root", $BackupRoot' in script
    assert script.index("$LockStream = Enter-MaintenanceLock") < script.index(
        '"--expected-database-path", $DbPath'
    )
    assert "guard_python_path" in script
    assert "guard_python_sha256" in script
    assert "Database guard diverge do manifesto operacional" in script


def test_backup_publishes_durable_audit_sidecar_before_paired_retention():
    script = _read(BACKUP_SCRIPT)

    for field in (
        'format = "crepaldi-handball-backup-audit/v1"',
        "guard_format =",
        "fingerprint_format =",
        "created_at_utc =",
        "release_id =",
        "database_file =",
        "logical_fingerprint =",
        "bytes =",
        "sha256 =",
        "quick_check =",
    ):
        assert field in script
    assert "function Write-DurableUtf8File" in script
    assert "$stream.Flush($true)" in script
    assert "[IO.File]::Move($auditTemporaryPath, $auditPath, $false)" in script

    sidecar_publish = script.index(
        "[IO.File]::Move($auditTemporaryPath, $auditPath, $false)"
    )
    retention = script.index("$expiredBackups = @(", sidecar_publish)
    assert sidecar_publish < retention
    assert "Get-BackupAuditPath -DatabasePath $oldBackup.FullName" in script
    assert '-Label "Sidecar do backup expirado"' in script
    assert "Remove-Item -LiteralPath $expiredPair.Database -Force" in script
    assert "Remove-Item -LiteralPath $expiredPair.Audit -Force" in script


def test_reset_is_release_only_path_bound_and_proves_database_nonmutation():
    script = _read(RESET_SCRIPT)
    _main_lock_precedes_release_and_config(script)

    assert '$Release.Kind -cne "release"' in script
    assert "release legado pode executar startup mutante" in script
    assert "-AllowBackupPointer" not in script
    assert "Assert-PersistentConfiguration `" in script
    assert '"--expected-database-path", $ExpectedDbPath' in script
    assert "$FingerprintAfterReset -cne $FingerprintBefore" in script
    assert "$FingerprintAfterStartup -cne $FingerprintBefore" in script
    assert "New-OwnedMaintenanceMarker `" in script
    assert "Remove-OwnedMaintenanceMarker `" in script
    assert '-Operation "PASSWORD_RESET"' in script
    assert "-Token $MaintenanceToken" in script
    assert 'Uri "http://127.0.0.1:8765/health"' not in script


def test_reset_stop_start_state_is_fail_closed_on_readiness_failure():
    script = _read(RESET_SCRIPT)

    main_stop = re.search(r"\$StopAttempted = \$true\s+Stop-HandballServer", script)
    assert main_stop is not None
    main_start = re.search(
        r"\$StartAttempted = \$true\s+"
        r'Start-ScheduledTask -TaskName "CrepaldiHandball"\s+'
        r"Wait-ExpectedReadiness",
        script,
    )
    assert main_start is not None
    assert "$StopAttempted -or $StartAttempted" in script
    catch_start = script.index("catch {", script.index("$StartAttempted = $true"))
    assert script.index("Stop-HandballServer", catch_start) > catch_start
    assert "serviço confirmado como parado" in script


def test_migration_is_lock_first_explicit_backup_gated_and_fail_closed():
    script = _read(MIGRATION_SCRIPT)
    _main_lock_precedes_release_and_config(script)

    assert "$maximumAttempts = 900" in script
    assert '$Release.Kind -cne "release"' in script
    assert "[switch]$Apply" in script
    assert '"database-plan"' in script
    assert '"database-migrate"' in script
    assert '"--expected-fingerprint"' in script
    assert '"--backup-path", $CliBackupPath' in script
    assert '"--destination", $GuardBackupPath' in script
    assert "$WriteGateEntered = $true" in script
    assert "Nenhum restore automático foi feito" in script
    assert 'Start-ScheduledTask -TaskName "CrepaldiHandball"' in script
    assert "Wait-ExpectedReadiness -ExpectedReleaseId $ReleaseId" in script
    assert "Startup alterou o banco recém-migrado" in script
    assert "modo de manutenção já está ativo" in script
    assert script.count('"--expected-database-path", $DbPath') >= 4
    assert "Restart-ScheduledTask" not in script


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 indisponível")
def test_hardened_operational_scripts_have_no_parser_errors():
    pwsh = shutil.which("pwsh")
    assert pwsh is not None

    for path in POWERSHELL_SCRIPTS:
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
