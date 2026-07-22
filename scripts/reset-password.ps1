param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

. (Join-Path $PSScriptRoot "release-resolver.ps1")

function Assert-Administrator {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        throw "Execute este script em um PowerShell 7 aberto como Administrador."
    }
}

function Enter-MaintenanceLock {
    param([Parameter(Mandatory)][string]$Root)
    try {
        return [IO.File]::Open(
            (Join-Path $Root ".maintenance.lock"),
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw "Outra manutenção está em andamento."
    }
}

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
    return $item
}

function Assert-PersistentConfiguration {
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$ExpectedDbPath,
        [Parameter(Mandatory)][string]$ExpectedBackupRoot
    )

    try {
        $config = Get-Content -Raw -LiteralPath $ConfigPath -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Reset recusado: app-config.json inválido."
    }
    foreach ($pair in @(
        @([string]$config.db_path, $ExpectedDbPath, "db_path"),
        @([string]$config.backup_dir, $ExpectedBackupRoot, "backup_dir")
    )) {
        if (
            [string]::IsNullOrWhiteSpace($pair[0]) -or
            -not [IO.Path]::IsPathFullyQualified($pair[0])
        ) {
            throw "Reset recusado: $($pair[2]) deve ser caminho absoluto."
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
                "Reset recusado: $($pair[2]) deve resolver exatamente para " +
                "'$expected'."
            )
        }
    }
}

function Resolve-VerifiedGuardRuntime {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][object]$Release
    )

    $opsRoot = Join-Path $Root "ops"
    $manifestPath = Join-Path $opsRoot "ops-manifest.json"
    $guardPath = Join-Path $opsRoot "database-guard.py"
    [void](Assert-RegularPath -Path $opsRoot -Container $true -Label "Diretório operacional")
    [void](Assert-RegularPath -Path $manifestPath -Container $false -Label "Manifesto operacional")
    [void](Assert-RegularPath -Path $guardPath -Container $false -Label "Database guard")
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Manifesto operacional inválido."
    }
    if ([int]$manifest.format -ne 1 -or [int]$manifest.protocol -ne 1) {
        throw "Contrato do manifesto operacional não suportado."
    }
    if (
        $manifest.PSObject.Properties.Name -contains "release_id" -and
        -not [string]::IsNullOrWhiteSpace([string]$manifest.release_id) -and
        [string]$manifest.release_id -cne [string]$Release.ReleaseId
    ) {
        throw "Manifesto operacional não pertence ao release ativo."
    }
    $entries = @(
        $manifest.files |
            Where-Object { [string]$_.path -ceq "ops/database-guard.py" }
    )
    if ($entries.Count -ne 1) {
        throw "Manifesto não autentica exatamente um database guard."
    }
    $expectedGuardHash = ([string]$entries[0].sha256).ToLowerInvariant()
    if (
        $expectedGuardHash -notmatch '^[0-9a-f]{64}$' -or
        -not ($entries[0].PSObject.Properties.Name -contains "bytes") -or
        [long]$entries[0].bytes -le 0
    ) {
        throw "Metadados do database guard são inválidos."
    }
    $guardInfo = Get-Item -LiteralPath $guardPath -Force
    $observedGuardHash = (
        Get-FileHash -LiteralPath $guardPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $guardInfo.Length -ne [long]$entries[0].bytes -or
        $observedGuardHash -cne $expectedGuardHash
    ) {
        throw "Database guard diverge do manifesto operacional."
    }

    $pythonValue = [string]$manifest.guard_python_path
    $expectedPythonHash = ([string]$manifest.guard_python_sha256).ToLowerInvariant()
    if (
        [string]::IsNullOrWhiteSpace($pythonValue) -or
        -not [IO.Path]::IsPathFullyQualified($pythonValue) -or
        $expectedPythonHash -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Manifesto não autentica um guard_python_path absoluto."
    }
    $pythonPath = [IO.Path]::GetFullPath($pythonValue)
    [void](Assert-RegularPath -Path $pythonPath -Container $false -Label "Python do guard")
    $observedPythonHash = (
        Get-FileHash -LiteralPath $pythonPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($observedPythonHash -cne $expectedPythonHash) {
        throw "Interpretador do database guard diverge do manifesto."
    }

    return [pscustomobject]@{
        GuardPath = $guardPath
        PythonPath = $pythonPath
    }
}

function Invoke-GuardJson {
    param(
        [Parameter(Mandatory)][object]$Runtime,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $output = @(
        & $Runtime.PythonPath -I -S $Runtime.GuardPath @Arguments 2>&1
    )
    $exitCode = $LASTEXITCODE
    $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "Database guard falhou ($exitCode): $text"
    }
    try {
        $result = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Database guard não retornou JSON válido: $text"
    }
    if (
        -not [bool]$result.ok -or
        [string]$result.format -cne "crepaldi-handball-database-guard/v1" -or
        [string]$result.fingerprint_format -cne `
            "crepaldi-handball-logical-sqlite/v1"
    ) {
        throw "Database guard retornou contrato incompatível."
    }
    return $result
}

function Get-GuardFingerprint {
    param(
        [Parameter(Mandatory)][object]$Runtime,
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$ExpectedDbPath
    )
    $result = Invoke-GuardJson `
        -Runtime $Runtime `
        -Arguments @(
            "fingerprint",
            "--config-path", $ConfigPath,
            "--expected-database-path", $ExpectedDbPath
        )
    $fingerprint = [string]$result.logical_fingerprint
    if ($fingerprint -notmatch '^[0-9a-f]{64}$') {
        throw "Database guard retornou fingerprint inválido."
    }
    return $fingerprint
}

function New-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][object]$Release
    )

    $payload = [ordered]@{
        format = 1
        operation = $Operation
        owner_token = $Token
        process_id = $PID
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        release_id = [string]$Release.ReleaseId
        release_generation = [int64]$Release.Generation
    }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(
        (($payload | ConvertTo-Json -Compress) + "`n")
    )
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Read-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Token
    )

    [void](Assert-RegularPath -Path $Path -Container $false -Label "Marcador de manutenção")
    try {
        $marker = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Marcador de manutenção é inválido; remoção recusada."
    }
    if (
        [int]$marker.format -ne 1 -or
        [string]$marker.operation -cne $Operation -or
        [string]$marker.owner_token -cne $Token
    ) {
        throw "Marcador de manutenção não pertence a esta operação."
    }
    return $marker
}

function Remove-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Token
    )

    [void](Read-OwnedMaintenanceMarker `
        -Path $Path `
        -Operation $Operation `
        -Token $Token)
    $retiredPath = "$Path.removed-$Token"
    if (Test-Path -LiteralPath $retiredPath) {
        throw "Destino interno de remoção do marcador já existe."
    }
    [IO.File]::Move($Path, $retiredPath, $false)
    try {
        [void](Read-OwnedMaintenanceMarker `
            -Path $retiredPath `
            -Operation $Operation `
            -Token $Token)
        [IO.File]::Delete($retiredPath)
    }
    catch {
        if (
            (Test-Path -LiteralPath $retiredPath) -and
            -not (Test-Path -LiteralPath $Path)
        ) {
            [IO.File]::Move($retiredPath, $Path, $false)
        }
        throw
    }
}

function Assert-ServerTaskAction {
    param([Parameter(Mandatory)][string]$Root)

    $task = Get-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction Stop
    $actions = @($task.Actions)
    $expectedPwsh = [IO.Path]::GetFullPath((Get-Command pwsh.exe -ErrorAction Stop).Source)
    $expectedScript = Join-Path $Root "app\scripts\run-server.ps1"
    $expectedArguments = (
        '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f `
            $expectedScript, $Root
    )
    if (
        $actions.Count -ne 1 -or
        -not [string]::Equals(
            [IO.Path]::GetFullPath([string]$actions[0].Execute),
            $expectedPwsh,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$actions[0].Arguments -cne $expectedArguments
    ) {
        throw "A ação da tarefa CrepaldiHandball não está na allowlist operacional."
    }
    return $task
}

function Stop-HandballServer {
    Stop-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction SilentlyContinue
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        $task = Get-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction Stop
        $listener = Get-NetTCPConnection `
            -LocalPort 8765 `
            -State Listen `
            -ErrorAction SilentlyContinue
        if ($task.State -ne "Running" -and -not $listener) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Servidor não parou ou a porta 8765 continua ocupada."
}

function Wait-ExpectedReadiness {
    param([Parameter(Mandatory)][string]$ExpectedReleaseId)
    $lastResult = "sem resposta"
    $maximumAttempts = 900
    for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/ready" `
                -TimeoutSec 5
            if (
                [string]$response.status -ceq "ok" -and
                [string]$response.database -ceq "ready" -and
                [string]$response.release_id -ceq $ExpectedReleaseId
            ) {
                return
            }
            $lastResult = "readiness divergente"
        }
        catch {
            $lastResult = $_.Exception.Message
        }
        Start-Sleep -Seconds 1
    }
    throw "O release '$ExpectedReleaseId' não ficou pronto: $lastResult"
}

function Assert-ReleasePointerUnchanged {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][object]$Expected
    )
    $current = Resolve-ActiveRelease -InstallRoot $Root
    foreach ($property in @(
        "Generation", "ReleaseId", "Kind", "ManifestSha256", "PointerSha256"
    )) {
        if ([string]$current.$property -cne [string]$Expected.$property) {
            throw "O ponteiro ativo mudou durante o reset; restart recusado."
        }
    }
    return $current
}

function Set-FixedApplicationEnvironment {
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$ReleaseId,
        [Parameter(Mandatory)][string]$MaintenanceFile
    )
    Get-ChildItem Env: |
        Where-Object { $_.Name -like "ATTENDANCE_*" } |
        ForEach-Object {
            Remove-Item -LiteralPath ("Env:{0}" -f $_.Name) -ErrorAction Stop
        }
    Remove-Item -LiteralPath "Env:PYTHONHOME" -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "Env:PYTHONPATH" -ErrorAction SilentlyContinue
    $env:ATTENDANCE_CONFIG_PATH = $ConfigPath
    $env:ATTENDANCE_RELEASE_ID = $ReleaseId
    $env:ATTENDANCE_MAINTENANCE_FILE = $MaintenanceFile
    $env:PYTHONDONTWRITEBYTECODE = "1"
}

Assert-Administrator
$InitialInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
$LockStream = Enter-MaintenanceLock -Root $InitialInstallRoot
$MaintenanceFile = $null
$MaintenanceToken = $null
$MaintenanceCreationAttempted = $false
$MaintenanceOwned = $false
$StopAttempted = $false
$StartAttempted = $false
$FingerprintBefore = $null
try {
    # Todo estado operacional/persistente é relido somente sob o lock.
    $ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    $Release = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if ($Release.Kind -cne "release") {
        throw "Reset recusado: release legado pode executar startup mutante."
    }
    $DataRoot = Join-Path $ResolvedInstallRoot "data"
    $ConfigPath = Join-Path $DataRoot "app-config.json"
    $DbPath = Join-Path $DataRoot "presencas.db"
    $BackupRoot = Join-Path $ResolvedInstallRoot "backups"
    $StateRoot = Join-Path $ResolvedInstallRoot "state"
    $MaintenanceFile = Join-Path $StateRoot "maintenance-mode"
    [void](Assert-RegularPath -Path $ConfigPath -Container $false -Label "Configuração")
    [void](Assert-RegularPath -Path $DbPath -Container $false -Label "Banco persistente")
    [void](Assert-RegularPath -Path $BackupRoot -Container $true -Label "Diretório de backups")
    [void](Assert-RegularPath -Path $StateRoot -Container $true -Label "Diretório de estado")
    [void](Assert-ServerTaskAction -Root $ResolvedInstallRoot)
    Assert-PersistentConfiguration `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath `
        -ExpectedBackupRoot $BackupRoot
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $verification = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if ([string]$verification.quick_check -cne "ok") {
        throw "Reset recusado: quick_check não retornou ok."
    }

    if (Test-Path -LiteralPath $MaintenanceFile) {
        throw "Reset recusado: modo de manutenção já está ativo."
    }
    $MaintenanceToken = [guid]::NewGuid().ToString("N")
    $MaintenanceCreationAttempted = $true
    New-OwnedMaintenanceMarker `
        -Path $MaintenanceFile `
        -Operation "PASSWORD_RESET" `
        -Token $MaintenanceToken `
        -Release $Release
    $MaintenanceOwned = $true

    $StopAttempted = $true
    Stop-HandballServer
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $FingerprintBefore = Get-GuardFingerprint `
        -Runtime $GuardRuntime `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath

    Set-FixedApplicationEnvironment `
        -ConfigPath $ConfigPath `
        -ReleaseId $Release.ReleaseId `
        -MaintenanceFile $MaintenanceFile
    Push-Location $Release.ApplicationRoot
    try {
        & $Release.PythonPath -m handball.cli reset-password `
            --config-path $ConfigPath
        if ($LASTEXITCODE -ne 0) {
            throw "A CLI não concluiu a redefinição de senha."
        }
    }
    finally {
        Pop-Location
    }

    Assert-PersistentConfiguration `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath `
        -ExpectedBackupRoot $BackupRoot
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $FingerprintAfterReset = Get-GuardFingerprint `
        -Runtime $GuardRuntime `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath
    if ($FingerprintAfterReset -cne $FingerprintBefore) {
        throw "Reset alterou o fingerprint lógico do SQLite; restart recusado."
    }

    $Release = Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release
    $StartAttempted = $true
    Start-ScheduledTask -TaskName "CrepaldiHandball"
    Wait-ExpectedReadiness -ExpectedReleaseId $Release.ReleaseId

    $FingerprintAfterStartup = Get-GuardFingerprint `
        -Runtime $GuardRuntime `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath
    if ($FingerprintAfterStartup -cne $FingerprintBefore) {
        throw "Startup posterior ao reset alterou o SQLite persistente."
    }
    [void](Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release)
    Remove-OwnedMaintenanceMarker `
        -Path $MaintenanceFile `
        -Operation "PASSWORD_RESET" `
        -Token $MaintenanceToken
    $MaintenanceOwned = $false

    Write-Host (
        "Senha redefinida; release '$($Release.ReleaseId)' validado sem " +
        "alteração do banco."
    )
}
catch {
    $failure = $_
    $markerMayBeOurs = (
        $MaintenanceCreationAttempted -and
        $MaintenanceFile -and
        (Test-Path -LiteralPath $MaintenanceFile)
    )
    if ($MaintenanceOwned -or $markerMayBeOurs -or $StopAttempted -or $StartAttempted) {
        try {
            Stop-HandballServer
        }
        catch {
            throw (
                "Reset falhou e a parada do serviço não pôde ser confirmada. " +
                "O marcador não foi removido. Falha original: " +
                "$($failure.Exception.Message); stop: $($_.Exception.Message)"
            )
        }
        throw (
            "Reset falhou; serviço confirmado como parado e marcador de " +
            "manutenção preservado. Nenhum restore do banco foi executado. " +
            "Falha: $($failure.Exception.Message)"
        )
    }
    throw $failure
}
finally {
    $LockStream.Dispose()
}
