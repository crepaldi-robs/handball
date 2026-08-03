# Arquitetura do design system multi-time

| Campo | Valor |
|---|---|
| Data | 1 de agosto de 2026 (fundação e Fase 7) — Fase 8 em 3 de agosto de 2026 |
| Depende de | `docs/design-system/AUDIT.md` (diagnóstico), `AGENTS.md`, `docs/SITE-INTEGRATION-CONTRACT.md` |
| Escopo desta entrega | fundação de tokens, resolução de time ativo, login neutro, hub tematizado **e Fase 7**: os 6 módulos restantes (Presenças, Estatísticas, Calendário, Playbook, Consultas, Administração) agora resolvem `organization`/`team_theme` pela sessão, não por uma constante fixa — ver "Estado e pendências". |

## As três camadas

### Camada 1 — Plataforma neutra

Governa `/login` e qualquer tela sem time resolvido. Fonte:
`design-system/platform.json` → `static/css/tokens.generated.css` sob
`:root, [data-theme="neutral"]`. Nunca contém HM-IME nem qualquer outra marca
de time — `handball/core/organization.py::ORGANIZATION` não é usada por
`templates/login.html`, e `IdentityService.resolve_active_team_view` só
retorna um time quando a sessão realmente tem `team_ids`.

### Camada 2 — Identidade do time

Um arquivo por time em `design-system/themes/<slug>.json`, validado por
`handball/core/design_tokens.py` contra o contrato de
`design-system/schemas/theme.schema.json`. Um time só pode sobrescrever
marca (`brand_primary`, `brand_primary_hover`, `brand_on_primary`, `canvas`,
`surface`, `surface_raised`, `text`, `text_muted`, `border`, `focus`) e a
fonte de título (`fonts.heading`). `success`, `warning`, `danger`, `info`,
espaçamento, raio e sombra são exclusivos da plataforma — um arquivo de tema
que tente redefini-los falha a validação (`DesignTokenError`), não é
corrigido em silêncio.

### Camada 3 — Identidade do módulo

Os namespaces `--playbook-*` e `--calendar-*` **não existem mais**. Eles
foram, nesta ordem: paleta própria com hex duplicado → bloco de apelidos que
só reapontava para os tokens compartilhados → nada. As regras de Playbook e
Calendário consomem `var(--color-*)` direto. A diferenciação de cada módulo
continua onde sempre esteve de verdade — ícone, navegação, densidade,
componentes próprios —, não em uma cor de marca paralela.

O que sobra de Camada 3 é `static/css/hm-ime-expressive.css`: dourado,
vermelho esportivo, vinho profundo e azul institucional do HM-IME. Eles não
cabem no arquivo de tema porque `theme.schema.json` declara
`"additionalProperties": false` em `colors`, e não deveriam mesmo caber — são
acentos de composição, não tokens de marca. Esse arquivo é carregado por
todas as telas autenticadas, **nunca por `/login`**.

Uma exceção controlada de escopo: `static/calendar.js` sobrescreve os
`--color-*` na subárvore do calendário quando o usuário troca de equipe no
seletor. Os valores vêm de `visual_identity`, resolvido no servidor a partir
de `team_ids` — o slug continua não vindo do cliente.

## Fonte única de verdade

```text
design-system/
  platform.json              # tokens neutros + identidade "Handball"/"H"
  themes/
    hm-ime.json               # somente marca do HM-IME + fontes.heading
  schemas/
    theme.schema.json         # contrato documentado de um tema de time

handball/core/design_tokens.py  # lê e valida os dois, sem dependência externa
handball/core/team_theme.py     # API pública (compatível com o código antigo):
                                 #   NEUTRAL_THEME, TEAM_THEMES, team_theme(slug)

scripts/build_design_tokens.py  # gera static/css/tokens.generated.css
static/css/tokens.generated.css # GERADO — não editar à mão
```

Rodar depois de qualquer mudança em `design-system/*.json`:

```powershell
.\.venv\Scripts\python.exe scripts\build_design_tokens.py
```

`tests/test_design_tokens.py::test_generated_css_is_not_stale` chama
`scripts/build_design_tokens.py --check` e falha se alguém esquecer de
regenerar — não existe caminho para o CSS divergir do JSON sem um teste
vermelho.

## Resolução do time ativo (nunca aceita dado do cliente)

```text
AuthSession.team_ids (frozenset[int], calculado em
handball/database/repositories/identity.py::access_context_data a partir de
team_memberships ativas)
        │
        ▼
IdentityService.resolve_active_team_view(context)      # handball/modules/usuarios/service.py
        │  IdentityRepository.get_teams_by_ids(context.team_ids)   # somente leitura, tabela teams
        ▼
team_theme(slug_resolvido_do_banco)                      # handball/core/team_theme.py
        │
        ▼
{"organization": {...}, "team_theme": {...}}  → template (data-theme, data-team)
```

Casos cobertos (nomes conforme a missão de design system) e onde estão
testados em `tests/test_design_tokens.py`:

| Caso | Comportamento | Teste |
|---|---|---|
| A — não autenticado | `/login` nunca carrega `organization`/`team_theme`; `data-theme="neutral"` estático | `test_login_page_has_no_team_branding` |
| B — exatamente um time | resolve o slug real da tabela `teams`, nunca um valor fixo | `test_hub_shows_resolved_team_theme_for_member` |
| C — mais de um time | **provisório**: escolhe o de menor `id`, deterministicamente. Não há seletor de time ativo nem armazenamento de preferência — ver "Caso C" abaixo | não testado (não há hoje nenhum usuário real com dois times) |
| D — sem time (papel só sistêmico) | cai no tema neutro; `organization.display_name == "Handball"`, nunca "HM-IME" | `test_hub_falls_back_to_neutral_for_dev_without_team` |
| E — time sem tema cadastrado ou inativo | `team_theme()` cai no neutro por definição (`TEAM_THEMES.get(slug, NEUTRAL_THEME)`); um aviso técnico é registrado via `logging` (`IdentityService.resolve_active_team_view`) | comportamento de `team_theme()` coberto por `test_team_theme_falls_back_to_neutral_for_unknown_or_absent_slug` |

### Caso C — mais de um time (decisão pendente do proprietário)

Hoje só existe um time (`hm-ime`) no banco, então nenhum usuário real cai
neste caso. A resolução implementada é uma escolha determinística e segura
(menor `id`), não uma adivinhação baseada em query string/cookie/
`localStorage` — mas também não é um seletor de verdade. Duas alternativas,
conforme pedido pela missão:

1. **Provisória (implementada agora, sem migration)**: manter a escolha
   determinística por `id`; adicionar, quando houver um segundo time real,
   um seletor de UI que troque a exibição *dentro da mesma requisição*
   (parâmetro validado no backend contra `context.team_ids`, nunca aceito
   cru), sem persistir a escolha entre sessões.
2. **Definitiva (exige `DB_MIGRATION` separada e autorizada)**: uma coluna
   de preferência (ex.: `users.active_team_id`) ou tabela
   `user_team_preferences`, validada no login/troca contra `team_ids`, com
   índice e FK para `teams(id)`. Não implementada nesta tarefa (regra 13 do
   `AGENTS.md`); proposta para decisão do proprietário quando o segundo time
   for cadastrado de fato.

## Segurança da tematização

- O slug nunca é lido de query string, cookie de cliente ou `localStorage`;
  sempre de `AccessContext.team_ids`, que por sua vez vem de
  `team_memberships` no banco (não de nada enviado pelo navegador).
- `design-system/schemas/theme.schema.json` e a validação em
  `design_tokens.py` recusam `logo_url` fora de `/static/` — nenhuma URL
  externa arbitrária pode virar um tema.
- Nenhum valor de tema é interpolado como HTML: os templates usam apenas
  atributos de texto simples (`class`, `data-team`, `content` de `<meta>`),
  todos autoescapados pelo Jinja2.
- `static/css/tokens.generated.css` é estático, versionado em Git e gerado a
  partir de arquivos igualmente versionados — nenhum CSS vem do banco.

## Estado e pendências (não confundir com "concluído")

### Concluído na Fase 8 — identidade visual unificada (3 de agosto de 2026)

Aplicação do handoff "HM-IME — Identidade Visual Unificada". As três
identidades concorrentes (navy/laranja legado, vermelho HM-IME, bordô do
Playbook) deixaram de existir: há um sistema só.

**Tokens.** `brand_primary` foi de `#D71920` para o vinho institucional
`#82143C` — o único vermelho do time com origem documentada (Manual de
Identidade Visual do IME-USP) e o que leva branco/primária de 5,19:1 para
9,93:1. `text` foi para o carvão `#111111`, `border` para `#E0D6D9`,
`fonts.heading` para Barlow Condensed. Detalhes e razões em
`teams/hm-ime/THEME.md`.

**Fim da paleta legada.** O bloco `:root` de `static/styles.css` era uma
paleta navy/laranja completa (`--navy-900`, `--orange`…) que competia com o
tema do time. Agora cada nome legado é apelido do token equivalente, o que
migrou ~90 regras sem reescrevê-las uma a uma; `--navy-*` e `--orange` foram
removidos e seus usos resolvidos caso a caso. `.topbar` e `.platform-appbar`
viraram o mesmo cabeçalho (fundo carvão, filete da cor do time) — a pendência
registrada na Fase 7 fecha aqui. `.mini-mark` foi apagada.

**Tema do arquivo, não do template.** `formal_name`, `athletics_name`,
`motto` e `achievement` passaram a existir em `TeamVisualIdentity`. O hero do
hub monta o eyebrow, a saudação, o lema e o selo de conquista a partir deles:
um segundo time cadastrado não herda o lema nem os títulos do primeiro.

**Login independente de time.** `/login` deixou de assumir o HM-IME. Tem
controle segmentado Entrar/Criar conta e um assistente de 3 passos (Time →
Elenco → Acesso). O passo 1 lista os times ativos; o passo 2, o elenco livre
*daquele* time. O `team_id` chega do formulário e é tratado como entrada não
confiável: só restringe a lista de atletas aceitáveis, e a conferência é
refeita no servidor (`IdentityService.register_player`). Nenhum tema,
permissão ou vínculo é derivado dele. A tela é a Camada 1 pura — sem
`data-team`, sem logotipo, sem `hm-ime-expressive.css`, com paleta neutra
própria.

**Mobile-first.** Breakpoint único de 760px, `env(safe-area-inset-*)` em tudo
que é fixo ou flutuante, alvos de toque de 44px, sidebar de Presenças virando
bottom nav de 5 abas (Auditoria inclusa). Tabela densa vira cartão sem perder
coluna: Histórico e Auditoria ganham uma lista de cartões alimentada pelo
mesmo laço; Elenco, que tem campo editável, empilha a própria tabela
(`.stacked-table` + `data-label`) para não existirem dois inputs do mesmo
dado. Usuários e Consultas SQL continuam desktop-first por decisão explícita
e mostram aviso e resumo somente-leitura no celular.

**Playbook.** O caminho da pasta entrou na URL (`?folder=<id>`): é linkável,
sobrevive a refresh e o botão Voltar do navegador sobe um nível da árvore em
vez de sair do módulo. Um nó com subpastas mostra linhas de pasta antes dos
conteúdos, e o breadcrumb usa `›` com o nó atual destacado.

**Fontes.** Inter e Barlow Condensed (ambas OFL) auto-hospedadas em
`static/fonts/`, subconjuntos latin e latin-ext. Nada de CDN: o servidor é
particular e precisa funcionar offline. Os arquivos e os três CSS entraram no
shell do service worker (`handball-shell-v13`) — antes nem
`tokens.generated.css` estava lá, então a identidade sumia sem rede.

### Ainda pendente depois da Fase 8

- **Fotografia.** O hero do hub usa `static/hm-ime-hero.jpg` (foto da própria
  equipe). O hero do `/login` continua no gradiente neutro de propósito: a
  foto ali precisa ser genérica de handebol, sem uniforme ou escudo
  identificável, porque a tela serve todos os times. As miniaturas do Playbook
  também seguem sem foto.
- **Cartão de ação de "Seu relatório"** mostra a data do próximo treino em
  aberto, sem hora nem local: `own_attendance` não traz esses campos. Nada foi
  inventado para preencher o espaço.
- `.platform-brand.has-image` ainda tem `/static/hm-ime-logo.jpg` fixo no CSS
  em vez de derivar de `team_theme.logo_url` (pendência herdada da Fase 7).
- `border` sobre `canvas` melhorou com `#E0D6D9`, mas continua abaixo de 3:1.
- Screenshots Playwright e varredura completa de teclado/zoom/leitor de tela
  não foram executados nesta sessão.

### Concluído na Fase 7

Todas as 9 páginas autenticadas (`/app`, `/app/presencas` — CT e jogador,
`/app/estatisticas`, `/app/calendario`, `/app/playbook`, `/app/consultas`,
`/app/admin/usuarios`, `/app/meu-relatorio`) e `/login` agora:

- resolvem `organization`/`team_theme` por
  `IdentityService.resolve_active_team_view(session.to_access_context())` —
  nenhum router importa mais `ORGANIZATION`/`team_theme(ORGANIZATION.slug)`
  diretamente (confirmável com
  `grep -rn "team_theme(ORGANIZATION" handball/`, que não deve retornar
  nada fora de `handball/core/team_theme.py`);
- carregam `static/css/tokens.generated.css` e expõem
  `data-theme`/`data-team` em `<html>`;
- no caso de Calendário e Playbook, a classe `theme-hm-ime` literal foi
  removida do `<body>` — a marca agora só existe via `data-team` dinâmico.

`.calendar-v2` e `.playbook-app` (`static/styles.css`) não duplicam mais
hexadecimais: seus blocos de variável (`--calendar-primary`,
`--playbook-primary` etc.) foram redefinidos para apontar para
`var(--color-brand-primary)` e o resto dos tokens compartilhados, em vez de
manter uma cópia própria. **Efeito visível**: o Playbook, que usava um bordô
próprio (`#7f1d1d`), passou a usar o mesmo vermelho do HM-IME — já
documentado como a correção esperada em
`docs/HM-IME-IDENTIDADE-VISUAL.md` §13.

As 6 páginas que ainda usavam `.mini-mark`/"H" fixo
(`presencas/index.html`, `presencas/player.html`, `estatisticas/index.html`,
`consultas/index.html`, `usuarios/admin.html`, `usuarios/report.html`) agora
incluem `templates/partials/_brand.html` (só o bloco de marca — ícone/nome
do time), reaproveitando `.platform-brand` (já tematizado) em vez do
`.mini-mark` preso ao laranja legado. O resto do cabeçalho dessas páginas
(`top-actions`, botões específicos) não mudou. `.button-primary` e
`.nav-item.active` (usado só em Presenças) também passaram a usar
`var(--color-brand-primary)`/`var(--color-brand-primary-hover)` em vez de
`var(--navy-900)`/`var(--navy-800)`.

### Ainda pendente ao fim da Fase 7 (tudo resolvido na Fase 8, acima)

- `.topbar`/`.topbar-inner` (fundo `rgba(11,31,51,.97)` hardcoded) continuam
  como estavam — só a marca dentro delas foi trocada. Consolidar esse
  cabeçalho com `.platform-appbar` (do hub) é possível trabalho futuro, não
  necessário para o design system ter uma fonte de tokens consistente.
- Outras cores "decorativas" não ligadas à marca (`--orange` em `.eyebrow`,
  acentos de `.metric`, estado "sujo" em `.athlete-card.dirty`, contorno de
  foco global) continuam com o laranja legado — não são a cor de marca da
  Camada 2, então não foram tocadas nesta migração incremental.
- `.platform-brand.has-image` (`static/styles.css`) ainda tem a URL do
  logotipo do HM-IME hardcoded no CSS
  (`background-image: url("/static/hm-ime-logo.jpg")`), não derivada de
  `team_theme.logo_url`. Isso já existia desde que `.platform-brand` foi
  criada para o hub; agora que 8 páginas a usam, um segundo time com
  logotipo próprio precisaria dessa correção (provavelmente uma variável CSS
  `--team-logo-url` setada por atributo `style` controlado, nunca por dado
  de usuário) antes de aparecer visualmente correto. Documentado, não
  corrigido — não há hoje nenhum segundo time com logotipo aprovado.
- Duas ocorrências de `rgba(215, 25, 32, ...)` hardcoded dentro de
  `.calendar-v2` (glow de fundo e outline de foco) não foram convertidas
  para derivar de `--color-brand-primary` (exigiria `color-mix()`, risco de
  compatibilidade para um efeito cosmético) — ver
  `docs/design-system/ACCESSIBILITY.md`. **Resolvido na Fase 8**: passaram a
  usar `color-mix()` com o valor sólido declarado na linha anterior como
  fallback, então navegador sem suporte fica no comportamento antigo em vez
  de perder a regra.
- Screenshots Playwright e varredura completa de teclado/zoom/leitor de tela
  nesses módulos não foram executados nesta sessão.
