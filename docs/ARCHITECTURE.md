# Arquitetura modular da plataforma Handball

## Visão geral

A plataforma é uma única aplicação FastAPI, executada em um único processo e
uma única porta. O pacote `handball` é o ponto canônico da implementação:

```text
app.py -> handball.application
              |-> handball.core
              |-> handball.database
              `-> handball.modules
```

O diretório `attendance` existe somente como fachada transitória de importação.
Ele não contém regras, SQL, conexões ou uma segunda implementação.

## Fronteiras de dependência

### `handball.core`

Contém configuração da plataforma, autenticação, sessão, proteção CSRF,
rate limit, middleware de segurança e erros compartilhados. Não executa SQL e
não contém regras específicas dos módulos.

### `handball.database`

É a única fronteira autorizada a importar `sqlite3`, resolver o caminho físico
do banco, abrir conexões, configurar PRAGMAs, executar SQL, controlar transações,
validar schema, planejar/aplicar migrations explícitas e criar backups.

O `DatabaseManager` cria unidades de trabalho. Cada `UnitOfWork` possui uma
conexão de vida curta e encerra com commit ou rollback centralizado. Os
repositórios recebem a conexão da unidade de trabalho e nunca abrem outra
conexão nem confirmam transações por conta própria. Não existe conexão global.

### `handball.modules`

Cada módulo possui router, service e schemas próprios. Regras puras ficam no
domínio do módulo. Services dependem somente dos contratos de repositório e
unidade de trabalho; routers dependem dos services e da infraestrutura de
autenticação compartilhada.

Módulos nunca podem:

- importar `sqlite3` ou o adaptador SQLite;
- conter SQL ou literais com caminhos `.db`;
- abrir conexões ou executar commit/rollback;
- definir ou alterar schema;
- importar templates ou routers a partir de `handball.database`.

## Autenticação e navegação

`POST /login` valida a credencial Argon2id, aplica o limitador atual e cria uma
sessão assinada. O cookie `handball_session` permanece `HttpOnly`,
`SameSite=Lax`, `Path=/` e `Secure` quando configurado. A mesma sessão protege o
hub, presenças, estatísticas, calendário e todas as APIs. Escritas em `/api/v1`
também exigem o token CSRF da sessão.

```text
/ -> /login -> /app
                 |-> /app/presencas
                 |-> /app/estatisticas
                 `-> /app/calendario
```

O logout é único: remove o cookie e, quando JavaScript está disponível,
limpa o cofre offline, caches e registro do service worker.

## Conexão, transação e persistência

1. `handball.application` carrega a configuração e compõe um
   `DatabaseManager`.
2. Startup chama somente validação read-only do SQLite existente.
3. Um service abre uma unidade de trabalho para cada caso de uso.
4. A unidade de trabalho disponibiliza os repositórios ligados à mesma conexão.
5. Sucesso confirma a transação; exceção reverte integralmente a operação.
6. A conexão é sempre fechada ao sair do contexto.

Conexões preservam `PRAGMA foreign_keys = ON`, `busy_timeout = 30000` e o
regime WAL. O banco de produção continua fora de qualquer release:

```text
C:\ProgramData\CrepaldiHandball\data\presencas.db
```

O código-fonte de persistência fica em `handball/database`; banco, WAL, SHM,
configuração, backups e logs nunca entram no repositório nem no OneDrive.

## Adicionar um módulo

1. Criar `handball/modules/<nome>` com `router.py`, `service.py`, `schemas.py` e,
   quando houver regras puras, `domain.py`.
2. Definir schemas de entrada/saída tipados e casos de uso no service.
3. Consumir somente contratos existentes; se faltar persistência, adicionar
   primeiro um contrato de repositório.
4. Criar template próprio e rota autenticada sob `/app/<nome>`.
5. Registrar o router apenas em `handball.application`.
6. Adicionar testes de sessão, comportamento, acessibilidade e fronteiras.

## Adicionar um repositório

1. Definir o protocolo e DTOs em `handball/database/contracts.py`.
2. Implementar o contrato em `handball/database/repositories` usando a conexão
   recebida da unidade de trabalho.
3. Expor a implementação pela `UnitOfWork`, sem revelar o adaptador ao módulo.
4. Testar a implementação com banco temporário e testar o service com um fake do
   contrato.
5. Se houver mudança de schema, interromper o fluxo `APP_ONLY` e abrir uma tarefa
   `DB_MIGRATION` separada.

## Outro backend no futuro

Uma troca por PostgreSQL deverá implementar os mesmos contratos, outro manager,
outra unidade de trabalho e outros repositórios. A composição selecionará o
backend; routers, services e schemas dos módulos não mudarão. Pooling, cache,
read replicas ou um segundo banco seguem a mesma fronteira, mas não fazem parte
da implementação atual.

## `APP_ONLY` e `DB_MIGRATION`

- `APP_ONLY` troca apenas código e dependências. Startup, backup e updater não
  executam DDL, seed ou migration e devem preservar o fingerprint lógico.
- `DB_MIGRATION` é manutenção separada, explicitamente autorizada, com plano
  confirmado por hash, serviço parado, backup verificado, transação e checks de
  integridade.

O schema atual continua na versão 1. Estatísticas e calendário não criam
tabelas, migrations ou dados fictícios persistidos.
