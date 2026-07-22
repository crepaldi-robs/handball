param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

. (Join-Path $PSScriptRoot "release-resolver.ps1")

function Assert-RegularPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][bool]$Container,
        [Parameter(Mandatory)][string]$Label
    )

    Assert-PathChainWithoutReparsePoint -Path $Path
    $pathType = if ($Container) { "Container" } else { "Leaf" }
    if (-not (Test-Path -LiteralPath $Path -PathType $pathType)) {
        throw "$Label ausente: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "$Label não pode ser symlink, junction ou reparse point: $Path"
    }
}

function Assert-PersistentConfiguration {
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$ExpectedDbPath,
        [Parameter(Mandatory)][string]$ExpectedBackupRoot
    )

    Assert-RegularPath -Path $ConfigPath -Container $false -Label "Configuração"
    try {
        $config = Get-Content -Raw -LiteralPath $ConfigPath -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Configuração persistente inválida: $ConfigPath"
    }

    foreach ($pair in @(
        @([string]$config.db_path, $ExpectedDbPath, "db_path"),
        @([string]$config.backup_dir, $ExpectedBackupRoot, "backup_dir")
    )) {
        if (
            [string]::IsNullOrWhiteSpace($pair[0]) -or
            -not [IO.Path]::IsPathFullyQualified($pair[0])
        ) {
            throw "Configuração recusada: $($pair[2]) deve ser caminho absoluto."
        }
        $configured = [IO.Path]::TrimEndingDirectorySeparator(
            [IO.Path]::GetFullPath($pair[0])
        )
        $expected = [IO.Path]::TrimEndingDirectorySeparator(
            [IO.Path]::GetFullPath($pair[1])
        )
        if (-not [string]::Equals(
            $configured,
            $expected,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw (
                "Configuração recusada: $($pair[2]) deve resolver exatamente " +
                "para '$expected'."
            )
        }
    }
}

function Assert-ReleasePointerUnchanged {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][object]$Expected
    )

    # O launcher jamais usa o ponteiro .bak: ponteiro ativo inválido falha fechado.
    $current = Resolve-ActiveRelease -InstallRoot $Root
    foreach ($property in @(
        "Generation", "ReleaseId", "Kind", "ManifestSha256", "PointerSha256"
    )) {
        if ([string]$current.$property -cne [string]$Expected.$property) {
            throw "O ponteiro ativo mudou durante a preparação do processo."
        }
    }
    return $current
}

$ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
$Release = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
if ($Release.Kind -cne "release") {
    throw "Inicialização recusada: o ponteiro ativo não identifica uma release formal."
}

$ConfigPath = Join-Path $ResolvedInstallRoot "data\app-config.json"
$DbPath = Join-Path $ResolvedInstallRoot "data\presencas.db"
$BackupRoot = Join-Path $ResolvedInstallRoot "backups"
$StateRoot = Join-Path $ResolvedInstallRoot "state"
$MaintenanceFile = Join-Path $StateRoot "maintenance-mode"
$LogDir = Join-Path $ResolvedInstallRoot "logs"

Assert-RegularPath -Path $DbPath -Container $false -Label "Banco persistente"
Assert-RegularPath -Path $BackupRoot -Container $true -Label "Diretório de backups"
Assert-RegularPath -Path $StateRoot -Container $true -Label "Diretório de estado"
Assert-RegularPath -Path $LogDir -Container $true -Label "Diretório de logs"
Assert-PersistentConfiguration `
    -ConfigPath $ConfigPath `
    -ExpectedDbPath $DbPath `
    -ExpectedBackupRoot $BackupRoot

# A tarefa SYSTEM não pode herdar nenhum override de banco, configuração,
# credencial, cookie, política ou diretório de backup de uma sessão externa.
Get-ChildItem Env: |
    Where-Object { $_.Name -like "ATTENDANCE_*" } |
    ForEach-Object {
        Remove-Item -LiteralPath ("Env:{0}" -f $_.Name) -ErrorAction Stop
    }
Remove-Item -LiteralPath "Env:PYTHONHOME" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "Env:PYTHONPATH" -ErrorAction SilentlyContinue

$env:ATTENDANCE_CONFIG_PATH = $ConfigPath
$env:ATTENDANCE_RELEASE_ID = $Release.ReleaseId
$env:ATTENDANCE_MAINTENANCE_FILE = $MaintenanceFile
$env:PYTHONDONTWRITEBYTECODE = "1"

$Release = Assert-ReleasePointerUnchanged `
    -Root $ResolvedInstallRoot `
    -Expected $Release
$LogPath = Join-Path $LogDir ("server-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

Set-Location $Release.ApplicationRoot
& $Release.PythonPath -m uvicorn app:app `
    --host 127.0.0.1 `
    --port 8765 `
    --proxy-headers `
    --forwarded-allow-ips "127.0.0.1" *>> $LogPath
$serverExitCode = $LASTEXITCODE
if ($serverExitCode -ne 0) {
    exit $serverExitCode
}
