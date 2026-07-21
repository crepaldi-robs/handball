from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_installer_uses_language_independent_acl_principals():
    script = (PROJECT_ROOT / "scripts" / "install-server.ps1").read_text(
        encoding="utf-8"
    )

    assert '"*S-1-5-18:(OI)(CI)F"' in script
    assert '"*S-1-5-32-544:(OI)(CI)F"' in script
    assert '"Administrators:(OI)(CI)F"' not in script
    assert "if ($LASTEXITCODE -ne 0)" in script
