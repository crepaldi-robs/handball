# Tema — HM-IME

Fonte de verdade: `design-system/themes/hm-ime.json` (validado por
`handball/core/design_tokens.py`, contrato em
`design-system/schemas/theme.schema.json`). Não copie estes valores para
CSS ou Python manualmente — regenere com
`scripts/build_design_tokens.py` sempre que o JSON mudar.

| Token | Valor | Papel |
|---|---:|---|
| `brand_primary` | `#D71920` | ação principal, seleção, destaque da marca |
| `brand_primary_hover` | `#A40E17` | hover, estado pressionado |
| `brand_on_primary` | `#FFFFFF` | texto/ícone sobre `brand_primary` |
| `canvas` | `#F7F4F2` | fundo geral branco quente |
| `surface` | `#FFFFFF` | cartões, formulários, diálogos |
| `text` | `#171717` | texto principal, app bar |
| `text_muted` | `#6B6464` | texto secundário |
| `border` | `#E6DEDB` | bordas e divisores |
| `focus` | `rgba(215, 25, 32, .4)` | anel de foco visível |
| `fonts.heading` | `"Roboto Condensed", "Bahnschrift Condensed", "Arial Narrow", sans-serif` | títulos esportivos (Calendário, capas) — nunca texto de formulário |

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

Ver `docs/design-system/ACCESSIBILITY.md`. Resumo: todo par
texto/fundo do HM-IME passa AA (o mais próximo do limite é branco sobre
`brand_primary`, 5,19:1). `border` sobre `canvas` fica em ~1,2:1 — limitação
conhecida, documentada, não corrigida nesta entrega (nenhum componente
depende hoje só da borda para ser percebido).

## Como este tema é aplicado

`/app` (hub) é a única tela migrada que já resolve este tema pela sessão do
usuário (`IdentityService.resolve_active_team_view`, nunca por um slug fixo
ou enviado pelo cliente). Um usuário sem vínculo com o time HM-IME nunca vê
este tema — ver Casos D/E em `docs/design-system/ARCHITECTURE.md`.

Calendário e Playbook ainda não consomem este arquivo: continuam com
paletas próprias (`--calendar-*`, `--playbook-*`) e a classe `theme-hm-ime`
escrita literalmente no HTML. Migrá-los faz parte da Fase 7 (ver
`docs/design-system/ARCHITECTURE.md` — "Estado e pendências").

## Como atualizar

1. Editar `design-system/themes/hm-ime.json` (só os campos permitidos pelo
   schema).
2. Rodar `.\.venv\Scripts\python.exe scripts\build_design_tokens.py`.
3. Rodar `.\.venv\Scripts\python.exe -m pytest tests/test_design_tokens.py`
   — o teste de contraste e o de artefato desatualizado pegam a maioria dos
   erros automaticamente.
4. Validar visualmente `/app` autenticado como um membro do HM-IME.
