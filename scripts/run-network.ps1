Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Ambiente virtual não encontrado. Execute .\scripts\setup.ps1 primeiro."
}

$Ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.InterfaceAlias -notmatch "Loopback|vEthernet"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host ""
Write-Host "Acesso neste computador: http://localhost:8501"
if ($Ip) {
    Write-Host "Acesso em celular na mesma rede: http://${Ip}:8501"
}
Write-Warning "Este modo não possui autenticação. Use apenas em rede privada e confiável."

& ".\.venv\Scripts\python.exe" -m streamlit run app.py `
    --server.address 0.0.0.0 `
    --server.port 8501
