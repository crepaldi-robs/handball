# Auditoria de código — trilha de auditoria, testes e segurança

| Campo | Valor |
|---|---|
| Data de consolidação | 30 de julho de 2026 |
| Fuso de referência | America/Sao_Paulo (UTC−03:00) |
| Classificação | documentação operacional interna; não publicável |
| Commit-base | `82c6023dab6fdb87e81c2a6530590cfac6652083` |
| Working tree | mudanças não commitadas restritas ao módulo `calendario` (feature em desenvolvimento: `handball/database/repositories/calendar.py`, `handball/modules/calendario/*`, `static/calendar.js`, `templates/calendario/index.html` e testes correspondentes); os arquivos críticos desta auditoria (`handball/database/repositories/attendance.py`, `handball/database/repositories/sql_explorer.py`, `handball/core/auth.py`, `handball/core/authorization.py`) estavam commitados e inalterados no momento da leitura |
| Documento relacionado (deploy/infra) | [`HANDBALL-DEPLOY-AUDIT-2026-07-21.md`](HANDBALL-DEPLOY-AUDIT-2026-07-21.md) |
| Contrato de segurança e testes mínimos | [`SITE-INTEGRATION-CONTRACT.md`](SITE-INTEGRATION-CONTRACT.md) §17–§18 |

## 1. Finalidade e conclusão executiva

Este documento é complementar ao de 21/07/2026, que auditou deploy e
infraestrutura de produção (instalador, DNS, backup, privilégio de serviço).
Este aqui audita **código e cobertura de teste**, com foco na regra 4 do
`AGENTS.md` — toda mudança em confirmação, presença ou observação deve gerar
auditoria — e na segurança de autenticação/autorização/SQL Explorer.

**Conclusão em 30/07/2026:** o mecanismo de auditoria já é sólido. Existem
duas tabelas complementares (`attendance_audit_log` para confirmação/presença/
observação, `security_audit_events` para ações administrativas), ambas
protegidas contra alteração via SQL Explorer mesmo para o papel DEV, por um
`sqlite3.set_authorizer` em tempo de execução — não apenas por lista de
tokens proibidos. As lacunas reais encontradas eram de **cobertura de
teste**, não de implementação: nenhum teste chamava o endpoint administrativo
de auditoria via HTTP, nenhum verificava os pares old/new ponta a ponta, e
nada impedia mecanicamente que um caminho de escrita futuro esquecesse de
gravar auditoria. As cinco lacunas foram fechadas nesta tarefa com testes
reais (seção 9), incluindo um teste estrutural (AST) que falha
automaticamente se um método futuro em `AttendanceRepository` alterar
`confirmation_status`/`present`/`notes` sem gravar em
`attendance_audit_log` na mesma função.

## 2. Escopo e não escopo

Dentro do escopo: leitura de código Python do repositório, leitura da suíte
de testes, e as mudanças descritas neste documento (testes novos/estendidos
em `tests/`, este documento, uma linha adicional em
`SITE-INTEGRATION-CONTRACT.md` §18).

Fora do escopo, por proibição explícita das regras 13/17/19 do `AGENTS.md` e
por não ser autoridade deste agente: qualquer DDL, migration ou seed sobre
banco existente; qualquer leitura/escrita em `data/*.db`,
`data/app-config.json`, `backups/` ou qualquer caminho fora deste
repositório; qualquer alteração em CI, instalador ou infraestrutura de
produção. Achados de infraestrutura (instalador, DNS, privilégio de serviço,
backup fora do PC) permanecem sob responsabilidade exclusiva da auditoria de
deploy de 21/07 — não foram revalidados aqui, exceto onde a evidência estava
inteiramente em código Python já lido nesta sessão.

## 3. Metodologia

Leitura direta do código-fonte (não apenas nomes de arquivo) dos seguintes
arquivos-chave: `handball/database/repositories/attendance.py` (1.280
linhas, os 4 métodos que escrevem em `attendance_records`),
`handball/database/repositories/identity.py` (trilha
`security_audit_events`), `handball/database/repositories/sql_explorer.py`
(guarda de imutabilidade), `handball/core/authorization.py` (matriz de
permissões), `handball/modules/presencas/router.py` e
`handball/modules/usuarios/router.py` (endpoints de leitura de auditoria),
`tests/test_architecture.py` (convenção de teste estrutural via AST já
existente no repositório) e a suíte completa de `tests/` (18 arquivos antes
desta tarefa). Nenhum comando foi executado contra o banco de produção nem
contra `C:\ProgramData\CrepaldiHandball`.

## 4. Como a trilha de auditoria funciona hoje

| Mecanismo | Tabela | Escritores confirmados | Colunas-chave |
|---|---|---|---|
| Auditoria de presença | `attendance_audit_log` | `update_self_confirmation` (`attendance.py:530`), `save_records` (`attendance.py:604`, sem rota HTTP — ver seção 8), `sync_records` (`attendance.py:731`), `finalize_session` (`attendance.py:955`) | `old_confirmation_status`/`new_confirmation_status`, `old_present`/`new_present`, `old_notes`/`new_notes`, `actor_user_id`, `action`, `target_id`, `operation_id` |
| Auditoria de segurança/admin | `security_audit_events` | `AttendanceRepository._security_audit` (`attendance.py:174-204`, usado por `finalize_session`, `reopen_session`, `update_session_notes`, `add_member`, `update_member`) e `IdentityRepository.audit_event` (`identity.py:562-621`, usado por `create_user`, `set_roles`, `deactivate_user`, `reset_password`, `change_own_password`, `set_permission_grants`, auto-registro) | `action`, `entity`, `target_id`, `origin`, `before_json`/`after_json`, `request_id` |

`update_session_notes` (`attendance.py:1062-1093`) altera
`training_sessions.notes` — a observação geral da sessão de treino — e por
isso é auditado via `security_audit_events` com `action=
"training.notes.update"`. Isso **não é uma lacuna**: é uma tabela diferente
de `attendance_records.notes` (a observação por atleta), que é o campo
coberto pela regra 4 e pela `attendance_audit_log`.

**Imutabilidade**: `IMMUTABLE_RELATIONS` (`sql_explorer.py:16-19`) inclui
`attendance_audit_log` e `security_audit_events`. Um `sqlite3.set_authorizer`
instalado em toda sessão do SQL Explorer (não uma simples lista de tokens
proibidos em regex) intercepta `SQLITE_INSERT`, `SQLITE_UPDATE`,
`SQLITE_DELETE`, `SQLITE_CREATE_TABLE`, `SQLITE_CREATE_INDEX` e
`SQLITE_ALTER_TABLE` contra essas tabelas — nem o papel DEV com `sql.admin`
consegue alterá-las, confirmado por teste (seção 9, item 4).

## 5. Matriz de cobertura de teste por regra de domínio (AGENTS.md 1-14)

| Regra | Descrição resumida | Teste(s) existente(s) confirmado(s) | Status |
|---|---|---|---|
| 1 | confirmação ≠ presença | `tests/test_database.py::test_initialization_and_audit` | coberta |
| 2 | chamada aberta não converte ausência automaticamente | nenhum teste dedicado localizado; decorre implicitamente do default `present=NULL` em `_ensure_attendance_records` (`attendance.py:437-458`) | **lacuna não fechada nesta tarefa** — fora do escopo, registrada como trabalho futuro (seção 12) |
| 3 | encerramento marca não apurado como ausência | `tests/test_database.py::test_finalize_marks_unchecked_as_absent`; conteúdo old/new dessa transição agora também em `tests/test_users_authorization.py::test_finalize_session_audit_log_records_null_present_as_zero` (novo) | coberta |
| 4 | toda mudança em confirmação/presença/observação gera auditoria | cobertura indireta pré-existente (verificava existência de linha, não conteúdo old/new nem generalidade); agora também `tests/test_audit_architecture.py` (novo, estrutural) e `tests/test_users_authorization.py::test_audit_log_api_exposes_old_and_new_values_for_confirmation_presence_and_notes` (novo) | coberta, incluindo garantia estrutural para caminhos futuros |
| 5 | banco do usuário nunca é apagado/recriado em migração | `tests/test_database.py::test_existing_database_is_validated_without_seed_or_data_changes`, `tests/test_migrations.py::test_apply_requires_fingerprint_and_never_creates_database_or_directory`, `tests/test_database_guard.py` (extenso) | coberta |
| 6/7 | compatibilidade Windows/PowerShell; UTF-8 | `tests/test_maintenance_scripts.py`, `tests/test_install_server.py`, `tests/test_release_resolver.py` (scripts PowerShell sem erro de parser) | coberta |
| 8 | servidor é fonte de verdade; conflito offline não sobrescreve | `tests/test_sync.py::test_sync_is_idempotent_and_rejects_stale_version` | coberta |
| 9 | operações móveis idempotentes e versionadas | `tests/test_sync.py` (idempotência, hash divergente, no-op avança versão) | coberta |
| 10-12 | isolamento com `../site`; segredos fora do Git | não é código Python testável por `pytest`; ver `SITE-INTEGRATION-CONTRACT.md` §17 | fora do escopo de teste automatizado |
| 13 | atualização comum não roda DDL/migration/seed | `tests/test_ops_safety.py::test_migration_is_lock_first_explicit_backup_gated_and_fail_closed`, `tests/test_update_wrapper.py` | coberta |
| 14 | startup/backup falham fechado se banco ausente/incompatível | `tests/test_database_guard.py` (extenso), `tests/test_web.py` (startup recusa recriar banco ausente) | coberta |

## 6. Revalidação dos achados de 21/07/2026

| Achado original | Fonte | Status em 30/07/2026 | Evidência |
|---|---|---|---|
| 19 nomes/apelidos e posições iniciais em `attendance/models.py` (elenco identificável no Git) | DEPLOY-AUDIT §10.3, P1 | **Resolvido** | `attendance/models.py` hoje tem 224 bytes (fachada vazia sem dados), confirmado por `tests/test_architecture.py::test_legacy_attendance_package_contains_no_persistence_implementation` |
| Auditoria cobre registros individuais, não todas as ações administrativas | DEPLOY-AUDIT §10.3, P1 / `SITE-INTEGRATION-CONTRACT.md` §21 | **Majoritariamente superado** | `security_audit_events` hoje cobre `user.create`, `user.roles.update`, `user.deactivate`, `user.password.reset`, `user.password.change`, `user.permissions.update` (`identity.py:268,340,447,515,524,534,544`), além de `training.finalize`, `training.reopen`, `training.notes.update`, `member.create_or_reactivate`, `member.update` (`attendance.py:1024,1053,1084,1200,1234`) — todos com `actor_user_id` explícito |
| `/health` retorna JSON fixo sem versão; instalador copia em-place | DEPLOY-AUDIT §10.3, P0 | **Não revalidado nesta sessão** | achado de deploy/instalador, fora do escopo de código desta auditoria — permanece como estava em `SITE-INTEGRATION-CONTRACT.md` §21 |
| Seed executa UPSERT de posição em toda inicialização | DEPLOY-AUDIT §10.3, P1 | **Não revalidado nesta sessão** | idem |
| Servidor/backup rodam como SYSTEM/Highest; backup no mesmo volume; PIN offline com entropia limitada | DEPLOY-AUDIT §10.3, P1/P2 | **Não revalidado nesta sessão** | achados de infraestrutura/instalação, fora do escopo de código |

Esta seção não relê arquivos de instalação/infraestrutura; revalida apenas
achados cuja evidência está inteiramente em código Python já lido nesta
sessão.

## 7. Achados novos desta sessão

| Prioridade | Achado | Evidência |
|---|---|---|
| P2 | Rate limit existe apenas em `/login` e `/register` (5 tentativas/15min); nenhum limite em `/api/v1/sql/*` nem nos demais endpoints autenticados | `handball/core/auth.py` (`LoginLimiter`); ausência confirmada por leitura dos routers de `consultas`, `presencas`, `usuarios` |
| P2 | `AppSettings.secret_key` é validado (mínimo 32 caracteres) mas nenhum uso concreto foi localizado no código explorado nesta sessão — candidato a código morto | `handball/core/config.py`; recomenda-se `grep -rn "secret_key"` dedicado antes de decidir remover |
| P2 | Módulo legado `presencas`/`attendance` (schema v1) não tem escopo por `team_id`, diferente de `calendario` (v2+) | risco latente apenas se o app deixar de ser single-team; não é vulnerabilidade hoje |
| Informativo | `save_records` (`attendance.py:604`) é um método de repositório sem nenhuma rota HTTP que o chame — `PUT /api/v1/sessions/{id}/records` sempre usa `sync_records`. Superfície de contrato não exercitada em produção, não vulnerabilidade | confirmado por busca de `save_records` em `handball/` e `tests/`; único uso é `tests/test_database.py::test_initialization_and_audit` |
| Informativo | Inconsistência menor: `GET /api/v1/audit` faz clamp de `limit` (`min(max(limit,1),1000)`, `presencas/router.py:231`); `GET /api/v1/admin/audit` não clampa (`usuarios/router.py:93`) | não é risco de segurança (ambos exigem permissão e o parâmetro não é controlado por terceiros anônimos), apenas inconsistência de contrato entre dois endpoints irmãos |

Controles positivos confirmados nesta sessão (sem achado associado):
Argon2id para senha; token de sessão opaco de 48 bytes, armazenado apenas
como hash SHA-256; cookie `HttpOnly`+`Secure`+`SameSite=Lax`; CSRF validado
com `secrets.compare_digest`; CSP restritiva self-only com
`frame-ancestors 'none'`; `X-Frame-Options: DENY`, `nosniff`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store` em `/api/*`;
Swagger/OpenAPI/Redoc desabilitados (`docs_url=None` etc.); nenhum CORS
configurado (origem única, intencional); nenhuma SQL de negócio concatenada a
partir de entrada do usuário fora do SQL Explorer (que tem guarda própria).

## 8. `save_records`: caminho de auditoria sem rota HTTP

`save_records` é um dos quatro métodos que escrevem em `attendance_records` e
gravam em `attendance_audit_log`, mas não é alcançável por nenhum endpoint —
`PUT /api/v1/sessions/{session_id}/records` sempre invoca `sync_records`
(`handball/modules/presencas/router.py:171-192`). Por isso, o conteúdo
old/new desse caminho específico só pôde ser verificado no nível de
repositório, não via API — ver `tests/test_database.py::
test_initialization_and_audit` (estendido nesta tarefa, seção 9, item 2).
Decidir se `save_records` deve ganhar uma rota, ser removido, ou permanecer
como método interno é decisão de produto fora do escopo desta auditoria.

## 9. Lacunas de teste fechadas nesta tarefa

1. **`GET /api/v1/admin/audit` nunca era chamado via HTTP** → fechada por
   `tests/test_users_authorization.py::test_admin_audit_endpoint_is_scoped_to_users_manage`
   (200 para DEV com evento presente; 403 para CT e PLAYER) e pela extensão
   de `test_player_is_denied_team_write_audit_export_and_backup`.
2. **Pares old/new de `attendance_audit_log` não verificados ponta a ponta
   via API** → fechada por
   `tests/test_users_authorization.py::test_audit_log_api_exposes_old_and_new_values_for_confirmation_presence_and_notes`
   (confirmação → presença → observação, correlacionado por `operation_id`
   para não depender da granularidade de segundo de `changed_at`) e por
   `tests/test_users_authorization.py::test_finalize_session_audit_log_records_null_present_as_zero`
   (transição `NULL→0` específica de `finalize_session`). No nível de
   repositório, `tests/test_database.py::test_initialization_and_audit` foi
   estendido com as mesmas asserções para cobrir `save_records` (sem rota
   HTTP, ver seção 8).
3. **Sem teste de paginação/clamp do parâmetro `limit`** → fechada por
   `tests/test_users_authorization.py::test_audit_endpoint_respects_limit_query_param`.
4. **Regressão de `IMMUTABLE_RELATIONS` só indireta** → fechada por
   `tests/test_sql_explorer.py::test_immutable_relations_include_both_audit_tables`
   (assert direto sobre a constante) e pela extensão de
   `test_dev_still_cannot_touch_restricted_tables_or_engine_commands` com
   tentativas de INSERT/UPDATE/DELETE contra as duas tabelas de auditoria,
   todas rejeitadas (400) mesmo para DEV com `sql.admin`.
5. **Nenhum teste impedia caminho de escrita futuro sem auditoria** →
   fechada por `tests/test_audit_architecture.py` (novo arquivo), com três
   testes: o detector estrutural principal (varre `handball/database` via
   AST e falha se alguma função alterar `confirmation_status`/`present`/
   `notes` de `attendance_records` sem gravar em `attendance_audit_log` na
   mesma função), uma âncora positiva (garante que o detector encontra os 4
   métodos conhecidos, para não passar "no vazio" se um refactor renomear a
   tabela) e um auto-teste do detector com AST sintético.

## 10. Emenda proposta ao `SITE-INTEGRATION-CONTRACT.md` §18

Uma linha foi adicionada à tabela existente de testes mínimos por tipo de
mudança (sem alterar as demais linhas):

> trilha de auditoria (confirmação/presença/observação): teste estrutural
> (AST) + conteúdo old/new via API + regressão de `IMMUTABLE_RELATIONS`.

## 11. Como verificar

```powershell
.\scripts\test.ps1
python -m compileall -q app.py attendance handball tests
```

Todos os testes novos/estendidos foram executados isoladamente durante esta
tarefa (`pytest -q tests/test_audit_architecture.py`,
`tests/test_sql_explorer.py`, `tests/test_users_authorization.py`,
`tests/test_database.py`) antes da suíte completa, todos passando.

## 12. Limitações conhecidas e trabalho futuro não incluído

- `save_records` permanece sem rota HTTP (seção 8) — decisão de produto, não
  desta auditoria.
- Regra 2 do AGENTS.md ("chamada aberta não converte ausência
  automaticamente") não ganhou teste dedicado nesta tarefa; a garantia hoje é
  implícita (default `present=NULL`). Recomenda-se um teste futuro que abra
  uma chamada, deixe registros não apurados, e confirme que `present`
  permanece `NULL` (não vira ausência) até um encerramento explícito.
- O teste estrutural de `tests/test_audit_architecture.py` verifica por
  função, sem resolução de chamada indireta — documentado no docstring do
  próprio módulo como limitação intencional (prefere fricção a
  falso-negativo silencioso).
- Achados P0/P1 de infraestrutura de produção (instalador, `/health` sem
  versão, privilégio de serviço, backup único no mesmo volume) não foram
  revalidados nesta sessão — pertencem à auditoria de deploy, não à de
  código.
- Inconsistência de clamp de `limit` entre `GET /api/v1/audit` e
  `GET /api/v1/admin/audit` (seção 7) não foi corrigida — é observação, não
  correção, para não alterar comportamento fora do escopo pedido.

## 13. Referências

- [`HANDBALL-DEPLOY-AUDIT-2026-07-21.md`](HANDBALL-DEPLOY-AUDIT-2026-07-21.md)
  — auditoria de deploy/infraestrutura, fonte dos achados revalidados na
  seção 6.
- [`SITE-INTEGRATION-CONTRACT.md`](SITE-INTEGRATION-CONTRACT.md) §17
  (contrato de segurança), §18 (testes mínimos por tipo de mudança, emendado
  na seção 10), §21 (dívida técnica).
- [`HANDBALL-DOCUMENTATION-SHA256-2026-07-21.txt`](HANDBALL-DOCUMENTATION-SHA256-2026-07-21.txt)
  — manifesto de integridade dos documentos de auditoria anteriores; este
  documento novo não foi incluído nesse manifesto (decisão de gerar ou
  atualizar o manifesto fica fora do escopo desta tarefa).
- `AGENTS.md` — regras de domínio (1-14) usadas como referência da matriz de
  cobertura (seção 5).
