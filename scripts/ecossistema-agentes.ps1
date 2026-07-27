<#
.SYNOPSIS
    Configura e opera o ecossistema de agentes somente deste repositorio.

.EXAMPLE
    .\scripts\ecossistema-agentes.ps1 -Acao Configurar

.EXAMPLE
    .\scripts\ecossistema-agentes.ps1 -Acao Diagnosticar
#>

[CmdletBinding()]
param(
    [ValidateSet("Configurar", "Iniciar", "Parar", "Diagnosticar", "AbrirPainel")]
    [string]$Acao = "Configurar",

    [switch]$PularLoginCodex
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$hashAlgorithm = [Security.Cryptography.SHA256]::Create()
try {
    $projectHashBytes = $hashAlgorithm.ComputeHash(
        [Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant())
    )
}
finally {
    $hashAlgorithm.Dispose()
}
$projectHash = -join ($projectHashBytes | ForEach-Object { $_.ToString("x2") })
$RuntimeRoot = Join-Path $env:LOCALAPPDATA (Join-Path "cpx" $projectHash.Substring(0, 12))
$OmniData = Join-Path $RuntimeRoot "omniroute"
$CodexHome = Join-Path $RuntimeRoot "codex-home"
$CodexAgents = Join-Path $CodexHome "agents"
$LogDir = Join-Path $RuntimeRoot "logs"
$PidPath = Join-Path $RuntimeRoot "omniroute.pid"
$OmniPort = 32128
$OmniBaseUrl = "http://127.0.0.1:$OmniPort"
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if ($null -ne $nodeCommand) {
    $NodePath = $nodeCommand.Source
}
else {
    $NodePath = "C:\Program Files\nodejs\node.exe"
}
$OmniEntry = Join-Path $env:APPDATA "npm\node_modules\omniroute\bin\omniroute.mjs"
$env:HANDBALL_AGENT_RUNTIME = $RuntimeRoot

function Find-CodexExecutable {
    $localRoot = Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin"
    if (Test-Path -LiteralPath $localRoot) {
        $found = Get-ChildItem -LiteralPath $localRoot -Depth 2 -Filter "codex.exe" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -ne $found) {
            return $found.FullName
        }
    }

    $command = Get-Command codex.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "Codex CLI nao encontrado. Atualize ou reinstale o aplicativo Codex."
}

function New-StorageKey {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

function Initialize-ProjectRuntime {
    foreach ($path in @($RuntimeRoot, $OmniData, $CodexHome, $CodexAgents, $LogDir)) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }

    $markerPath = Join-Path $RuntimeRoot "project-path.txt"
    if (Test-Path -LiteralPath $markerPath) {
        $registeredProject = (Get-Content -LiteralPath $markerPath -Raw).Trim()
        if ($registeredProject -ne $ProjectRoot) {
            throw "Colisao de runtime: $RuntimeRoot pertence a outro projeto."
        }
    }
    else {
        Set-Content -LiteralPath $markerPath -Value $ProjectRoot -Encoding utf8
    }

    $omniEnv = Join-Path $OmniData ".env"
    if (-not (Test-Path -LiteralPath $omniEnv)) {
        $key = New-StorageKey
        @(
            "STORAGE_ENCRYPTION_KEY=$key"
            "OMNIROUTE_AUTO_FREE_FALLBACK_TO_FULL_POOL=false"
            "OMNIROUTE_EMERGENCY_FALLBACK=false"
        ) | Set-Content -LiteralPath $omniEnv -Encoding utf8
    }

    $codexConfig = Join-Path $CodexHome "config.toml"
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".codex\codex-home.config.toml") `
        -Destination $codexConfig -Force

    # A confianca e restrita ao caminho absoluto deste repositorio e vive no
    # CODEX_HOME isolado. Ela permite carregar .codex/config.toml e apresentar
    # o hook para a revisao de hash exigida pelo Codex.
    $tomlProjectRoot = $ProjectRoot.Replace("\", "\\").Replace('"', '\"')
    @(
        ""
        "[projects.`"$tomlProjectRoot`"]"
        'trust_level = "trusted"'
    ) | Add-Content -LiteralPath $codexConfig -Encoding utf8

    Get-ChildItem -LiteralPath (Join-Path $ProjectRoot ".codex\agent-templates") -Filter "*.toml" |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $CodexAgents $_.Name) -Force
        }
}

function Test-OmniReady {
    try {
        $null = Invoke-RestMethod -Uri "$OmniBaseUrl/v1/models" -TimeoutSec 3
        return $true
    }
    catch {
        return $false
    }
}

function Get-ProjectOmniProcess {
    if (-not (Test-Path -LiteralPath $PidPath)) {
        return $null
    }
    $raw = (Get-Content -LiteralPath $PidPath -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) {
        return $null
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    $executablePath = [string]$process.ExecutablePath
    if (
        -not $commandLine.Contains($OmniEntry, [StringComparison]::OrdinalIgnoreCase) -or
        -not $executablePath.Equals($NodePath, [StringComparison]::OrdinalIgnoreCase) -or
        $commandLine -notmatch "(^|\s)--port(\s|=)32128(\s|$)"
    ) {
        return $null
    }
    return $process
}

function Set-OmniProcessEnvironment {
    $storageLine = Get-Content -LiteralPath (Join-Path $OmniData ".env") |
        Where-Object { $_ -like "STORAGE_ENCRYPTION_KEY=*" } |
        Select-Object -First 1
    if (-not $storageLine) {
        throw "Chave local do OmniRoute ausente."
    }

    $env:DATA_DIR = $OmniData
    $env:PORT = [string]$OmniPort
    $env:OMNIROUTE_SERVER_HOST = "127.0.0.1"
    $env:OMNIROUTE_CLI_SKIP_REPO_ENV = "1"
    $env:OMNIROUTE_AUTO_FREE_FALLBACK_TO_FULL_POOL = "false"
    $env:OMNIROUTE_EMERGENCY_FALLBACK = "false"
    $env:STORAGE_ENCRYPTION_KEY = $storageLine.Substring("STORAGE_ENCRYPTION_KEY=".Length)

    # A CLI do OmniRoute e iniciada pelo node.exe absoluto, mas seu supervisor
    # cria o servidor-filho chamando "node". Garanta o caminho apenas neste
    # processo, sem alterar PATH do usuario ou da maquina.
    $nodeDirectory = Split-Path -Parent $NodePath
    $pathParts = @($env:Path -split ";" | Where-Object { $_ })
    if ($pathParts -notcontains $nodeDirectory) {
        $env:Path = "$nodeDirectory;$env:Path"
    }
}

function Start-ProjectOmniRoute {
    if (Test-OmniReady) {
        if ($null -ne (Get-ProjectOmniProcess)) {
            Write-Host "OmniRoute do projeto ja esta ativo em $OmniBaseUrl." -ForegroundColor Green
            return
        }

        # O OmniRoute inicia um processo-filho (server-ws.mjs) que fica como
        # dono da porta; o PID persistido pelo supervisor pode ser perdido ou
        # ficar obsoleto apos uma atualizacao. Reassocie somente um supervisor
        # que contenha a entrada deste OmniRoute e a porta deste projeto.
        $runningSupervisor = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "node.exe" -and
                ([string]$_.CommandLine).Contains($OmniEntry, [StringComparison]::OrdinalIgnoreCase) -and
                ([string]$_.CommandLine) -match "(^|\s)--port(\s|=)32128(\s|$)"
            } |
            Select-Object -First 1
        if ($null -ne $runningSupervisor) {
            Set-Content -LiteralPath $PidPath -Value ([string]$runningSupervisor.ProcessId) -Encoding ascii
            Write-Host "OmniRoute do projeto ja estava ativo; PID reassociado ($($runningSupervisor.ProcessId))." -ForegroundColor Green
            return
        }
        throw "A porta $OmniPort responde, mas nao pertence ao processo registrado deste projeto."
    }

    if (-not (Test-Path -LiteralPath $NodePath)) {
        throw "Node.js nao encontrado em $NodePath."
    }
    if (-not (Test-Path -LiteralPath $OmniEntry)) {
        throw "OmniRoute nao encontrado em $OmniEntry."
    }

    Set-OmniProcessEnvironment
    $stdout = Join-Path $LogDir "omniroute.stdout.log"
    $stderr = Join-Path $LogDir "omniroute.stderr.log"
    $arguments = @(
        $OmniEntry,
        "serve",
        "--port",
        [string]$OmniPort,
        "--no-open",
        "--no-tray"
    )

    $process = Start-Process -FilePath $NodePath `
        -ArgumentList $arguments `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Set-Content -LiteralPath $PidPath -Value $process.Id -Encoding ascii

    for ($attempt = 1; $attempt -le 45; $attempt++) {
        if ($process.HasExited) {
            $details = ""
            if (Test-Path -LiteralPath $stderr) {
                $details = (Get-Content -LiteralPath $stderr -Tail 40) -join [Environment]::NewLine
            }
            throw "OmniRoute encerrou durante a inicializacao.`n$details"
        }
        if (Test-OmniReady) {
            Write-Host "OmniRoute do projeto ativo em $OmniBaseUrl." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "OmniRoute nao ficou pronto em 45 segundos. Consulte $stderr."
}

function Stop-ProjectOmniRoute {
    $process = Get-ProjectOmniProcess
    if ($null -eq $process) {
        Write-Host "Nenhum processo OmniRoute registrado para este projeto."
        return
    }
    Stop-Process -Id ([int]$process.ProcessId) -Force
    if (Test-Path -LiteralPath $PidPath) {
        Remove-Item -LiteralPath $PidPath -Force
    }
    Write-Host "OmniRoute deste projeto foi encerrado." -ForegroundColor Yellow
}

function Ensure-CodexLogin {
    $codex = Find-CodexExecutable
    $previousHome = $env:CODEX_HOME
    try {
        $env:CODEX_HOME = $CodexHome
        & $codex login status *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Codex isolado: login ja esta valido." -ForegroundColor Green
            return
        }

        Write-Host ""
        Write-Host "O navegador sera aberto. Entre com sua conta paga do ChatGPT." -ForegroundColor Cyan
        & $codex login
        if ($LASTEXITCODE -ne 0) {
            throw "Login do Codex nao foi concluido."
        }
    }
    finally {
        $env:CODEX_HOME = $previousHome
    }
}

function Show-Diagnostics {
    Write-Host ""
    Write-Host "=== Diagnostico do ecossistema deste projeto ===" -ForegroundColor Cyan
    Write-Host "Projeto:      $ProjectRoot"
    Write-Host "Runtime:      $RuntimeRoot"
    Write-Host "OmniRoute:    $OmniBaseUrl"

    if (Test-Path -LiteralPath $NodePath) {
        Write-Host "Node:         $(& $NodePath --version)"
    }
    if (Test-Path -LiteralPath $OmniEntry) {
        Write-Host "OmniRoute:    $(& $NodePath $OmniEntry --version)"
    }

    $codex = Find-CodexExecutable
    Write-Host "Codex:        $(& $codex --version)"
    $previousHome = $env:CODEX_HOME
    try {
        $env:CODEX_HOME = $CodexHome
        & $codex login status
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Codex deste projeto ainda precisa de login."
        }
    }
    finally {
        $env:CODEX_HOME = $previousHome
    }

    & py -3 (Join-Path $PSScriptRoot "consultar_planejadores.py") --check --formato markdown
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Um dos planejadores pagos nao passou no diagnostico."
    }

    if (Test-OmniReady) {
        $catalog = Invoke-RestMethod -Uri "$OmniBaseUrl/v1/models" -TimeoutSec 10
        $ids = @($catalog.data | ForEach-Object { $_.id })
        if ($ids -contains "auto/coding:free") {
            Write-Host "Rota gratuita: auto/coding:free disponivel." -ForegroundColor Green
        }
        else {
            Write-Warning "A rota auto/coding:free nao apareceu no catalogo."
        }

        $freeModels = @(
            $catalog.data |
                Where-Object { $_.id -match "(?i)free|pickle" } |
                Select-Object -ExpandProperty id -Unique |
                Sort-Object
        )
        if ($freeModels.Count -gt 0) {
            Write-Host "Modelos/rotas gratuitas visiveis:"
            $freeModels | ForEach-Object { Write-Host "  - $_" }
        }

        try {
            $smokeBody = @{
                model = "auto/coding:free"
                input = "Responda somente com OK."
                stream = $false
            } | ConvertTo-Json
            $smoke = Invoke-WebRequest -Method Post `
                -Uri "$OmniBaseUrl/v1/responses" `
                -ContentType "application/json" `
                -Body $smokeBody `
                -TimeoutSec 30
            $smokePayload = $smoke.Content | ConvertFrom-Json
            $smokeCost = [string]$smoke.Headers["x-omniroute-response-cost"]
            $parsedCost = [decimal]::Parse(
                $smokeCost,
                [Globalization.CultureInfo]::InvariantCulture
            )
            if ($smokePayload.output_text -and $parsedCost -eq 0) {
                Write-Host "Inferencia gratuita: OK (custo reportado $smokeCost)." -ForegroundColor Green
            }
            else {
                Write-Warning "A inferencia respondeu, mas nao comprovou texto e custo zero."
            }
        }
        catch {
            Write-Warning "O smoke test de auto/coding:free falhou: $($_.Exception.Message)"
        }

        & $NodePath $OmniEntry --base-url $OmniBaseUrl providers list
    }
    else {
        Write-Warning "OmniRoute do projeto nao esta ativo."
    }
}

Set-Location $ProjectRoot

switch ($Acao) {
    "Configurar" {
        Initialize-ProjectRuntime
        Start-ProjectOmniRoute
        if (-not $PularLoginCodex) {
            Ensure-CodexLogin
        }
        Show-Diagnostics
        Write-Host ""
        Write-Host "Proximo passo: abra $OmniBaseUrl e cadastre somente provedores/modelos gratuitos." -ForegroundColor Cyan
    }
    "Iniciar" {
        Initialize-ProjectRuntime
        Start-ProjectOmniRoute
    }
    "Parar" {
        Stop-ProjectOmniRoute
    }
    "Diagnosticar" {
        Initialize-ProjectRuntime
        Show-Diagnostics
    }
    "AbrirPainel" {
        Initialize-ProjectRuntime
        Start-ProjectOmniRoute
        Start-Process $OmniBaseUrl
    }
}
