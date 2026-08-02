# Notas do /design-sync

## Origem deste repositório de sync

`design-mirror/` é um espelho React/TypeScript criado **só** para alimentar
o `/design-sync` — o produto real (`registrador-presencas`) é FastAPI +
Jinja2 + CSS/JS vanilla, sem framework de frontend, por decisão arquitetural
explícita (`AGENTS.md` na raiz do repositório). `design-mirror/` nunca é
importado pelo app real, nunca é buildado pelo servidor, nunca é deployado.

## `[FONT_MISSING]` — substitutos aceitos (não é uma lacuna a corrigir)

`package-validate.mjs` reporta que "Inter", "Roboto Condensed",
"Bahnschrift Condensed" e "Arial Narrow" são referenciadas por
`--font-interface`/`--font-heading` mas nenhum `@font-face` as embute. Isso é
**intencional e fiel ao produto real**: `static/styles.css` do app real
também não embute nenhuma dessas fontes como webfont — ele depende da fonte
já estar instalada no sistema operacional, com fallback gracioso (a pilha
completa é `Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe
UI", sans-serif`; "Bahnschrift" já vem pré-instalada no Windows 10+, ver
`docs/design-system/teams/hm-ime/RESEARCH.md`). Embutir essas fontes aqui
tornaria o espelho **mais** completo que o produto real, o que violaria o
princípio de "espelhar o que já existe". Substitutos de sistema aceitos
deliberadamente — não é uma pendência.

## Re-sync risks

- **`design-mirror/src/styles.css` é uma cópia manual**, não gerada, de
  regras equivalentes em `../static/styles.css`. Se o CSS real mudar
  (`.button`, `.platform-brand`, `.module-card`, `.alert`, `.metric`,
  `.status-badge`, campos de formulário), esta cópia pode ficar
  desatualizada silenciosamente. Não há teste automatizado comparando os
  dois arquivos — checar manualmente antes de um re-sync se `static/styles.css`
  tiver mudado alguma dessas regras.
- `design-mirror/src/tokens.generated.css` É gerado automaticamente
  (`scripts/copy-tokens.mjs`, rodado no `prebuild`) a partir de
  `../static/css/tokens.generated.css` — este arquivo nunca fica
  desatualizado por conta própria, só precisa que `npm run build` rode de
  novo depois de qualquer mudança em `design-system/*.json`.
- Só existe um time real (`hm-ime`) hoje. Quando um segundo time for
  cadastrado com tema próprio (`design-system/themes/<slug>.json`), os
  previews podem ganhar uma variante `data-team="<slug>"` para provar que o
  componente muda de cor sozinho — hoje os previews só demonstram
  `hm-ime` e `neutral`.
- `.platform-brand.has-image` no espelho usa `--brand-logo-url` (uma CSS
  custom property setada via `style` no componente `Brand`) em vez do
  `background-image: url("/static/hm-ime-logo.jpg")` hardcoded que o app
  real ainda tem (ver `docs/design-system/ARCHITECTURE.md` — "Ainda
  pendente"). Isso é uma correção **só no espelho**; o app real ainda
  precisa dessa correção separadamente se um segundo time com logotipo
  aparecer.
- Nenhum toolchain version foi pinado além do que está em
  `design-mirror/package.json` (`^` ranges) — um re-sync futuro pode puxar
  versões mais novas de `react`/`tsup`/`typescript`.
