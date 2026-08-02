# design-mirror

Espelho React/TypeScript **só para o Claude Design** (`/design-sync`). Não é
importado pelo app real, não é buildado pelo servidor, não é deployado — o
produto de verdade é FastAPI + Jinja2 + CSS/JS vanilla, servido por
`handball/application.py`, sem framework de frontend (ver `AGENTS.md` na raiz
do repositório).

## Por que isso existe

O `/design-sync` só sabe sincronizar uma biblioteca de componentes React
compilada (`dist/` + `.d.ts`). Este projeto existe para dar a ele algo real
para sincronizar, espelhando fielmente os componentes compartilhados que já
existem como classes CSS + `templates/partials/` no app real — mesmo nome de
classe, mesma estrutura de DOM, mesmos tokens (`--color-*`).

## Fonte de verdade

Os tokens (`src/tokens.generated.css`) são copiados de
`../static/css/tokens.generated.css` pelo script `scripts/copy-tokens.mjs`
(rodado automaticamente antes do build) — nunca editados aqui. Mudar uma cor
significa editar `../design-system/*.json` e rodar
`../scripts/build_design_tokens.py`, não este diretório.

As classes CSS em `src/styles.css` são uma cópia das regras equivalentes em
`../static/styles.css` (`.button`, `.platform-brand`, `.module-card` etc.).
Se o CSS real mudar, esta cópia pode ficar desatualizada — ver
`.design-sync/NOTES.md` na raiz do repositório, seção "Re-sync risks".

## Build

```powershell
npm install
npm run build
```

Gera `dist/index.js` + `dist/index.d.ts`, consumidos por
`.ds-sync/package-build.mjs` (script do skill `/design-sync`).
