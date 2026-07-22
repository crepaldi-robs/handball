from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = PROJECT_ROOT / "scripts" / "release-resolver.ps1"


def read_resolver() -> str:
    return RESOLVER.read_text(encoding="utf-8")


def run_pwsh(body: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 não está disponível.")
    resolver_path = str(RESOLVER).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop'; "
        f". '{resolver_path}'; "
        f"{body}"
    )
    return subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def ps_single_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def file_entries(root: Path, relative_paths: list[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for relative_path in sorted(relative_paths):
        content = (root / Path(relative_path)).read_bytes()
        entries.append(
            {
                "path": relative_path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return entries


def canonical_entries_sha256(entries: list[dict[str, object]]) -> str:
    canonical = "".join(
        f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n"
        for entry in entries
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_formal_release(root: Path) -> str:
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Lib").mkdir(parents=True)
    (root / "app.py").write_text("app = object()\n", encoding="utf-8")
    (root / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    # Não é um executável real: o teste prova que o resolver nunca o executa.
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"not-an-executable")
    (root / ".venv" / "Lib" / "installed.txt").write_bytes(b"installed")

    payload = file_entries(root, ["app.py", "requirements.txt"])
    environment = file_entries(
        root,
        [".venv/Lib/installed.txt", ".venv/Scripts/python.exe"],
    )
    environment_sha256 = canonical_entries_sha256(environment)
    environment_document = {
        "format": 1,
        "environment_sha256": environment_sha256,
        "files": environment,
    }
    environment_bytes = (
        json.dumps(environment_document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    (root / "environment-files.json").write_bytes(environment_bytes)

    manifest = {
        "format": 1,
        "release_id": "release-test-1",
        "install_kind": "app-only",
        "database_action": "none",
        "source_commit": "a" * 40,
        "schema_compatibility": {"minimum": 1, "maximum": 2},
        "payload_sha256": canonical_entries_sha256(payload),
        "payload_files": payload,
        "environment_manifest": "environment-files.json",
        "environment_manifest_sha256": hashlib.sha256(environment_bytes).hexdigest(),
        "environment_sha256": environment_sha256,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    (root / "release-manifest.json").write_bytes(manifest_bytes)
    return hashlib.sha256(manifest_bytes).hexdigest()


def test_resolver_has_no_powershell_parser_errors():
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 não está disponível.")
    resolver_path = str(RESOLVER).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{resolver_path}',[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("expression", "expected_total_hours"),
    [
        ("'PT72H'", "72"),
        ("'PT0S'", "0"),
        ("'3.00:00:00'", "72"),
        ("[TimeSpan]::FromMinutes(90)", "1.5"),
    ],
)
def test_scheduled_task_duration_accepts_cim_and_timespan_formats(
    expression: str,
    expected_total_hours: str,
):
    result = run_pwsh(
        "$duration = ConvertFrom-ScheduledTaskDuration -Value "
        f"({expression}); "
        "$duration.TotalHours.ToString("
        "[Globalization.CultureInfo]::InvariantCulture)"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected_total_hours


def test_scheduled_task_duration_rejects_empty_and_invalid_values():
    for expression in ("''", "'not-a-duration'", "'PTnot-valid'"):
        result = run_pwsh(
            "try { ConvertFrom-ScheduledTaskDuration -Value "
            f"({expression}); exit 0 }} catch {{ exit 23 }}"
        )
        assert result.returncode == 23, result.stdout + result.stderr


def test_formal_release_is_verified_without_executing_python():
    script = read_resolver()

    assert "pip freeze" not in script
    assert "-m pip" not in script
    assert "& $pythonPath" not in script
    assert "& $Python" not in script
    assert "Get-RegularFileEvidence" in script
    assert "Assert-FileEntriesMatchTree" in script
    assert "payload_sha256 diverge do inventário canônico validado" in script
    assert "environment_sha256 diverge do ambiente integralmente validado" in script


def test_environment_inventory_contract_is_explicit_and_cross_hashed():
    script = read_resolver()

    assert '$script:EnvironmentManifestName = "environment-files.json"' in script
    assert '-Name "environment_manifest"' in script
    assert '-Name "environment_manifest_sha256"' in script
    assert '-Name "environment_sha256"' in script
    assert '-Name "files"' in script
    assert '".venv/Scripts/python.exe"' in script
    assert '"__pycache__"' in script
    assert 'EndsWith(".pyc"' in script


def test_manifest_semantics_and_schema_range_are_fail_closed():
    script = read_resolver()

    assert '($installKind -ceq "initial" -and $databaseAction -ceq "bootstrap")' in script
    assert '($installKind -ceq "app-only" -and $databaseAction -ceq "none")' in script
    assert '-Name "schema_compatibility"' in script
    assert '-Name "minimum"' in script
    assert '-Name "maximum"' in script
    assert "$schemaMinimum -gt $schemaMaximum" in script
    assert "SchemaMinimum =" in script
    assert "SchemaMaximum =" in script


def test_release_ids_reject_windows_device_names_and_trailing_dot():
    result = run_pwsh(
        """
        [void](Assert-SafeReleaseId -ReleaseId 'release-20260721.1')
        foreach ($invalid in @(
            'CON', 'nul.txt', 'COM1.release', 'LPT9', 'release.',
            '../escape', ('a' * 65)
        )) {
            $accepted = $true
            try { [void](Assert-SafeReleaseId -ReleaseId $invalid) }
            catch { $accepted = $false }
            if ($accepted) { throw "release_id inseguro aceito: $invalid" }
        }
        'ok'
        """
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"


def test_relative_paths_reject_traversal_ads_backslashes_and_device_segments():
    result = run_pwsh(
        """
        [void](Assert-SafeRelativeFilePath -Path 'attendance/web.py' -Label 'test')
        foreach ($invalid in @(
            '../escape.py', 'a/../b.py', 'a\\b.py', '/root.py',
            'C:stream.py', 'safe/NUL.txt', 'safe/file.','a//b'
        )) {
            $accepted = $true
            try {
                [void](Assert-SafeRelativeFilePath -Path $invalid -Label 'test')
            }
            catch { $accepted = $false }
            if ($accepted) { throw "caminho inseguro aceito: $invalid" }
        }
        'ok'
        """
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"


def test_canonical_file_list_hash_matches_utf8_ordinal_contract():
    entries = [
        (".venv/Lib/A.txt", 1, "0" * 64),
        (".venv/Lib/a.txt", 2, "f" * 64),
    ]
    canonical = "".join(
        f"{path}\t{size}\t{sha256}\n" for path, size, sha256 in entries
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    result = run_pwsh(
        """
        $entries = @(
            [pscustomobject]@{ Path='.venv/Lib/A.txt'; Bytes=[int64]1; Sha256=('0' * 64) },
            [pscustomobject]@{ Path='.venv/Lib/a.txt'; Bytes=[int64]2; Sha256=('f' * 64) }
        )
        Get-CanonicalFileListSha256 -Entries $entries
        """
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected


def test_full_formal_release_validation_never_executes_fake_python(tmp_path: Path):
    release_root = tmp_path / "release-test-1"
    release_root.mkdir()
    manifest_sha256 = build_formal_release(release_root)
    result = run_pwsh(
        "$result = Read-ValidatedReleaseManifest "
        f"-ApplicationRoot {ps_single_quote(release_root)} "
        "-ExpectedReleaseId 'release-test-1' "
        f"-ExpectedManifestSha256 '{manifest_sha256}'; "
        "\"$($result.InstallKind)|$($result.DatabaseAction)|\" + "
        "\"$($result.SchemaMinimum)|$($result.SchemaMaximum)\""
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "app-only|none|1|2"


@pytest.mark.parametrize(
    ("relative_path", "new_bytes"),
    [
        ("app.py", b"tampered\n"),
        (".venv/Lib/installed.txt", b"tampered-environment\n"),
    ],
)
def test_formal_release_rejects_tampered_payload_or_environment(
    tmp_path: Path,
    relative_path: str,
    new_bytes: bytes,
):
    release_root = tmp_path / "release-test-1"
    release_root.mkdir()
    manifest_sha256 = build_formal_release(release_root)
    (release_root / Path(relative_path)).write_bytes(new_bytes)
    result = run_pwsh(
        "[void](Read-ValidatedReleaseManifest "
        f"-ApplicationRoot {ps_single_quote(release_root)} "
        "-ExpectedReleaseId 'release-test-1' "
        f"-ExpectedManifestSha256 '{manifest_sha256}')"
    )
    assert result.returncode != 0


def test_formal_release_rejects_uninventoried_payload_file_including_pyc(
    tmp_path: Path,
):
    release_root = tmp_path / "release-test-1"
    release_root.mkdir()
    manifest_sha256 = build_formal_release(release_root)
    cache = release_root / "__pycache__"
    cache.mkdir()
    (cache / "app.cpython-313.pyc").write_bytes(b"untrusted-cache")
    result = run_pwsh(
        "[void](Read-ValidatedReleaseManifest "
        f"-ApplicationRoot {ps_single_quote(release_root)} "
        "-ExpectedReleaseId 'release-test-1' "
        f"-ExpectedManifestSha256 '{manifest_sha256}')"
    )
    assert result.returncode != 0


def test_pointer_switch_requires_generation_compare_and_swap():
    script = read_resolver()

    assert "[Nullable[int64]]$ExpectedGeneration" in script
    assert '$PSBoundParameters.ContainsKey("ExpectedGeneration")' in script
    assert "$current.Generation -ne [int64]$ExpectedGeneration" in script
    assert "$candidate.Generation -ne ($current.Generation + 1)" in script
    assert "legacy/geração 0 ou release/geração 1" in script
    assert "PointerSha256" in script
    assert "ponteiro ativo mudou durante a troca" in script


def test_backup_fallback_remains_explicit_and_observable():
    script = read_resolver()

    assert "[switch]$AllowBackupPointer" in script
    assert "if (-not $AllowBackupPointer)" in script
    assert "UsedBackupPointer" in script
    assert "-NotePropertyValue $true" in script
    assert '"active-release.rejected-{0}.json" -f [guid]::NewGuid()' in script
