# Contrato de integração e isolamento — Handball × Portal `/roberto/`

| Campo | Valor |
|---|---|
| Versão do contrato | 1.1 |
| Data-base | 21 de julho de 2026 |
| Repositório proprietário deste documento | `handball\registrador-presencas` |
| Aplicação | `https://handball.crepaldi.com.br/` |
| Portal relacionado | `https://crepaldi.com.br/roberto/` |
| Tipo de integração | navegação por link HTTPS; nenhuma integração de código ou dados |
| Estado público conhecido | túnel e `/health` operacionais na última verificação |
| Classificação | documentação interna; não copiar para a aplicação instalada nem publicar |

## 1. Objetivo

Este contrato permite que qualquer desenvolvedor ou agente continue evoluindo o
Registro Oficial de Presenças sem interferir no portal estático, no cofre
privado, na Hostinger, no site principal ou no e-mail de `crepaldi.com.br`.

Ele responde, de forma normativa:

- o que pertence ao aplicativo;
- o que pertence ao portal;
- qual é o único elo entre eles;
- quais mudanças são isoladas e quais quebram o contrato;
- como desenvolver, testar, instalar, atualizar e recuperar o aplicativo;
- quando parar e pedir uma decisão do proprietário;
- quais arquivos, dados e credenciais nunca atravessam a fronteira.

Este documento não transforma os dois repositórios em monorepo. A integração é
intencionalmente mínima para que cada sistema possa evoluir, falhar e ser
restaurado de maneira independente.

## 2. Autoridade e ordem de leitura

Antes de alterar este aplicativo, leia nesta ordem:

1. `AGENTS.md` deste repositório;
2. este `docs/SITE-INTEGRATION-CONTRACT.md`;
3. `CONTRIBUTING.md`;
4. `README.md`;
5. `docs/DEPLOYMENT.md`;
6. os testes relacionados à área que será alterada.

Para compreender a implantação histórica e a operação completa, as fontes
canônicas no computador são:

```text
C:\Users\rober\OneDrive\Área de Trabalho\site\docs\HANDBALL-DEPLOY-AUDIT-2026-07-21.md
C:\Users\rober\OneDrive\Área de Trabalho\site\docs\HANDBALL-OPERATIONS.md
C:\Users\rober\OneDrive\Área de Trabalho\site\docs\HANDOFF-HANDBALL.md
```

Esses arquivos podem ser lidos como referência, mas um agente trabalhando neste
repositório não deve editá-los incidentalmente. Se uma mudança realmente exigir
alteração do portal, ela deve virar um handoff explícito para o repositório
`site`, sujeito ao `AGENTS.md` daquele projeto e à publicação manual do
proprietário.

Em caso de conflito:

1. segurança, preservação de dados e instruções `AGENTS.md` prevalecem;
2. o contrato de fronteira prevalece sobre conveniência de implementação;
3. documentação histórica registra o que aconteceu, mas o código e os testes
   atuais determinam o comportamento presente;
4. nenhuma documentação autoriza credenciais ou mutação remota.

## 3. Modelo mental: dois produtos, um link

```text
PRODUTO A — PORTAL ESTÁTICO
https://crepaldi.com.br/roberto/
Hostinger
HTML + CSS + JavaScript estático + cofre cifrado
       |
       | link HTTPS comum, sem dados e sem sessão compartilhada
       v
PRODUTO B — APLICATIVO DINÂMICO
https://handball.crepaldi.com.br/
Cloudflare Tunnel -> 127.0.0.1:8765
FastAPI + SQLite + autenticação + PWA no PC Windows
```

O link é a integração inteira. O portal não chama a API, não carrega assets do
handball, não compartilha cookies e não conhece o banco. O handball não lê o
cofre, não altera o portal e não depende dos arquivos publicados em
`public_html/roberto/`.

## 4. Contrato público estável

### 4.1 Valores contratuais

| Interface | Valor estável |
|---|---|
| URL de entrada | `https://handball.crepaldi.com.br/` |
| Saúde pública | `GET https://handball.crepaldi.com.br/health` |
| Resposta saudável | HTTP 200 com `{"status":"ok"}` |
| Login | `/login` |
| Aplicação autenticada | `/app` |
| Origem interna | `http://127.0.0.1:8765` |
| Escopo de caminho | raiz do subdomínio; não um prefixo dentro de `/roberto/` |
| Rota Cloudflare | hostname completo para a origem local |
| Relação com o portal | elemento `<a>` normal para a URL de entrada |

### 4.2 O que o portal pode assumir

O portal pode assumir somente que:

1. existe um destino HTTPS chamado “Registro de handebol”;
2. o aplicativo possui autenticação própria;
3. o aplicativo pode ficar indisponível quando o PC servidor estiver desligado;
4. abrir o link sai da origem do portal e entra numa origem separada.

O portal não pode assumir formato de API, usuário logado, disponibilidade 24/7,
conteúdo de banco, rota interna adicional ou acesso offline.

### 4.3 O que o aplicativo pode assumir

O aplicativo não precisa saber se o portal está publicado nem de qual página o
visitante veio. Não deve exigir `Referer`, cookie do portal, parâmetro secreto,
token na URL ou header gerado pelo portal.

### 4.4 Mudanças que quebram o contrato

Qualquer item abaixo exige revisão deste documento e handoff para `site`:

- mudar `handball.crepaldi.com.br`;
- hospedar o aplicativo sob `/roberto/handball/`;
- remover ou mudar semanticamente `/health`, `/login` ou `/app`;
- exigir query string ou token no link;
- tentar single sign-on com o cofre do portal;
- exigir iframe ou script embutido no portal;
- expor uma API cross-origin para o portal;
- fazer o portal depender de disponibilidade do PC para renderizar;
- mudar a natureza de dados compartilhados de “nenhum” para qualquer outra.

Uma mudança quebradora não deve ser implementada silenciosamente “porque é
pequena”. Primeiro documente objetivo, ameaça, migração, rollback e impacto no
portal; depois obtenha autorização explícita.

## 5. Matriz de propriedade e proibição

| Recurso | Dono | Handball pode alterar? | Site pode alterar? |
|---|---|---:|---:|
| backend FastAPI | handball | sim | não |
| frontend/PWA do handball | handball | sim | não |
| SQLite de produção | operação handball | somente via app/migração/recuperação controlada | nunca |
| configuração e hash | operação handball | somente scripts autorizados | nunca |
| backups do SQLite | operação handball | criar/verificar/restaurar com cautela | nunca |
| serviço cloudflared | proprietário/operação | diagnosticar localmente; token é secreto | não |
| rota `handball` | proprietário/Cloudflare | nenhuma mutação automática | não |
| DNS do domínio | proprietário | nenhuma mutação automática | nenhuma mutação automática |
| `site/index.html` | site | não | sim, localmente |
| `site/privado/` e cofre | site | nunca | sim, sob regras do site |
| `deploy-manifest.txt` do site | site | nunca | sim, com revisão |
| Hostinger/public_html | proprietário | nunca | somente publicação manual do proprietário |
| e-mail/MX/SPF/DKIM/DMARC | proprietário | nunca | nunca |

“Não” significa que uma tarefa comum de desenvolvimento neste repositório não
autoriza a ação. Se o proprietário abrir um trabalho separado no outro projeto,
as regras daquele projeto passam a governar esse novo escopo.

## 6. Fronteiras técnicas obrigatórias

### 6.1 Nenhum compartilhamento de arquivos

Nunca copie para o repositório `site`:

- `app.py`, `attendance/`, `templates/` ou `static/` do handball;
- ambiente virtual ou dependências Python;
- `app-config.json`;
- `presencas.db`, WAL, SHM ou qualquer backup;
- logs;
- exports CSV com dados reais;
- token do Tunnel;
- scripts de instalação do servidor.

Nunca copie do `site` para o handball:

- `privado/vault.json` ou segredo do cofre;
- assets por referência relativa entre repositórios;
- credenciais ou arquivos de publicação da Hostinger;
- scripts de upload ou sincronização remota.

### 6.2 Nenhum compartilhamento de runtime

- não importar módulos Python a partir de `../site`;
- não servir o diretório `site` pelo FastAPI;
- não fazer symlink/junction entre diretórios de runtime;
- não usar o service worker do handball para controlar `/roberto/`;
- não registrar service worker do portal sob o subdomínio handball;
- não usar `localStorage`, IndexedDB ou cookie como se fossem compartilhados
  entre as duas origens;
- não usar uma pasta `.release` comum.

Cookies, storage e service workers são naturalmente separados por origem. Essa
separação é uma propriedade desejada, não um problema a contornar.

### 6.3 Nenhum embed

O aplicativo envia `X-Frame-Options: DENY` e CSP com
`frame-ancestors 'none'`. Isso impede iframe por projeto. Não enfraqueça essas
proteções para “integrar” o portal. A navegação deve permanecer um link comum.

### 6.4 Nenhuma API cross-origin para o portal

A CSP do aplicativo usa `connect-src 'self'`, e o portal não precisa chamar a
API. Não adicione CORS `*`, JSONP, postMessage ou token público para exibir dados
de presença no portal. Uma futura necessidade desse tipo é um novo produto e
exige análise de privacidade e ameaça.

### 6.5 Nenhum acoplamento de disponibilidade

Se o PC estiver desligado, somente o aplicativo dinâmico deve ficar
indisponível. O site principal, o portal e o e-mail não podem depender de um
request ao handball para carregar ou funcionar.

## 7. Arquitetura interna atual do handball

### 7.1 Componentes

| Caminho | Responsabilidade |
|---|---|
| `app.py` | ponto de entrada, chama `create_app()` |
| `handball/application.py` | composição FastAPI, middleware e registro dos routers |
| `handball/core/` | configuração, Argon2id, sessão, CSRF, rate limit e segurança |
| `handball/database/` | única fronteira de SQLite, SQL, schema, transações, migrations e backup |
| `handball/modules/hub/` | Hub Handebol autenticado em `/app` |
| `handball/modules/presencas/` | regras, service, schemas, página e API v1 de presenças |
| `handball/modules/estatisticas/` | esqueleto autenticado, sem persistência própria |
| `handball/modules/calendario/` | esqueleto autenticado, sem persistência própria |
| `attendance/` | fachada temporária sem implementação ou acesso ao banco |
| `templates/` | HTML de login e aplicativo |
| `static/` | CSS, JS, manifest, ícones e service worker |
| `scripts/` | setup, execução, instalação, backup, senha e testes |
| `tests/` | regressões de domínio, banco, web, sync, CLI e instalação |

### 7.2 Persistência

O SQLite ativa:

- `PRAGMA foreign_keys = ON`;
- `PRAGMA busy_timeout = 30000`;
- `PRAGMA journal_mode = WAL` na inicialização.

Tabelas conhecidas:

| Tabela | Finalidade |
|---|---|
| `team_members` | atletas, posição e atividade |
| `training_sessions` | data, observação e estado de encerramento |
| `attendance_records` | confirmação, presença, observação e versão |
| `attendance_audit_log` | valores antigos/novos, origem e momento da mudança |
| `sync_operations` | idempotência por operação, hash e resposta persistida |

Invariantes de domínio vindos de `AGENTS.md`:

1. confirmação e presença real são campos distintos;
2. caixa desmarcada em chamada aberta não é ausência;
3. encerrar transforma presença não apurada em ausência;
4. toda mudança individual relevante gera auditoria;
5. migração não apaga nem recria o banco do usuário;
6. servidor é fonte de verdade em conflito offline;
7. operações móveis são idempotentes e versionadas.

### 7.3 API e páginas

Superfície conhecida:

| Método e caminho | Autenticação | Função |
|---|---|---|
| `GET /health` | não | saúde mínima do processo |
| `GET /robots.txt` | não | `Disallow: /` |
| `GET /sw.js` | não | service worker sem cache persistente do próprio arquivo |
| `GET /` | indireta | redireciona a `/app` ou `/login` |
| `GET/POST /login` | credencial | cria sessão no POST válido |
| `POST /logout` | não crítica | remove cookie e retorna ao login |
| `GET /app` | sessão | Hub Handebol |
| `GET /app/presencas` | sessão | shell funcional da PWA de presenças |
| `GET /app/estatisticas` | sessão | esqueleto em preparação |
| `GET /app/calendario` | sessão | esqueleto em preparação |
| `GET /api/v1/auth/session` | sessão | usuário e token CSRF |
| `GET /api/v1/session` | sessão | chamada pela data |
| `PUT /api/v1/sessions/{id}/records` | sessão + CSRF | sync versionado/idempotente |
| `POST /api/v1/sessions/{id}/finalize` | sessão + CSRF | encerra chamada |
| `POST /api/v1/sessions/{id}/reopen` | sessão + CSRF | reabre chamada |
| `PUT /api/v1/sessions/{id}/notes` | sessão + CSRF | observação geral |
| `GET /api/v1/history` | sessão | histórico |
| `GET /api/v1/audit` | sessão | auditoria, limitada a 1.000 itens por request |
| `GET/POST/PUT /api/v1/members...` | sessão; escrita com CSRF | elenco |
| `GET /api/v1/exports/...` | sessão | CSV UTF-8 com BOM |
| `GET /api/v1/backup` | sessão | backup consistente via API SQLite |

FastAPI docs, Redoc e OpenAPI estão desativados. Não os habilite publicamente
sem justificativa e controle de acesso.

### 7.4 Autenticação e headers

- hash de senha: Argon2id via `argon2-cffi`;
- sessão: `itsdangerous.URLSafeTimedSerializer`;
- duração padrão: 12 horas;
- cookie: `handball_session`, HttpOnly, SameSite Lax, path `/`;
- produção inicializa `cookie_secure=true`;
- CSRF: token dentro da sessão e header `X-CSRF-Token` nas escritas;
- login limiter em memória: 5 falhas numa janela de 15 minutos por chave de
  cliente; reiniciar o processo limpa esse estado;
- CSP self-only, `object-src 'none'`, `frame-ancestors 'none'`;
- headers: nosniff, DENY, no-referrer e Permissions-Policy restritiva;
- `/api/` recebe `Cache-Control: no-store`.

Não reduza essas proteções para facilitar debug. Testes podem injetar settings
próprios sem alterar a configuração de produção.

## 8. Desenvolvimento local isolado

### 8.1 Ambiente

No VSCode/PowerShell, a partir deste repositório:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

O desenvolvimento usa os caminhos locais ignorados pelo Git. Não aponte testes
ou servidor de desenvolvimento para o banco de produção em `C:\ProgramData`.

### 8.2 Verificação obrigatória antes de concluir uma mudança

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance handball tests
git diff --check
git status --short
```

Na base de 21/07/2026, a suíte tinha 11 testes aprovados. O número pode crescer;
o requisito é zero falhas. A advertência Starlette/httpx existente é dívida
técnica não bloqueante, não licença para ignorar novas advertências.

Quando Node.js/Playwright estiverem disponíveis, valide a PWA em WebKit. Mudança
de frontend exige também teste visual desktop/móvel e teclado.

### 8.3 Git

- `main` deve permanecer utilizável;
- um commit por mudança lógica;
- Conventional Commits em português;
- não misturar refatoração ampla e feature funcional;
- revisar `git diff --cached` antes de commitar;
- não reescrever histórico publicado sem autorização;
- não fazer commit automático só para “limpar” o worktree.

Marco conhecido:

```text
72cb9e3 fix: flexibiliza senha e corrige instalação no Windows
```

## 9. Classificação de impacto de mudanças

Antes de codificar, classifique a proposta:

### Classe A — somente handball, contrato preservado

Exemplos:

- corrigir regra de presença;
- adicionar relatório interno autenticado;
- melhorar layout do `/app`;
- criar teste;
- otimizar consulta SQLite;
- atualizar dependência após testes;
- melhorar PWA mantendo hostname e rotas contratuais.

Ação: trabalhar somente neste repositório. Não tocar em `../site`.

### Classe B1 — atualização da aplicação (`APP_ONLY`)

Exemplos:

- mudar requisito Python;
- adicionar pacote;
- adicionar novo arquivo de runtime;
- melhorar backend, template, asset ou service worker sem mudar o schema.

Ação: atualizar código, testes e documentação operacional; criar backup
de marco; publicar uma nova release imutável e trocar somente o ponteiro ativo;
provar o mesmo fingerprint lógico antes/depois. Não mover nem substituir `data`,
configuração, banco, backups existentes ou logs; o backup de marco e os logs da
própria operação podem ser acrescentados. Não tocar em tarefas, porta, túnel ou
portal, salvo a ponte legada explicitamente descrita na seção 12.

### Classe B2 — evolução do banco (`DB_MIGRATION`)

Exemplos:

- adicionar tabela, coluna, índice ou constraint;
- adotar uma versão formal em banco legado;
- executar backfill ou transformação de dados;
- mudar regra cuja ativação dependa de novo schema.

Ação: usar uma janela separada, plano confirmado, serviço parado, backup
verificado, transação e evidência de integridade. `DB_MIGRATION` nunca é chamada
pelo startup, backup ou updater `APP_ONLY`.

Mudança de tarefa, configuração, ACL, porta ou retenção é manutenção de
infraestrutura própria; não deve ser disfarçada como `APP_ONLY` nem como
`DB_MIGRATION`.

### Classe C — contrato de integração

Exemplos:

- mudar hostname, rota inicial ou semântica de login;
- exigir informação do portal;
- alterar o texto/expectativa que o portal apresenta;
- criar indisponibilidade planejada relevante ao uso do link;
- compartilhar estado, dados ou autenticação.

Ação: parar, escrever proposta de mudança de contrato e pedir autorização.
Depois, entregar handoff separado ao projeto `site`; não editar o site como
efeito colateral da feature.

### Classe D — domínio/infraestrutura externa

Exemplos:

- DNS, nameserver, DNSSEC, MX, SPF, DKIM ou DMARC;
- token, rota ou exclusão do Cloudflare Tunnel;
- Hostinger, SSL ou `public_html`;
- encaminhamento de porta no roteador.

Ação: operação exclusiva do proprietário. O desenvolvedor pode documentar,
validar localmente e fornecer dry-run, mas não deve executar mutação remota.

## 10. Migrações e proteção do SQLite

Uma **atualização comum** não é uma migração. Ela publica código, dependências,
templates e assets numa release imutável em `releases\<release_id>` e ativa essa
release pela troca atômica de `state\active-release.json`. Ela não executa DDL,
seed nem alteração de conteúdo no SQLite existente. O startup apenas abre e
valida a base; se o arquivo ou a estrutura esperada estiver ausente, falha sem
criar uma base vazia. A criação é exclusiva do comando
`handball.cli init-database`, usado no bootstrap da primeira instalação.

`app\scripts` contém apenas launchers e o resolver de release em caminhos
operacionais estáveis. `ops\database-guard.py` é independente do pacote
`attendance` e executa `quick_check`, fingerprint e backup SQLite sem DDL ou
seed. Nenhum desses fluxos escolhe outro banco: configuração, SQLite, backups e
logs permanecem fora das releases.

Aplicação e guard implementam independentemente o mesmo contrato versionado de
fingerprint, `crepaldi-handball-logical-sqlite/v1`. O preflight `APP_ONLY` e o
runner `DB_MIGRATION` exigem igualdade entre ambos e falham antes de qualquer gate
de escrita se os algoritmos divergirem.

Se uma melhoria exigir mudança de esquema, ela deixa de ser uma atualização
comum. Deve virar manutenção de banco separada, explicitamente autorizada pelo
proprietário e fora de `scripts\update-server.ps1`.

O versionamento formal usa dois registros na mesma transação:

- `PRAGMA user_version`, com a versão numérica corrente;
- `schema_migrations`, com `version`, `name`, `checksum_sha256`, `applied_at`,
  `app_version` e `origin`.

O aplicativo declara intervalo mínimo/máximo compatível. Um banco futuro,
parcial ou com checksum divergente é recusado; não é “corrigido” no startup. Um
banco legado já compatível pode continuar atendendo a aplicação e adotar o
baseline formal somente no fluxo separado de migration.

Toda evolução de esquema deve ser:

1. aditiva sempre que possível;
2. idempotente;
3. executável sobre banco já populado;
4. coberta por teste com esquema anterior;
5. transacional;
6. compatível com rollback de código ou acompanhada de plano explícito;
7. precedida de backup consistente;
8. incapaz de apagar/recriar silenciosamente o banco.

Não existe migration automática no startup. `database-plan` inspeciona e produz
fingerprint/hash sem escrita. `scripts\migrate-database.ps1` exige uma segunda
execução com `-Apply -ExpectedPlanSha256`, recalcula o plano após parar o serviço,
cria backup verificado e só então chama `database-migrate`. O updater comum não
contém nem invoca essa chamada.

Nunca:

- usar banco real nos testes;
- rodar `DROP TABLE` em inicialização comum;
- chamar bootstrap ou seed durante startup, backup ou update;
- substituir arquivo enquanto o servidor grava;
- copiar somente `.db` de um banco WAL sem API de backup/fechamento adequado;
- semear novamente dados de modo que mudanças legítimas do usuário sejam
  revertidas;
- tornar migration dependente do portal.

Para backup operacional, prefira o script já instalado:

```powershell
& 'C:\ProgramData\CrepaldiHandball\app\scripts\backup-server.ps1'
```

Para integridade em leitura:

```powershell
$handballRoot = 'C:\ProgramData\CrepaldiHandball'
$opsManifest = Get-Content -Raw `
    -LiteralPath (Join-Path $handballRoot 'ops\ops-manifest.json') |
    ConvertFrom-Json
$guardPython = [IO.Path]::GetFullPath([string]$opsManifest.guard_python_path)
$guardPath = Join-Path $handballRoot 'ops\database-guard.py'
$guardEntry = @($opsManifest.files | Where-Object path -CEQ 'ops/database-guard.py')
if (
    [int]$opsManifest.format -ne 1 -or
    [int]$opsManifest.protocol -ne 1 -or
    $guardEntry.Count -ne 1 -or
    (Get-FileHash $guardPython -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$opsManifest.guard_python_sha256 -or
    (Get-FileHash $guardPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$guardEntry[0].sha256
) { throw 'Runtime operacional não corresponde ao manifesto.' }
& $guardPython -I -S $guardPath verify `
    --config-path (Join-Path $handballRoot 'data\app-config.json') `
    --expected-database-path (Join-Path $handballRoot 'data\presencas.db')
```

Esperado: JSON com `ok = true`, `quick_check = "ok"`, nenhuma violação de
chave estrangeira e fingerprint lógico SHA-256.

## 11. Offline, idempotência e service worker

O PC é a fonte de verdade. Uma operação offline contém `operation_id`,
`member_id`, `base_version` e conteúdo normalizado. O servidor deve:

- reconhecer repetição idêntica sem duplicar efeito;
- rejeitar reutilização do mesmo ID com conteúdo diferente;
- detectar versão desatualizada;
- não sobrescrever silenciosamente mudança mais nova do PC;
- registrar origem adequada na auditoria.

O service worker atual:

- usa `CACHE_NAME = "handball-shell-v3"`;
- pré-carrega `/app`, CSS, JS, manifest e ícones;
- usa network-first para `/app` e `/static/` com fallback em cache;
- exclui qualquer caminho `/api/`;
- remove caches com nome antigo na ativação.

Ao mudar assets ou formato offline:

1. considere incrementar o nome do cache;
2. mantenha API fora do cache comum;
3. teste instalação limpa e atualização sobre PWA existente;
4. teste offline e reconexão;
5. confirme que não há operação perdida antes de limpar storage;
6. não envolva o service worker do portal.

Segundo o comportamento documentado, somente chamada, confirmação e observação
individual funcionam offline. Elenco, histórico, auditoria, exportações,
encerramento e reabertura exigem servidor.

## 12. Instalação e allowlist de produção

O instalador não copia o repositório inteiro. O payload imutável da release é:

```text
app.py
requirements.txt
attendance/
templates/
static/
```

Os componentes operacionais são publicados separadamente em caminhos estáveis:

```text
scripts/run-server.ps1
scripts/backup-server.ps1
scripts/reset-password.ps1
scripts/update-server.ps1
scripts/migrate-database.ps1
scripts/release-resolver.ps1
handball/database/guard.py
```

Os seis scripts PowerShell são instalados em `app\scripts`; o guard é instalado
em `ops\database-guard.py`. O diretório `app` não é mais a release executável.

Consequência crítica: se uma feature criar um arquivo ou diretório de runtime
fora desses caminhos, ela pode funcionar localmente e faltar em produção. Nesse
caso, atualize a allowlist de runtime ou o mapeamento operacional correspondente e
crie teste de regressão do instalador.

Dentro das allowlists, o instalador materializa somente arquivos rastreados, sem
modificação no worktree ou no index e já contidos no commit `HEAD`. O updater
materializa o runtime da nova release a partir desse mesmo snapshot e somente
publica a camada operacional ao criar a ponte inicial de um layout legado. Fonte
não rastreada, suja, staged mas ainda não commitada ou alterada durante a coleta é
recusada para impedir que caches, rascunhos ou artefatos concorrentes entrem
silenciosamente na produção.

O instalador:

- exige PowerShell 7 como Administrador;
- exige o destino exatamente `C:\ProgramData\CrepaldiHandball`;
- cria `app`, `ops`, `releases`, `state`, `data`, `backups` e `logs`;
- é exclusivo do bootstrap e recusa instalação já existente;
- cria configuração e banco somente pela CLI explícita de primeira instalação;
- cria uma release imutável e sua `.venv` em `releases\<release_id>`;
- grava atomicamente `state\active-release.json` apontando para essa release;
- instala launchers/resolver em `app\scripts` e o guard independente em `ops`;
- atualiza pip e instala `requirements.txt`;
- protege toda a raiz instalada, inclusive releases, ponteiros, `app`, `ops`,
  `data`, `backups`, estado e logs, com SIDs Local System e Administrators;
- registra `CrepaldiHandball` no startup como SYSTEM;
- configura `StartWhenAvailable`, 5 reinícios, intervalo de um minuto para o
  servidor;
- registra `CrepaldiHandballBackup` diariamente às 03:00 com
  `StartWhenAvailable`;
- inicia o servidor e exige `/ready` com `release_id` e fingerprint do banco
  inalterado.

Atualizações posteriores usam exclusivamente `scripts/update-server.ps1`, com
staging, ambiente isolado, guard independente, backup/hash, promoção de uma nova
release imutável e troca atômica do ponteiro. O rollback restaura somente
ponteiro/código; nunca restaura banco, configuração, backups ou logs. O mesmo lock
impede concorrência com o backup das 03:00.

Em instalações formais, esse fluxo autentica e preserva os launchers e o guard
estáveis; mudar essa camada é manutenção operacional separada, sem qualquer
permissão implícita para migrar o SQLite.

A primeira ponte de uma instalação legada é exceção operacional explícita: ela
publica os launchers/guard, endurece recursivamente as ACLs e normaliza
`ExecutionTimeLimit` do servidor. Depois dessa transição, `APP_ONLY` somente
verifica tarefas, ACLs e camada operacional; não as regrava.

## 13. Release seguro do aplicativo

### 13.1 Antes

1. confirme que nenhum usuário está salvando chamada;
2. rode testes, compileall, diff check e status;
3. confirme que toda fonte da release/operação está rastreada, limpa e commitada;
4. revise secrets e arquivos fora das allowlists;
5. confirme espaço para staging, `.venv`, backup e release anterior;
6. deixe o updater criar e registrar o backup de marco;
7. registre o commit que será instalado;
8. confirme que é update comum sem migration;
9. confirme que novos runtimes/operações estão nas allowlists do instalador.

### 13.2 Atualizar

Em PowerShell 7 como Administrador:

```powershell
Set-Location -LiteralPath 'C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas'
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\update-server.ps1
```

Isso é uma atualização do aplicativo, não do portal. Não abra Hostinger e não
copie arquivos para `site`.

### 13.3 Depois

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health | ConvertTo-Json -Compress
Invoke-RestMethod http://127.0.0.1:8765/ready | ConvertTo-Json -Compress
Get-ScheduledTask -TaskName CrepaldiHandball,CrepaldiHandballBackup |
    Select-Object TaskName, State
Invoke-RestMethod https://handball.crepaldi.com.br/health | ConvertTo-Json -Compress
```

Depois valide no navegador público sem provocar escrita no SQLite:

- login;
- assets e navegação autenticada;
- consulta de elenco ou histórico já existente;
- logout;
- PWA/cache se o frontend mudou.

Não crie treino, não sincronize chamada e não faça gravação controlada como gate
de `APP_ONLY`. Testes de escrita usam banco temporário ou uma manutenção
separadamente autorizada.

O site público não “atualiza automaticamente” porque o código foi editado. A
URL só muda depois que o updater promove a release imutável e publica o novo
`state\active-release.json`.

## 14. Rollback independente

### 14.1 Código

- identifique commit anterior testado;
- confirme compatibilidade com o esquema atual;
- preserve banco e configuração;
- restaure atomicamente o ponteiro para a release anterior preservada pelo updater;
- valide `release_id`, readiness e fingerprint sem escrever no banco.

Esse rollback é exclusivamente de ponteiro/código. Não mova nem restaure
`presencas.db`, `app-config.json`, `backups` ou `logs` como parte dele.

Não use `git reset --hard` como procedimento operacional padrão.

### 14.2 Banco

- pare `CrepaldiHandball`;
- preserve o banco atual com timestamp;
- selecione backup consistente;
- restaure sem o servidor escrevendo;
- exija `PRAGMA quick_check` com resultado exatamente igual a uma linha `ok`;
- exija `PRAGMA foreign_key_check` sem linhas;
- reinicie e teste login/leitura/gravação/auditoria.

Não restaure o portal: ele não contém dados do handball.

### 14.3 Exposição pública

Desabilitar temporariamente a rota do túnel não apaga o banco. Mudança de
Cloudflare é exclusiva do proprietário e deve ser usada somente após diagnóstico
da camada local.

### 14.4 Portal

O rollback do portal restaura somente arquivos sob `public_html/roberto/` a
partir do backup próprio do site. Nunca use um pacote do handball para isso.

## 15. Computador desligado e disponibilidade

Quando o PC está desligado, dormindo ou hibernando:

- FastAPI para;
- cloudflared desconecta;
- o hostname continua existindo no DNS, mas a origem fica indisponível;
- login, API e sincronização com o servidor não funcionam;
- shell offline previamente instalado pode ter capacidade limitada;
- portal, site principal e e-mail continuam independentes.

Ao iniciar, a tarefa do servidor e o serviço cloudflared devem voltar. Esse
comportamento deve ser validado por reboot controlado. Se disponibilidade 24/7
se tornar requisito, isso é uma decisão de infraestrutura do handball, não uma
razão para mover código para o portal.

## 16. DNS e túnel

Estado-base conhecido:

- Cloudflare Free;
- túnel `crepaldi-handball`;
- origem `http://127.0.0.1:8765`;
- nameservers `dawn.ns.cloudflare.com` e `nash.ns.cloudflare.com`;
- CNAME do handball para o Tunnel;
- registros anteriores de site/e-mail preservados como DNS only;
- DNSSEC não habilitado no marco inicial.

O desenvolvimento comum não exige tocar em nenhum desses itens. Se `/health`
local funciona e o público falha, diagnostique serviço cloudflared e rota; não
mude MX, e-mail, site principal ou nameserver por tentativa.

Nenhum token deve aparecer em commit, documentação, terminal compartilhado ou
captura. Em caso de suspeita, o proprietário rotaciona o token e registra apenas
a data.

## 17. Contrato de segurança

Uma mudança não pode ser aceita se:

- expõe Uvicorn em `0.0.0.0` sem projeto e autorização específicos;
- abre a porta 8765 no roteador;
- desliga cookie Secure em produção;
- remove CSRF de escrita;
- adiciona CORS amplo;
- permite iframe;
- cria endpoint público com dados de atleta;
- registra senha, hash, secret, cookie ou token;
- envia banco/log/backup para Git ou portal;
- enfraquece auditoria ou controle de versão offline;
- permite que seed sobrescreva decisão do usuário;
- torna o portal dependente do backend doméstico;
- mistura credencial do cofre com login administrativo.

Uma senha tecnicamente pode ser qualquer valor não vazio. Isso não altera a
recomendação operacional: usar senha longa, única e protegida.

## 18. Testes mínimos por tipo de mudança

| Mudança | Testes adicionais obrigatórios |
|---|---|
| regra de confirmação/presença | domínio, banco, auditoria, encerramento/reabertura |
| sync/offline | idempotência, hash divergente, versão em conflito, reconexão |
| updater `APP_ONLY` | parser, allowlist, lock, staging, identidade, rollback e fingerprint invariável |
| `DB_MIGRATION` | banco anterior populado, plano obsoleto, backup/hash, ledger/checksum, segunda execução e rollback transacional |
| autenticação | login válido/inválido, rate limit, cookie, expiração, CSRF, logout |
| API | auth, validação, no-store, erro e efeito no SQLite |
| frontend | desktop, móvel, teclado, cache antigo e service worker novo |
| backup | consistência SQLite, rotação, falha de caminho, integridade |
| instalador | parser PowerShell, SIDs, allowlists de runtime/operação, ponteiro e preservação de estado |
| dependências | suíte completa, compileall e smoke local |
| contrato público | `/`, `/login`, `/app`, `/health` e hostname |

Todo bug corrigido deve ganhar regressão quando reproduzível.

## 19. Stop conditions: quando não continuar sozinho

Pare e peça decisão do proprietário se a tarefa exigir:

- editar qualquer arquivo dentro de `..\..\site`;
- publicar ou acessar Hostinger;
- alterar DNS, DNSSEC, e-mail ou Tunnel no painel;
- ler/copiar credencial ou token;
- apagar, recriar ou substituir banco de produção;
- mudar hostname ou integração por link;
- compartilhar autenticação ou dados com o portal;
- mudar escopo de privacidade;
- efetuar manutenção com usuários ainda gravando;
- escolher entre perda potencial de dados e indisponibilidade.

Uma solicitação explícita e separada pode abrir novo escopo, mas as instruções
do projeto de destino precisam ser lidas antes de agir.

## 20. Handoff quando uma mudança afetar o portal

O handoff deve conter, no mínimo:

```text
Motivo da mudança:
Classe de impacto:
Contrato atual:
Contrato proposto:
URL antiga e nova:
Arquivos do site que provavelmente mudariam:
Dados compartilhados (esperado: nenhum):
Alteração de autenticação (esperado: nenhuma):
Alteração de CSP/CORS/iframe (esperado: nenhuma):
Compatibilidade e prazo:
Teste local do handball:
Teste público do handball:
Rollback do handball:
Rollback do portal:
Riscos para site/e-mail/DNS:
Segredos incluídos: NÃO
Autorização do proprietário:
```

O agente do handball entrega isso; não implementa a metade do portal no mesmo
commit ou no mesmo worktree.

## 21. Dívida técnica descoberta na auditoria de continuidade

Esta seção distingue o estado efetivo do estado desejado. Os itens abaixo foram
identificados por leitura do código em 21/07/2026; não devem ser descritos como
corrigidos até existir commit, regressão e validação de produção.

Estado local após a melhoria de persistência do mesmo dia: o código-fonte agora
contém updater transacional, readiness com identidade, Stop/Start correto,
bootstrap separado e validação read-only do SQLite. Isso ainda não altera a
instalação ativa em `C:\ProgramData`; os P0 abaixo permanecem como descrição do
release instalado até ocorrer uma janela de update com backup e aceite.

### P0 operacional — instalação ativa ainda usa o release legado

O release instalado no marco `72cb9e3` copia arquivos diretamente sobre
`C:\ProgramData`, não cria
staging/release versionada, não remove sobras de versões antigas e não para nem
reinicia explicitamente uma tarefa já em execução. Ao final chama apenas
`Start-ScheduledTask`. Se a tarefa já estiver `Running`, o processo antigo pode
continuar carregado.

Além disso, `/health` retorna JSON fixo sem versão. Assim, `ok` após o instalador
pode vir do processo anterior e não comprova que o commit novo está ativo.

Para fazer a primeira transição da instalação ativa ao layout novo:

1. interromper edições dos usuários;
2. criar backup consistente e hash;
3. confirmar o processo legado esperado antes da janela;
4. executar `scripts\update-server.ps1` a partir de fonte rastreada, limpa e
   commitada; o updater deve parar `CrepaldiHandball` e confirmar a porta livre,
   e o instalador inicial não deve sobrescrever uma raiz existente;
5. confirmar novo processo, `release_id` e ponteiro ativo;
6. registrar commit implantado fora do segredo de configuração;
7. testar liveness/readiness local e pública, sem escrita como gate de `APP_ONLY`;
8. nunca tomar `/health` isolado como prova de atualização.

Correção já presente no código-fonte candidato: staging no mesmo volume, `.venv`
isolada, allowlists, manifesto/hash do runtime, releases imutáveis em
`releases\<release_id>`, launchers/guard estáveis e ponteiro atômico
`state\active-release.json`. O rollback é somente de ponteiro/código; `/ready` e
o guard comparam `release_id` e fingerprint do SQLite antes/depois.

Na primeira transição legada, uma falha ocorrida depois da parada deve manter o
serviço parado: ainda não existe release anterior confiável no ponteiro, e reiniciar
o código legado poderia executar startup mutável. O banco não é restaurado,
migrado, semeado ou movido pelo rollback. Falta instalar e aceitar esse release em
produção; a existência do código local não é prova de deploy.

### P0 operacional — reset instalado ainda depende do cmdlet inexistente

O `scripts/reset-password.ps1` do release instalado e a documentação histórica chamam
`Restart-ScheduledTask`. O módulo ScheduledTasks disponível possui
`Stop-ScheduledTask` e `Start-ScheduledTask`, mas não esse cmdlet. Consequência:

- a CLI pode gravar novo hash e nova `secret_key`;
- o wrapper falha ao tentar reiniciar;
- o processo em memória continua aceitando a credencial/sessão antiga até ser
  realmente parado e iniciado;
- dizer que o reset “reinicia e invalida sessões” sem essa ressalva é incorreto.

O código-fonte candidato já usa Stop → espera/porta livre → Start → `/ready` e
possui regressão. Até ele ser instalado, o procedimento manual seguro continua
necessário na cópia ativa.

### P0 operacional — release instalado ainda não oferece `/ready`

Manter `GET /health` como liveness simples é uma decisão arquitetural, não uma
dívida: ele não deve abrir banco nem executar verificação custosa. O P0 é o
release legado instalado ainda não oferecer `/ready`, deixando a produção sem
prova de identidade da release e compatibilidade do schema.

Separação implementada no código-fonte candidato:

- manter `/health` como liveness simples;
- `/ready` faz abertura somente leitura, valida schema e informa versão de schema e
  versão de aplicação;
- manter `PRAGMA quick_check` como verificação operacional separada, porque pode
  ser mais custosa.

### P1 — elenco inicial identificável está no Git

`attendance/models.py` contém 19 nomes/apelidos e posições em
`INITIAL_MEMBERS`. Portanto:

- dados operacionais estão no SQLite, mas parte do elenco identificável também
  está no código rastreado;
- o repositório deve ser tratado como privado;
- compartilhar/publicar o repositório expõe esse bootstrap;
- nenhuma fonte do app deve ir para `site` ou Hostinger.

Melhoria: mover bootstrap para importação local não rastreada ou migration
one-shot consentida e remover dados identificáveis do código.

### P1 operacional — seed do release instalado pode sobrescrever posições

No release instalado, `seed_initial_members()` executa UPSERT e atualiza
`position` para cada nome inicial em toda inicialização. Uma posição editada na
interface pode voltar ao valor codificado após restart, contrariando “SQLite
como fonte de verdade”.

O código-fonte candidato limita o seed ao bootstrap, usa `ON CONFLICT DO NOTHING`
e testa que restart não modifica banco existente. A pendência termina somente
depois do update e da verificação de produção.

### P1 — auditoria administrativa é parcial

Confirmação, presença e observação individual são auditadas. Porém o modelo
atual não registra de forma completa:

- reabertura de treino;
- alteração de observação geral;
- criação/alteração/inativação de atleta;
- encerramento como evento próprio quando não há registros `NULL`;
- ator explícito em cada evento; existe `source`, mas não campo de usuário.

Até corrigir, chamar a tela de “auditoria de registros individuais”, não de
auditoria completa de administração. A evolução deve ter eventos append-only e
testes para cada ação mutável.

### P1 — serviço exposto roda como SYSTEM/Highest

Servidor e backup são tarefas `SYSTEM` com nível mais alto. Isso facilita ACL,
mas amplia o impacto de uma vulnerabilidade web. Projetar conta de serviço
dedicada, sem login interativo, com privilégio mínimo sobre app, data, backups e
logs. A migração precisa preservar boot, ACL e recuperação.

### P1 — backups locais não cobrem desastre do computador

Banco e backups ficam no mesmo PC e provavelmente no mesmo volume. Isso ajuda
contra erro lógico e corrupção localizada, mas não contra falha física, furto,
ransomware ou perda total do Windows.

Projetar cópia externa cifrada, com retenção e restauração testada, sem usar a
Hostinger como banco. Não sincronizar um SQLite aberto por cópia bruta.

### P1 operacional — tarefa de backup instalada pode perder 03:00

No release instalado, o servidor recebe `StartWhenAvailable`; a tarefa de backup não recebe
explicitamente esse setting. Se o PC estiver desligado às 03:00, a janela pode
ser perdida. Corrigir a tarefa e testar o caso “liga depois das 03:00”, evitando
duplicação indevida. O instalador candidato já configura `StartWhenAvailable` na
tarefa nova, mas o updater `APP_ONLY` não re-registra tarefas existentes.

### P1 operacional — banco instalado ainda não adotou o baseline formal

O código-fonte candidato possui `PRAGMA user_version`, ledger com checksum,
planejamento read-only, confirmação por hash, backup obrigatório e runner
transacional. A base ativa ainda precisa ser inspecionada e, se o plano for
aceito, adotar o baseline por `scripts\migrate-database.ps1` em janela separada.
Não existe downgrade automático; rollback posterior ao commit restaura backup
sob decisão operacional explícita.

### P2 — dependências de produção não são reproduzíveis

`requirements.txt` usa intervalos e inclui ferramentas de teste como `pytest` e
`httpx` na produção. Não há lockfile/hashes. Separar runtime/dev, gerar lock
reproduzível, executar `pip check` e registrar versões por release.

### P2 — logs não têm retenção

`run-server.ps1` cria `logs/server-AAAA-MM-DD.log`, mas não há rotação/remoção.
Definir retenção, limite e inspeção, além de comprovar na instalação ativa a ACL
já aplicada pelo código candidato. Logs podem conter IP e caminho, então também
são dados operacionais e nunca entram no Git/site.

### P2 operacional — release instalado aceita prefixo semelhante em `InstallRoot`

O instalador legado usa `StartsWith()` contra
`C:\ProgramData\CrepaldiHandball`. Um caminho com o mesmo prefixo textual pode
passar sem ser a raiz/descendente desejada. Exigir igualdade ou prefixo seguido
por separador canônico, com testes de caminhos vizinhos. Os scripts candidatos
já exigem igualdade canônica exata.

### P2 — rate limit precisa ser validado através do Tunnel

O limitador é em memória, cinco falhas em quinze minutos, indexado por
`request.client.host`. É necessário provar qual IP chega através do cloudflared.
Se todos forem vistos como localhost, um atacante pode impor bloqueio coletivo;
reiniciar o processo também limpa o contador.

### P2 — PIN offline e dados locais

O cofre offline usa PBKDF2-SHA256 com 600 mil iterações e AES-GCM no IndexedDB,
mas aceita PIN numérico de seis ou mais dígitos. Isso oferece resistência
limitada contra ataque local ao dispositivo. O navegador guarda, cifrados,
elenco/presenças/observações necessários ao offline. Validar limpeza no logout,
fila antes de limpar dados e orientação de PIN não reutilizado.

### Ordem sugerida de continuidade

1. instalar e aceitar em produção a release candidata, comprovando ponteiro,
   `/ready`, startup read-only, reset e fingerprint invariável;
2. inspecionar a base ativa e, somente com plano aprovado, adotar o baseline formal
   pelo fluxo separado `DB_MIGRATION`;
3. retirar o elenco identificável do Git e completar a auditoria administrativa;
4. fortalecer restore, tarefa atrasada e cópia cifrada externa;
5. reduzir o privilégio SYSTEM e separar dependências runtime/desenvolvimento;
6. tratar retenção de logs, rate limit no túnel e hardening offline.

Cada item deve ser um commit lógico separado, com testes, e não autoriza mudança
no portal.

## 22. Estado conhecido e pendências em 21/07/2026

Comprovado no marco:

- commit `72cb9e3` e suíte de 11 testes;
- instalação permanente concluída;
- saúde local `ok`;
- tarefas de servidor/backup presentes;
- banco e pasta de backups existentes;
- login local funcional;
- DNS propagado para Cloudflare por 1.1.1.1 e 8.8.8.8;
- site principal, portal e e-mail confirmados após a migração;
- túnel saudável com uma réplica;
- `/health` público e página pública de login funcionando.

Ainda pendente:

- login autenticado e gravação controlada pela URL pública;
- `PRAGMA quick_check`;
- backup manual de marco com hash;
- exercício de restauração;
- reboot e auto-start controlados;
- link real no portal, validação, pacote e publicação manual;
- teste PWA/offline no iPhone;
- revisão final de controles de IA/robots;
- decisão futura sobre DNSSEC.

Não transforme pendência em fato concluído sem nova evidência.

## 23. Definição de pronto para desenvolvimento futuro

Uma alteração do handball está pronta quando:

- regras de domínio e fronteira permanecem válidas;
- testes e compileall passam;
- diff e arquivos staged foram revisados;
- nenhum segredo/dado entrou no Git;
- as allowlists contêm todo novo runtime e componente operacional;
- release local e público foi validado quando instalado;
- cache/PWA foi testado quando afetado;
- documentação deste repositório foi atualizada;
- nenhuma mudança ocorreu no site, Hostinger, DNS ou e-mail como efeito colateral;
- eventual mudança de contrato foi encaminhada, autorizada e executada em fluxo
  separado.

Uma operação `APP_ONLY` somente está pronta quando também:

- `release_id` esperado foi comprovado por `/ready`;
- `state\active-release.json` apontou para a release imutável esperada;
- banco/configuração permaneceram nos mesmos caminhos;
- backups/logs permaneceram fora das releases e sem troca;
- fingerprint lógico do SQLite foi idêntico antes/depois;
- o guard independente comprovou `quick_check`, fingerprint e backup de marco;
- nenhuma CLI de bootstrap, seed ou migration foi chamada;
- rollback de ponteiro/código preservou a base nos testes de falha;
- a falha do primeiro update legado após a parada deixou o serviço parado.

Uma operação `DB_MIGRATION` somente está pronta quando também:

- plano/fingerprint foram revistos e o `plan_sha256` foi confirmado;
- backup consistente e seu SHA-256 foram preservados;
- ledger, `user_version`, DDL e pós-condições foram aplicados na mesma transação;
- `quick_check` retornou exatamente `ok` e `foreign_key_check` nenhuma linha;
- `schema_version` antes/depois e compatibilidade do `release_id` foram registrados.

## 24. Resumo normativo para agentes

```text
Trabalhe somente em handball/registrador-presencas.
Preserve o SQLite e a configuração.
Classifique a operação como INITIAL_INSTALL, APP_ONLY ou DB_MIGRATION.
Nunca migre ou semeie no startup, backup ou updater APP_ONLY.
Em APP_ONLY, publique releases/<release_id> imutáveis e troque apenas o ponteiro atômico.
Mantenha launchers em app/scripts e o guard independente em ops.
Exija fonte tracked, clean e committed; preserve data, backups e logs fora das releases.
Teste regras, migrações, segurança e PWA.
Atualize as allowlists do instalador se criar novo runtime ou componente operacional.
Mantenha handball.crepaldi.com.br, /health, /login e /app estáveis.
Não importe, copie, sirva ou edite o repositório site.
Não toque em Hostinger, DNS, e-mail ou Tunnel sem tarefa externa explícita do proprietário.
O único elo com /roberto/ é um link HTTPS comum, sem dados ou sessão compartilhada.
Se esse contrato precisar mudar, pare e produza um handoff antes de codificar.
```
