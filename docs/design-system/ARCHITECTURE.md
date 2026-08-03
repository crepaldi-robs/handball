# Arquitetura do design system multi-time

| Campo | Valor |
|---|---|
| Data | 1 de agosto de 2026 (fundação) — atualizado com a Fase 7 na mesma data |
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

Playbook e Calendário mantêm namespaces de variável próprios
(`--playbook-*`, `--calendar-*`) porque têm dezenas de regras que os
consomem, mas esses namespaces agora **derivam** dos tokens compartilhados
(`--playbook-primary: var(--color-brand-primary)` etc., em vez de hex
duplicado) — ver "Estado e pendências". Isso preserva a diferenciação de
*conteúdo* de cada módulo (ícone, navegação, densidade) sem duplicar a cor
de marca, exatamente como a Camada 3 exige.

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

### Ainda pendente (fora do escopo desta entrega)

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
  `docs/design-system/ACCESSIBILITY.md`.
- Screenshots Playwright e varredura completa de teclado/zoom/leitor de tela
  nesses módulos (Fase 8 da missão) não foram executados nesta sessão.
