Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Ambiente virtual não encontrado. Execute .\scripts\setup.ps1 primeiro."
}

Write-Warning "A exposição direta na rede foi desativada. Use o túnel HTTPS documentado."
$env:ATTENDANCE_CONFIG_PATH = Join-Path $ProjectRoot "data\app-config.json"
& ".\.venv\Scripts\python.exe" -m uvicorn app:app `
    --host 127.0.0.1 `
    --port 8765
