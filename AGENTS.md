# Instruções para agentes de código

## Objetivo

Manter um registrador local, simples e auditável para confirmações e presenças
nos treinos.

## Regras de domínio

1. Situação da confirmação e presença real são campos diferentes.
2. Uma chamada aberta não transforma automaticamente caixa desmarcada em ausência.
3. O botão de encerramento transforma todos os registros ainda não apurados em ausência.
4. Toda mudança em confirmação, presença ou observação deve gerar auditoria.
5. O banco SQLite do usuário não deve ser apagado nem recriado durante migrações.
6. Manter compatibilidade com Windows, VSCode e PowerShell.
7. Textos e arquivos devem permanecer em UTF-8.

## Verificação obrigatória

Antes de concluir uma alteração:

```powershell
.\scripts\test.ps1
```
