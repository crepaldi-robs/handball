# Sincronização com Claude Design

| Campo | Valor |
|---|---|
| Status | **executado** — primeira sincronização concluída |
| Data | 1 de agosto de 2026 |
| Projeto | [HM-IME Design System](https://claude.ai/design/p/adfe9426-00c9-4abc-b36f-43932f8f9dd1) |
| Componentes sincronizados | 8 (Alert, AppBar, Brand, Button, Field, MetricTile, ModuleCard, StatusBadge) |
| Render check | 8/8 renderizam limpo (0 `bad`, 0 `thin`, 0 `variantsIdentical`) |
| Previews avaliados | 8/8 componentes, todas as células na rubrica absoluta = `good` |

## Por que existe `design-mirror/` em vez de sincronizar o app real

`/design-sync` converte uma biblioteca de componentes **React compilada**
(`dist/` + `.d.ts`) — este repositório não tem uma (FastAPI + Jinja2 + CSS
vanilla, sem framework de frontend, por decisão explícita do `AGENTS.md`).
Em vez de inventar componentes que não existem no produto, criei
`design-mirror/`: um pacote npm isolado, **nunca importado pelo app real,
nunca deployado**, que espelha fielmente as classes CSS/estrutura de DOM já
compartilhadas (`.button`, `.platform-appbar`, `.platform-brand`,
`.module-card`, `.alert`, `.metric`, `.status-badge`, campo rotulado) usando
exatamente os mesmos tokens (`design-mirror/src/tokens.generated.css` é uma
cópia automática de `static/css/tokens.generated.css`, nunca editada à mão).

Essa decisão foi tomada com o usuário depois de eu apontar o descompasso —
ver a pergunta e resposta registradas na conversa. O trade-off aceito:
`design-mirror/src/styles.css` é uma **cópia manual** das regras
equivalentes do app real e pode ficar desatualizada se o CSS mudar sem
replicação aqui — ver `.design-sync/NOTES.md`, seção "Re-sync risks".

## O que foi sincronizado

Os 8 componentes cobrem o "casco" compartilhado hoje espalhado por
`templates/partials/_brand.html` + as classes de `static/styles.css` usadas
por `/app` e pelos módulos migrados na Fase 7. Cada preview foi autorado com
2-6 variações reais (texto em português idêntico ao produto, não
placeholder), e pelo menos uma célula por componente sensível à marca
(`Button`, `AppBar`, `Brand`) demonstra a mesma instância mudando de cor
sozinha ao trocar `data-team="hm-ime"` por `data-theme="neutral"` — prova
visual de que a arquitetura de tokens não está acoplada ao HM-IME.

## Limitações registradas (não apresentar como validado)

- Fontes: `Inter`/`Roboto Condensed`/`Bahnschrift Condensed`/`Arial Narrow`
  não são embutidas como `@font-face` — decisão deliberada, o app real
  também depende de fontes do sistema (ver `.design-sync/NOTES.md`).
- `.platform-brand.has-image` no espelho usa uma logo placeholder (SVG
  inline), nunca o `static/hm-ime-logo.jpg` real — esse asset só resolve
  contra a origem do app real.
- Responsividade, teclado e leitor de tela (Fase 8 da missão original) não
  foram varridos — o render check cobre "renderiza sem quebrar", não
  acessibilidade completa.
- Só o "casco" compartilhado foi sincronizado; os módulos com conteúdo
  próprio (Calendário, Playbook, tabelas do Consultas/Admin) não têm
  componente espelhado — ver `docs/design-system/ARCHITECTURE.md` "Ainda
  pendente" para o que falta migrar no app real primeiro.

## Re-sync

Para atualizar depois de mudar tokens ou componentes:

```powershell
# se os tokens mudaram:
.\.venv\Scripts\python.exe scripts\build_design_tokens.py
cd design-mirror && npm run build && cd ..
node .ds-sync/resync.mjs --config .design-sync/config.json `
  --node-modules design-mirror/node_modules --entry design-mirror/dist/index.js `
  --out ds-bundle --remote .design-sync/.cache/remote-sync.json
```

`.design-sync/config.json`, `NOTES.md`, `conventions.md` e `previews/` estão
prontos para commit (ver oferta feita ao usuário nesta sessão) — isso é o
que torna um re-sync futuro rápido e determinístico.
