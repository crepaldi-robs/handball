from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"

INSTALL_SCRIPT = SCRIPTS_ROOT / "install-server.ps1"
UPDATE_SCRIPT = SCRIPTS_ROOT / "update-server.ps1"
RESOLVER_SCRIPT = SCRIPTS_ROOT / "release-resolver.ps1"
RUN_SCRIPT = SCRIPTS_ROOT / "run-server.ps1"

POINTER_ARCHITECTURE_SCRIPTS = (
    INSTALL_SCRIPT,
    UPDATE_SCRIPT,
    RESOLVER_SCRIPT,
    RUN_SCRIPT,
)

EXPECTED_RUNTIME_ITEMS = {
    "app.py",
    "requirements.txt",
    "attendance",
    "templates",
    "static",
}

EXPECTED_OPERATIONAL_MAPPINGS = {
    "scripts/run-server.ps1": "app/scripts/run-server.ps1",
    "scripts/backup-server.ps1": "app/scripts/backup-server.ps1",
    "scripts/reset-password.ps1": "app/scripts/reset-password.ps1",
    "scripts/update-server.ps1": "app/scripts/update-server.ps1",
    "scripts/migrate-database.ps1": "app/scripts/migrate-database.ps1",
    "scripts/release-resolver.ps1": "app/scripts/release-resolver.ps1",
    "scripts/database-guard.py": "ops/database-guard.py",
}


def read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_string_array(script: str, variable: str) -> set[str]:
    match = re.search(
        rf"\${re.escape(variable)}\s*=\s*@\((?P<body>.*?)\)",
        script,
        flags=re.DOTALL,
    )
    assert match is not None, f"A lista ${variable} não foi encontrada."
    return {
        item.replace("\\", "/")
        for item in re.findall(r'"([^"]+)"', match["body"])
    }


def extract_mapping(script: str, variable: str) -> dict[str, str]:
    match = re.search(
        rf"\${re.escape(variable)}\s*=\s*\[ordered\]@\{{(?P<body>.*?)\n\}}",
        script,
        flags=re.DOTALL,
    )
    assert match is not None, f"O mapa ${variable} não foi encontrado."
    return {
        source.replace("\\", "/"): destination.replace("\\", "/")
        for source, destination in re.findall(
            r'^\s*"([^"]+)"\s*=\s*"([^"]+)"\s*$',
            match["body"],
            flags=re.MULTILINE,
        )
    }


def test_installer_and_updater_separate_runtime_releases_from_stable_ops():
    installer = read_script(INSTALL_SCRIPT)
    updater = read_script(UPDATE_SCRIPT)

    for script in (installer, updater):
        assert extract_string_array(script, "RuntimeItems") == EXPECTED_RUNTIME_ITEMS
        assert (
            extract_mapping(script, "OperationalMappings")
            == EXPECTED_OPERATIONAL_MAPPINGS
        )

    for item in EXPECTED_RUNTIME_ITEMS | set(EXPECTED_OPERATIONAL_MAPPINGS):
        parts = item.lower().split("/")
        assert parts[0] not in {"data", "backups", "logs", "state"}
        assert parts[-1] not in {
            "app-config.json",
            "presencas.db",
            "release-manifest.json",
            "active-release.json",
        }


def test_payload_is_git_tracked_clean_and_bound_to_one_commit():
    installer = read_script(INSTALL_SCRIPT)
    updater = read_script(UPDATE_SCRIPT)

    for script in (installer, updater):
        assert "git -C $ProjectRoot status --porcelain=v1 --untracked-files=all" in script
        assert "git -C $ProjectRoot ls-tree -r --name-only" in script
        assert "git -C $ProjectRoot archive `" in script
        assert "--format=zip" in script
        assert "rev-parse --verify HEAD" in script
        assert "alterações não commitadas" in script
        assert "[Parameter(Mandatory)][string]$SourceCommit" in script

    assert updater.count("Assert-CleanTrackedSources -ProjectRoot") >= 2
    assert "$SourceCommitAfterCopy -cne $SourceCommitBefore" in updater
    assert "allowedLocalExceptions" not in updater


def test_initial_install_is_bootstrap_only_and_creates_first_pointer():
    script = read_script(INSTALL_SCRIPT)

    assert "$maximumAttempts = 900" in script
    assert "Instalação existente detectada" in script
    assert "o bootstrap não sobrescreve estado persistente" in script
    assert "-m attendance.cli init `" in script
    assert "-m attendance.cli init-database --config-path $ConfigPath" in script
    assert 'Join-Path $ReleasesRoot $ReleaseId' in script
    assert 'Join-Path $ReleaseRoot ".venv\\Scripts\\python.exe"' in script
    assert "payload_sha256 = $payloadHash" in script
    assert "payload_files = $PayloadFiles" in script
    assert 'environment_manifest = "environment-files.json"' in script
    assert "environment_manifest_sha256 = $EnvironmentEvidence.ManifestSha256" in script
    assert "environment_sha256 = $EnvironmentEvidence.EnvironmentSha256" in script
    assert "Get-ReleaseSchemaCompatibility `" in script
    assert "-m attendance.cli release-contract" in script
    assert 'install_kind = "initial"' in script
    assert "database_action = \"bootstrap\"" in script
    assert "[IO.Directory]::Move($ReleaseRoot, $FinalReleaseRoot)" in script
    assert "Set-ActiveReleasePointer `" in script
    assert 'application_relative_path = "releases/$ReleaseId"' in script
    assert 'python_relative_path = "releases/$ReleaseId/.venv/Scripts/python.exe"' in script
    assert "database_fingerprint_after_bootstrap = $InitialFingerprint" in script
    assert '$env:PYTHONDONTWRITEBYTECODE = "1"' in script
    assert script.count("Remove-ApplicationBuildCaches -ReleaseRoot $ReleaseRoot") >= 2
    final_cache_cleanup = script.rindex(
        "Remove-ApplicationBuildCaches -ReleaseRoot $ReleaseRoot"
    )
    payload_inventory = script.index(
        "[string[]]$SortedSourceFiles = @($SourceFiles)",
        final_cache_cleanup,
    )
    assert final_cache_cleanup < payload_inventory


def test_app_only_uses_guard_and_never_bootstraps_migrates_or_moves_data():
    script = read_script(UPDATE_SCRIPT)

    assert "foreach ($requiredFile in @($ConfigPath, $DbPath))" in script
    assert "Update recusado; arquivo persistente obrigatório ausente" in script
    assert "Assert-PersistentConfiguration `" in script
    assert 'Guard = Join-Path $InstallRoot "ops\\database-guard.py"' in script
    assert '"verify", "--config-path", $ConfigPath' in script
    assert '"fingerprint", "--config-path", $ConfigPath' in script
    assert '"--expected-fingerprint", $StoppedFingerprint' in script
    assert "database_action = \"none\"" in script
    assert 'Join-Path $StateRoot "preflight"' in script
    assert "-Port 18765" in script
    assert "$candidateCopyFingerprint -cne" in script
    assert "[string]$preflightBackup.logical_fingerprint" in script
    assert "Assert-ConfigurationUnchanged `" in script
    assert "$ConfigSha256Before" in script

    forbidden_calls = (
        "init-database",
        "database-migrate",
        "database-plan",
        "repository.initialize",
    )
    for forbidden in forbidden_calls:
        assert forbidden not in script

    for persistent_variable in (
        "$DataRoot",
        "$ConfigPath",
        "$DbPath",
        "$BackupRoot",
        "$LogRoot",
    ):
        assert not re.search(
            rf"(?:Move-Item|Copy-Item|Remove-Item)[^\n]*{re.escape(persistent_variable)}",
            script,
        )


def test_updater_publishes_immutable_release_and_switches_only_the_pointer():
    script = read_script(UPDATE_SCRIPT)

    assert '$StagePath = Join-Path $ReleasesRoot (' in script
    assert '".stage-$ReleaseId-$([guid]::NewGuid().ToString(\'N\'))"' in script
    assert 'Join-Path $StagePath ".venv\\Scripts\\python.exe"' in script
    assert "-m pip check" in script
    assert "-m compileall -q app.py attendance" in script
    assert "[IO.Directory]::Move($StagePath, $FinalReleaseRoot)" in script
    assert "Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256" in script
    assert "Set-ActiveReleasePointer `" in script
    assert "-ExpectedGeneration ([int64]$PreviousRelease.Generation)" in script
    assert "$PointerSwitched = $true" in script

    assert "Move-Item -LiteralPath $AppRoot" not in script
    assert "-Destination $AppRoot" not in script
    assert "previous-$" not in script
    assert "failed-$" not in script

    publish = script.index("[IO.Directory]::Move($StagePath, $FinalReleaseRoot)")
    pointer = script.index("[void](Set-ActiveReleasePointer `", publish)
    start = script.index('Start-ScheduledTask -TaskName "CrepaldiHandball"', pointer)
    assert publish < pointer < start


def test_stable_ops_are_verified_and_only_bootstrapped_for_legacy_layout():
    script = read_script(UPDATE_SCRIPT)

    assert "function Assert-SafeReleaseId" not in script
    assert "[void](Assert-SafeReleaseId -ReleaseId $ReleaseId)" in script
    assert "function Install-OperationalBridge" in script
    assert "function Get-VerifiedOperationalRuntime" in script
    assert 'if ($PreviousRelease.Kind -ceq "legacy")' in script
    assert "$bridgeRequired = $true" in script
    assert "if ($bridgeRequired)" in script
    assert "Install-OperationalBridge `" in script
    assert "guard_python_path = $GuardPython" in script
    assert "guard_python_sha256 = (" in script
    assert "Integridade operacional divergente" in script
    assert "Assert-StableScheduledTasks -InstallRoot $ResolvedInstallRoot" in script

    resolver_destination = EXPECTED_OPERATIONAL_MAPPINGS["scripts/release-resolver.ps1"]
    run_destination = EXPECTED_OPERATIONAL_MAPPINGS["scripts/run-server.ps1"]
    assert resolver_destination in script
    assert run_destination in script


def test_readiness_and_fingerprint_gate_acceptance_and_rollback():
    script = read_script(UPDATE_SCRIPT)

    assert "[ValidateRange(1, 1200)][int]$MaximumAttempts = 40" in script
    assert script.count("-MaximumAttempts 1200") == 2
    assert '[string]$ready.status -ceq "ok"' in script
    assert '[string]$ready.release_id -ceq $ExpectedReleaseId' in script
    assert "Wait-GatedReadiness `" in script
    assert "[string]$afterDirect.logical_fingerprint -cne $StoppedFingerprint" in script
    assert "[string]$afterOfficial.logical_fingerprint -cne $StoppedFingerprint" in script
    assert "Restore-BackupReleasePointer -InstallRoot $ResolvedInstallRoot" in script
    assert "[string]$restored.logical_fingerprint -cne $StoppedFingerprint" in script
    assert "$databasePreserved" in script
    assert "$configurationPreserved" in script
    assert "Nenhum restore de banco foi executado" in script


def test_legacy_layout_is_bridged_but_never_auto_restarted_on_failure():
    script = read_script(UPDATE_SCRIPT)

    assert '$legacyId = "legacy-$([DateTime]::UtcNow.ToString' in script
    assert 'kind = "legacy"' in script
    assert "generation = 0" in script
    assert "$PreviousRelease.Kind -ceq \"release\"" in script
    assert "O release legado não foi reiniciado automaticamente" in script

    recovery_gate = script.index('$PreviousRelease.Kind -ceq "release"')
    restart = script.index(
        'Start-ScheduledTask -TaskName "CrepaldiHandball"', recovery_gate
    )
    assert recovery_gate < restart


def test_resolver_validates_manifest_payload_and_python_environment():
    script = read_script(RESOLVER_SCRIPT)

    assert "function Read-ValidatedReleaseManifest" in script
    assert "function Assert-SafeRelativeFilePath" in script
    assert "function Assert-FileEntriesMatchTree" in script
    assert "[IO.Path]::IsPathRooted($Path)" in script
    assert '$Path.Contains("\\")' in script
    assert "payload_sha256 diverge do inventário canônico validado" in script
    assert "environment_manifest_sha256 diverge" in script
    assert "environment_sha256 diverge do ambiente integralmente validado" in script
    assert '".venv/Scripts/python.exe"' in script
    assert "Read-ValidatedReleaseManifest `" in script


def test_resolver_handles_legacy_and_pointer_crash_recovery_safely():
    script = read_script(RESOLVER_SCRIPT)

    assert '$manifestSha256 = ""' in script
    assert "ManifestSha256 = $manifestSha256" in script
    assert "if (-not $AllowBackupPointer)" in script
    assert "[IO.File]::Replace($temporaryPath, $activePath, $backupPath, $true)" in script
    assert '"active-release.rejected-{0}.json"' in script
    assert "[IO.File]::Replace($restorePath, $activePath, $rejectedPath, $true)" in script
    assert "[IO.File]::Move($restorePath, $activePath)" in script
    assert "-AllowBackupPointer" not in read_script(RUN_SCRIPT)


def test_run_server_binds_database_and_auth_to_persistent_config():
    script = read_script(RUN_SCRIPT)

    assert "$Release = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot" in script
    assert "-AllowBackupPointer" not in script
    assert '$env:ATTENDANCE_CONFIG_PATH = $ConfigPath' in script
    assert '$env:ATTENDANCE_RELEASE_ID = $Release.ReleaseId' in script
    assert '$env:ATTENDANCE_MAINTENANCE_FILE = $MaintenanceFile' in script
    assert 'Where-Object { $_.Name -like "ATTENDANCE_*" }' in script
    assert 'Remove-Item -LiteralPath ("Env:{0}" -f $_.Name)' in script
    assert 'Remove-Item -LiteralPath "Env:PYTHONHOME"' in script
    assert 'Remove-Item -LiteralPath "Env:PYTHONPATH"' in script
    assert "Assert-PersistentConfiguration `" in script
    assert "Assert-ReleasePointerUnchanged `" in script
    assert "Set-Location $Release.ApplicationRoot" in script
    assert "& $Release.PythonPath -m uvicorn app:app" in script


def test_acl_and_scheduled_task_remove_code_write_and_time_limit_risks():
    installer = read_script(INSTALL_SCRIPT)
    updater = read_script(UPDATE_SCRIPT)

    assert '"*S-1-5-18:(OI)(CI)F"' in installer
    assert '"*S-1-5-32-544:(OI)(CI)F"' in installer
    assert "/inheritance:r /grant:r" in installer
    assert "$systemGrant $administratorsGrant /T /C" in installer
    assert "Set-PrivateDirectoryAcl -Path $ResolvedInstallRoot" in installer

    assert 'foreach ($sidValue in @("S-1-5-18", "S-1-5-32-544"))' in updater
    assert "$security.SetAccessRuleProtection($true, $false)" in updater
    assert "Set-PrivateTreeAcl -Path $ResolvedInstallRoot" in updater
    assert "Assert-PrivateAcl -Path $protectedPath" in updater

    for script in (installer, updater):
        assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script

    assert "Set-ScheduledTask `" in updater
    assert 'TaskName "CrepaldiHandball"' in updater
    assert "ExecutionTimeLimit infinito" in updater
    assert "if (-not $AllowLegacyRepair)" in updater
    assert updater.count("-AllowLegacyRepair") == 1
    assert "APP_ONLY formal não altera infraestrutura" in updater


def test_update_stop_calls_are_conservatively_flagged_and_locked():
    script = read_script(UPDATE_SCRIPT)

    assert 'Join-Path $Root ".maintenance.lock"' in script
    assert "[IO.FileShare]::None" in script
    lock = script.index("$LockStream = Enter-MaintenanceLock")
    persistent_validation = script.index("foreach ($requiredFile", lock)
    stop_attempt = script.index("$StopAttempted = $true", persistent_validation)
    main_stop = script.index("Stop-HandballServer", stop_attempt)
    catch_gate = script.index("if ($StopAttempted)", main_stop)
    catch_stop = script.index("Stop-HandballServer", catch_gate)
    assert lock < persistent_validation < stop_attempt < main_stop < catch_gate < catch_stop


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 indisponível")
def test_pointer_architecture_scripts_have_no_parser_errors():
    pwsh = shutil.which("pwsh")
    assert pwsh is not None

    for path in POINTER_ARCHITECTURE_SCRIPTS:
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
