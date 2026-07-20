param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$Principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em um PowerShell 7 aberto como Administrador."
}

$ExpectedRoot = [IO.Path]::GetFullPath("C:\ProgramData\CrepaldiHandball")
$ResolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
if (-not $ResolvedInstallRoot.StartsWith($ExpectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Por segurança, a instalação deve permanecer em C:\ProgramData\CrepaldiHandball."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $ResolvedInstallRoot "app"
$DataRoot = Join-Path $ResolvedInstallRoot "data"
$BackupRoot = Join-Path $ResolvedInstallRoot "backups"
$LogRoot = Join-Path $ResolvedInstallRoot "logs"
$ConfigPath = Join-Path $DataRoot "app-config.json"
$DbPath = Join-Path $DataRoot "presencas.db"

foreach ($directory in @($ResolvedInstallRoot, $AppRoot, $DataRoot, $BackupRoot, $LogRoot)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$SourceItems = @(
    "app.py",
    "requirements.txt",
    "attendance",
    "templates",
    "static",
    "scripts\run-server.ps1",
    "scripts\backup-server.ps1",
    "scripts\reset-password.ps1"
)
foreach ($relativePath in $SourceItems) {
    $source = Join-Path $ProjectRoot $relativePath
    $destination = Join-Path $AppRoot $relativePath
    if ((Get-Item -LiteralPath $source).PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Get-ChildItem -LiteralPath $source -Force | Copy-Item `
            -Destination $destination -Recurse -Force
    }
    else {
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$VenvPython = Join-Path $ResolvedInstallRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    py -3.13 -m venv (Join-Path $ResolvedInstallRoot ".venv")
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $AppRoot "requirements.txt")

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Set-Location $AppRoot
    & $VenvPython -m attendance.cli init `
        --config-path $ConfigPath `
        --db-path $DbPath `
        --backup-dir $BackupRoot `
        --secure-cookie
}

& icacls.exe $DataRoot /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
& icacls.exe $BackupRoot /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$ServerScript = Join-Path $AppRoot "scripts\run-server.ps1"
$BackupScript = Join-Path $AppRoot "scripts\backup-server.ps1"
$ServerAction = New-ScheduledTaskAction -Execute $Pwsh -Argument (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f $ServerScript, $ResolvedInstallRoot
)
$ServerTrigger = New-ScheduledTaskTrigger -AtStartup
$SystemPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "CrepaldiHandball" -Action $ServerAction -Trigger $ServerTrigger -Principal $SystemPrincipal -Settings $Settings -Force | Out-Null

$BackupAction = New-ScheduledTaskAction -Execute $Pwsh -Argument (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f $BackupScript, $ResolvedInstallRoot
)
$BackupTrigger = New-ScheduledTaskTrigger -Daily -At 3am
Register-ScheduledTask -TaskName "CrepaldiHandballBackup" -Action $BackupAction -Trigger $BackupTrigger -Principal $SystemPrincipal -Force | Out-Null

Start-ScheduledTask -TaskName "CrepaldiHandball"
Start-Sleep -Seconds 3
$Health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 10
if ($Health.status -ne "ok") {
    throw "O servidor foi instalado, mas a verificação de saúde falhou."
}

Write-Host ""
Write-Host "Servidor instalado e iniciado em http://127.0.0.1:8765"
Write-Host "Próxima etapa: configure o Cloudflare Tunnel conforme docs\DEPLOYMENT.md."
