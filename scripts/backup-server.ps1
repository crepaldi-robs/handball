param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:ATTENDANCE_CONFIG_PATH = Join-Path $InstallRoot "data\app-config.json"

$AppRoot = Join-Path $InstallRoot "app"
$Python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
Set-Location $AppRoot
& $Python -m attendance.cli backup `
    --config-path $env:ATTENDANCE_CONFIG_PATH `
    --keep 30
