param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball",
    [switch]$Apply,
    [string]$ExpectedPlanSha256 = "",
    [switch]$OpenMaintenanceWindow,
    [switch]$CloseMaintenanceWindow,
    [string]$MaintenanceWindowToken = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

. (Join-Path $PSScriptRoot "release-resolver.ps1")

$PlanningActions = @(
    "none",
    "adopt-baseline",
    "migrate",
    "blocked",
    "bootstrap-required"
)
$WritableActions = @("adopt-baseline", "migrate")

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
        throw "Migração recusada: app-config.json inválido."
    }
    foreach ($pair in @(
        @([string]$config.db_path, $ExpectedDbPath, "db_path"),
        @([string]$config.backup_dir, $ExpectedBackupRoot, "backup_dir")
    )) {
        if (
            [string]::IsNullOrWhiteSpace($pair[0]) -or
            -not [IO.Path]::IsPathFullyQualified($pair[0])
        ) {
            throw "Migração recusada: $($pair[2]) deve ser caminho absoluto."
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
                "Migração recusada: $($pair[2]) deve resolver exatamente para " +
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
        GuardSha256 = $observedGuardHash
        PythonSha256 = $observedPythonHash
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

function Assert-BackupArtifact {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Result
    )
    $item = Assert-RegularPath -Path $Path -Container $false -Label "Backup pré-migration"
    $expectedPath = [IO.Path]::GetFullPath($Path)
    if (-not [string]::Equals(
        [IO.Path]::GetFullPath($item.FullName),
        $expectedPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Backup pré-migration foi publicado em caminho inesperado."
    }
    $reportedHash = [string]$Result.sha256
    if ([string]::IsNullOrWhiteSpace($reportedHash)) {
        $reportedHash = [string]$Result.backup_sha256
    }
    $reportedHash = $reportedHash.ToLowerInvariant()
    $localHash = (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $reportedHash -notmatch '^[0-9a-f]{64}$' -or
        [long]$Result.backup_bytes -le 0 -or
        [string]$Result.quick_check -cne "ok" -or
        [string]$Result.logical_fingerprint -notmatch '^[0-9a-f]{64}$' -or
        $item.Length -ne [long]$Result.backup_bytes -or
        $localHash -cne $reportedHash
    ) {
        throw "Backup primário não passou na validação local de bytes/SHA/fingerprint."
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$Result.backup_sha256) -and
        ([string]$Result.backup_sha256).ToLowerInvariant() -cne $reportedHash
    ) {
        throw "Hashes redundantes do backup primário são divergentes."
    }
    foreach ($suffix in @("-journal", "-wal", "-shm")) {
        if (Test-Path -LiteralPath "$Path$suffix") {
            throw "Backup primário não foi consolidado em arquivo único."
        }
    }
    return [pscustomobject]@{
        Bytes = [long]$item.Length
        Sha256 = $localHash
        LogicalFingerprint = [string]$Result.logical_fingerprint
    }
}

function Assert-CliBackupArtifact {
    param(
        [Parameter(Mandatory)][string]$ExpectedPath,
        [Parameter(Mandatory)][object]$Result
    )
    $item = Assert-RegularPath `
        -Path $ExpectedPath `
        -Container $false `
        -Label "Backup secundário da CLI"
    $reportedPath = [IO.Path]::GetFullPath([string]$Result.backup_path)
    if (-not [string]::Equals(
        $reportedPath,
        [IO.Path]::GetFullPath($ExpectedPath),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "CLI reportou um backup secundário fora do caminho solicitado."
    }
    $expectedHash = ([string]$Result.backup_sha256).ToLowerInvariant()
    $localHash = (
        Get-FileHash -LiteralPath $ExpectedPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $item.Length -le 0 -or
        $expectedHash -notmatch '^[0-9a-f]{64}$' -or
        $localHash -cne $expectedHash
    ) {
        throw "Backup secundário da CLI falhou na validação local."
    }
    return $localHash
}

function Invoke-JsonCli {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ApplicationRoot,
        [Parameter(Mandatory)][ValidateSet("database-plan", "database-migrate")]
        [string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )
    Push-Location $ApplicationRoot
    try {
        $output = @(& $Python -m handball.cli $Command @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
        if ($AllowedExitCodes -notcontains $exitCode) {
            throw "CLI $Command falhou ($exitCode): $text"
        }
        try {
            return $text | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "CLI $Command não retornou JSON válido: $text"
        }
    }
    finally {
        Pop-Location
    }
}

function Assert-MigrationPlan {
    param(
        [Parameter(Mandatory)][object]$Plan,
        [Parameter(Mandatory)][string]$GuardFingerprint
    )
    $action = [string]$Plan.action
    if ($PlanningActions -cnotcontains $action) {
        throw "Plano retornou action fora da allowlist: '$action'."
    }
    if (
        [string]$Plan.plan_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$Plan.fingerprint_format -cne `
            "crepaldi-handball-logical-sqlite/v1" -or
        [string]$Plan.logical_fingerprint -notmatch '^[0-9a-f]{64}$' -or
        [string]$Plan.logical_fingerprint -cne $GuardFingerprint
    ) {
        throw "Plano não coincide com o fingerprint produzido pelo guard estável."
    }
    if ([int]$Plan.from_version -lt 0 -or [int]$Plan.to_version -lt 1) {
        throw "Plano contém intervalo de schema inválido."
    }
    return $action
}

function New-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][object]$Release,
        [Parameter(Mandatory)][string]$PlanSha256
    )
    $payload = [ordered]@{
        format = 1
        operation = "DB_MIGRATION"
        owner_token = $Token
        process_id = $PID
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        release_id = [string]$Release.ReleaseId
        release_generation = [int64]$Release.Generation
        plan_sha256 = $PlanSha256
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
        [string]$marker.operation -cne "DB_MIGRATION" -or
        [string]$marker.owner_token -cne $Token
    ) {
        throw "Marcador de manutenção não pertence a esta migration."
    }
    return $marker
}

function Remove-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Token
    )
    [void](Read-OwnedMaintenanceMarker -Path $Path -Token $Token)
    $retiredPath = "$Path.removed-$Token"
    if (Test-Path -LiteralPath $retiredPath) {
        throw "Destino interno de remoção do marcador já existe."
    }
    [IO.File]::Move($Path, $retiredPath, $false)
    try {
        [void](Read-OwnedMaintenanceMarker -Path $retiredPath -Token $Token)
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

function New-MaintenanceWindowMarker {
    param([Parameter(Mandatory)][string]$Path)

    $token = [guid]::NewGuid().ToString("N")
    $content = ([ordered]@{
        format = 1
        operation = "DB_MIGRATION_WINDOW"
        token = $token
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Compress) + "`n"
    try {
        Write-DurableUtf8File -Path $Path -Content $content
    }
    catch {
        throw "Modo de manutenção já existe ou não pôde ser criado: $Path"
    }
    return $token
}

function Remove-MaintenanceWindowMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Token
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Marcador de manutenção desapareceu antes da liberação."
    }
    try {
        $marker = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Marcador de manutenção foi alterado ou corrompido."
    }
    if ([string]$marker.token -cne $Token) {
        throw "Marcador de manutenção pertence a outra operação."
    }
    Remove-Item -LiteralPath $Path -Force
}

function Assert-ScheduledTaskAction {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][ValidateSet("run-server.ps1", "backup-server.ps1")]
        [string]$ScriptName
    )
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $actions = @($task.Actions)
    $expectedPwsh = [IO.Path]::GetFullPath((Get-Command pwsh.exe -ErrorAction Stop).Source)
    $expectedScript = Join-Path $Root "app\scripts\$ScriptName"
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
        throw "A ação de $TaskName não está na allowlist operacional."
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
        if ($task.State -ne "Running" -and -not $listener) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Servidor/tarefa não parou ou a porta 8765 continua ocupada."
}

function Wait-ExpectedReadiness {
    param([Parameter(Mandatory)][string]$ExpectedReleaseId)
    $lastResult = "sem resposta"
    $maximumAttempts = 900
    for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
        try {
            $ready = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/ready" `
                -TimeoutSec 5
            if (
                [string]$ready.status -ceq "ok" -and
                [string]$ready.database -ceq "ready" -and
                [string]$ready.release_id -ceq $ExpectedReleaseId
            ) { return }
            $lastResult = "readiness divergente"
        }
        catch {
            $lastResult = $_.Exception.Message
        }
        Start-Sleep -Seconds 1
    }
    throw "Readiness não confirmou '$ExpectedReleaseId': $lastResult"
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
            throw "O ponteiro ativo mudou durante a migration; restart recusado."
        }
    }
    return $current
}

function Assert-ReleaseSupportsSchema {
    param(
        [Parameter(Mandatory)][object]$Release,
        [Parameter(Mandatory)][int]$SchemaVersion
    )
    foreach ($property in @("SchemaMinimum", "SchemaMaximum")) {
        if (-not ($Release.PSObject.Properties.Name -contains $property)) {
            throw "Resolvedor não informou a compatibilidade de schema da release."
        }
    }
    if (
        $SchemaVersion -lt [int]$Release.SchemaMinimum -or
        $SchemaVersion -gt [int]$Release.SchemaMaximum
    ) {
        throw (
            "Release '$($Release.ReleaseId)' não aceita schema v$SchemaVersion " +
            "(intervalo $($Release.SchemaMinimum)..$($Release.SchemaMaximum))."
        )
    }
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
$WriteGateEntered = $false
$StoppedFingerprint = $null
$GuardBackupPath = $null
$CliBackupPath = $null
$Release = $null
try {
    if ($OpenMaintenanceWindow -or $CloseMaintenanceWindow) {
        if ($OpenMaintenanceWindow -and $CloseMaintenanceWindow) {
            throw (
                "-OpenMaintenanceWindow e -CloseMaintenanceWindow são " +
                "mutuamente exclusivos."
            )
        }
        if ($Apply) {
            throw (
                "-OpenMaintenanceWindow/-CloseMaintenanceWindow não podem " +
                "ser combinados com -Apply."
            )
        }
        $WindowInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
        $WindowMaintenanceFile = Join-Path $WindowInstallRoot "state\maintenance-mode"
        if ($OpenMaintenanceWindow) {
            $windowToken = New-MaintenanceWindowMarker -Path $WindowMaintenanceFile
            [ordered]@{ format = 1; token = $windowToken } | ConvertTo-Json -Compress
        }
        else {
            if ([string]::IsNullOrWhiteSpace($MaintenanceWindowToken)) {
                throw "-CloseMaintenanceWindow exige -MaintenanceWindowToken."
            }
            Remove-MaintenanceWindowMarker `
                -Path $WindowMaintenanceFile `
                -Token $MaintenanceWindowToken
            [ordered]@{ format = 1; closed = $true } | ConvertTo-Json -Compress
        }
        return
    }

    # Ponteiro, configuração e paths são relidos somente sob exclusão mútua.
    $ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    $Release = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if ($Release.Kind -cne "release") {
        throw (
            "O release legado não contém o runner formal. " +
            "Instale primeiro uma release APP_ONLY compatível."
        )
    }
    $ApplicationRoot = $Release.ApplicationRoot
    $Python = $Release.PythonPath
    $ReleaseId = $Release.ReleaseId
    $DataRoot = Join-Path $ResolvedInstallRoot "data"
    $BackupRoot = Join-Path $ResolvedInstallRoot "backups"
    $ConfigPath = Join-Path $DataRoot "app-config.json"
    $DbPath = Join-Path $DataRoot "presencas.db"
    $StateRoot = Join-Path $ResolvedInstallRoot "state"
    $MaintenanceFile = Join-Path $StateRoot "maintenance-mode"
    [void](Assert-RegularPath -Path $ConfigPath -Container $false -Label "Configuração")
    [void](Assert-RegularPath -Path $DbPath -Container $false -Label "Banco persistente")
    [void](Assert-RegularPath -Path $BackupRoot -Container $true -Label "Diretório de backups")
    [void](Assert-RegularPath -Path $StateRoot -Container $true -Label "Diretório de estado")
    [void](Assert-ScheduledTaskAction `
        -Root $ResolvedInstallRoot `
        -TaskName "CrepaldiHandball" `
        -ScriptName "run-server.ps1")
    $backupTask = Assert-ScheduledTaskAction `
        -Root $ResolvedInstallRoot `
        -TaskName "CrepaldiHandballBackup" `
        -ScriptName "backup-server.ps1"
    if ($backupTask.State -eq "Running") {
        throw "Backup agendado está em execução; tente novamente depois."
    }
    Assert-PersistentConfiguration `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath `
        -ExpectedBackupRoot $BackupRoot
    Set-FixedApplicationEnvironment `
        -ConfigPath $ConfigPath `
        -ReleaseId $ReleaseId `
        -MaintenanceFile $MaintenanceFile

    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $guardBeforePlan = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if ([string]$guardBeforePlan.quick_check -cne "ok") {
        throw "Migração recusada: quick_check prévio não retornou ok."
    }
    $GuardFingerprintBeforePlan = [string]$guardBeforePlan.logical_fingerprint

    $plan = Invoke-JsonCli `
        -Python $Python `
        -ApplicationRoot $ApplicationRoot `
        -Command "database-plan" `
        -Arguments @("--config-path", $ConfigPath) `
        -AllowedExitCodes @(0, 2)
    $action = Assert-MigrationPlan `
        -Plan $plan `
        -GuardFingerprint $GuardFingerprintBeforePlan

    if (-not $Apply) {
        $plan | ConvertTo-Json -Depth 10
        Write-Host ""
        Write-Host "Somente planejamento: nenhuma escrita foi executada."
        if ($WritableActions -ccontains $action) {
            Write-Host (
                "Para aplicar, repita com -Apply -ExpectedPlanSha256 " +
                "'$([string]$plan.plan_sha256)'."
            )
        }
        elseif ($action -cne "none") {
            Write-Host "Action '$action' não pertence à allowlist de escrita."
        }
        return
    }
    if ($action -ceq "none") {
        Write-Host "Banco já está no schema esperado; nenhuma migration aplicada."
        return
    }
    if ($WritableActions -cnotcontains $action) {
        throw "Aplicação recusada: action '$action' não pode escrever."
    }
    if (
        $ExpectedPlanSha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$plan.plan_sha256 -cne $ExpectedPlanSha256
    ) {
        throw (
            "Plano não confirmado. Execute sem -Apply e informe exatamente " +
            "-ExpectedPlanSha256 '$([string]$plan.plan_sha256)'."
        )
    }
    Assert-ReleaseSupportsSchema `
        -Release $Release `
        -SchemaVersion ([int]$plan.to_version)

    if (Test-Path -LiteralPath $MaintenanceFile) {
        throw "Migração recusada: modo de manutenção já está ativo."
    }
    $MaintenanceToken = [guid]::NewGuid().ToString("N")
    $MaintenanceCreationAttempted = $true
    New-OwnedMaintenanceMarker `
        -Path $MaintenanceFile `
        -Token $MaintenanceToken `
        -Release $Release `
        -PlanSha256 $ExpectedPlanSha256
    $MaintenanceOwned = $true

    $StopAttempted = $true
    Stop-HandballServer
    $Release = Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release
    Assert-PersistentConfiguration `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath `
        -ExpectedBackupRoot $BackupRoot
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $stoppedVerification = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if ([string]$stoppedVerification.quick_check -cne "ok") {
        throw "quick_check com serviço parado não retornou ok."
    }
    $StoppedFingerprint = [string]$stoppedVerification.logical_fingerprint

    $stoppedPlan = Invoke-JsonCli `
        -Python $Python `
        -ApplicationRoot $ApplicationRoot `
        -Command "database-plan" `
        -Arguments @("--config-path", $ConfigPath) `
        -AllowedExitCodes @(0, 2)
    $stoppedAction = Assert-MigrationPlan `
        -Plan $stoppedPlan `
        -GuardFingerprint $StoppedFingerprint
    if (
        $WritableActions -cnotcontains $stoppedAction -or
        [string]$stoppedPlan.plan_sha256 -cne $ExpectedPlanSha256
    ) {
        throw "O banco ou o catálogo de migrations mudou; operação recusada."
    }

    $fromVersion = [int]$stoppedPlan.from_version
    $toVersion = [int]$stoppedPlan.to_version
    $migrationStamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
    $GuardBackupPath = Join-Path $BackupRoot (
        "migration-guard-v$fromVersion-to-v$toVersion-$migrationStamp.db"
    )
    $CliBackupPath = Join-Path $BackupRoot (
        "migration-cli-v$fromVersion-to-v$toVersion-$migrationStamp.db"
    )
    foreach ($backupPath in @($GuardBackupPath, $CliBackupPath)) {
        if (Test-Path -LiteralPath $backupPath) {
            throw "Backup pré-migration já existe: $backupPath"
        }
    }

    # Backup primário: implementação estável, stdlib-only e isolada da aplicação.
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $guardBackupResult = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "backup",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath,
            "--expected-backup-root", $BackupRoot,
            "--destination", $GuardBackupPath,
            "--expected-fingerprint", $StoppedFingerprint
        )
    $guardBackup = Assert-BackupArtifact `
        -Path $GuardBackupPath `
        -Result $guardBackupResult
    if ($guardBackup.LogicalFingerprint -cne $StoppedFingerprint) {
        throw "Backup primário não corresponde ao baseline parado."
    }
    $fingerprintAfterBackup = Get-GuardFingerprint `
        -Runtime $GuardRuntime `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath
    if ($fingerprintAfterBackup -cne $StoppedFingerprint) {
        throw "Banco mudou durante a criação do backup primário."
    }

    # Recalcula imediatamente antes do gate; a CLI ainda exige seu próprio
    # --backup-path, preservado como segundo artefato independente.
    $finalPlan = Invoke-JsonCli `
        -Python $Python `
        -ApplicationRoot $ApplicationRoot `
        -Command "database-plan" `
        -Arguments @("--config-path", $ConfigPath) `
        -AllowedExitCodes @(0, 2)
    $finalAction = Assert-MigrationPlan `
        -Plan $finalPlan `
        -GuardFingerprint $StoppedFingerprint
    if (
        $WritableActions -cnotcontains $finalAction -or
        [string]$finalPlan.plan_sha256 -cne $ExpectedPlanSha256
    ) {
        throw "Plano mudou após o backup primário; operação recusada."
    }
    [void](Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release)

    $WriteGateEntered = $true
    $result = Invoke-JsonCli `
        -Python $Python `
        -ApplicationRoot $ApplicationRoot `
        -Command "database-migrate" `
        -Arguments @(
            "--config-path", $ConfigPath,
            "--apply",
            "--expected-plan-sha256", [string]$finalPlan.plan_sha256,
            "--expected-fingerprint", $StoppedFingerprint,
            "--backup-path", $CliBackupPath,
            "--app-version", $ReleaseId
        )
    if (
        [string]$result.status -cne "applied" -or
        [string]$result.verification.quick_check -cne "ok" -or
        -not [bool]$result.verification.ok
    ) {
        throw "Verificação pós-migration da CLI reprovada."
    }
    $cliBackupSha256 = Assert-CliBackupArtifact `
        -ExpectedPath $CliBackupPath `
        -Result $result

    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release
    $postVerification = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if (
        [string]$postVerification.quick_check -cne "ok" -or
        [string]$postVerification.logical_fingerprint -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Guard estável reprovou o banco após a migration."
    }
    $postPlan = Invoke-JsonCli `
        -Python $Python `
        -ApplicationRoot $ApplicationRoot `
        -Command "database-plan" `
        -Arguments @("--config-path", $ConfigPath)
    $postAction = Assert-MigrationPlan `
        -Plan $postPlan `
        -GuardFingerprint ([string]$postVerification.logical_fingerprint)
    if ($postAction -cne "none" -or -not [bool]$postPlan.compatible_with_application) {
        throw "Banco migrado ainda não é compatível com a aplicação ativa."
    }
    Assert-ReleaseSupportsSchema `
        -Release $Release `
        -SchemaVersion ([int]$postPlan.to_version)

    $Release = Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release
    [void](Read-OwnedMaintenanceMarker `
        -Path $MaintenanceFile `
        -Token $MaintenanceToken)
    $StartAttempted = $true
    Start-ScheduledTask -TaskName "CrepaldiHandball"
    Wait-ExpectedReadiness -ExpectedReleaseId $ReleaseId
    $postStartupFingerprint = Get-GuardFingerprint `
        -Runtime $GuardRuntime `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath
    if ($postStartupFingerprint -cne [string]$postVerification.logical_fingerprint) {
        throw "Startup alterou o banco recém-migrado; serviço será parado."
    }
    [void](Assert-ReleasePointerUnchanged `
        -Root $ResolvedInstallRoot `
        -Expected $Release)
    Remove-OwnedMaintenanceMarker `
        -Path $MaintenanceFile `
        -Token $MaintenanceToken
    $MaintenanceOwned = $false

    Write-Host "Migration concluída separadamente da atualização da aplicação."
    Write-Host "Esquema: v$fromVersion -> v$toVersion"
    Write-Host "Backup primário do guard: $GuardBackupPath"
    Write-Host "SHA-256 primário: $($guardBackup.Sha256)"
    Write-Host "Backup secundário da CLI: $CliBackupPath"
    Write-Host "SHA-256 secundário: $cliBackupSha256"
}
catch {
    $failure = $_
    $markerMayBeOurs = (
        $MaintenanceCreationAttempted -and
        $MaintenanceFile -and
        (Test-Path -LiteralPath $MaintenanceFile)
    )
    if (-not ($MaintenanceOwned -or $markerMayBeOurs -or $StopAttempted -or $StartAttempted)) {
        throw $failure
    }

    try {
        Stop-HandballServer
    }
    catch {
        throw (
            "Migration falhou e a parada do serviço não pôde ser confirmada. " +
            "Nenhum restore foi feito; marcador preservado. Falha original: " +
            "$($failure.Exception.Message); stop: $($_.Exception.Message)"
        )
    }

    $databaseUnchanged = $false
    if ($StoppedFingerprint -and $Release) {
        try {
            $RecoveryRuntime = Resolve-VerifiedGuardRuntime `
                -Root $ResolvedInstallRoot `
                -Release $Release
            $recoveryFingerprint = Get-GuardFingerprint `
                -Runtime $RecoveryRuntime `
                -ConfigPath $ConfigPath `
                -ExpectedDbPath $DbPath
            $databaseUnchanged = $recoveryFingerprint -ceq $StoppedFingerprint
        }
        catch {
            $databaseUnchanged = $false
        }
    }

    # Antes ou depois do gate, só há restart quando o guard estável prova que
    # o SQLite continua exatamente no baseline parado. Nunca há auto-restore.
    if ($databaseUnchanged -and $MaintenanceOwned) {
        $recoveredSafely = $false
        try {
            $Release = Assert-ReleasePointerUnchanged `
                -Root $ResolvedInstallRoot `
                -Expected $Release
            [void](Read-OwnedMaintenanceMarker `
                -Path $MaintenanceFile `
                -Token $MaintenanceToken)
            Start-ScheduledTask -TaskName "CrepaldiHandball"
            Wait-ExpectedReadiness -ExpectedReleaseId $Release.ReleaseId
            $restartedFingerprint = Get-GuardFingerprint `
                -Runtime $RecoveryRuntime `
                -ConfigPath $ConfigPath `
                -ExpectedDbPath $DbPath
            if ($restartedFingerprint -cne $StoppedFingerprint) {
                throw "Startup de recuperação alterou o banco."
            }
            Remove-OwnedMaintenanceMarker `
                -Path $MaintenanceFile `
                -Token $MaintenanceToken
            $MaintenanceOwned = $false
            $recoveredSafely = $true
        }
        catch {
            $recoveryFailure = $_
            try { Stop-HandballServer } catch { }
            throw (
                "Migration falhou; a recuperação segura também falhou. Serviço " +
                "e marcador foram mantidos. Nenhum restore foi feito. Falha " +
                "original: $($failure.Exception.Message); recuperação: " +
                "$($recoveryFailure.Exception.Message)"
            )
        }
        if ($recoveredSafely) {
            throw $failure
        }
    }

    $gateDescription = if ($WriteGateEntered) {
        "após o gate de escrita"
    }
    else {
        "antes do gate de escrita"
    }
    throw (
        "Migration falhou $gateDescription; o serviço e o marcador de " +
        "manutenção foram mantidos porque a preservação do banco não foi " +
        "comprovada. Nenhum restore automático foi feito. Backup primário: " +
        "$GuardBackupPath. Backup da CLI: $CliBackupPath. Falha: " +
        "$($failure.Exception.Message)"
    )
}
finally {
    $LockStream.Dispose()
}
