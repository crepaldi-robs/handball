param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:ATTENDANCE_CONFIG_PATH = Join-Path $InstallRoot "data\app-config.json"

$AppRoot = Join-Path $InstallRoot "app"
$Python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $InstallRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ("server-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

Set-Location $AppRoot
& $Python -m uvicorn app:app `
    --host 127.0.0.1 `
    --port 8765 `
    --proxy-headers `
    --forwarded-allow-ips "127.0.0.1" *>> $LogPath
