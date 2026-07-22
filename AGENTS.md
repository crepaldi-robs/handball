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
8. O PC/servidor é a fonte de verdade; conflitos offline não o sobrescrevem.
9. Operações móveis precisam ser idempotentes e versionadas.
10. Não expor a porta local diretamente nem misturar este projeto com `../site`.
11. Configuração, hash de senha, banco e backups não entram no Git.
12. Ler `docs/SITE-INTEGRATION-CONTRACT.md` antes de alterar hostname, rotas
    públicas, autenticação, PWA, instalador, banco ou qualquer vínculo com o
    portal. O único vínculo permitido com `/roberto/` é um link HTTPS comum.
13. Atualização comum troca somente código e dependências: não executa DDL,
    migration ou seed sobre banco existente. Mudança de esquema é manutenção
    separada, explícita e previamente autorizada, sempre precedida de backup.
14. Startup e backup de instalação existente devem falhar se o SQLite estiver
    ausente ou incompatível; nunca criar silenciosamente uma base vazia.

## Verificação obrigatória

Antes de concluir uma alteração:

```powershell
.\scripts\test.ps1
```

Também execute `python -m compileall -q app.py attendance tests` e valide a PWA
em WebKit quando Node.js/Playwright estiverem disponíveis.

## Histórico Git

Preservar um histórico legível com Conventional Commits em português. Cada
commit deve representar uma mudança lógica, manter `main` utilizável e excluir
banco, configuração, senhas, backups, exportações e ambiente virtual. Antes de
commitar, revisar `git diff --cached` e executar as verificações acima. Não
reescrever histórico já publicado sem autorização explícita.
