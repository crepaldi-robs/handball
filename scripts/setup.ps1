Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    py -3.13 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

if (-not (Test-Path "data\app-config.json")) {
    & ".\.venv\Scripts\python.exe" -m handball.cli init `
        --config-path "data\app-config.json" `
        --db-path "data\presencas.db" `
        --backup-dir "backups"
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível criar a configuração local."
    }
}

& ".\.venv\Scripts\python.exe" -m handball.cli init-database `
    --config-path "data\app-config.json"
if ($LASTEXITCODE -ne 0) {
    throw "Não foi possível preparar ou validar o banco local."
}

Write-Host ""
Write-Host "Ambiente e acesso administrativo preparados."
Write-Host "Execute: .\scripts\run.ps1"
