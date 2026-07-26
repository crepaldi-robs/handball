[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("APP_ONLY", "DB_MIGRATION")]
    [string]$Modo = "APP_ONLY",

    [string]$InstallRoot = "C:\ProgramData\CrepaldiHandball"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Assert-Administrator {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        throw (
            "Abra o PowerShell 7 como Administrador e execute novamente este " +
            "mesmo comando."
        )
    }
}

function Assert-PowerShell7 {
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw (
            "PowerShell 7 ou superior é obrigatório. Abra o aplicativo " +
            "'PowerShell 7' como Administrador."
        )
    }
}

function Write-Step {
    param(
        [Parameter(Mandatory)][int]$Number,
        [Parameter(Mandatory)][int]$Total,
        [Parameter(Mandatory)][string]$Message
    )

    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Number, $Total, $Message) `
        -ForegroundColor Cyan
}

function Assert-RequiredFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label ausente: $Path"
    }
}

function Invoke-GitCheck {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )

    & git -C $ProjectRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Invoke-ProjectValidation {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$TestScript
    )

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git não foi encontrado no PATH."
    }

    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    Assert-RequiredFile `
        -Path $python `
        -Label "Python do ambiente virtual do projeto"

    & $TestScript
    if ($LASTEXITCODE -ne 0) {
        throw "Testes falharam; nenhuma atualização foi iniciada."
    }

    & $python -m compileall -q app.py attendance handball tests
    if ($LASTEXITCODE -ne 0) {
        throw "compileall falhou; nenhuma atualização foi iniciada."
    }

    Invoke-GitCheck `
        -ProjectRoot $ProjectRoot `
        -Arguments @("diff", "--check") `
        -FailureMessage "git diff --check reprovou alterações locais."
    Invoke-GitCheck `
        -ProjectRoot $ProjectRoot `
        -Arguments @("diff", "--cached", "--check") `
        -FailureMessage "git diff --cached --check reprovou o index."
}

function Get-DatabaseMigrationPlan {
    param(
        [Parameter(Mandatory)][string]$MigrationScript,
        [Parameter(Mandatory)][string]$InstallRoot
    )

    $planOutput = @(
        & $MigrationScript -InstallRoot $InstallRoot
    )
    if ($planOutput.Count -eq 0) {
        throw "O planejador da migração não retornou JSON."
    }

    $planText = $planOutput -join [Environment]::NewLine
    try {
        $plan = $planText | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Não foi possível interpretar o plano de migração: $planText"
    }

    $action = [string]$plan.action
    if ($action -notin @(
        "none",
        "adopt-baseline",
        "migrate",
        "blocked",
        "bootstrap-required"
    )) {
        throw "O plano retornou uma ação não reconhecida: '$action'."
    }

    return $plan
}

Assert-PowerShell7
Assert-Administrator

$ProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$TestScript = Join-Path $ProjectRoot "scripts\test.ps1"
$UpdateScript = Join-Path $ProjectRoot "scripts\update-server.ps1"
$MigrationScript = Join-Path $ProjectRoot "scripts\migrate-database.ps1"

Assert-RequiredFile -Path $TestScript -Label "Runner de testes"
Assert-RequiredFile -Path $UpdateScript -Label "Atualizador APP_ONLY"
Assert-RequiredFile -Path $MigrationScript -Label "Runner DB_MIGRATION"

$TotalSteps = if ($Modo -ceq "DB_MIGRATION") { 4 } else { 2 }
$startedAt = [DateTimeOffset]::Now

Write-Host ""
Write-Host "Atualização automatizada do Handball" -ForegroundColor Green
Write-Host "Modo: $Modo"
Write-Host "Instalação: $InstallRoot"
if ($Modo -ceq "APP_ONLY") {
    Write-Host (
        "Garantia: este modo não executa DDL, migration, seed ou restore."
    )
}
else {
    Write-Host (
        "Autorização: DB_MIGRATION planejará e aplicará a evolução do banco " +
        "somente após ativar uma release compatível."
    ) -ForegroundColor Yellow
}

Push-Location $ProjectRoot
try {
    Write-Step `
        -Number 1 `
        -Total $TotalSteps `
        -Message "Executando testes, compileall e verificações Git"
    Invoke-ProjectValidation `
        -ProjectRoot $ProjectRoot `
        -TestScript $TestScript

    Write-Step `
        -Number 2 `
        -Total $TotalSteps `
        -Message "Criando e ativando release APP_ONLY"
    & $UpdateScript -InstallRoot $InstallRoot

    if ($Modo -ceq "DB_MIGRATION") {
        Write-Step `
            -Number 3 `
            -Total $TotalSteps `
            -Message "Gerando e validando o plano DB_MIGRATION sem escrita"
        $plan = Get-DatabaseMigrationPlan `
            -MigrationScript $MigrationScript `
            -InstallRoot $InstallRoot
        $plan | ConvertTo-Json -Depth 10

        $action = [string]$plan.action
        if ($action -ceq "none") {
            Write-Host ""
            Write-Host (
                "O banco já está no schema esperado; nenhuma escrita de " +
                "migração foi necessária."
            ) -ForegroundColor Green
        }
        elseif ($action -in @("adopt-baseline", "migrate")) {
            $planSha256 = [string]$plan.plan_sha256
            if ($planSha256 -notmatch '^[0-9a-f]{64}$') {
                throw "O plano não contém um plan_sha256 válido."
            }

            Write-Step `
                -Number 4 `
                -Total $TotalSteps `
                -Message "Aplicando exatamente o plano SHA-256 $planSha256"
            & $MigrationScript `
                -InstallRoot $InstallRoot `
                -Apply `
                -ExpectedPlanSha256 $planSha256
        }
        else {
            throw (
                "Migração não aplicável automaticamente: action '$action'. " +
                "Nenhuma escrita de migração foi iniciada."
            )
        }
    }
}
finally {
    Pop-Location
}

$elapsed = [DateTimeOffset]::Now - $startedAt
Write-Host ""
Write-Host "ATUALIZAÇÃO CONCLUÍDA COM SUCESSO" -ForegroundColor Green
Write-Host "Modo executado: $Modo"
Write-Host ("Tempo total: {0:hh\:mm\:ss}" -f $elapsed)
Write-Host "Você já pode fechar este terminal."
