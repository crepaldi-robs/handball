param(
    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball",
    [string]$ReleaseId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
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

function Assert-SafeReleaseId {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "ReleaseId inválido."
    }
    if ($Value.EndsWith(".") -or $Value.EndsWith(" ")) {
        throw "ReleaseId não pode terminar em ponto ou espaço."
    }
    $baseName = $Value.Split(".")[0].ToUpperInvariant()
    if (
        $baseName -in @("CON", "PRN", "AUX", "NUL") -or
        $baseName -match '^(COM|LPT)[1-9]$'
    ) {
        throw "ReleaseId reservado pelo Windows."
    }
}

function Assert-DirectoryNotReparsePoint {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Diretório obrigatório ausente: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Diretório de segurança não pode ser reparse point: $Path"
    }
}

function New-PrivateFileSystemSecurity {
    param([Parameter(Mandatory)][bool]$IsDirectory)

    if ($IsDirectory) {
        $security = [Security.AccessControl.DirectorySecurity]::new()
        $inheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
    }
    else {
        $security = [Security.AccessControl.FileSecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @("S-1-5-18", "S-1-5-32-544")) {
        $sid = [Security.Principal.SecurityIdentifier]::new($sidValue)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    return $security
}

function Set-PrivateTreeAcl {
    param([Parameter(Mandatory)][string]$Path)

    Assert-DirectoryNotReparsePoint -Path $Path
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force)
    foreach ($file in $files) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "ACL recusada em reparse point: $($file.FullName)"
        }
        Set-Acl `
            -LiteralPath $file.FullName `
            -AclObject (New-PrivateFileSystemSecurity -IsDirectory $false)
    }
    $directories = @(
        Get-ChildItem -LiteralPath $Path -Recurse -Directory -Force |
            Sort-Object { $_.FullName.Length } -Descending
    )
    foreach ($directory in $directories) {
        if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "ACL recusada em reparse point: $($directory.FullName)"
        }
        Set-Acl `
            -LiteralPath $directory.FullName `
            -AclObject (New-PrivateFileSystemSecurity -IsDirectory $true)
    }
    Set-Acl `
        -LiteralPath $Path `
        -AclObject (New-PrivateFileSystemSecurity -IsDirectory $true)
}

function Assert-PrivateAcl {
    param([Parameter(Mandatory)][string]$Path)

    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) {
        throw "ACL deve ter herança desativada: $Path"
    }
    $rules = @($acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ))
    $allowedSids = @("S-1-5-18", "S-1-5-32-544")
    if ($rules.Count -ne 2) {
        throw "ACL contém quantidade inesperada de regras: $Path"
    }
    foreach ($rule in $rules) {
        if (
            $rule.IdentityReference.Value -notin $allowedSids -or
            $rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            ($rule.FileSystemRights -band
                [Security.AccessControl.FileSystemRights]::FullControl) -ne
                [Security.AccessControl.FileSystemRights]::FullControl
        ) {
            throw "ACL contém regra não autorizada: $Path"
        }
    }
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
        throw "Update recusado: app-config.json inválido."
    }
    foreach ($pair in @(
        @([string]$config.db_path, $ExpectedDbPath, "db_path"),
        @([string]$config.backup_dir, $ExpectedBackupRoot, "backup_dir")
    )) {
        if (
            [string]::IsNullOrWhiteSpace($pair[0]) -or
            -not [IO.Path]::IsPathFullyQualified($pair[0])
        ) {
            throw "Update recusado: $($pair[2]) deve ser caminho absoluto."
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
            throw "Update recusado: $($pair[2]) deve resolver para '$expected'."
        }
    }
}

function Assert-ConfigurationUnchanged {
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )

    $observed = (
        Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($observed -cne $ExpectedSha256) {
        throw "APP_ONLY alterou app-config.json; ativação/restart recusado."
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
    $status = @(
        & git -C $ProjectRoot status --porcelain=v1 --untracked-files=all -- $Items
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao verificar o estado Git do runtime/ops."
    }
    if ($status.Count -gt 0) {
        $details = ($status | ForEach-Object { ("$_").Trim() }) -join ", "
        throw "Runtime/ops possui alterações não commitadas; update recusado: $details"
    }
}

function Get-SourceCommit {
    param([Parameter(Mandatory)][string]$ProjectRoot)

    $commit = (@(
        & git -C $ProjectRoot rev-parse --verify HEAD 2>$null
    ) -join "").Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
        throw "Não foi possível identificar o commit HEAD do release."
    }
    return $commit
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
            throw "Falha ao materializar o snapshot imutável de HEAD."
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
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            throw "Arquivo do snapshot ausente após extração: $relativePath"
        }
        $destinationItem = Get-Item -LiteralPath $destination -Force
        if ($destinationItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Snapshot contém reparse point: $relativePath"
        }
    }
    return $trackedFiles
}

function Get-OrdinalPaths {
    param([Parameter(Mandatory)][string[]]$Paths)

    [string[]]$copy = @($Paths)
    [Array]::Sort($copy, [StringComparer]::Ordinal)
    return $copy
}

function New-InventoryFromPaths {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string[]]$RelativePaths
    )

    $byPath = @{}
    foreach ($relativePathValue in $RelativePaths) {
        $relativePath = $relativePathValue.Replace("\", "/")
        if (
            [IO.Path]::IsPathRooted($relativePath) -or
            $relativePath.Split("/") -contains ".." -or
            $byPath.ContainsKey($relativePath)
        ) {
            throw "Caminho inválido ou duplicado no inventário: $relativePath"
        }
        $path = Join-Path $Root $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Arquivo de inventário ausente: $path"
        }
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Inventário recusa reparse point: $path"
        }
        $byPath[$relativePath] = [ordered]@{
            path = $relativePath
            bytes = [int64]$item.Length
            sha256 = (
                Get-FileHash -LiteralPath $path -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
    }
    $sortedPaths = Get-OrdinalPaths -Paths @($byPath.Keys)
    $entries = @($sortedPaths | ForEach-Object { $byPath[$_] })
    $canonical = ($entries | ForEach-Object {
        "$($_.path)`t$($_.bytes)`t$($_.sha256)"
    }) -join "`n"
    $bytes = [Text.Encoding]::UTF8.GetBytes("$canonical`n")
    return [pscustomobject]@{
        Entries = $entries
        Sha256 = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData($bytes)
        ).ToLowerInvariant()
    }
}

function New-EnvironmentInventory {
    param(
        [Parameter(Mandatory)][string]$ReleaseRoot,
        [Parameter(Mandatory)][string]$InventoryPath
    )

    $venvRoot = Join-Path $ReleaseRoot ".venv"
    $relativePaths = @(
        Get-ChildItem -LiteralPath $venvRoot -Recurse -File -Force |
            ForEach-Object {
                if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Ambiente Python contém reparse point: $($_.FullName)"
                }
                [IO.Path]::GetRelativePath($ReleaseRoot, $_.FullName).Replace("\", "/")
            } |
            Where-Object {
                $_ -notmatch '(^|/)__pycache__(/|$)' -and
                $_ -notmatch '\.pyc$'
            }
    )
    $inventory = New-InventoryFromPaths `
        -Root $ReleaseRoot `
        -RelativePaths $relativePaths
    $document = [ordered]@{
        format = 1
        environment_sha256 = $inventory.Sha256
        files = $inventory.Entries
    }
    $content = ($document | ConvertTo-Json -Depth 6 -Compress) + "`n"
    Write-DurableUtf8File -Path $InventoryPath -Content $content
    return [pscustomobject]@{
        EnvironmentSha256 = $inventory.Sha256
        ManifestSha256 = (
            Get-FileHash -LiteralPath $InventoryPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
}

function Remove-ApplicationBuildCaches {
    param([Parameter(Mandatory)][string]$ReleaseRoot)

    $releasePrefix = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath($ReleaseRoot)
    ) + [IO.Path]::DirectorySeparatorChar
    $venvPrefix = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath((Join-Path $ReleaseRoot ".venv"))
    ) + [IO.Path]::DirectorySeparatorChar
    $buildCaches = @(
        Get-ChildItem `
            -LiteralPath $ReleaseRoot `
            -Directory `
            -Filter "__pycache__" `
            -Recurse |
            Where-Object {
                -not $_.FullName.StartsWith(
                    $venvPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    foreach ($cache in $buildCaches) {
        $cachePath = [IO.Path]::GetFullPath($cache.FullName)
        if (
            -not $cachePath.StartsWith(
                $releasePrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            $cache.Attributes -band [IO.FileAttributes]::ReparsePoint
        ) {
            throw "Limpeza de cache recusada fora do stage seguro: $cachePath"
        }
        Remove-Item -LiteralPath $cachePath -Recurse -Force
    }
}

function Get-GuardPython {
    $output = @(
        & py -3.13 -I -S -c "import sys; print(sys.executable)" 2>$null
    )
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) {
        throw "Python 3.13 operacional não pôde ser resolvido."
    }
    $path = [IO.Path]::GetFullPath(("$($output[0])").Trim())
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Interpretador operacional ausente: $path"
    }
    return $path
}

function Install-FileAtomically {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Destination.next-$([guid]::NewGuid().ToString('N'))"
    $bytes = [IO.File]::ReadAllBytes($Source)
    $stream = [IO.FileStream]::new(
        $temporary,
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
    try {
        [IO.File]::Move($temporary, $Destination, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Install-OperationalBridge {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Mappings,
        [Parameter(Mandatory)][string]$SourceCommit,
        [Parameter(Mandatory)][string]$GuardPython
    )

    $legacyArchive = Join-Path $InstallRoot (
        "ops\legacy-scripts\{0}-{1}" -f `
            [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"),
            [guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $legacyArchive -Force | Out-Null
    foreach ($destinationRelative in @($Mappings.Values)) {
        if (-not $destinationRelative.StartsWith("app/scripts/")) { continue }
        $existing = Join-Path $InstallRoot $destinationRelative
        if (Test-Path -LiteralPath $existing -PathType Leaf) {
            Copy-Item -LiteralPath $existing -Destination (
                Join-Path $legacyArchive ([IO.Path]::GetFileName($existing))
            ) -Force
        }
    }

    # O runner é substituído por último: em qualquer crash anterior, o runner
    # histórico continua executável; depois dele, resolver e guard já existem.
    $orderedSources = @(
        "scripts/database-guard.py",
        "scripts/release-resolver.ps1",
        "scripts/reset-password.ps1",
        "scripts/update-server.ps1",
        "scripts/migrate-database.ps1",
        "scripts/backup-server.ps1",
        "scripts/run-server.ps1"
    )
    $entries = @()
    foreach ($sourceRelative in $orderedSources) {
        $destinationRelative = [string]$Mappings[$sourceRelative]
        if ([string]::IsNullOrWhiteSpace($destinationRelative)) {
            throw "Mapeamento operacional ausente: $sourceRelative"
        }
        $source = Join-Path $ProjectRoot $sourceRelative
        $destination = Join-Path $InstallRoot $destinationRelative
        Install-FileAtomically -Source $source -Destination $destination
        $item = Get-Item -LiteralPath $destination -Force
        $entries += [ordered]@{
            path = $destinationRelative.Replace("\", "/")
            bytes = [int64]$item.Length
            sha256 = (
                Get-FileHash -LiteralPath $destination -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
    }
    $manifest = [ordered]@{
        format = 1
        protocol = 1
        source_commit = $SourceCommit
        installed_at_utc = [DateTime]::UtcNow.ToString("o")
        guard_python_path = $GuardPython
        guard_python_sha256 = (
            Get-FileHash -LiteralPath $GuardPython -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        files = $entries
    }
    $manifestPath = Join-Path $InstallRoot "ops\ops-manifest.json"
    $manifestTemporary = "$manifestPath.next-$([guid]::NewGuid().ToString('N'))"
    Write-DurableUtf8File `
        -Path $manifestTemporary `
        -Content (($manifest | ConvertTo-Json -Depth 6) + "`n")
    try {
        [IO.File]::Move($manifestTemporary, $manifestPath, $true)
    }
    finally {
        if (Test-Path -LiteralPath $manifestTemporary) {
            Remove-Item -LiteralPath $manifestTemporary -Force
        }
    }
}

function Get-VerifiedOperationalRuntime {
    param([Parameter(Mandatory)][string]$InstallRoot)

    $manifestPath = Join-Path $InstallRoot "ops\ops-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Manifesto operacional ausente: $manifestPath"
    }
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Manifesto operacional inválido."
    }
    if ([int]$manifest.format -ne 1 -or [int]$manifest.protocol -ne 1) {
        throw "Protocolo operacional incompatível."
    }
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in @($manifest.files)) {
        $relative = ([string]$entry.path).Replace("\", "/")
        if (
            [IO.Path]::IsPathRooted($relative) -or
            $relative.Split("/") -contains ".." -or
            -not $seen.Add($relative)
        ) {
            throw "Entrada operacional inválida: $relative"
        }
        $path = [IO.Path]::GetFullPath((Join-Path $InstallRoot $relative))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Arquivo operacional ausente: $relative"
        }
        $item = Get-Item -LiteralPath $path -Force
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if (
            $item.Attributes -band [IO.FileAttributes]::ReparsePoint -or
            [int64]$entry.bytes -ne [int64]$item.Length -or
            [string]$entry.sha256 -cne $hash
        ) {
            throw "Integridade operacional divergente: $relative"
        }
    }
    foreach ($required in @(
        "app/scripts/run-server.ps1",
        "app/scripts/backup-server.ps1",
        "app/scripts/reset-password.ps1",
        "app/scripts/update-server.ps1",
        "app/scripts/migrate-database.ps1",
        "app/scripts/release-resolver.ps1",
        "ops/database-guard.py"
    )) {
        if (-not $seen.Contains($required)) {
            throw "Manifesto operacional não cobre: $required"
        }
    }
    $guardPython = [string]$manifest.guard_python_path
    if (
        [string]::IsNullOrWhiteSpace($guardPython) -or
        -not [IO.Path]::IsPathFullyQualified($guardPython) -or
        -not (Test-Path -LiteralPath $guardPython -PathType Leaf)
    ) {
        throw "Python operacional inválido no manifesto."
    }
    $guardPython = [IO.Path]::GetFullPath($guardPython)
    $observedPythonHash = (
        Get-FileHash -LiteralPath $guardPython -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ([string]$manifest.guard_python_sha256 -cne $observedPythonHash) {
        throw "Python operacional diverge do manifesto."
    }
    return [pscustomobject]@{
        Python = $guardPython
        Guard = Join-Path $InstallRoot "ops\database-guard.py"
        Manifest = $manifest
    }
}

function Invoke-GuardJson {
    param(
        [Parameter(Mandatory)][object]$Runtime,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $output = @(& $Runtime.Python -I -S $Runtime.Guard @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "Database guard falhou ($exitCode): $text"
    }
    try {
        $result = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Database guard não retornou JSON válido."
    }
    if (
        [string]$result.format -cne "crepaldi-handball-database-guard/v1" -or
        -not [bool]$result.ok -or
        (
            [string]$result.command -in @("verify", "backup") -and
            [string]$result.quick_check -cne "ok"
        )
    ) {
        throw "Database guard retornou contrato inválido."
    }
    return $result
}

function Assert-BackupArtifact {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$GuardResult
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Backup esperado não foi publicado: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Backup não pode ser reparse point: $Path"
    }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if (
        [IO.Path]::GetFullPath([string]$GuardResult.destination) -cne
            [IO.Path]::GetFullPath($Path) -or
        [int64]$GuardResult.backup_bytes -ne [int64]$item.Length -or
        [string]$GuardResult.backup_sha256 -cne $hash
    ) {
        throw "Hash, tamanho ou destino do backup diverge do guard."
    }
}

function Assert-StableScheduledTasks {
    param(
        [Parameter(Mandatory)][string]$InstallRoot,
        [switch]$AllowLegacyRepair
    )

    $pwsh = [IO.Path]::GetFullPath((Get-Command pwsh -ErrorAction Stop).Source)
    foreach ($definition in @(
        @("CrepaldiHandball", "app\scripts\run-server.ps1"),
        @("CrepaldiHandballBackup", "app\scripts\backup-server.ps1")
    )) {
        $task = Get-ScheduledTask -TaskName $definition[0] -ErrorAction Stop
        $actions = @($task.Actions)
        if ($actions.Count -ne 1) {
            throw "Tarefa $($definition[0]) deve possuir exatamente uma ação."
        }
        $expectedScript = Join-Path $InstallRoot $definition[1]
        $expectedArguments = (
            '-NoProfile -ExecutionPolicy Bypass -File "{0}" -InstallRoot "{1}"' -f `
                $expectedScript, $InstallRoot
        )
        if (
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$actions[0].Execute),
                $pwsh,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            [string]$actions[0].Arguments -cne $expectedArguments
        ) {
            throw "Ação da tarefa $($definition[0]) diverge do caminho estável."
        }
        if ($definition[0] -ceq "CrepaldiHandball") {
            $executionTimeLimit = ConvertFrom-ScheduledTaskDuration `
                -Value $task.Settings.ExecutionTimeLimit
            if ($executionTimeLimit -ne [TimeSpan]::Zero) {
                if (-not $AllowLegacyRepair) {
                    throw (
                        "Tarefa do servidor possui ExecutionTimeLimit; " +
                        "APP_ONLY formal não altera infraestrutura."
                    )
                }
                $serverSettings = New-ScheduledTaskSettingsSet `
                    -StartWhenAvailable `
                    -RestartCount 5 `
                    -RestartInterval (New-TimeSpan -Minutes 1) `
                    -ExecutionTimeLimit ([TimeSpan]::Zero)
                Set-ScheduledTask `
                    -TaskName $definition[0] `
                    -Settings $serverSettings `
                    -ErrorAction Stop | Out-Null
                $persisted = Get-ScheduledTask `
                    -TaskName $definition[0] `
                    -ErrorAction Stop
                $persistedLimit = ConvertFrom-ScheduledTaskDuration `
                    -Value $persisted.Settings.ExecutionTimeLimit
                if ($persistedLimit -ne [TimeSpan]::Zero) {
                    throw "ExecutionTimeLimit infinito não foi persistido no servidor."
                }
            }
        }
    }
}

function Assert-CurrentServiceHealthy {
    param([Parameter(Mandatory)][object]$Release)

    $task = Get-ScheduledTask -TaskName "CrepaldiHandball" -ErrorAction Stop
    if ($task.State -ne "Running") {
        throw "O serviço atual deve estar saudável e em execução antes do update."
    }
    try {
        if ($Release.Kind -ceq "legacy") {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/health" `
                -TimeoutSec 5
            if ([string]$response.status -cne "ok") { throw "health divergente" }
        }
        else {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/ready" `
                -TimeoutSec 5
            if (
                [string]$response.status -cne "ok" -or
                [string]$response.release_id -cne $Release.ReleaseId
            ) { throw "readiness divergente" }
        }
    }
    catch {
        throw "O serviço atual não comprovou identidade/saúde: $($_.Exception.Message)"
    }
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

function Wait-PortReleased {
    param([Parameter(Mandatory)][int]$Port)

    for ($attempt = 1; $attempt -le 40; $attempt++) {
        $listener = Get-NetTCPConnection `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue
        if (-not $listener) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "A porta $Port permaneceu ocupada."
}

function New-OwnedMaintenanceMarker {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Operation
    )

    $token = [guid]::NewGuid().ToString("N")
    $content = ([ordered]@{
        format = 1
        operation = $Operation
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

function Remove-OwnedMaintenanceMarker {
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

function Invoke-CandidateCliText {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ApplicationRoot,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $environmentNames = @(
        Get-ChildItem Env: |
            Where-Object {
                $_.Name.StartsWith("ATTENDANCE_", [StringComparison]::OrdinalIgnoreCase) -or
                $_.Name -in @("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
            } |
            ForEach-Object { $_.Name }
    )
    $saved = @{}
    foreach ($name in $environmentNames) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    $previousBytecode = [Environment]::GetEnvironmentVariable(
        "PYTHONDONTWRITEBYTECODE",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "Process"
    )
    Push-Location $ApplicationRoot
    try {
        $output = @(& $Python -m attendance.cli @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
        if ($exitCode -ne 0) {
            throw "CLI candidata falhou ($exitCode): $text"
        }
        return $text
    }
    finally {
        Pop-Location
        [Environment]::SetEnvironmentVariable(
            "PYTHONDONTWRITEBYTECODE",
            $previousBytecode,
            "Process"
        )
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }
}

function Start-CandidateServer {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ApplicationRoot,
        [Parameter(Mandatory)][string]$ConfigPath,
        [Parameter(Mandatory)][string]$MaintenanceFile,
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$StdoutPath,
        [Parameter(Mandatory)][string]$StderrPath
    )

    Wait-PortReleased -Port $Port
    $namesToClear = @(
        Get-ChildItem Env: |
            Where-Object {
                $_.Name.StartsWith("ATTENDANCE_", [StringComparison]::OrdinalIgnoreCase) -or
                $_.Name -in @("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
            } |
            ForEach-Object { $_.Name }
    )
    $saved = @{}
    foreach ($name in $namesToClear) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    $explicit = @{
        ATTENDANCE_CONFIG_PATH = $ConfigPath
        ATTENDANCE_RELEASE_ID = $ExpectedReleaseId
        ATTENDANCE_MAINTENANCE_FILE = $MaintenanceFile
        PYTHONDONTWRITEBYTECODE = "1"
        PYTHONUTF8 = "1"
    }
    $explicitPrevious = @{}
    foreach ($name in $explicit.Keys) {
        $explicitPrevious[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $explicit[$name], "Process")
    }
    try {
        return Start-Process `
            -FilePath $Python `
            -ArgumentList @(
                "-m", "uvicorn", "app:app",
                "--host", "127.0.0.1",
                "--port", "$Port"
            ) `
            -WorkingDirectory $ApplicationRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -PassThru
    }
    finally {
        foreach ($name in $explicit.Keys) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $explicitPrevious[$name],
                "Process"
            )
        }
        foreach ($name in $namesToClear) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }
}

function Stop-CandidateServer {
    param([Parameter(Mandatory)][Diagnostics.Process]$Process)

    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        [void]$Process.WaitForExit(10000)
    }
    Wait-PortReleased -Port 18765
}

function Wait-GatedReadiness {
    param(
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [Parameter(Mandatory)][int]$Port,
        [Diagnostics.Process]$Process = $null
    )

    $lastResult = "sem resposta"
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        if ($Process -and $Process.HasExited) {
            throw "Processo candidato encerrou com exit code $($Process.ExitCode)."
        }
        try {
            $ready = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/ready" `
                -TimeoutSec 5
            $login = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$Port/login" `
                -SkipHttpErrorCheck `
                -TimeoutSec 5
            if (
                [string]$ready.status -ceq "ok" -and
                [string]$ready.release_id -ceq $ExpectedReleaseId -and
                [int]$login.StatusCode -eq 503
            ) { return }
            $lastResult = "readiness, release_id ou gate 503 divergente"
        }
        catch {
            $lastResult = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 750
    }
    throw "Candidato '$ExpectedReleaseId' não confirmou readiness/gate: $lastResult"
}

function Remove-ScopedDirectory {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ExpectedParent
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = [IO.Path]::TrimEndingDirectorySeparator([IO.Path]::GetFullPath($Path))
    $parent = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath((Split-Path -Parent $resolved))
    )
    $expected = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath($ExpectedParent)
    )
    if (-not [string]::Equals(
        $parent,
        $expected,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Limpeza recusada fora do diretório temporário esperado: $resolved"
    }
    $item = Get-Item -LiteralPath $resolved -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Limpeza recusada para reparse point: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

Assert-Administrator
$ResolvedInstallRoot = Resolve-ExactInstallRoot -Path $InstallRoot
if (-not (Test-Path -LiteralPath $ResolvedInstallRoot -PathType Container)) {
    throw "Instalação ausente: $ResolvedInstallRoot"
}

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
$SourceCommitBefore = Get-SourceCommit -ProjectRoot $ProjectRoot

$AppRoot = Join-Path $ResolvedInstallRoot "app"
$DataRoot = Join-Path $ResolvedInstallRoot "data"
$BackupRoot = Join-Path $ResolvedInstallRoot "backups"
$LogRoot = Join-Path $ResolvedInstallRoot "logs"
$ReleasesRoot = Join-Path $ResolvedInstallRoot "releases"
$StateRoot = Join-Path $ResolvedInstallRoot "state"
$OpsRoot = Join-Path $ResolvedInstallRoot "ops"
$ConfigPath = Join-Path $DataRoot "app-config.json"
$DbPath = Join-Path $DataRoot "presencas.db"
$MaintenancePath = Join-Path $StateRoot "maintenance-mode"
$LockStream = Enter-MaintenanceLock -Root $ResolvedInstallRoot
$StagePath = $null
$StagePromoted = $false
$PreflightRoot = $null
$OpsSourceRoot = $null
$CandidateProcess = $null
$PreviousRelease = $null
$GuardRuntime = $null
$InitialFingerprint = $null
$StoppedFingerprint = $null
$ConfigSha256Before = $null
$MaintenanceToken = $null
$StopAttempted = $false
$ServerStopped = $false
$PointerSwitched = $false
$FinalReleaseRoot = $null
try {
    foreach ($requiredFile in @($ConfigPath, $DbPath)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Update recusado; arquivo persistente obrigatório ausente: $requiredFile"
        }
    }
    Assert-DirectoryNotReparsePoint -Path $ResolvedInstallRoot
    Assert-DirectoryNotReparsePoint -Path $AppRoot
    Assert-DirectoryNotReparsePoint -Path $DataRoot
    Assert-DirectoryNotReparsePoint -Path $BackupRoot
    Assert-DirectoryNotReparsePoint -Path $LogRoot
    Assert-PersistentConfiguration `
        -ConfigPath $ConfigPath `
        -ExpectedDbPath $DbPath `
        -ExpectedBackupRoot $BackupRoot
    $ConfigSha256Before = (
        Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    foreach ($directory in @($ReleasesRoot, $StateRoot, $OpsRoot)) {
        if (-not (Test-Path -LiteralPath $directory)) {
            New-Item -ItemType Directory -Path $directory | Out-Null
        }
        Assert-DirectoryNotReparsePoint -Path $directory
    }

    $legacyAclHardened = $false
    $activePointer = Join-Path $StateRoot "active-release.json"
    if (-not (Test-Path -LiteralPath $activePointer -PathType Leaf)) {
        $legacyPython = Join-Path $ResolvedInstallRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $legacyPython -PathType Leaf)) {
            throw "Layout legado incompleto: Python histórico ausente."
        }
        Assert-StableScheduledTasks `
            -InstallRoot $ResolvedInstallRoot `
            -AllowLegacyRepair
        Set-PrivateTreeAcl -Path $ResolvedInstallRoot
        $legacyAclHardened = $true
        $legacyId = "legacy-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
        $legacyPointer = @{
            format = 1
            generation = 0
            release_id = $legacyId
            kind = "legacy"
            application_relative_path = "app"
            python_relative_path = ".venv/Scripts/python.exe"
            manifest_sha256 = $null
        }
        [void](Set-ActiveReleasePointer `
            -InstallRoot $ResolvedInstallRoot `
            -Pointer $legacyPointer)
    }

    $PreviousRelease = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if ($PreviousRelease.Kind -ceq "legacy" -and -not $legacyAclHardened) {
        Set-PrivateTreeAcl -Path $ResolvedInstallRoot
    }
    foreach ($protectedPath in @(
        $ResolvedInstallRoot, $AppRoot, $DataRoot, $BackupRoot,
        $LogRoot, $ReleasesRoot, $StateRoot, $OpsRoot
    )) {
        Assert-PrivateAcl -Path $protectedPath
    }
    $opsManifestPath = Join-Path $OpsRoot "ops-manifest.json"
    $bridgeRequired = $false
    if ($PreviousRelease.Kind -ceq "legacy") {
        if (-not (Test-Path -LiteralPath $opsManifestPath -PathType Leaf)) {
            $bridgeRequired = $true
        }
        else {
            try {
                $GuardRuntime = Get-VerifiedOperationalRuntime `
                    -InstallRoot $ResolvedInstallRoot
            }
            catch {
                $bridgeRequired = $true
                $GuardRuntime = $null
            }
        }
    }
    if ($bridgeRequired) {
        $guardPython = Get-GuardPython
        $OpsSourceRoot = Join-Path $StateRoot (
            ".ops-source-$([guid]::NewGuid().ToString('N'))"
        )
        New-Item -ItemType Directory -Path $OpsSourceRoot | Out-Null
        [void](Copy-ReleaseSources `
            -ProjectRoot $ProjectRoot `
            -DestinationRoot $OpsSourceRoot `
            -SourceItems @($OperationalMappings.Keys) `
            -SourceCommit $SourceCommitBefore)
        Install-OperationalBridge `
            -ProjectRoot $OpsSourceRoot `
            -InstallRoot $ResolvedInstallRoot `
            -Mappings $OperationalMappings `
            -SourceCommit $SourceCommitBefore `
            -GuardPython $guardPython
        Remove-ScopedDirectory -Path $OpsSourceRoot -ExpectedParent $StateRoot
        $OpsSourceRoot = $null
    }
    if (-not $GuardRuntime) {
        $GuardRuntime = Get-VerifiedOperationalRuntime `
            -InstallRoot $ResolvedInstallRoot
    }
    Assert-StableScheduledTasks -InstallRoot $ResolvedInstallRoot
    Assert-CurrentServiceHealthy -Release $PreviousRelease

    $initial = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    $InitialFingerprint = [string]$initial.logical_fingerprint
    if ($InitialFingerprint -notmatch '^[0-9a-f]{64}$') {
        throw "Fingerprint lógico inicial inválido."
    }

    if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
        $ReleaseId = "{0}-{1}" -f `
            $SourceCommitBefore.Substring(0, 12),
            [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    }
    Assert-SafeReleaseId -Value $ReleaseId
    $FinalReleaseRoot = Join-Path $ReleasesRoot $ReleaseId
    if (Test-Path -LiteralPath $FinalReleaseRoot) {
        throw "Release imutável já existe: $FinalReleaseRoot"
    }
    $StagePath = Join-Path $ReleasesRoot (
        ".stage-$ReleaseId-$([guid]::NewGuid().ToString('N'))"
    )
    New-Item -ItemType Directory -Path $StagePath | Out-Null
    $SourceFiles = @(Copy-ReleaseSources `
        -ProjectRoot $ProjectRoot `
        -DestinationRoot $StagePath `
        -SourceItems $RuntimeItems `
        -SourceCommit $SourceCommitBefore)
    Assert-CleanTrackedSources -ProjectRoot $ProjectRoot -Items $AllSources
    $SourceCommitAfterCopy = Get-SourceCommit -ProjectRoot $ProjectRoot
    if ($SourceCommitAfterCopy -cne $SourceCommitBefore) {
        throw "HEAD mudou durante a montagem; update recusado."
    }

    $CandidatePython = Join-Path $StagePath ".venv\Scripts\python.exe"
    & py -3.13 -I -S -m venv (Join-Path $StagePath ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar venv candidata." }
    & $CandidatePython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip da candidata." }
    & $CandidatePython -m pip install -r (Join-Path $StagePath "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências da candidata." }
    & $CandidatePython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependências da candidata inconsistentes." }
    Push-Location $StagePath
    try {
        & $CandidatePython -m compileall -q app.py attendance
        if ($LASTEXITCODE -ne 0) { throw "Compilação Python candidata falhou." }
    }
    finally {
        Pop-Location
    }
    Remove-ApplicationBuildCaches -ReleaseRoot $StagePath
    $schemaContractText = Invoke-CandidateCliText `
        -Python $CandidatePython `
        -ApplicationRoot $StagePath `
        -Arguments @("release-contract")
    try {
        $schemaContract = $schemaContractText |
            ConvertFrom-Json -ErrorAction Stop
        $schemaMinimum = [int64]$schemaContract.schema_compatibility.minimum
        $schemaMaximum = [int64]$schemaContract.schema_compatibility.maximum
    }
    catch {
        throw "Candidata emitiu contrato de schema inválido: $schemaContractText"
    }
    if (
        [int64]$schemaContract.format -ne 1 -or
        $schemaMinimum -lt 1 -or
        $schemaMaximum -lt $schemaMinimum
    ) {
        throw "Candidata emitiu faixa de schema inválida: $schemaContractText"
    }

    # Validação 1: a candidata só vê uma cópia descartável e consistente.
    $maintenanceWorkRoot = Join-Path $StateRoot "preflight"
    if (-not (Test-Path -LiteralPath $maintenanceWorkRoot)) {
        New-Item -ItemType Directory -Path $maintenanceWorkRoot | Out-Null
    }
    Assert-DirectoryNotReparsePoint -Path $maintenanceWorkRoot
    $PreflightRoot = Join-Path $maintenanceWorkRoot ([guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $PreflightRoot | Out-Null
    $preflightDb = Join-Path $PreflightRoot "presencas-copy.db"
    $liveNow = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "fingerprint", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    $preflightBackup = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "backup", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath,
            "--destination", $preflightDb,
            "--expected-fingerprint", [string]$liveNow.logical_fingerprint
        )
    Assert-BackupArtifact -Path $preflightDb -GuardResult $preflightBackup
    $preflightConfig = Join-Path $PreflightRoot "app-config.json"
    $synthetic = [ordered]@{
        db_path = $preflightDb
        admin_username = "candidate-preflight"
        password_hash = "candidate-preflight-not-used"
        secret_key = "candidate-preflight-secret-key-0000000000000000000000000000"
        cookie_secure = $false
        session_max_age_seconds = 3600
        backup_dir = $PreflightRoot
    }
    [IO.File]::WriteAllText(
        $preflightConfig,
        (($synthetic | ConvertTo-Json -Depth 4) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    $preflightMarker = Join-Path $PreflightRoot "maintenance-mode"
    [IO.File]::WriteAllText($preflightMarker, "APP_ONLY_PREFLIGHT`n")
    $verifyText = Invoke-CandidateCliText `
        -Python $CandidatePython `
        -ApplicationRoot $StagePath `
        -Arguments @("verify-database", "--config-path", $preflightConfig)
    if ($verifyText -cne "ok") {
        throw "Candidata não aceitou o esquema atual na cópia descartável."
    }
    $candidateCopyFingerprint = Invoke-CandidateCliText `
        -Python $CandidatePython `
        -ApplicationRoot $StagePath `
        -Arguments @("fingerprint-database", "--config-path", $preflightConfig)
    if (
        $candidateCopyFingerprint -notmatch '^[0-9a-f]{64}$' -or
        $candidateCopyFingerprint -cne
            [string]$preflightBackup.logical_fingerprint
    ) {
        throw (
            "Candidata e guard operacional divergiram no fingerprint " +
            "da cópia descartável."
        )
    }
    $CandidateProcess = Start-CandidateServer `
        -Python $CandidatePython `
        -ApplicationRoot $StagePath `
        -ConfigPath $preflightConfig `
        -MaintenanceFile $preflightMarker `
        -ExpectedReleaseId $ReleaseId `
        -Port 18765 `
        -StdoutPath (Join-Path $PreflightRoot "candidate.stdout.log") `
        -StderrPath (Join-Path $PreflightRoot "candidate.stderr.log")
    Wait-GatedReadiness `
        -ExpectedReleaseId $ReleaseId `
        -Port 18765 `
        -Process $CandidateProcess
    Stop-CandidateServer -Process $CandidateProcess
    $CandidateProcess = $null
    $copyAfter = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @("fingerprint", "--config-path", $preflightConfig)
    if ([string]$copyAfter.logical_fingerprint -cne [string]$preflightBackup.logical_fingerprint) {
        throw "Candidata alterou a cópia SQLite durante o preflight."
    }
    Remove-ApplicationBuildCaches -ReleaseRoot $StagePath

    $PayloadInventory = New-InventoryFromPaths `
        -Root $StagePath `
        -RelativePaths $SourceFiles
    $environmentInventoryPath = Join-Path $StagePath "environment-files.json"
    $EnvironmentInventory = New-EnvironmentInventory `
        -ReleaseRoot $StagePath `
        -InventoryPath $environmentInventoryPath
    $manifest = [ordered]@{
        format = 1
        release_id = $ReleaseId
        installed_at_utc = [DateTime]::UtcNow.ToString("o")
        install_kind = "app-only"
        database_action = "none"
        source_commit = $SourceCommitBefore
        source_files = $SourceFiles
        environment_manifest = "environment-files.json"
        environment_manifest_sha256 = $EnvironmentInventory.ManifestSha256
        environment_sha256 = $EnvironmentInventory.EnvironmentSha256
        payload_sha256 = $PayloadInventory.Sha256
        payload_files = $PayloadInventory.Entries
        schema_compatibility = [ordered]@{
            minimum = $schemaMinimum
            maximum = $schemaMaximum
        }
        database_preflight_fingerprint = [string]$preflightBackup.logical_fingerprint
    }
    $manifestPath = Join-Path $StagePath "release-manifest.json"
    Write-DurableUtf8File `
        -Path $manifestPath `
        -Content (($manifest | ConvertTo-Json -Depth 8) + "`n")
    $manifestHash = (
        Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    [IO.Directory]::Move($StagePath, $FinalReleaseRoot)
    $StagePromoted = $true
    $StagePath = $null
    $CandidatePython = Join-Path $FinalReleaseRoot ".venv\Scripts\python.exe"
    Remove-ScopedDirectory -Path $PreflightRoot -ExpectedParent $maintenanceWorkRoot
    $PreflightRoot = $null

    # Validação 2: janela fechada, backup final, candidata na porta sem túnel.
    $MaintenanceToken = New-OwnedMaintenanceMarker `
        -Path $MaintenancePath `
        -Operation "APP_ONLY"
    $StopAttempted = $true
    Stop-HandballServer
    $ServerStopped = $true
    $stopped = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "verify", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    $StoppedFingerprint = [string]$stopped.logical_fingerprint
    $backupStamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
    $BackupPath = Join-Path $BackupRoot "app-only-$ReleaseId-$backupStamp.db"
    $finalBackup = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "backup", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath,
            "--expected-backup-root", $BackupRoot,
            "--destination", $BackupPath,
            "--expected-fingerprint", $StoppedFingerprint
        )
    Assert-BackupArtifact -Path $BackupPath -GuardResult $finalBackup
    if ([string]$finalBackup.logical_fingerprint -cne $StoppedFingerprint) {
        throw "Backup final não corresponde ao banco parado."
    }

    $CandidateProcess = Start-CandidateServer `
        -Python $CandidatePython `
        -ApplicationRoot $FinalReleaseRoot `
        -ConfigPath $ConfigPath `
        -MaintenanceFile $MaintenancePath `
        -ExpectedReleaseId $ReleaseId `
        -Port 18765 `
        -StdoutPath (Join-Path $LogRoot "candidate-$ReleaseId.stdout.log") `
        -StderrPath (Join-Path $LogRoot "candidate-$ReleaseId.stderr.log")
    Wait-GatedReadiness `
        -ExpectedReleaseId $ReleaseId `
        -Port 18765 `
        -Process $CandidateProcess
    Stop-CandidateServer -Process $CandidateProcess
    $CandidateProcess = $null
    $afterDirect = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "fingerprint", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if ([string]$afterDirect.logical_fingerprint -cne $StoppedFingerprint) {
        throw "Candidata alterou o SQLite persistente; ativação recusada."
    }
    Assert-ConfigurationUnchanged `
        -ConfigPath $ConfigPath `
        -ExpectedSha256 $ConfigSha256Before

    $currentPointer = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if (
        $currentPointer.Generation -ne $PreviousRelease.Generation -or
        $currentPointer.ReleaseId -cne $PreviousRelease.ReleaseId -or
        $currentPointer.Kind -cne $PreviousRelease.Kind
    ) {
        throw "Ponteiro ativo mudou durante o update; ativação recusada."
    }
    $newPointer = @{
        format = 1
        generation = [int64]$PreviousRelease.Generation + 1
        release_id = $ReleaseId
        kind = "release"
        application_relative_path = "releases/$ReleaseId"
        python_relative_path = "releases/$ReleaseId/.venv/Scripts/python.exe"
        manifest_sha256 = $manifestHash
    }
    [void](Set-ActiveReleasePointer `
        -InstallRoot $ResolvedInstallRoot `
        -Pointer $newPointer `
        -ExpectedGeneration ([int64]$PreviousRelease.Generation))
    $PointerSwitched = $true

    Start-ScheduledTask -TaskName "CrepaldiHandball"
    Wait-GatedReadiness -ExpectedReleaseId $ReleaseId -Port 8765
    $afterOfficial = Invoke-GuardJson `
        -Runtime $GuardRuntime `
        -Arguments @(
            "fingerprint", "--config-path", $ConfigPath,
            "--expected-database-path", $DbPath
        )
    if ([string]$afterOfficial.logical_fingerprint -cne $StoppedFingerprint) {
        throw "Startup oficial alterou o SQLite persistente."
    }
    Assert-ConfigurationUnchanged `
        -ConfigPath $ConfigPath `
        -ExpectedSha256 $ConfigSha256Before
    $activeAfter = Resolve-ActiveRelease -InstallRoot $ResolvedInstallRoot
    if (
        $activeAfter.ReleaseId -cne $ReleaseId -or
        $activeAfter.Generation -ne ([int64]$PreviousRelease.Generation + 1)
    ) {
        throw "Identidade persistida do release ativo diverge após o start."
    }
    Remove-OwnedMaintenanceMarker `
        -Path $MaintenancePath `
        -Token $MaintenanceToken
    $MaintenanceToken = $null
    $ServerStopped = $false

    Write-Host "Update APP_ONLY concluído: $ReleaseId"
    Write-Host "Banco/configuração não foram migrados, movidos ou substituídos."
    Write-Host "Fingerprint lógico preservado: $StoppedFingerprint"
    Write-Host "Backup final verificado: $BackupPath"
    Write-Host "Ponteiro ativo: $StateRoot\active-release.json"
}
catch {
    $failure = $_
    if ($CandidateProcess) {
        try { Stop-CandidateServer -Process $CandidateProcess } catch { }
        $CandidateProcess = $null
    }

    $rollbackFailure = $null
    if ($PointerSwitched) {
        try {
            [void](Restore-BackupReleasePointer -InstallRoot $ResolvedInstallRoot)
            $PointerSwitched = $false
        }
        catch {
            $rollbackFailure = $_.Exception.Message
        }
    }

    if ($StopAttempted) {
        try {
            Stop-HandballServer
            $ServerStopped = $true
        }
        catch {
            throw (
                "Update falhou e a parada segura não pôde ser confirmada. " +
                "Nenhum restore de banco foi executado. Falha original: " +
                "$($failure.Exception.Message); stop: $($_.Exception.Message)"
            )
        }
    }

    $databasePreserved = $false
    $configurationPreserved = $false
    if ($ServerStopped -and $StoppedFingerprint -and $GuardRuntime) {
        try {
            $failureState = Invoke-GuardJson `
                -Runtime $GuardRuntime `
                -Arguments @(
                    "fingerprint", "--config-path", $ConfigPath,
                    "--expected-database-path", $DbPath
                )
            $databasePreserved = (
                [string]$failureState.logical_fingerprint -ceq $StoppedFingerprint
            )
        }
        catch {
            $databasePreserved = $false
        }
    }
    if ($ConfigSha256Before) {
        try {
            Assert-ConfigurationUnchanged `
                -ConfigPath $ConfigPath `
                -ExpectedSha256 $ConfigSha256Before
            $configurationPreserved = $true
        }
        catch {
            $configurationPreserved = $false
        }
    }

    if (
        $ServerStopped -and
        $databasePreserved -and
        $configurationPreserved -and
        -not $rollbackFailure -and
        $PreviousRelease -and
        $PreviousRelease.Kind -ceq "release" -and
        $MaintenanceToken
    ) {
        try {
            Start-ScheduledTask -TaskName "CrepaldiHandball"
            Wait-GatedReadiness `
                -ExpectedReleaseId $PreviousRelease.ReleaseId `
                -Port 8765
            $restored = Invoke-GuardJson `
                -Runtime $GuardRuntime `
                -Arguments @(
                    "fingerprint", "--config-path", $ConfigPath,
                    "--expected-database-path", $DbPath
                )
            if ([string]$restored.logical_fingerprint -cne $StoppedFingerprint) {
                throw "Release anterior alterou o banco ao reiniciar."
            }
            Assert-ConfigurationUnchanged `
                -ConfigPath $ConfigPath `
                -ExpectedSha256 $ConfigSha256Before
            Remove-OwnedMaintenanceMarker `
                -Path $MaintenancePath `
                -Token $MaintenanceToken
            $MaintenanceToken = $null
            $ServerStopped = $false
            throw (
                "Update recusado; rollback automático de código concluído e " +
                "SQLite preservado. Release candidata retida em '$FinalReleaseRoot'. " +
                "Falha: $($failure.Exception.Message)"
            )
        }
        catch {
            if ($_.Exception.Message.StartsWith("Update recusado; rollback automático")) {
                throw
            }
            throw (
                "Update falhou; rollback do código foi tentado, mas a recuperação " +
                "não foi comprovada. Serviço e manutenção foram mantidos. " +
                "Nenhum restore de banco foi executado. Falha original: " +
                "$($failure.Exception.Message); recuperação: $($_.Exception.Message)"
            )
        }
    }

    if ($StopAttempted) {
        $legacyNote = if ($PreviousRelease -and $PreviousRelease.Kind -ceq "legacy") {
            " O release legado não foi reiniciado automaticamente."
        } else { "" }
        $rollbackNote = if ($rollbackFailure) {
            " Falha ao restaurar ponteiro: $rollbackFailure."
        } else { "" }
        throw (
            "Update falhou; serviço e modo de manutenção foram mantidos. " +
            "Nenhum restore de banco foi executado.$legacyNote$rollbackNote " +
            "Falha: $($failure.Exception.Message)"
        )
    }
    throw $failure
}
finally {
    if ($CandidateProcess) {
        try { Stop-CandidateServer -Process $CandidateProcess } catch { }
    }
    if ($PreflightRoot) {
        try {
            Remove-ScopedDirectory `
                -Path $PreflightRoot `
                -ExpectedParent (Join-Path $StateRoot "preflight")
        }
        catch { }
    }
    if ($OpsSourceRoot) {
        try {
            Remove-ScopedDirectory -Path $OpsSourceRoot -ExpectedParent $StateRoot
        }
        catch { }
    }
    if ($StagePath -and -not $StagePromoted) {
        try {
            Remove-ScopedDirectory -Path $StagePath -ExpectedParent $ReleasesRoot
        }
        catch { }
    }
    $LockStream.Dispose()
}
