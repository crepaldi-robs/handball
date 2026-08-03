# Tema — HM-IME

Fonte de verdade: `design-system/themes/hm-ime.json` (validado por
`handball/core/design_tokens.py`, contrato em
`design-system/schemas/theme.schema.json`). Não copie estes valores para
CSS ou Python manualmente — regenere com
`scripts/build_design_tokens.py` sempre que o JSON mudar.

| Token | Valor | Papel |
|---|---:|---|
| `brand_primary` | `#82143C` | ação principal, seleção, destaque da marca |
| `brand_primary_hover` | `#5E0B22` | hover, estado pressionado |
| `brand_on_primary` | `#FFFFFF` | texto/ícone sobre `brand_primary` |
| `canvas` | `#F7F4F2` | fundo geral branco quente |
| `surface` | `#FFFFFF` | cartões, formulários, diálogos |
| `text` | `#111111` | texto principal, app bar |
| `text_muted` | `#6B6464` | texto secundário |
| `border` | `#E0D6D9` | bordas e divisores |
| `focus` | `rgba(130, 20, 60, 0.4)` | anel de foco visível |
| `fonts.heading` | `"Barlow Condensed", "Roboto Condensed", "Bahnschrift Condensed", "Arial Narrow", sans-serif` | títulos esportivos (Calendário, capas) — nunca texto de formulário |

## Por que vinho `#82143C` e não o vermelho `#D71920`

Trocado em 3 de agosto de 2026, conforme o handoff de identidade visual
unificada (`docs/design-system/teams/hm-ime/RESEARCH.md`):

- é o único vermelho do time com **origem documentada** — Manual de Identidade
  Visual do IME-USP, RGB 130/20/60. O `#D71920` anterior vinha do feed, sem
  fonte;
- **contraste melhor**: branco sobre `#82143C` dá 9,93:1, contra 5,19:1 do
  `#D71920` — que era o par mais apertado de todo o tema;
- distingue o handebol da AAAMAT sem perder o endosso da atlética.

`text` foi de `#171717` para o carvão `#111111` (17,24:1 sobre o off-white) e
`border` de `#E6DEDB` para `#E0D6D9`, escurecendo levemente um par
borda/canvas que estava em ~1,2:1. `fonts.heading` passou a pedir Barlow
Condensed primeiro, mantendo Roboto Condensed como fallback.

## Acentos que não cabem neste arquivo

`design-system/schemas/theme.schema.json` declara `"additionalProperties":
false` em `colors`, então dourado, vermelho esportivo e azul institucional
**não podem** entrar aqui — são acentos de Camada 3 (módulo), definidos em
`static/css/hm-ime-expressive.css`, carregado depois de
`tokens.generated.css`.

| Var | Valor | Uso | Regra |
|---|---:|---|---|
| `--hm-gold` | `#E6AF3C` | conquista, título, final | máx. 10% da composição; **nunca texto branco sobre ele** (1,99:1, reprovado) — só carvão (9,50:1) ou vinho (5,00:1) |
| `--hm-sport-red` | `#B5122B` | energia, placar, detalhe | não substitui `brand_primary` |
| `--hm-wine-deep` | `#5E0B22` | sobreposição em foto, peça solene | — |
| `--hm-institutional-blue` | `#0064A0` | co-branding IME/USP | só em aplicação institucional |

`success` (`#0F7B5A`), `warning` (`#B45F06`), `danger` (`#7F1D1D`) e `info`
(`#1D4ED8`) **não** aparecem neste arquivo — são fundamentos herdados de
`design-system/platform.json` e um tema de time não pode redefini-los
(`handball/core/design_tokens.py` recusa a tentativa).

Identidade complementar (não é cor, mas faz parte do tema resolvido em
`handball/core/team_theme.py::TeamVisualIdentity`):

| Campo | Valor |
|---|---|
| `slug` | `hm-ime` |
| `display_name` | HM-IME |
| `formal_name` | Handebol Masculino IME-USP |
| `athletics_name` | AAAMAT |
| `monogram` | HM |
| `logo_url` | `/static/hm-ime-logo.jpg` |

## Contraste validado

Ver `docs/design-system/ACCESSIBILITY.md`. Resumo: todo par texto/fundo do
HM-IME passa AA com folga depois da troca para o vinho.

| Par | Razão |
|---|---:|
| branco / `brand_primary` (`#82143C`) | 9,93:1 |
| branco / `brand_primary_hover` (`#5E0B22`) | 13,58:1 |
| `text` (`#111111`) / `canvas` (`#F7F4F2`) | 17,24:1 |
| `text` / `--hm-gold` | 9,50:1 |
| `brand_primary` / `--hm-gold` | 5,00:1 |
| branco / `--hm-sport-red` (`#B5122B`) | 6,80:1 |
| **branco / `--hm-gold`** | **1,99:1 — reprovado, proibido** |

`border` sobre `canvas` melhorou com `#E0D6D9`, mas continua abaixo de 3:1 —
limitação conhecida e documentada; nenhum componente depende só da borda para
ser percebido.

## Como este tema é aplicado

Todas as telas autenticadas resolvem este tema pela sessão do usuário
(`IdentityService.resolve_active_team_view`, nunca por um slug fixo ou
enviado pelo cliente) e expõem `data-theme`/`data-team` em `<html>`. Um
usuário sem vínculo com o time HM-IME nunca vê este tema — ver Casos D/E em
`docs/design-system/ARCHITECTURE.md`. `/login` é deliberadamente neutro.

Calendário e Playbook não têm mais paleta própria: os namespaces
`--calendar-*` e `--playbook-*` foram removidos e as regras consomem os
tokens compartilhados diretamente.

## Como atualizar

1. Editar `design-system/themes/hm-ime.json` (só os campos permitidos pelo
   schema).
2. Rodar `.\.venv\Scripts\python.exe scripts\build_design_tokens.py`.
3. Rodar `.\.venv\Scripts\python.exe -m pytest tests/test_design_tokens.py`
   — o teste de contraste e o de artefato desatualizado pegam a maioria dos
   erros automaticamente.
4. Validar visualmente `/app` autenticado como um membro do HM-IME.
