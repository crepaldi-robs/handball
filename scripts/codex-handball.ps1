<#
.SYNOPSIS
    Abre o Codex com configuracao e credenciais isoladas deste projeto.

.EXAMPLE
    .\scripts\codex-handball.ps1

.EXAMPLE
    .\scripts\codex-handball.ps1 -Prompt "Faca a peer-review completa para o proximo commit."
#>

[CmdletBinding()]
param(
    [string]$Prompt = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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
$CodexHome = Join-Path $RuntimeRoot "codex-home"
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

& (Join-Path $PSScriptRoot "ecossistema-agentes.ps1") -Acao Iniciar

$codex = Find-CodexExecutable
$previousHome = $env:CODEX_HOME
try {
    $env:CODEX_HOME = $CodexHome
    & $codex login status *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Entre com sua conta paga do ChatGPT no navegador." -ForegroundColor Cyan
        & $codex login
        if ($LASTEXITCODE -ne 0) {
            throw "Login do Codex nao foi concluido."
        }
    }

    Write-Host ""
    Write-Host "Na primeira abertura, use /hooks e confie no hook deste repositorio." -ForegroundColor Yellow
    Write-Host "Depois disso, converse somente com o Codex; ele delegara a execucao aos agentes free_*." -ForegroundColor Cyan
    Write-Host ""

    $arguments = @(
        "--strict-config",
        "-C",
        $ProjectRoot,
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never"
    )
    if ($Prompt) {
        $arguments += $Prompt
    }
    & $codex @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Codex terminou com codigo $LASTEXITCODE."
    }
}
finally {
    $env:CODEX_HOME = $previousHome
}
