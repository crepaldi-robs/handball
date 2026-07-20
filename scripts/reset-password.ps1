param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ConfigPath = Join-Path $InstallRoot "data\app-config.json"
$Python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
& $Python -m attendance.cli reset-password --config-path $ConfigPath
Restart-ScheduledTask -TaskName "CrepaldiHandball"
