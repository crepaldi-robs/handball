<#
.SYNOPSIS
    Ponte de compatibilidade para o novo fluxo: o usuario fala somente com Codex.

.EXAMPLE
    .\scripts\agente.ps1 -Pedido "revise o proximo commit"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Pedido
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "codex-handball.ps1") -Prompt $Pedido
