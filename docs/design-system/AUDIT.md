# Auditoria do sistema visual — fundação para o design system multi-time

| Campo | Valor |
|---|---|
| Data | 1 de agosto de 2026 |
| Escopo | leitura de código e templates; **nenhum arquivo de produto foi alterado nesta etapa** |
| Autoridade normativa | `AGENTS.md`, `docs/SITE-INTEGRATION-CONTRACT.md`, `docs/HM-IME-IDENTIDADE-VISUAL.md`, `docs/HM-IME-USUARIOS-E-AUTORIZACAO.md` |
| Fase | 1 — Leitura e auditoria (ver missão do design system) |

Este documento é o inventário e diagnóstico exigidos antes de qualquer mudança
de código. Toda afirmação abaixo cita arquivo e, quando útil, linha. Nenhuma
observação sobre Instagram, licença de fonte ou aprovação de ativo foi
inventada — a pesquisa de marca por time é tratada em
`docs/design-system/teams/hm-ime/RESEARCH.md` (etapa seguinte), não aqui.

## 1. Inventário das rotas visuais

Fonte: `docs/SITE-INTEGRATION-CONTRACT.md` §7.3, confirmado por leitura de
`handball/modules/*/router.py`.

| Rota | Autenticação | Template | Observação |
|---|---|---|---|
| `/login` | não | `login.html` | única tela pré-autenticação com marca própria |
| `/app` (hub real; a missão trata como "o hub") | sessão | `hub.html` | resolve tema sempre a partir de `ORGANIZATION` global, não da sessão |
| `/app/presencas` | sessão | `presencas/index.html` | paleta legada (navy/laranja) |
| `/app/presencas` (visão jogador) | sessão | `presencas/player.html` | idem |
| `/app/estatisticas` | sessão | `estatisticas/index.html` | esqueleto, paleta legada |
| `/app/calendario` | sessão | `calendario/index.html` | paleta própria `calendar-v2`, tema HM-IME hardcoded na classe |
| `/app/playbook` | sessão | `playbook/index.html` | paleta própria `playbook-app` (bordô, não é o vermelho HM-IME) |
| `/app/admin/usuarios` | sessão (DEV) | `usuarios/admin.html` | paleta legada, HTML minificado em uma linha |
| `/app/meu-relatorio` | sessão | `usuarios/report.html` | não lido em detalhe nesta auditoria (6 linhas, HTML minificado) |
| `/app/consultas` | sessão | `consultas/index.html` | paleta legada |

Não existe rota `/hub`; a missão usa esse nome apenas conceitualmente. Ver
achado da seção 10.

## 2. Inventário dos templates

10 templates em `templates/`. Nenhum usa uma macro Jinja ou `{% include %}`
compartilhado para o cabeçalho (`topbar`/`platform-appbar`) — cada template
repete o próprio HTML do cabeçalho com pequenas variações (comparar
`presencas/index.html:20-39`, `estatisticas/index.html:15-29`,
`consultas/index.html:14-17`, `usuarios/admin.html:3`). Isso é duplicação de
marcação, não só de CSS.

## 3. Inventário de componentes

Não existe um único "casco" compartilhado; existem **três** implementações
paralelas do mesmo conceito (app bar + marca + navegação):

1. `.topbar` / `.topbar-inner` / `.mini-mark` (`static/styles.css:538-596`) —
   usado por `presencas/index.html`, `presencas/player.html`,
   `estatisticas/index.html`, `consultas/index.html`, `usuarios/admin.html`.
   Monograma fixo `"H"` escrito literalmente no HTML (não vem de
   `team_theme.monogram`).
2. `.platform-appbar` / `.platform-brand` (`static/styles.css:44-71`) — usado
   somente por `hub.html`. Único lugar que já lê `team_theme.monogram` e
   `team_theme.logo_url` corretamente.
3. `.playbook-appbar` / `.playbook-brand-mark` (`static/styles.css:90-141`) e
   `.calendar-appbar` / `.calendar-brand-mark` (`static/styles.css:1156-1217`)
   — duas outras reimplementações completas, cada uma com seu próprio
   `sticky`, `z-index`, altura e tratamento de logo.

Também não existem os componentes compartilhados que
`docs/HM-IME-IDENTIDADE-VISUAL.md` §14.2 já previa (`dialog`, `toast`,
`empty-state`, `field` unificado). Cada módulo define os seus: `.modal`
genérico (`styles.css:952`) convive com `.playbook-dialog` e `.calendar-sheet`
sem relação estrutural entre si.

## 4. Inventário de tokens e cores

`static/styles.css` contém **quatro sistemas de cor independentes**, todos
ativos ao mesmo tempo:

| Sistema | Onde é definido | Quem usa | Cor de marca |
|---|---|---|---|
| Legado navy/laranja | `:root` (`styles.css:1-22`) | login, presenças, estatísticas, admin, consultas, sidebar, botões, `.metric` | `--navy-900 #0b1f33`, `--orange #ed6c2f` |
| HM-IME (`--hm-*`) | `:root` (`styles.css:27-36`) | somente `.platform-appbar`/`.platform-brand`/`.module-icon` no hub | `--hm-primary #D71920` |
| Playbook (`--playbook-*`) | escopado em `.playbook-app` (`styles.css:77-89`) | só o módulo Playbook | `--playbook-primary #7f1d1d` (bordô, **não** é o vermelho HM-IME) |
| Calendário (`--calendar-*`) | escopado em `.calendar-v2` (`styles.css:1123-1134`) | só o módulo Calendário | `--calendar-primary #d71920` (mesmo hex do HM-IME, mas copiado à mão, não referenciando `--hm-primary`) |

`handball/core/team_theme.py` é um quinto lugar com os mesmos valores
(`primary="#D71920"`, `primary_dark="#A40E17"` etc.), em Python. O comentário
em `styles.css:25-26` já admite isso: *"valores espelham
handball/core/team_theme.py::TEAM_THEMES\["hm-ime"\]"* — ou seja, o próprio
código reconhece que é uma cópia manual, não uma fonte única.

## 5. Estilos duplicados

O vermelho `#D71920`/`#A40E17` do HM-IME aparece **hardcoded em pelo menos
quatro lugares** sem nenhum deles referenciar os outros:

1. `handball/core/team_theme.py:50-51` (fonte "canônica" pretendida)
2. `static/styles.css:27-28` (`--hm-primary`/`--hm-primary-dark`, cópia manual)
3. `static/styles.css:1124-1125` (`--calendar-primary`/`--calendar-primary-dark`
   dentro de `.calendar-v2`, segunda cópia manual, nem usa `var(--hm-primary)`)
4. `static/styles.css:1216` (`.theme-hm-ime .calendar-brand-mark.has-image`
   referencia `/static/hm-ime-logo.jpg` diretamente, uma quarta menção)

Se o vermelho do HM-IME mudar um dia, são no mínimo três arquivos/blocos a
editar manualmente, e nada barra que fiquem divergentes silenciosamente — não
há teste que compare `team_theme.py` com o CSS gerado (mission item 8.1 exige
esse teste; hoje não existe, confirmado por busca em `tests/`).

## 6. Estilos específicos de módulo

- **Playbook** tem paleta própria (bordô `#7f1d1d`) que não é a marca HM-IME —
  já diagnosticado em `docs/HM-IME-IDENTIDADE-VISUAL.md` §13 ("marca
  parcialmente aplicada, com bordô e casco próprio"), confirmado aqui por
  leitura direta do CSS.
- **Calendário** tem paleta funcionalmente idêntica ao HM-IME mas
  implementada em variáveis `--calendar-*` isoladas, com App Bar, toasts,
  diálogos e grade de mês inteiramente próprios (`styles.css:1122-2163`, ~1000
  linhas só para esse módulo).
- **Hub** usa `--hm-*` diretamente, sem escopo de módulo.
- **Presenças, Estatísticas, Admin, Consultas** não têm identidade HM-IME
  nenhuma; ainda usam o navy/laranja original do produto pré-rebranding.

Nenhum módulo hoje viola "significado de sucesso/aviso/erro" entre si (verde
= sucesso e vermelho/laranja = alerta são consistentes), mas a marca (cor de
ação primária, tipografia de título, app bar) diverge em três variações
visuais coexistindo na mesma sessão de uso.

## 7. Estilos legados

Confirma-se uso ativo do navy/laranja original (pré-HM-IME) em:

- `login.html` (via `.login-body`, `.login-brand`, `.brand-mark`,
  `theme-color` fixo `#0b1f33`);
- `presencas/index.html`, `presencas/player.html` (`.topbar`, `.mini-mark`,
  `.sidebar`, `.nav-item.active` com `var(--navy-900)`);
- `estatisticas/index.html`, `consultas/index.html`, `usuarios/admin.html`
  (mesmo `.topbar`/`.mini-mark`, `theme-color` fixo `#0b1f33`);
- botões primários em geral: `.button-primary` usa `var(--navy-900)`
  (`styles.css:767`), não o vermelho HM-IME, em qualquer tela que não seja
  Hub/Calendário/Playbook.

Ou seja: 6 das 10 telas autenticadas (mais o login) ainda são a identidade
antiga. Isso concorda com o diagnóstico já registrado em
`docs/HM-IME-IDENTIDADE-VISUAL.md` §13, que este código confirma linha a
linha.

## 8. Inconsistências entre Python e CSS

- `handball/core/team_theme.py` é a única fonte que a missão poderia
  considerar "canônica hoje", mas nada gera o CSS a partir dela; a cópia em
  `:root` é manual (comentário confirma) e a cópia em `.calendar-v2` nem
  contém o comentário de origem.
- `handball/core/organization.py` (`ORGANIZATION = OrganizationIdentity(...)`)
  é importado diretamente por **quatro** routers distintos —
  `handball/modules/hub/router.py:9`,
  `handball/modules/calendario/router.py` (`grep` confirmou import e uso),
  `handball/modules/playbook/router.py` (idem) — cada um repetindo
  `"organization": ORGANIZATION` e `"team_theme": team_theme(ORGANIZATION.slug)`
  de forma independente. Não existe uma função central
  `resolve_active_team(session)`; existe uma constante global reimportada.
- `handball/modules/usuarios/router.py` e templates como `usuarios/admin.html`
  usam apenas `organization.display_name` no `<title>` e no cabeçalho — nem
  chegam a usar `team_theme`.

## 9. Dependências entre templates e seletores

- `templates/playbook/index.html:17` e `templates/calendario/index.html:16`
  escrevem a classe **`theme-hm-ime` literalmente no HTML**, não como
  expressão Jinja. Não há branch nenhum: mesmo que o backend resolvesse outro
  time no futuro, essas duas telas continuariam anunciando `theme-hm-ime` no
  `<body>`. `calendario/index.html:23` ao menos expõe
  `data-theme-slug="{{ team_theme.slug }}"` como dado dinâmico (não usado pelo
  CSS hoje, só está disponível para JS).
- `static/styles.css:1215-1217` depende dessa classe literal
  (`.theme-hm-ime .calendar-brand-mark.has-image`) para decidir se mostra o
  logotipo — ou seja, JS/CSS e o texto do template já pressupõem um único
  tema fixo, não uma variável.
- `presencas/index.html:19` já teve que resolver "qual time" na marra para o
  cofre offline: `data-team-id="{{ session.team_ids|list|first or 0 }}"`. Como
  `team_ids` é um `frozenset[int]` (`handball/core/auth.py:31`), "pegar o
  primeiro" de um conjunto não ordenado é uma pista concreta e já existente do
  problema que a missão pede para resolver corretamente — hoje é inofensivo
  porque só existe um time.

## 10. Funcionamento atual da identidade de organização

`handball/core/organization.py:11` define um único singleton:

```python
ORGANIZATION = OrganizationIdentity("HM_IME", "hm-ime", "HM-IME")
```

Ele é importado e usado como valor fixo em todo lugar que precisa de "o nome
da organização" — nunca é derivado da sessão do usuário autenticado. Mesmo um
`DEV` sem nenhum vínculo de time (`session.team_ids` vazio) veria
`organization.display_name == "HM-IME"` no cabeçalho, porque nada consulta
`session.team_ids` para decidir o que mostrar. Isso viola diretamente o Caso D
da missão ("usuário sem time... não atribuir visualmente um time
inexistente").

Divergência `/hub` vs `/app`: a rota real é `/app`
(`handball/modules/hub/router.py:16`); não existe `/hub` no código. A missão
já orienta tratar `/app` como o hub — não há ação de código necessária aqui,
só a convenção de nomenclatura na documentação nova.

## 11. Funcionamento atual de `team_ids`

A infraestrutura de identidade **já é multi-time-ready no nível de dados**:

- `AuthSession.team_ids: frozenset[int]` (`handball/core/auth.py:31`) é
  calculado corretamente a partir de `team_memberships` ativas
  (`handball/database/repositories/identity.py:99-111`), então já suportaria
  um usuário com mais de um vínculo.
- A tabela `teams` já existe desde o schema v2
  (`handball/database/migrations.py:364`, colunas `id, code, slug,
  display_name, active`) — ela já tem `slug`, exatamente o campo que
  `team_theme.py` espera. Hoje só existe uma linha (`HM_IME` /
  `hm-ime`), inserida pela própria migração
  (`handball/database/migrations.py:1849`).
- **O elo que falta**: nada no código converte `session.team_ids` (inteiros,
  chave primária de `teams`) em slugs de tema. `team_theme()` é chamado
  sempre com `ORGANIZATION.slug` (uma string fixa), nunca com um slug
  derivado de `teams.slug WHERE id IN team_ids`. Não existe método em
  `IdentityRepository` que devolva `teams.slug` a partir de `team_ids` — foi
  conferido por leitura completa de `handball/database/repositories/identity.py`
  (nenhum método consulta a tabela `teams`).

Ou seja: o banco já modela múltiplos times: falta o código de resolução de
tema ler a tabela `teams` em vez de usar a constante global.

## 12. Limitações para múltiplos times

1. `TEAM_THEMES` (`handball/core/team_theme.py:44-61`) só tem a chave
   `"hm-ime"`. Qualquer outro slug cai no `NEUTRAL_THEME` — isso já é o
   fallback correto exigido pela missão (Caso E), só falta ser alcançável por
   um caminho real (hoje é inalcançável porque nada além de `ORGANIZATION.slug`
   é passado para `team_theme()`).
2. Não existe seletor de time ativo em lugar nenhum da interface — não seria
   necessário hoje (só existe um time), mas confirma que o Caso C da missão
   ("usuário com mais de um time") está completamente não implementado, nem
   no armazenamento de preferência nem na UI.
3. `playbook/index.html` e `calendario/index.html` cravam `theme-hm-ime` no
   HTML (seção 9) — mesmo que o backend resolvesse o tema certo amanhã, essas
   duas telas ignorariam o resultado.
4. Login (`login.html`) hoje **não** referencia HM-IME, `team_theme` nem
   `organization` em lugar nenhum — o que é, por acidente de arquitetura
   (essas variáveis nunca foram passadas ao template de login, ver
   `handball/core/auth.py:266-282`), exatamente o comportamento neutro que a
   missão pede para o Caso A. Não é uma decisão deliberada de design, é
   ausência de acoplamento — mas o resultado observável já está correto e
   deve ser preservado (e formalizado) na Camada 1, não "corrigido".

## 13. Riscos para autenticação e autorização

Nenhum risco de autenticação/autorização foi introduzido pelo código atual de
tema — `team_theme()` é uma função pura sobre uma string, sem I/O, sem SQL, e
os valores só alimentam `<meta theme-color>`, uma classe CSS e um atributo
`data-*` (nenhum é `style=` inline nem HTML não escapado). O risco real é de
**produto, não de segurança**: como a seção 10 mostra, o hub mostraria
"HM-IME" para qualquer usuário autenticado, inclusive um `DEV` sem
`team_ids`, porque a resolução de tema nunca checa a sessão. Ao introduzir a
resolução por `team_ids`, a escolha do slug deve continuar vindo
exclusivamente do backend (nunca de query string, cookie de cliente ou
`localStorage`) — não há nenhum código hoje que aceite tema vindo do
navegador, e isso não deve mudar.

## 14. Riscos para PWA e CSP

- CSP é `self`-only, sem `unsafe-inline` (`docs/SITE-INTEGRATION-CONTRACT.md`
  §7.4); nenhum template lido usa `style="..."` inline nem `<style>` com dado
  de usuário — os valores de tema hoje só aparecem em atributos de texto
  simples (`content`, `class`, `data-theme-slug`), que o Jinja autoescapa.
  Qualquer novo mecanismo de tema deve manter essa restrição: token de cor
  nunca deve virar `style` inline construído a partir de dado não confiável.
- Service worker (`static/sw.js`, `CACHE_NAME = "handball-shell-v3"` conforme
  `docs/SITE-INTEGRATION-CONTRACT.md` §11) faz cache network-first de `/app` e
  `/static/`. Hoje isso é seguro porque `/app` é idêntico para todo mundo
  (mesma marca fixa). Se o tema passar a variar por usuário/time, uma resposta
  de `/app` cacheada offline poderia, em tese, ser reaproveitada para o
  usuário errado no mesmo dispositivo compartilhado — risco a mitigar
  explicitamente ao implementar a Camada 2 (ver seção 15, item de teste PWA
  obrigatório antes de fechar a Fase 8 da missão).
- Nenhum CSS é lido do banco hoje (SQL Explorer é somente leitura de
  metadados de tema, que são um dicionário Python, não uma coluna); a
  arquitetura de tokens proposta deve preservar isso — tema por time deve
  continuar sendo um registro estático versionado em código/arquivo, nunca
  uma linha de banco interpretada como CSS.

## 15. Plano incremental de refatoração (visão preliminar)

Esta é a leitura de arquitetura da Fase 1. O desenho detalhado de tokens,
componentes e resolução de time é responsabilidade da Fase 2 (próxima etapa),
mas o formato do trabalho já fica claro pela auditoria:

1. **Fundação de tokens**: criar uma fonte única (schema validado) para
   tokens neutros + tokens por time; gerar `tokens.generated.css`
   deterministicamente a partir dela; fazer `handball/core/team_theme.py`
   carregar dessa mesma fonte em vez de manter valores Python paralelos.
2. **Resolução de time**: adicionar a `IdentityRepository` um método que
   traduza `team_ids`/sessão em `teams.slug`; substituir toda chamada
   `team_theme(ORGANIZATION.slug)` (hoje em 3 routers) por uma resolução que
   parte da sessão, com fallback neutro explícito para Casos D/E.
3. **Camada 1 (login)**: formalizar o que já é observável — login sem marca
   de time — como tema neutro deliberado, usando os tokens novos em vez do
   navy/laranja hardcoded de `styles.css:1-22`.
4. **Componentes compartilhados**: unificar as três implementações de app bar
   (seção 3) em uma só, parametrizada por tema.
5. **Migração por módulo**: Presenças/Estatísticas/Admin/Consultas (ainda
   legados) e depois Playbook/Calendário (já "quase lá", mas com paletas
   próprias) passam a consumir os componentes e tokens compartilhados,
   removendo `--playbook-*` e `--calendar-*` como paletas independentes.
6. **Testes**: cobrir os casos A-E da missão, o contrato de schema dos
   tokens, e o artefato CSS gerado vs. fonte (hoje nenhum desses testes
   existe — confirmado na seção 17 abaixo).

## 16. Arquivos que deverão ser modificados

```text
handball/core/team_theme.py            # passa a ler de fonte canônica versionada
handball/core/organization.py          # deixa de ser "a" identidade única; vira fallback/tipo
handball/database/repositories/identity.py  # ganha resolução team_ids -> teams.slug
handball/modules/hub/router.py         # resolve tema pela sessão, não por ORGANIZATION fixo
handball/modules/calendario/router.py  # idem
handball/modules/playbook/router.py    # idem
templates/login.html                   # tema neutro explícito (tokens novos)
templates/hub.html                     # app bar compartilhada
templates/calendario/index.html        # remove `theme-hm-ime` literal
templates/playbook/index.html          # remove `theme-hm-ime` literal
templates/presencas/index.html         # migra para casco compartilhado
templates/presencas/player.html        # idem
templates/estatisticas/index.html      # idem
templates/consultas/index.html         # idem
templates/usuarios/admin.html          # idem
static/styles.css                      # divide em tokens + base + componentes + módulos
```

## 17. Arquivos que não devem ser modificados nesta iniciativa

```text
handball/core/auth.py                  # contrato de sessão/cookie/CSRF já correto (ver seção 13)
handball/core/authorization.py         # matriz de permissões fora de escopo
handball/database/migrations.py       # nenhuma alteração de schema nesta etapa (regra 13 AGENTS.md)
handball/database/schema.py
static/sw.js                           # mudar exige plano próprio de cache (seção 14)
scripts/*                              # fora do escopo de design visual
data/, backups/, app-config.json       # nunca tocados por agente (regra 17 AGENTS.md)
```

## Testes existentes relevantes (linha de base)

Confirmado por leitura de `tests/test_web.py` e `tests/test_modular_web.py`:
existem testes de segurança de sessão/cookie/CSRF, de redirecionamento
anônimo (`test_every_application_page_redirects_anonymous_users`), de
navegação por teclado no hub (`test_hub_exposes_all_modules_as_keyboard_accessible_links`)
e de PWA/offline (`test_pwa_v9_keeps_last_calendar_navigation_read_only_offline`).
**Não existe** nenhum teste hoje que verifique: ausência de marca de time no
login, resolução de tema por `team_ids`, fallback neutro para time
desconhecido/ausente, ou consistência entre `team_theme.py` e o CSS. Esses
testes são trabalho novo da Fase 4/8, não uma lacuna de um teste quebrado.

## Nota sobre trabalho não relacionado já presente no worktree

O `git status` no início desta tarefa já mostrava mudanças não commitadas em
`README.md`, `docs/SITE-INTEGRATION-CONTRACT.md`, `tests/test_database.py`,
`tests/test_sql_explorer.py`, `tests/test_users_authorization.py`, além dos
arquivos novos `docs/HANDBALL-CODE-AUDIT-2026-07-30.md` e
`tests/test_audit_architecture.py`. Essas mudanças pertencem a uma auditoria
anterior sobre trilha de auditoria de presença/segurança (30/07/2026), não a
este trabalho de design system. Não foram tocadas nem revertidas por esta
auditoria.

## Conclusão da Fase 1

A base é mais favorável do que o pior cenário possível: o modelo de dados
(`team_ids`, tabela `teams`) já suporta múltiplos times, o login já não
carrega marca de time (mesmo que por acidente), e já existe uma tentativa
deliberada de tokens compartilhados (`--hm-*`) com um comentário reconhecendo
a duplicação. O trabalho real da Fase 2 em diante é: (1) dar a esses tokens
uma fonte única de verdade geradora de CSS; (2) trocar a constante global
`ORGANIZATION` por resolução real a partir da sessão; (3) consolidar três
app bars e quatro paletas em um casco só; (4) tornar o login neutro uma
decisão explícita e testada, não um efeito colateral.
