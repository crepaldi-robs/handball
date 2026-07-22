param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball",
    [string]$ReleaseId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

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

function Set-PrivateDirectoryAcl {
    param([Parameter(Mandatory)][string]$Path)
    $systemGrant = "*S-1-5-18:(OI)(CI)F"
    $administratorsGrant = "*S-1-5-32-544:(OI)(CI)F"
    & icacls.exe $Path /inheritance:r /grant:r `
        $systemGrant $administratorsGrant /T /C |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível proteger as permissões de $Path."
    }
}

function Assert-CleanTrackedSources {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string[]]$Items
    )
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git é obrigatório para montar um release auditável."
    }
    $status = @(& git -C $ProjectRoot status --porcelain=v1 --untracked-files=all -- $Items)
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao verificar o estado Git do runtime."
    }
    if ($status.Count -gt 0) {
        throw (
            "Runtime/ops possui alterações não commitadas; instalação recusada: " +
            (($status | ForEach-Object { "$_".Trim() }) -join ", ")
        )
    }
}

function Copy-ReleaseSources {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$DestinationRoot,
        [Parameter(Mandatory)][string[]]$SourceItems,
        [Parameter(Mandatory)][string]$SourceCommit
    )
    $trackedFiles = @(
        & git -C $ProjectRoot ls-tree -r --name-only $SourceCommit -- $SourceItems |
            ForEach-Object { ("$_").Trim().Replace("\", "/") } |
            Where-Object { $_ } |
            Sort-Object -Unique
    )
    if ($LASTEXITCODE -ne 0 -or $trackedFiles.Count -eq 0) {
        throw "Falha ao enumerar o runtime rastreado."
    }
    foreach ($requiredItem in $SourceItems) {
        $covered = @(
            $trackedFiles | Where-Object {
                $_ -ceq $requiredItem -or $_.StartsWith("$requiredItem/")
            }
        )
        if ($covered.Count -eq 0) {
            throw "Item obrigatório sem arquivo rastreado: $requiredItem"
        }
    }
    $archivePath = Join-Path $DestinationRoot (
        ".source-$([guid]::NewGuid().ToString('N')).zip"
    )
    try {
        & git -C $ProjectRoot archive `
            --format=zip `
            --output=$archivePath `
            $SourceCommit `
            -- `
            $SourceItems
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao materializar o snapshot imutável do commit."
        }
        Expand-Archive `
            -LiteralPath $archivePath `
            -DestinationPath $DestinationRoot `
            -Force
    }
    finally {
        if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
            Remove-Item -LiteralPath $archivePath -Force
        }
    }
    foreach ($relativePath in $trackedFiles) {
        $destination = Join-Path $DestinationRoot $relativePath
        Assert-RegularFileWithoutReparsePoint -Path $destination
    }
    return $trackedFiles
}

function Install-OperationalFiles {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Mappings,
        [Parameter(Mandatory)][string]$SourceCommit,
        [Parameter(Mandatory)][string]$GuardPython
    )
    $entries = @()
    foreach ($sourceRelative in ($Mappings.Keys | Sort-Object)) {
        $source = Join-Path $ProjectRoot $sourceRelative
        $destinationRelative = [string]$Mappings[$sourceRelative]
        $destination = Join-Path $InstallRoot $destinationRelative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Arquivo operacional ausente: $source"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) |
            Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $entries += [ordered]@{
            path = $destinationRelative.Replace("\", "/")
            bytes = [int64](Get-Item -LiteralPath $destination).Length
            sha256 = (
                Get-FileHash -LiteralPath $destination -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
    }
    $manifestPath = Join-Path $InstallRoot "ops\ops-manifest.json"
    [ordered]@{
        format = 1
        protocol = 1
        source_commit = $SourceCommit
        installed_at_utc = [DateTime]::UtcNow.ToString("o")
        guard_python_path = $GuardPython
        guard_python_sha256 = (
            Get-FileHash -LiteralPath $GuardPython -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        files = $entries
    } | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $manifestPath -Encoding utf8
}

function Get-GuardPython {
    $output = @(
        & py -3.13 -I -S -c "import sys; print(sys.executable)" 2>$null
    )
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) {
        throw "Python 3.13 operacional não pôde ser resolvido."
    }
    $path = [IO.Path]::GetFullPath(("$($output[0])").Trim())
    Assert-RegularFileWithoutReparsePoint -Path $path
    return $path
}

function Remove-ApplicationBuildCaches {
    param([Parameter(Mandatory)][string]$ReleaseRoot)

    $root = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath($ReleaseRoot)
    )
    $prefix = $root + [IO.Path]::DirectorySeparatorChar
    $venvPrefix = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath((Join-Path $root ".venv"))
    ) + [IO.Path]::DirectorySeparatorChar
    foreach ($cache in @(
        Get-ChildItem -LiteralPath $root -Directory -Filter "__pycache__" -Recurse |
            Where-Object {
                -not $_.FullName.StartsWith(
                    $venvPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
    )) {
        $cachePath = [IO.Path]::GetFullPath($cache.FullName)
        if (
            -not $cachePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
            $cache.Attributes -band [IO.FileAttributes]::ReparsePoint
        ) {
            throw "Limpeza de cache recusada fora do stage: $cachePath"
        }
        Remove-Item -LiteralPath $cachePath -Recurse -Force
    }
}

function Get-ReleaseSchemaCompatibility {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ApplicationRoot
    )

    Push-Location $ApplicationRoot
    try {
        $output = @(& $Python -m attendance.cli release-contract 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "Release não emitiu contrato de schema ($exitCode): $text"
    }
    try {
        $contract = $text | ConvertFrom-Json -ErrorAction Stop
        $minimum = [int64]$contract.schema_compatibility.minimum
        $maximum = [int64]$contract.schema_compatibility.maximum
    }
    catch {
        throw "Contrato de schema inválido: $text"
    }
    if ([int64]$contract.format -ne 1 -or $minimum -lt 1 -or $maximum -lt $minimum) {
        throw "Faixa de compatibilidade de schema inválida: $text"
    }
    return [pscustomobject]@{
        Minimum = $minimum
        Maximum = $maximum
    }
}

function Invoke-GuardJson {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$GuardPath,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $output = @(& $Python -I -S $GuardPath @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "Database guard falhou ($exitCode): $text"
    }
    try {
        return $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Database guard não retornou JSON válido: $text"
    }
}

function Wait-ExpectedReadiness {
    param([Parameter(Mandatory)][string]$ExpectedReleaseId)
    $lastResult = "sem resposta"
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $ready = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/ready" `
                -TimeoutSec 5
            if (
                [string]$ready.status -ceq "ok" -and
                [string]$ready.release_id -ceq $ExpectedReleaseId
            ) { return }
            $lastResult = "release_id divergente"
        }
        catch { $lastResult = $_.Exception.Message }
        Start-Sleep -Seconds 1
    }
    throw "Readiness não confirmou '$ExpectedReleaseId': $lastResult"
}

Assert-Administrator
$ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeItems = @("app.py", "requirements.txt", "attendance", "templates", "static")
$OperationalMappings = [ordered]@{
    "scripts/run-server.ps1" = "app/scripts/run-server.ps1"
    "scripts/backup-server.ps1" = "app/scripts/backup-server.ps1"
    "scripts/reset-password.ps1" = "app/scripts/reset-password.ps1"
    "scripts/update-server.ps1" = "app/scripts/update-server.ps1"
    "scripts/migrate-database.ps1" = "app/scripts/migrate-database.ps1"
    "scripts/release-resolver.ps1" = "app/scripts/release-resolver.ps1"
    "scripts/database-guard.py" = "ops/database-guard.py"
}
$AllSources = @($RuntimeItems + @($OperationalMappings.Keys))
Assert-CleanTrackedSources -ProjectRoot $ProjectRoot -Items $AllSources

if (Test-Path -LiteralPath $ResolvedInstallRoot) {
    if (@(Get-ChildItem -LiteralPath $ResolvedInstallRoot -Force).Count -gt 0) {
        throw (
            "Instalação existente detectada. Use scripts\update-server.ps1; " +
            "o bootstrap não sobrescreve estado persistente."
        )
    }
}
else {
    New-Item -ItemType Directory -Path $ResolvedInstallRoot | Out-Null
}

# Protege a raiz antes de gravar configuração, banco, código ou ponteiros.
Set-PrivateDirectoryAcl -Path $ResolvedInstallRoot
$LockStream = Enter-MaintenanceLock -Root $ResolvedInstallRoot
$ReleaseRoot = $null
$ReleasePublished = $false
$ServerTaskRegistered = $false
$BackupTaskRegistered = $false
$InstallSucceeded = $false
try {
    foreach ($taskName in @("CrepaldiHandball", "CrepaldiHandballBackup")) {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            throw "Instalação inicial recusada: tarefa já existe: $taskName"
        }
    }
    $AppRoot = Join-Path $ResolvedInstallRoot "app"
    $DataRoot = Join-Path $ResolvedInstallRoot "data"
    $BackupRoot = Join-Path $ResolvedInstallRoot "backups"
    $LogRoot = Join-Path $ResolvedInstallRoot "logs"
    $ReleasesRoot = Join-Path $ResolvedInstallRoot "releases"
    $StateRoot = Join-Path $ResolvedInstallRoot "state"
    $OpsRoot = Join-Path $ResolvedInstallRoot "ops"
    foreach ($directory in @(
        $AppRoot, $DataRoot, $BackupRoot, $LogRoot,
        $ReleasesRoot, $StateRoot, $OpsRoot
    )) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    $sourceCommit = (@(& git -C $ProjectRoot rev-parse --verify HEAD) -join "").Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Commit de origem inválido."
    }
    $releaseStamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
        $ReleaseId = "$($sourceCommit.Substring(0, 12))-$releaseStamp"
    }
    if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "ReleaseId inválido."
    }
    [void](Assert-SafeReleaseId -ReleaseId $ReleaseId)
    $FinalReleaseRoot = Join-Path $ReleasesRoot $ReleaseId
    if (Test-Path -LiteralPath $FinalReleaseRoot) {
        throw "Release já existe: $FinalReleaseRoot"
    }
    $ReleaseRoot = Join-Path $ReleasesRoot (
        ".stage-$ReleaseId-$([guid]::NewGuid().ToString('N'))"
    )
    New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
    $SourceFiles = @(Copy-ReleaseSources `
        -ProjectRoot $ProjectRoot `
        -DestinationRoot $ReleaseRoot `
        -SourceItems $RuntimeItems `
        -SourceCommit $sourceCommit)

    $Python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
    & py -3.13 -m venv (Join-Path $ReleaseRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar venv do release inicial." }
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip." }
    & $Python -m pip install -r (Join-Path $ReleaseRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências." }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependências inconsistentes." }
    Push-Location $ReleaseRoot
    try {
        & $Python -m compileall -q app.py attendance
        if ($LASTEXITCODE -ne 0) { throw "Compilação Python falhou." }
    }
    finally { Pop-Location }
    Remove-ApplicationBuildCaches -ReleaseRoot $ReleaseRoot
    $SchemaCompatibility = Get-ReleaseSchemaCompatibility `
        -Python $Python `
        -ApplicationRoot $ReleaseRoot

    $ConfigPath = Join-Path $DataRoot "app-config.json"
    $DbPath = Join-Path $DataRoot "presencas.db"
    Push-Location $ReleaseRoot
    try {
        & $Python -m attendance.cli init `
            --config-path $ConfigPath `
            --db-path $DbPath `
            --backup-dir $BackupRoot `
            --secure-cookie
        if ($LASTEXITCODE -ne 0) { throw "Falha ao criar configuração inicial." }
        & $Python -m attendance.cli init-database --config-path $ConfigPath
        if ($LASTEXITCODE -ne 0) { throw "Falha no bootstrap explícito do banco." }
    }
    finally { Pop-Location }

    $GuardPython = Get-GuardPython
    $OpsSourceRoot = Join-Path $StateRoot (
        ".ops-source-$([guid]::NewGuid().ToString('N'))"
    )
    New-Item -ItemType Directory -Path $OpsSourceRoot | Out-Null
    try {
        [void](Copy-ReleaseSources `
            -ProjectRoot $ProjectRoot `
            -DestinationRoot $OpsSourceRoot `
            -SourceItems @($OperationalMappings.Keys) `
            -SourceCommit $sourceCommit)
        Install-OperationalFiles `
            -ProjectRoot $OpsSourceRoot `
            -InstallRoot $ResolvedInstallRoot `
            -Mappings $OperationalMappings `
            -SourceCommit $sourceCommit `
            -GuardPython $GuardPython
    }
    finally {
        if (Test-Path -LiteralPath $OpsSourceRoot -PathType Container) {
            $opsSourceParent = [IO.Path]::GetFullPath(
                (Split-Path -Parent $OpsSourceRoot)
            )
            if (-not [string]::Equals(
                $opsSourceParent,
                [IO.Path]::GetFullPath($StateRoot),
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Limpeza do snapshot operacional recusada fora de state."
            }
            Remove-Item -LiteralPath $OpsSourceRoot -Recurse -Force
        }
    }
    $GuardPath = Join-Path $OpsRoot "database-guard.py"
    $verification = Invoke-GuardJson `
        -Python $GuardPython `
        -GuardPath $GuardPath `
        -Arguments @(
            "verify", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if (-not [bool]$verification.ok -or [string]$verification.quick_check -cne "ok") {
        throw "Banco inicial reprovado pelo guard operacional."
    }
    $InitialFingerprint = [string]$verification.logical_fingerprint
    # As CLIs de bootstrap já terminaram. O payload formal não admite caches
    # Python não inventariados, mesmo que algum subprocesso ignore a variável.
    Remove-ApplicationBuildCaches -ReleaseRoot $ReleaseRoot

    [string[]]$SortedSourceFiles = @($SourceFiles)
    [Array]::Sort($SortedSourceFiles, [StringComparer]::Ordinal)
    $PayloadFiles = @(
        foreach ($relativePath in $SortedSourceFiles) {
            $payloadPath = Join-Path $ReleaseRoot $relativePath
            [ordered]@{
                path = $relativePath
                bytes = (Get-Item -LiteralPath $payloadPath).Length
                sha256 = (
                    Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256
                ).Hash.ToLowerInvariant()
            }
        }
    )
    $payloadCanonical = (
        $PayloadFiles |
            ForEach-Object { "$($_.path)`t$($_.bytes)`t$($_.sha256)" }
    ) -join "`n"
    $payloadBytes = [Text.Encoding]::UTF8.GetBytes("$payloadCanonical`n")
    $payloadHash = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($payloadBytes)
    ).ToLowerInvariant()
    $EnvironmentEvidence = New-ReleaseEnvironmentManifest `
        -ApplicationRoot $ReleaseRoot
    $manifest = [ordered]@{
        format = 1
        release_id = $ReleaseId
        installed_at_utc = [DateTime]::UtcNow.ToString("o")
        install_kind = "initial"
        database_action = "bootstrap"
        source_commit = $sourceCommit
        environment_manifest = "environment-files.json"
        environment_manifest_sha256 = $EnvironmentEvidence.ManifestSha256
        environment_sha256 = $EnvironmentEvidence.EnvironmentSha256
        payload_sha256 = $payloadHash
        source_files = $SourceFiles
        payload_files = $PayloadFiles
        schema_compatibility = [ordered]@{
            minimum = $SchemaCompatibility.Minimum
            maximum = $SchemaCompatibility.Maximum
        }
        database_fingerprint_after_bootstrap = $InitialFingerprint
    }
    $ManifestPath = Join-Path $ReleaseRoot "release-manifest.json"
    Write-DurableUtf8File `
        -Path $ManifestPath `
        -Content (($manifest | ConvertTo-Json -Depth 7) + "`n")
    $manifestHash = (
        Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    [IO.Directory]::Move($ReleaseRoot, $FinalReleaseRoot)
    $ReleaseRoot = $FinalReleaseRoot
    $ReleasePublished = $true
    $Python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"

    $pointer = @{
        format = 1
        generation = 1
        release_id = $ReleaseId
        kind = "release"
        application_relative_path = "releases/$ReleaseId"
        python_relative_path = "releases/$ReleaseId/.venv/Scripts/python.exe"
        manifest_sha256 = $manifestHash
    }
    [void](Set-ActiveReleasePointer `
        -InstallRoot $ResolvedInstallRoot `
        -Pointer $pointer)

    # Toda a instalação fica gravável apenas por SYSTEM/Administrators.
    # Isso inclui código, ponteiros, ops e os diretórios persistentes.
    Set-PrivateDirectoryAcl -Path $ResolvedInstallRoot
    $Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    $ServerScript = Join-Path $AppRoot "scripts\run-server.ps1"
    $BackupScript = Join-Path $AppRoot "scripts\backup-server.ps1"
    $ServerAction = New-ScheduledTaskAction -Execute $Pwsh -Argument (
        '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f `
            $ServerScript, $ResolvedInstallRoot
    )
    $BackupAction = New-ScheduledTaskAction -Execute $Pwsh -Argument (
        '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f `
            $BackupScript, $ResolvedInstallRoot
    )
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $ServerSettings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $BackupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
    Register-ScheduledTask `
        -TaskName "CrepaldiHandball" `
        -Action $ServerAction `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Principal $principal `
        -Settings $ServerSettings `
        -Force | Out-Null
    $ServerTaskRegistered = $true
    Register-ScheduledTask `
        -TaskName "CrepaldiHandballBackup" `
        -Action $BackupAction `
        -Trigger (New-ScheduledTaskTrigger -Daily -At 3am) `
        -Principal $principal `
        -Settings $BackupSettings `
        -Force | Out-Null
    $BackupTaskRegistered = $true

    $MaintenanceFile = Join-Path $StateRoot "maintenance-mode"
    $MaintenanceToken = [guid]::NewGuid().ToString("N")
    Write-DurableUtf8File `
        -Path $MaintenanceFile `
        -Content (([ordered]@{
            format = 1
            operation = "INITIAL_INSTALL"
            owner_token = $MaintenanceToken
            created_at_utc = [DateTime]::UtcNow.ToString("o")
            release_id = $ReleaseId
        } | ConvertTo-Json -Compress) + "`n")

    Start-ScheduledTask -TaskName "CrepaldiHandball"
    try {
        Wait-ExpectedReadiness -ExpectedReleaseId $ReleaseId
        $login = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8765/login" `
            -SkipHttpErrorCheck `
            -TimeoutSec 5
        if ([int]$login.StatusCode -ne 503) {
            throw "Gate de manutenção não bloqueou /login no primeiro start."
        }
        $afterStart = Invoke-GuardJson `
            -Python $GuardPython `
            -GuardPath $GuardPath `
            -Arguments @(
                "fingerprint", "--config-path", $ConfigPath,
                "--expected-database-path", $DbPath
            )
        if ([string]$afterStart.logical_fingerprint -cne $InitialFingerprint) {
            throw "Startup alterou o SQLite persistente."
        }
    }
    catch {
        Stop-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction SilentlyContinue
        throw
    }
    $marker = Get-Content -Raw -LiteralPath $MaintenanceFile -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    if ([string]$marker.owner_token -cne $MaintenanceToken) {
        throw "Marcador de manutenção mudou; liberação recusada."
    }
    Remove-Item -LiteralPath $MaintenanceFile -Force

    Write-Host "Servidor instalado com release_id $ReleaseId."
    Write-Host "Ponteiro ativo: $StateRoot\active-release.json"
    Write-Host "Banco persistente preservado fora dos releases: $DbPath"
    $InstallSucceeded = $true
}
finally {
    if (-not $InstallSucceeded) {
        Stop-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction SilentlyContinue
        if ($BackupTaskRegistered) {
            Unregister-ScheduledTask `
                -TaskName "CrepaldiHandballBackup" `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        }
        if ($ServerTaskRegistered) {
            Unregister-ScheduledTask `
                -TaskName "CrepaldiHandball" `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        }
        if ($ReleaseRoot -and -not $ReleasePublished -and (Test-Path $ReleaseRoot)) {
            $releaseParent = [IO.Path]::GetFullPath((Split-Path -Parent $ReleaseRoot))
            if (
                [string]::Equals(
                    $releaseParent,
                    [IO.Path]::GetFullPath((Join-Path $ResolvedInstallRoot "releases")),
                    [StringComparison]::OrdinalIgnoreCase
                ) -and
                ([IO.Path]::GetFileName($ReleaseRoot)).StartsWith(".stage-")
            ) {
                Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
            }
        }
    }
    $LockStream.Dispose()
}
