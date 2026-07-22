param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball",
    [int]$Keep = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

. (Join-Path $PSScriptRoot "release-resolver.ps1")

function Enter-MaintenanceLock {
    param([Parameter(Mandatory)][string]$Root)

    $lockPath = Join-Path $Root ".maintenance.lock"
    try {
        return [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw "Outra manutenção está em andamento: $lockPath"
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
        throw "Manifesto operacional inválido: $manifestPath"
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

    $guardEntries = @(
        $manifest.files |
            Where-Object { [string]$_.path -ceq "ops/database-guard.py" }
    )
    if ($guardEntries.Count -ne 1) {
        throw "Manifesto operacional não autentica exatamente um database guard."
    }
    $expectedGuardHash = ([string]$guardEntries[0].sha256).ToLowerInvariant()
    if ($expectedGuardHash -notmatch '^[0-9a-f]{64}$') {
        throw "SHA-256 do database guard é inválido no manifesto operacional."
    }
    $observedGuardHash = (
        Get-FileHash -LiteralPath $guardPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($observedGuardHash -cne $expectedGuardHash) {
        throw "Database guard diverge do manifesto operacional."
    }
    if (
        -not ($guardEntries[0].PSObject.Properties.Name -contains "bytes") -or
        [long]$guardEntries[0].bytes -le 0
    ) {
        throw "Manifesto operacional não informa os bytes do database guard."
    }
    $guardInfo = Get-Item -LiteralPath $guardPath -Force
    if ($guardInfo.Length -ne [long]$guardEntries[0].bytes) {
        throw "Tamanho do database guard diverge do manifesto operacional."
    }

    $pythonValue = [string]$manifest.guard_python_path
    $expectedPythonHash = ([string]$manifest.guard_python_sha256).ToLowerInvariant()
    if (
        [string]::IsNullOrWhiteSpace($pythonValue) -or
        -not [IO.Path]::IsPathFullyQualified($pythonValue) -or
        $expectedPythonHash -notmatch '^[0-9a-f]{64}$'
    ) {
        throw (
            "Manifesto operacional não autentica guard_python_path e " +
            "guard_python_sha256."
        )
    }
    $pythonPath = [IO.Path]::GetFullPath($pythonValue)
    [void](Assert-RegularPath -Path $pythonPath -Container $false -Label "Python do guard")
    $observedPythonHash = (
        Get-FileHash -LiteralPath $pythonPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($observedPythonHash -cne $expectedPythonHash) {
        throw "Interpretador do database guard diverge do manifesto operacional."
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

function Assert-BackupArtifact {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Result
    )

    $item = Assert-RegularPath -Path $Path -Container $false -Label "Backup publicado"
    $expectedPath = [IO.Path]::GetFullPath($Path)
    $observedPath = [IO.Path]::GetFullPath($item.FullName)
    if (-not [string]::Equals(
        $observedPath,
        $expectedPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Backup publicado em caminho diferente do solicitado."
    }

    $reportedHash = [string]$Result.sha256
    if ([string]::IsNullOrWhiteSpace($reportedHash)) {
        $reportedHash = [string]$Result.backup_sha256
    }
    $reportedHash = $reportedHash.ToLowerInvariant()
    if (
        $reportedHash -notmatch '^[0-9a-f]{64}$' -or
        [long]$Result.backup_bytes -le 0 -or
        [string]$Result.quick_check -cne "ok" -or
        [string]$Result.logical_fingerprint -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Database guard não comprovou tamanho, hash, integridade e fingerprint."
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$Result.backup_sha256) -and
        ([string]$Result.backup_sha256).ToLowerInvariant() -cne $reportedHash
    ) {
        throw "Hashes redundantes do database guard são divergentes."
    }
    $observedHash = (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $item.Length -ne [long]$Result.backup_bytes -or
        $observedHash -cne $reportedHash
    ) {
        throw "Backup local diverge do tamanho ou SHA-256 informado pelo guard."
    }
    foreach ($suffix in @("-journal", "-wal", "-shm")) {
        if (Test-Path -LiteralPath "$Path$suffix") {
            throw "Backup não foi consolidado em arquivo SQLite único."
        }
    }

    return [pscustomobject]@{
        Bytes = [long]$item.Length
        Sha256 = $observedHash
        LogicalFingerprint = [string]$Result.logical_fingerprint
    }
}

function Write-DurableUtf8File {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Content)
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

function Get-BackupAuditPath {
    param([Parameter(Mandatory)][string]$DatabasePath)
    return [IO.Path]::ChangeExtension($DatabasePath, ".audit.json")
}

# Resolve-ExactInstallRoot não consulta release nem configuração. O lock é
# adquirido antes de qualquer leitura de estado operacional/persistente.
$InitialInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
$LockStream = Enter-MaintenanceLock -Root $InitialInstallRoot
try {
    $ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    $Release = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if ($Release.Kind -cne "release") {
        throw "Backup recusado: release legado não é aceito pelo fluxo persistente."
    }

    $DataRoot = Join-Path $ResolvedInstallRoot "data"
    $ConfigPath = Join-Path $DataRoot "app-config.json"
    $DbPath = Join-Path $DataRoot "presencas.db"
    $BackupRoot = Join-Path $ResolvedInstallRoot "backups"
    [void](Assert-RegularPath -Path $ConfigPath -Container $false -Label "Configuração")
    [void](Assert-RegularPath -Path $DbPath -Container $false -Label "Banco persistente")
    [void](Assert-RegularPath -Path $BackupRoot -Container $true -Label "Diretório de backups")
    $GuardRuntime = Resolve-VerifiedGuardRuntime `
        -Root $ResolvedInstallRoot `
        -Release $Release

    $timestamp = [DateTime]::Now.ToString("yyyyMMdd-HHmmss-fff")
    $destination = Join-Path $BackupRoot "presencas-$timestamp.db"
    $auditPath = Get-BackupAuditPath -DatabasePath $destination
    if (
        (Test-Path -LiteralPath $destination) -or
        (Test-Path -LiteralPath $auditPath)
    ) {
        throw "Par de backup já existe para o timestamp selecionado."
    }

    $result = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "backup",
            "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath,
            "--expected-backup-root", $BackupRoot,
            "--destination", $destination
        )
    $artifact = Assert-BackupArtifact -Path $destination -Result $result

    $audit = [ordered]@{
        format = "crepaldi-handball-backup-audit/v1"
        guard_format = [string]$result.format
        guard_sha256 = [string]$GuardRuntime.GuardSha256
        guard_python_sha256 = [string]$GuardRuntime.PythonSha256
        fingerprint_format = [string]$result.fingerprint_format
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        release_id = [string]$Release.ReleaseId
        release_generation = [int64]$Release.Generation
        database_file = [IO.Path]::GetFileName($destination)
        logical_fingerprint = [string]$artifact.LogicalFingerprint
        bytes = [long]$artifact.Bytes
        sha256 = [string]$artifact.Sha256
        quick_check = [string]$result.quick_check
        foreign_key_check = @($result.foreign_key_check)
    }
    $auditContent = ($audit | ConvertTo-Json -Depth 6) + "`n"
    $auditTemporaryPath = Join-Path $BackupRoot (
        ".{0}.{1}.partial" -f `
            ([IO.Path]::GetFileName($auditPath)),
            [guid]::NewGuid().ToString("N")
    )
    try {
        Write-DurableUtf8File -Path $auditTemporaryPath -Content $auditContent
        [IO.File]::Move($auditTemporaryPath, $auditPath, $false)
    }
    finally {
        if (Test-Path -LiteralPath $auditTemporaryPath) {
            Remove-Item -LiteralPath $auditTemporaryPath -Force
        }
    }

    $backups = @(
        Get-ChildItem -LiteralPath $BackupRoot -Filter "presencas-*.db" -File |
            Sort-Object Name -Descending
    )
    $retention = [Math]::Max($Keep, 1)
    $expiredBackups = @($backups | Select-Object -Skip $retention)
    $expiredPairs = @(
        foreach ($oldBackup in $expiredBackups) {
            [void](Assert-RegularPath `
                -Path $oldBackup.FullName `
                -Container $false `
                -Label "Backup expirado")
            $oldAudit = Get-BackupAuditPath -DatabasePath $oldBackup.FullName
            [void](Assert-RegularPath `
                -Path $oldAudit `
                -Container $false `
                -Label "Sidecar do backup expirado")
            [pscustomobject]@{ Database = $oldBackup.FullName; Audit = $oldAudit }
        }
    )
    foreach ($expiredPair in $expiredPairs) {
        Remove-Item -LiteralPath $expiredPair.Database -Force
        Remove-Item -LiteralPath $expiredPair.Audit -Force
    }

    Write-Host "Backup verificado: $destination"
    Write-Host "Sidecar auditável: $auditPath"
    Write-Host "SHA-256: $($artifact.Sha256)"
}
finally {
    $LockStream.Dispose()
}
