Set-StrictMode -Version Latest

$script:ReleaseManifestName = "release-manifest.json"
$script:EnvironmentManifestName = "environment-files.json"

function Resolve-ExactInstallRoot {
    param([Parameter(Mandatory)][string]$Path)

    $expected = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath("C:\ProgramData\CrepaldiHandball")
    )
    $resolved = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath($Path)
    )
    if (-not [string]::Equals(
        $resolved,
        $expected,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "InstallRoot deve ser exatamente C:\ProgramData\CrepaldiHandball."
    }
    return $resolved
}

function Get-RequiredJsonProperty {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$DocumentLabel
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "$DocumentLabel não contém a propriedade obrigatória '$Name'."
    }
    return $property.Value
}

function ConvertTo-RequiredInt64 {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Label,
        [int64]$Minimum = 0
    )

    $integerTypes = @(
        [byte], [sbyte], [int16], [uint16], [int32], [uint32], [int64], [uint64]
    )
    if ($Value -is [bool] -or $integerTypes -notcontains $Value.GetType()) {
        throw "$Label deve ser um número inteiro."
    }
    try {
        $converted = [Convert]::ToInt64(
            $Value,
            [Globalization.CultureInfo]::InvariantCulture
        )
    }
    catch {
        throw "$Label está fora do intervalo de Int64."
    }
    if ($converted -lt $Minimum) {
        throw "$Label deve ser maior ou igual a $Minimum."
    }
    return $converted
}

function Test-WindowsReservedName {
    param([Parameter(Mandatory)][string]$Name)

    return $Name -cmatch (
        '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)'
    )
}

function Assert-SafeReleaseId {
    param([Parameter(Mandatory)][string]$ReleaseId)

    if ($ReleaseId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "release_id inválido."
    }
    if (
        $ReleaseId.EndsWith(".", [StringComparison]::Ordinal) -or
        (Test-WindowsReservedName -Name $ReleaseId)
    ) {
        throw "release_id não é um nome de diretório seguro no Windows."
    }
    return $ReleaseId
}

function Assert-SafeRelativeFilePath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )

    if (
        [string]::IsNullOrWhiteSpace($Path) -or
        $Path.Contains("\") -or
        [IO.Path]::IsPathRooted($Path) -or
        $Path.StartsWith("/", [StringComparison]::Ordinal)
    ) {
        throw "$Label deve ser um caminho relativo canônico com '/'."
    }
    $segments = $Path.Split("/")
    foreach ($segment in $segments) {
        if (
            [string]::IsNullOrEmpty($segment) -or
            $segment -ceq "." -or
            $segment -ceq ".." -or
            $segment.EndsWith(".", [StringComparison]::Ordinal) -or
            $segment.EndsWith(" ", [StringComparison]::Ordinal) -or
            $segment -cmatch '[\x00-\x1f<>:"\\|?*]' -or
            (Test-WindowsReservedName -Name $segment)
        ) {
            throw "$Label contém segmento inválido para Windows: '$segment'."
        }
    }
    return $Path
}

function Assert-PathChainWithoutReparsePoint {
    param([Parameter(Mandatory)][string]$Path)

    $current = [IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point recusado na cadeia de caminho: $current"
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) {
            break
        }
        $parentPath = [IO.Path]::TrimEndingDirectorySeparator($parent.FullName)
        if ([string]::Equals(
            $parentPath,
            [IO.Path]::TrimEndingDirectorySeparator($current),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            break
        }
        $current = $parentPath
    }
}

function Assert-RegularFileWithoutReparsePoint {
    param([Parameter(Mandatory)][string]$Path)

    Assert-PathChainWithoutReparsePoint -Path $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Arquivo regular obrigatório ausente: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (
        $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        throw "Arquivo regular não pode ser reparse point: $Path"
    }
}

function Get-BytesSha256 {
    param([Parameter(Mandatory)][byte[]]$Bytes)

    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

function Read-JsonFileEvidence {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$DocumentLabel
    )

    Assert-RegularFileWithoutReparsePoint -Path $Path
    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
    }
    catch {
        throw "Não foi possível ler ${DocumentLabel}: $Path"
    }
    try {
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
        if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
            $text = $text.Substring(1)
        }
        $document = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$DocumentLabel não é JSON UTF-8 válido: $Path"
    }
    if ($null -eq $document) {
        throw "$DocumentLabel está vazio: $Path"
    }
    return [pscustomobject]@{
        Document = $document
        Sha256 = Get-BytesSha256 -Bytes $bytes
        Bytes = [int64]$bytes.LongLength
    }
}

function Get-RegularFileEvidence {
    param([Parameter(Mandatory)][string]$Path)

    Assert-RegularFileWithoutReparsePoint -Path $Path
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read,
        1048576,
        [IO.FileOptions]::SequentialScan
    )
    $digest = [Security.Cryptography.SHA256]::Create()
    try {
        $length = [int64]$stream.Length
        $hashBytes = $digest.ComputeHash($stream)
    }
    finally {
        $digest.Dispose()
        $stream.Dispose()
    }
    return [pscustomobject]@{
        Bytes = $length
        Sha256 = [Convert]::ToHexString($hashBytes).ToLowerInvariant()
    }
}

function Get-OrdinalSortedStrings {
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Values)

    $copy = [string[]]@($Values)
    [Array]::Sort($copy, [StringComparer]::Ordinal)
    return $copy
}

function Resolve-SafeDescendantPath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Label
    )

    [void](Assert-SafeRelativeFilePath -Path $RelativePath -Label $Label)
    $resolvedRoot = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath($Root)
    )
    $candidate = [IO.Path]::GetFullPath((Join-Path $resolvedRoot $RelativePath))
    $prefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label escapa da raiz permitida."
    }
    return $candidate
}

function Get-RegularFilePathsUnderRoot {
    param(
        [Parameter(Mandatory)][string]$Root,
        [AllowEmptyCollection()][string[]]$SkipDirectoryRelativePaths = @()
    )

    Assert-PathChainWithoutReparsePoint -Path $Root
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Diretório obrigatório ausente: $Root"
    }
    $rootItem = Get-Item -LiteralPath $Root -Force -ErrorAction Stop
    if ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Diretório não pode ser reparse point: $Root"
    }

    $skip = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($relative in $SkipDirectoryRelativePaths) {
        [void]$skip.Add($relative.Replace("\", "/"))
    }
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push([IO.Path]::GetFullPath($Root))
    $files = [Collections.Generic.List[string]]::new()
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
            $relativePath = [IO.Path]::GetRelativePath($Root, $item.FullName).Replace("\", "/")
            [void](Assert-SafeRelativeFilePath `
                -Path $relativePath `
                -Label "Caminho observado")
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point recusado dentro do release: $relativePath"
            }
            if ($item.PSIsContainer) {
                if (-not $skip.Contains($relativePath)) {
                    $pending.Push($item.FullName)
                }
            }
            else {
                $files.Add($relativePath)
            }
        }
    }
    return Get-OrdinalSortedStrings -Values $files.ToArray()
}

function ConvertTo-ValidatedFileEntries {
    param(
        [Parameter(Mandatory)]$FilesValue,
        [Parameter(Mandatory)][string]$ListLabel
    )

    $rawEntries = @($FilesValue)
    if ($rawEntries.Count -eq 0) {
        throw "$ListLabel deve conter ao menos um arquivo."
    }
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $validated = [Collections.Generic.List[object]]::new()
    $previousPath = $null
    foreach ($entry in $rawEntries) {
        if ($null -eq $entry -or $entry -is [string]) {
            throw "$ListLabel contém entrada inválida."
        }
        $path = [string](Get-RequiredJsonProperty `
            -Object $entry `
            -Name "path" `
            -DocumentLabel $ListLabel)
        [void](Assert-SafeRelativeFilePath -Path $path -Label "$ListLabel.path")
        if (-not $seen.Add($path)) {
            throw "$ListLabel contém caminho duplicado no Windows: $path"
        }
        if (
            $null -ne $previousPath -and
            [StringComparer]::Ordinal.Compare($previousPath, $path) -ge 0
        ) {
            throw "$ListLabel deve estar ordenado ordinalmente por path."
        }
        $bytes = ConvertTo-RequiredInt64 `
            -Value (Get-RequiredJsonProperty `
                -Object $entry `
                -Name "bytes" `
                -DocumentLabel $ListLabel) `
            -Label "$ListLabel.bytes" `
            -Minimum 0
        $sha256 = [string](Get-RequiredJsonProperty `
            -Object $entry `
            -Name "sha256" `
            -DocumentLabel $ListLabel)
        if ($sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "$ListLabel.sha256 deve ser SHA-256 hexadecimal minúsculo."
        }
        $validated.Add([pscustomobject]@{
            Path = $path
            Bytes = $bytes
            Sha256 = $sha256
        })
        $previousPath = $path
    }
    return $validated.ToArray()
}

function Get-CanonicalFileListSha256 {
    param([Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Entries)

    $lines = @(
        foreach ($entry in $Entries) {
            "$($entry.Path)`t$($entry.Bytes)`t$($entry.Sha256)"
        }
    )
    $canonical = ($lines -join "`n") + "`n"
    return Get-BytesSha256 -Bytes ([Text.Encoding]::UTF8.GetBytes($canonical))
}

function Assert-FileEntriesMatchTree {
    param(
        [Parameter(Mandatory)][string]$ReleaseRoot,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Entries,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ObservedPaths,
        [Parameter(Mandatory)][string]$ListLabel
    )

    if ($Entries.Count -ne $ObservedPaths.Count) {
        throw "$ListLabel não cobre exatamente os arquivos observados."
    }
    for ($index = 0; $index -lt $Entries.Count; $index++) {
        $entry = $Entries[$index]
        if ($entry.Path -cne $ObservedPaths[$index]) {
            throw (
                "$ListLabel diverge da árvore no índice ${index}: " +
                "'$($entry.Path)' != '$($ObservedPaths[$index])'."
            )
        }
        $filePath = Resolve-SafeDescendantPath `
            -Root $ReleaseRoot `
            -RelativePath $entry.Path `
            -Label "$ListLabel.path"
        $evidence = Get-RegularFileEvidence -Path $filePath
        if (
            $evidence.Bytes -ne $entry.Bytes -or
            $evidence.Sha256 -cne $entry.Sha256
        ) {
            throw "$ListLabel não autentica o arquivo '$($entry.Path)'."
        }
    }
}

function Test-IsEnvironmentCachePath {
    param([Parameter(Mandatory)][string]$RelativePath)

    if ($RelativePath.EndsWith(".pyc", [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    foreach ($segment in $RelativePath.Split("/")) {
        if ([string]::Equals(
            $segment,
            "__pycache__",
            [StringComparison]::OrdinalIgnoreCase
        )) {
            return $true
        }
    }
    return $false
}

function New-ReleaseEnvironmentManifest {
    param([Parameter(Mandatory)][string]$ApplicationRoot)

    $resolvedRoot = [IO.Path]::GetFullPath($ApplicationRoot)
    $venvRoot = Join-Path $resolvedRoot ".venv"
    $relativeFiles = @(Get-RegularFilePathsUnderRoot -Root $venvRoot)
    $entries = @(
        foreach ($relativePath in $relativeFiles) {
            $releaseRelativePath = ".venv/$relativePath"
            if (Test-IsEnvironmentCachePath -RelativePath $releaseRelativePath) {
                continue
            }
            $filePath = Resolve-SafeDescendantPath `
                -Root $resolvedRoot `
                -RelativePath $releaseRelativePath `
                -Label "Arquivo do ambiente"
            $evidence = Get-RegularFileEvidence -Path $filePath
            [ordered]@{
                path = $releaseRelativePath
                bytes = $evidence.Bytes
                sha256 = $evidence.Sha256
            }
        }
    )
    $environmentSha256 = Get-CanonicalFileListSha256 -Entries $entries
    $manifestPath = Join-Path $resolvedRoot $script:EnvironmentManifestName
    if (Test-Path -LiteralPath $manifestPath) {
        throw "Inventário do ambiente já existe: $manifestPath"
    }
    $content = ([ordered]@{
        format = 1
        environment_sha256 = $environmentSha256
        files = $entries
    } | ConvertTo-Json -Depth 6) + "`n"
    Write-DurableUtf8File -Path $manifestPath -Content $content
    $manifestEvidence = Get-RegularFileEvidence -Path $manifestPath
    return [pscustomobject]@{
        EnvironmentSha256 = $environmentSha256
        ManifestPath = $manifestPath
        ManifestSha256 = $manifestEvidence.Sha256
    }
}

function Read-ValidatedReleaseManifest {
    param(
        [Parameter(Mandatory)][string]$ApplicationRoot,
        [Parameter(Mandatory)][string]$ExpectedReleaseId,
        [Parameter(Mandatory)][string]$ExpectedManifestSha256
    )

    $manifestPath = Join-Path $ApplicationRoot $script:ReleaseManifestName
    $manifestEvidence = Read-JsonFileEvidence `
        -Path $manifestPath `
        -DocumentLabel "Manifesto do release"
    if ($manifestEvidence.Sha256 -cne $ExpectedManifestSha256) {
        throw "Hash do manifesto do release ativo diverge do ponteiro."
    }
    $manifest = $manifestEvidence.Document
    $format = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $manifest -Name "format" -DocumentLabel "Manifesto do release") `
        -Label "release-manifest.format"
    if ($format -ne 1) {
        throw "Formato de manifesto de release não suportado."
    }
    $releaseId = [string](Get-RequiredJsonProperty `
        -Object $manifest -Name "release_id" -DocumentLabel "Manifesto do release")
    [void](Assert-SafeReleaseId -ReleaseId $releaseId)
    if ($releaseId -cne $ExpectedReleaseId) {
        throw "release_id do manifesto diverge do ponteiro."
    }

    $installKind = [string](Get-RequiredJsonProperty `
        -Object $manifest -Name "install_kind" -DocumentLabel "Manifesto do release")
    $databaseAction = [string](Get-RequiredJsonProperty `
        -Object $manifest -Name "database_action" -DocumentLabel "Manifesto do release")
    if (
        -not (
            ($installKind -ceq "initial" -and $databaseAction -ceq "bootstrap") -or
            ($installKind -ceq "app-only" -and $databaseAction -ceq "none")
        )
    ) {
        throw (
            "Combinação install_kind/database_action inválida; use " +
            "initial/bootstrap ou app-only/none."
        )
    }

    $sourceCommit = [string](Get-RequiredJsonProperty `
        -Object $manifest -Name "source_commit" -DocumentLabel "Manifesto do release")
    if ($sourceCommit -cnotmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
        throw "source_commit inválido no manifesto do release."
    }

    $schema = Get-RequiredJsonProperty `
        -Object $manifest `
        -Name "schema_compatibility" `
        -DocumentLabel "Manifesto do release"
    if ($null -eq $schema -or $schema -is [string]) {
        throw "schema_compatibility inválido no manifesto do release."
    }
    $schemaMinimum = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $schema -Name "minimum" -DocumentLabel "schema_compatibility") `
        -Label "schema_compatibility.minimum" `
        -Minimum 1
    $schemaMaximum = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $schema -Name "maximum" -DocumentLabel "schema_compatibility") `
        -Label "schema_compatibility.maximum" `
        -Minimum 1
    if ($schemaMinimum -gt $schemaMaximum) {
        throw "Faixa schema_compatibility inválida."
    }

    $payloadSha256 = [string](Get-RequiredJsonProperty `
        -Object $manifest -Name "payload_sha256" -DocumentLabel "Manifesto do release")
    if ($payloadSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "payload_sha256 inválido no manifesto do release."
    }
    $payloadEntries = @(ConvertTo-ValidatedFileEntries `
        -FilesValue (Get-RequiredJsonProperty `
            -Object $manifest -Name "payload_files" -DocumentLabel "Manifesto do release") `
        -ListLabel "payload_files")
    foreach ($entry in $payloadEntries) {
        if (
            [string]::Equals(
                $entry.Path,
                $script:ReleaseManifestName,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            [string]::Equals(
                $entry.Path,
                $script:EnvironmentManifestName,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            $entry.Path.StartsWith(".venv/", [StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "payload_files contém arquivo reservado: $($entry.Path)"
        }
    }
    $allPayloadPaths = @(Get-RegularFilePathsUnderRoot `
        -Root $ApplicationRoot `
        -SkipDirectoryRelativePaths @(".venv"))
    $observedPayloadPaths = @(
        $allPayloadPaths | Where-Object {
            -not [string]::Equals(
                $_,
                $script:ReleaseManifestName,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            -not [string]::Equals(
                $_,
                $script:EnvironmentManifestName,
                [StringComparison]::OrdinalIgnoreCase
            )
        }
    )
    Assert-FileEntriesMatchTree `
        -ReleaseRoot $ApplicationRoot `
        -Entries $payloadEntries `
        -ObservedPaths $observedPayloadPaths `
        -ListLabel "payload_files"
    $observedPayloadSha256 = Get-CanonicalFileListSha256 -Entries $payloadEntries
    if ($observedPayloadSha256 -cne $payloadSha256) {
        throw "payload_sha256 diverge do inventário canônico validado."
    }
    $payloadPathSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($entry in $payloadEntries) { [void]$payloadPathSet.Add($entry.Path) }
    foreach ($requiredPayloadPath in @("app.py", "requirements.txt")) {
        if (-not $payloadPathSet.Contains($requiredPayloadPath)) {
            throw "Payload obrigatório ausente: $requiredPayloadPath"
        }
    }

    $environmentManifestReference = [string](Get-RequiredJsonProperty `
        -Object $manifest `
        -Name "environment_manifest" `
        -DocumentLabel "Manifesto do release")
    if ($environmentManifestReference -cne $script:EnvironmentManifestName) {
        throw "environment_manifest deve ser exatamente environment-files.json."
    }
    $environmentManifestSha256 = [string](Get-RequiredJsonProperty `
        -Object $manifest `
        -Name "environment_manifest_sha256" `
        -DocumentLabel "Manifesto do release")
    $environmentSha256 = [string](Get-RequiredJsonProperty `
        -Object $manifest `
        -Name "environment_sha256" `
        -DocumentLabel "Manifesto do release")
    foreach ($hashField in @(
        @("environment_manifest_sha256", $environmentManifestSha256),
        @("environment_sha256", $environmentSha256)
    )) {
        if ([string]$hashField[1] -cnotmatch '^[0-9a-f]{64}$') {
            throw "$($hashField[0]) inválido no manifesto do release."
        }
    }

    $environmentManifestPath = Join-Path `
        $ApplicationRoot `
        $script:EnvironmentManifestName
    $environmentEvidence = Read-JsonFileEvidence `
        -Path $environmentManifestPath `
        -DocumentLabel "Inventário do ambiente"
    if ($environmentEvidence.Sha256 -cne $environmentManifestSha256) {
        throw "environment_manifest_sha256 diverge de environment-files.json."
    }
    $environmentDocument = $environmentEvidence.Document
    $environmentFormat = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $environmentDocument `
            -Name "format" `
            -DocumentLabel "Inventário do ambiente") `
        -Label "environment-files.format"
    if ($environmentFormat -ne 1) {
        throw "Formato de environment-files.json não suportado."
    }
    $inventoryEnvironmentSha256 = [string](Get-RequiredJsonProperty `
        -Object $environmentDocument `
        -Name "environment_sha256" `
        -DocumentLabel "Inventário do ambiente")
    if ($inventoryEnvironmentSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "environment_sha256 inválido em environment-files.json."
    }
    if ($inventoryEnvironmentSha256 -cne $environmentSha256) {
        throw "environment_sha256 diverge entre os dois manifestos."
    }
    $environmentEntries = @(ConvertTo-ValidatedFileEntries `
        -FilesValue (Get-RequiredJsonProperty `
            -Object $environmentDocument `
            -Name "files" `
            -DocumentLabel "Inventário do ambiente") `
        -ListLabel "environment-files.files")
    foreach ($entry in $environmentEntries) {
        if (-not $entry.Path.StartsWith(
            ".venv/",
            [StringComparison]::Ordinal
        )) {
            throw "Arquivo do ambiente deve começar com '.venv/': $($entry.Path)"
        }
        if (Test-IsEnvironmentCachePath -RelativePath $entry.Path) {
            throw "Cache Python não deve constar do inventário: $($entry.Path)"
        }
    }

    $venvRoot = Join-Path $ApplicationRoot ".venv"
    $venvRelativeFiles = @(Get-RegularFilePathsUnderRoot -Root $venvRoot)
    $observedEnvironmentPaths = @(
        foreach ($relativePath in $venvRelativeFiles) {
            $releaseRelativePath = ".venv/$relativePath"
            if (-not (Test-IsEnvironmentCachePath -RelativePath $releaseRelativePath)) {
                $releaseRelativePath
            }
        }
    )
    $observedEnvironmentPaths = @(
        Get-OrdinalSortedStrings -Values $observedEnvironmentPaths
    )
    Assert-FileEntriesMatchTree `
        -ReleaseRoot $ApplicationRoot `
        -Entries $environmentEntries `
        -ObservedPaths $observedEnvironmentPaths `
        -ListLabel "environment-files.files"
    $observedEnvironmentSha256 = Get-CanonicalFileListSha256 `
        -Entries $environmentEntries
    if ($observedEnvironmentSha256 -cne $environmentSha256) {
        throw "environment_sha256 diverge do ambiente integralmente validado."
    }
    $environmentPathSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($entry in $environmentEntries) {
        [void]$environmentPathSet.Add($entry.Path)
    }
    if (-not $environmentPathSet.Contains(".venv/Scripts/python.exe")) {
        throw "Inventário do ambiente não contém .venv/Scripts/python.exe."
    }

    return [pscustomobject]@{
        ManifestPath = $manifestPath
        ManifestSha256 = $manifestEvidence.Sha256
        InstallKind = $installKind
        DatabaseAction = $databaseAction
        SchemaMinimum = $schemaMinimum
        SchemaMaximum = $schemaMaximum
        PayloadSha256 = $payloadSha256
        EnvironmentSha256 = $environmentSha256
        EnvironmentManifestSha256 = $environmentManifestSha256
    }
}

function Read-ReleasePointerFile {
    param(
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][string]$PointerPath
    )

    $resolvedRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    Assert-PathChainWithoutReparsePoint -Path $resolvedRoot
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "Raiz de instalação ausente: $resolvedRoot"
    }
    $stateRoot = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath((Join-Path $resolvedRoot "state"))
    )
    $resolvedPointerPath = [IO.Path]::GetFullPath($PointerPath)
    $pointerParent = [IO.Path]::TrimEndingDirectorySeparator(
        [IO.Path]::GetFullPath((Split-Path -Parent $resolvedPointerPath))
    )
    if (-not [string]::Equals(
        $pointerParent,
        $stateRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Ponteiro deve ser arquivo descendente direto de state."
    }
    $pointerEvidence = Read-JsonFileEvidence `
        -Path $resolvedPointerPath `
        -DocumentLabel "Ponteiro de release"
    $pointer = $pointerEvidence.Document
    $format = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $pointer -Name "format" -DocumentLabel "Ponteiro de release") `
        -Label "pointer.format"
    if ($format -ne 1) {
        throw "Formato de ponteiro não suportado: $resolvedPointerPath"
    }
    $generation = ConvertTo-RequiredInt64 `
        -Value (Get-RequiredJsonProperty `
            -Object $pointer -Name "generation" -DocumentLabel "Ponteiro de release") `
        -Label "pointer.generation"
    $releaseId = [string](Get-RequiredJsonProperty `
        -Object $pointer -Name "release_id" -DocumentLabel "Ponteiro de release")
    [void](Assert-SafeReleaseId -ReleaseId $releaseId)
    $kind = [string](Get-RequiredJsonProperty `
        -Object $pointer -Name "kind" -DocumentLabel "Ponteiro de release")
    $applicationRelative = [string](Get-RequiredJsonProperty `
        -Object $pointer `
        -Name "application_relative_path" `
        -DocumentLabel "Ponteiro de release")
    $pythonRelative = [string](Get-RequiredJsonProperty `
        -Object $pointer `
        -Name "python_relative_path" `
        -DocumentLabel "Ponteiro de release")
    [void](Assert-SafeRelativeFilePath `
        -Path $applicationRelative `
        -Label "application_relative_path")
    [void](Assert-SafeRelativeFilePath `
        -Path $pythonRelative `
        -Label "python_relative_path")
    $applicationRoot = Resolve-SafeDescendantPath `
        -Root $resolvedRoot `
        -RelativePath $applicationRelative `
        -Label "application_relative_path"
    $pythonPath = Resolve-SafeDescendantPath `
        -Root $resolvedRoot `
        -RelativePath $pythonRelative `
        -Label "python_relative_path"

    $manifestSha256 = ""
    $validatedManifest = $null
    if ($kind -ceq "legacy") {
        if (
            $applicationRelative -cne "app" -or
            $pythonRelative -cne ".venv/Scripts/python.exe"
        ) {
            throw "Ponteiro legado não usa os caminhos históricos exatos."
        }
        $legacyManifestHash = Get-RequiredJsonProperty `
            -Object $pointer `
            -Name "manifest_sha256" `
            -DocumentLabel "Ponteiro de release"
        if (-not [string]::IsNullOrEmpty([string]$legacyManifestHash)) {
            throw "Ponteiro legado não pode declarar manifest_sha256."
        }
        Assert-PathChainWithoutReparsePoint -Path $applicationRoot
        if (-not (Test-Path -LiteralPath $applicationRoot -PathType Container)) {
            throw "Aplicação legada ausente: $applicationRoot"
        }
        Assert-RegularFileWithoutReparsePoint -Path $pythonPath
    }
    elseif ($kind -ceq "release") {
        if ($generation -lt 1) {
            throw "Release formal exige geração maior ou igual a 1."
        }
        $expectedApplicationRelative = "releases/$releaseId"
        $expectedPythonRelative = "$expectedApplicationRelative/.venv/Scripts/python.exe"
        if (
            $applicationRelative -cne $expectedApplicationRelative -or
            $pythonRelative -cne $expectedPythonRelative
        ) {
            throw "Caminhos do release não correspondem ao release_id."
        }
        Assert-PathChainWithoutReparsePoint -Path $applicationRoot
        if (-not (Test-Path -LiteralPath $applicationRoot -PathType Container)) {
            throw "Diretório de release ausente: $applicationRoot"
        }
        $manifestSha256 = [string](Get-RequiredJsonProperty `
            -Object $pointer `
            -Name "manifest_sha256" `
            -DocumentLabel "Ponteiro de release")
        if ($manifestSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Hash do manifesto inválido no ponteiro."
        }
        $validatedManifest = Read-ValidatedReleaseManifest `
            -ApplicationRoot $applicationRoot `
            -ExpectedReleaseId $releaseId `
            -ExpectedManifestSha256 $manifestSha256
        Assert-RegularFileWithoutReparsePoint -Path $pythonPath
    }
    else {
        throw "Tipo de release desconhecido no ponteiro: $kind"
    }

    return [pscustomobject]@{
        Format = 1
        Generation = $generation
        ReleaseId = $releaseId
        Kind = $kind
        ApplicationRelativePath = $applicationRelative
        PythonRelativePath = $pythonRelative
        ApplicationRoot = $applicationRoot
        PythonPath = $pythonPath
        ManifestSha256 = $manifestSha256
        ManifestPath = if ($null -ne $validatedManifest) {
            $validatedManifest.ManifestPath
        } else { $null }
        InstallKind = if ($null -ne $validatedManifest) {
            $validatedManifest.InstallKind
        } else { "legacy" }
        DatabaseAction = if ($null -ne $validatedManifest) {
            $validatedManifest.DatabaseAction
        } else { $null }
        SchemaMinimum = if ($null -ne $validatedManifest) {
            $validatedManifest.SchemaMinimum
        } else { $null }
        SchemaMaximum = if ($null -ne $validatedManifest) {
            $validatedManifest.SchemaMaximum
        } else { $null }
        PayloadSha256 = if ($null -ne $validatedManifest) {
            $validatedManifest.PayloadSha256
        } else { $null }
        EnvironmentSha256 = if ($null -ne $validatedManifest) {
            $validatedManifest.EnvironmentSha256
        } else { $null }
        PointerPath = $resolvedPointerPath
        PointerSha256 = $pointerEvidence.Sha256
    }
}

function Resolve-ActiveRelease {
    param(
        [Parameter(Mandatory)][string]$InstallRoot,
        [switch]$AllowBackupPointer
    )

    $resolvedRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    $stateRoot = Join-Path $resolvedRoot "state"
    $activePath = Join-Path $stateRoot "active-release.json"
    try {
        $result = Read-ReleasePointerFile `
            -InstallRoot $resolvedRoot `
            -PointerPath $activePath
        $result | Add-Member -NotePropertyName UsedBackupPointer -NotePropertyValue $false
        return $result
    }
    catch {
        $activeFailure = $_.Exception.Message
        if (-not $AllowBackupPointer) {
            throw
        }
        $backupPath = Join-Path $stateRoot "active-release.json.bak"
        try {
            $result = Read-ReleasePointerFile `
                -InstallRoot $resolvedRoot `
                -PointerPath $backupPath
            $result | Add-Member -NotePropertyName UsedBackupPointer -NotePropertyValue $true
            return $result
        }
        catch {
            throw (
                "Ponteiros ativo e de backup inválidos. " +
                "Ativo: $activeFailure Backup: $($_.Exception.Message)"
            )
        }
    }
}

function Write-DurableUtf8File {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    Assert-PathChainWithoutReparsePoint -Path (Split-Path -Parent $Path)
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

function Set-ActiveReleasePointer {
    param(
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Pointer,
        [Nullable[int64]]$ExpectedGeneration
    )

    $resolvedRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    Assert-PathChainWithoutReparsePoint -Path $resolvedRoot
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "Raiz de instalação ausente: $resolvedRoot"
    }
    $stateRoot = Join-Path $resolvedRoot "state"
    New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
    Assert-PathChainWithoutReparsePoint -Path $stateRoot
    $activePath = Join-Path $stateRoot "active-release.json"
    $backupPath = Join-Path $stateRoot "active-release.json.bak"
    $temporaryPath = Join-Path $stateRoot (
        "active-release.next-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    $content = ($Pointer | ConvertTo-Json -Depth 6) + "`n"
    Write-DurableUtf8File -Path $temporaryPath -Content $content
    try {
        $candidate = Read-ReleasePointerFile `
            -InstallRoot $resolvedRoot `
            -PointerPath $temporaryPath

        $activeExists = Test-Path -LiteralPath $activePath -PathType Leaf
        if (
            -not $activeExists -and
            (Test-Path -LiteralPath $activePath)
        ) {
            throw "Ponteiro ativo existe, mas não é arquivo regular."
        }
        if ($activeExists) {
            if (-not $PSBoundParameters.ContainsKey("ExpectedGeneration")) {
                throw "Troca de ponteiro existente exige -ExpectedGeneration."
            }
            $current = Read-ReleasePointerFile `
                -InstallRoot $resolvedRoot `
                -PointerPath $activePath
            if ($current.Generation -ne [int64]$ExpectedGeneration) {
                throw (
                    "CAS recusado: geração ativa $($current.Generation), " +
                    "esperada $([int64]$ExpectedGeneration)."
                )
            }
            if ($candidate.Generation -ne ($current.Generation + 1)) {
                throw "Nova geração deve ser exatamente a geração ativa + 1."
            }
            $latestActiveEvidence = Read-JsonFileEvidence `
                -Path $activePath `
                -DocumentLabel "Ponteiro ativo"
            if ($latestActiveEvidence.Sha256 -cne $current.PointerSha256) {
                throw "CAS recusado: ponteiro ativo mudou durante a troca."
            }
            if (Test-Path -LiteralPath $backupPath) {
                Assert-RegularFileWithoutReparsePoint -Path $backupPath
            }
            [IO.File]::Replace($temporaryPath, $activePath, $backupPath, $true)
        }
        else {
            if ($PSBoundParameters.ContainsKey("ExpectedGeneration")) {
                throw "Criação inicial não aceita -ExpectedGeneration."
            }
            if (Test-Path -LiteralPath $backupPath) {
                throw "Criação inicial recusada porque já existe ponteiro de backup."
            }
            $validInitialPointer = (
                ($candidate.Kind -ceq "legacy" -and $candidate.Generation -eq 0) -or
                ($candidate.Kind -ceq "release" -and $candidate.Generation -eq 1)
            )
            if (-not $validInitialPointer) {
                throw (
                    "Criação inicial exige legacy/geração 0 ou release/geração 1."
                )
            }
            [IO.File]::Move($temporaryPath, $activePath)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
    return Resolve-ActiveRelease -InstallRoot $resolvedRoot
}

function Restore-BackupReleasePointer {
    param([Parameter(Mandatory)][string]$InstallRoot)

    $resolvedRoot = Resolve-ExactInstallRoot -Path $InstallRoot
    $stateRoot = Join-Path $resolvedRoot "state"
    $activePath = Join-Path $stateRoot "active-release.json"
    $backupPath = Join-Path $stateRoot "active-release.json.bak"
    $backup = Read-ReleasePointerFile `
        -InstallRoot $resolvedRoot `
        -PointerPath $backupPath
    $active = $null
    if (Test-Path -LiteralPath $activePath -PathType Leaf) {
        try {
            $active = Read-ReleasePointerFile `
                -InstallRoot $resolvedRoot `
                -PointerPath $activePath
        }
        catch {
            # O restore pode reparar um ativo corrompido, mas jamais usa seus
            # campos para construir a nova geração.
            $active = $null
        }
    }
    elseif (Test-Path -LiteralPath $activePath) {
        throw "Ponteiro ativo existe, mas não é arquivo regular."
    }
    $baseGeneration = if ($null -ne $active) {
        $active.Generation
    }
    else {
        $backup.Generation
    }
    $restorePointer = [ordered]@{
        format = 1
        generation = $baseGeneration + 1
        release_id = $backup.ReleaseId
        kind = $backup.Kind
        application_relative_path = $backup.ApplicationRelativePath
        python_relative_path = $backup.PythonRelativePath
        manifest_sha256 = if ($backup.Kind -ceq "release") {
            $backup.ManifestSha256
        } else { $null }
    }
    $restorePath = Join-Path $stateRoot (
        "active-release.restore-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    $rejectedPath = Join-Path $stateRoot (
        "active-release.rejected-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    try {
        $restoreContent = ($restorePointer | ConvertTo-Json -Depth 6) + "`n"
        Write-DurableUtf8File -Path $restorePath -Content $restoreContent
        [void](Read-ReleasePointerFile `
            -InstallRoot $resolvedRoot `
            -PointerPath $restorePath)
        if ($null -ne $active) {
            $latestActiveEvidence = Read-JsonFileEvidence `
                -Path $activePath `
                -DocumentLabel "Ponteiro ativo"
            if ($latestActiveEvidence.Sha256 -cne $active.PointerSha256) {
                throw "Restore recusado: ponteiro ativo mudou durante a operação."
            }
            [IO.File]::Replace($restorePath, $activePath, $rejectedPath, $true)
        }
        elseif (Test-Path -LiteralPath $activePath -PathType Leaf) {
            # Ativo corrompido: arquive-o sem sobrescrever o .bak válido.
            [IO.File]::Replace($restorePath, $activePath, $rejectedPath, $true)
        }
        else {
            # Ativo ausente: o .bak continua preservado; restorePath é uma cópia.
            [IO.File]::Move($restorePath, $activePath)
        }
    }
    finally {
        if (Test-Path -LiteralPath $restorePath) {
            Remove-Item -LiteralPath $restorePath -Force
        }
    }
    return Resolve-ActiveRelease -InstallRoot $resolvedRoot
}
