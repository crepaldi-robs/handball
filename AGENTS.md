# Instruções para agentes de código

Este arquivo é a fonte única de regras do repositório. Vale igualmente para
Claude Code, Codex CLI, Gemini CLI e qualquer outro agente. `CLAUDE.md` e
`GEMINI.md` apenas apontam para cá — se precisar mudar uma regra, mude aqui.

## Objetivo

Manter um registrador local, simples e auditável para confirmações e presenças
nos treinos de handebol. É uma aplicação privada, instalada na máquina do
usuário, com SQLite como fonte de verdade.

## Como se orientar

Aplicação FastAPI servida por Uvicorn em `127.0.0.1:8765`, com templates Jinja2
e uma PWA instalável no iPhone.

| Caminho | O que é |
| --- | --- |
| `app.py` | Ponto de entrada; só monta `handball.application:create_app`. |
| `handball/application.py` | Composição: serviços, routers, middlewares. |
| `handball/core/` | Regras transversais: auth, autorização, config, segurança, temas. |
| `handball/database/` | **Toda** persistência: schema, migrations, repositórios, unidade de trabalho, backup. |
| `handball/modules/` | Um diretório por módulo web (`presencas`, `elenco`, `usuarios`, `playbook`, `estatisticas`, `calendario`, `hub`, `consultas`, `integracoes`). |
| `handball/integrations/` | Integrações externas (ex.: Google Calendar). |
| `attendance/` | Fachada de compatibilidade legada; reexporta de `handball`. Não acrescente lógica aqui. |
| `templates/`, `static/` | Interface, service worker e assets da PWA. |
| `design-system/`, `design-mirror/`, `.design-sync/` | Tokens de design e o conversor descrito em `docs/design-system/`. |
| `scripts/` | Operação em PowerShell: setup, run, testes, instalação, atualização, backup, migração, reset de senha. |
| `tests/` | Pytest. Cobre web, banco, migrações, sync, scripts de operação e arquitetura. |
| `docs/` | Arquitetura, deploy, operação, contrato com o site, backlog e auditorias datadas. |
| `data/`, `backups/` | Dados reais do usuário. Fora do Git e fora do alcance de agente. |

Leituras antes de mexer em áreas sensíveis:

- `docs/ARCHITECTURE.md` — camadas e processo para estender módulos;
- `docs/HM-IME-USUARIOS-E-AUTORIZACAO.md` — identidade, papéis e permissões;
- `docs/SITE-INTEGRATION-CONTRACT.md` — obrigatório antes de tocar em hostname,
  rotas públicas, autenticação, PWA, instalador, banco ou qualquer vínculo com
  o portal;
- `docs/DEPLOYMENT.md` e `docs/HANDBALL-OPERATIONS.md` — servidor, tarefa
  agendada, atualização e recuperação.

## Preparar o ambiente

No PowerShell, a partir da raiz do repositório:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

`setup.ps1` cria `.venv` com Python 3.13, instala `requirements.txt`, gera
`data\app-config.json` se não existir e valida o banco local. `run.ps1` sobe o
servidor em `http://127.0.0.1:8765`.

Num ambiente sem PowerShell, o equivalente mínimo é criar a venv, instalar
`requirements.txt` e rodar `python -m pytest -q`. Os testes de operação se
pulam sozinhos quando `pwsh` não existe.

## Verificação obrigatória

Antes de concluir qualquer alteração:

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance handball tests
```

Quando Node.js e Playwright estiverem disponíveis, valide também a PWA em
WebKit. O portão de CI (`.github/workflows/testes.yml`) roda a mesma
verificação em `windows-latest`.

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
    O único vínculo permitido com `/roberto/` é um link HTTPS comum.
11. Configuração, hash de senha, banco e backups não entram no Git.
12. Atualização comum troca somente código e dependências: não executa DDL,
    migration ou seed sobre banco existente. Mudança de esquema é manutenção
    separada, explícita e previamente autorizada, sempre precedida de backup.
13. Startup e backup de instalação existente devem falhar se o SQLite estiver
    ausente ou incompatível; nunca criar silenciosamente uma base vazia.

## Limites de um agente neste repositório

14. Não leia nem escreva `data/*.db`, `data/app-config.json`, `backups/`, nem
    qualquer caminho fora deste repositório. Não há motivo para um agente ver
    dado de atleta ou segredo de instalação.
15. Chave de API, senha e segredo não aparecem em log, commit, comentário ou PR.
16. Pedido que implique DDL, migration ou seed sobre banco existente deve ser
    recusado com referência à regra 12: mudança de esquema é decisão humana,
    tratada como manutenção `DB_MIGRATION` separada.
17. Nenhum agente cria commit, faz push, abre PR, publica release ou altera
    serviço externo sem autorização humana explícita e específica para aquela
    ação. Autorizar um commit não autoriza o push seguinte.
18. Prefira a mudança mínima que resolve o pedido. Não reformate arquivo
    inteiro, não renomeie em massa e não troque dependência por conta própria.

## Histórico Git

Preservar um histórico legível com Conventional Commits em português
(`tipo(escopo): descrição curta`; tipos preferenciais `feat`, `fix`,
`refactor`, `test`, `docs`, `ops`, `security`, `chore`). Cada commit deve
representar uma mudança lógica e manter `main` utilizável.

Antes de commitar, revisar `git diff --cached` e executar a verificação
obrigatória. Banco, configuração, senhas, backups, exportações e `.venv` nunca
entram no Git. Não reescrever histórico já publicado sem autorização explícita.

Detalhes e exemplos em `CONTRIBUTING.md`.
