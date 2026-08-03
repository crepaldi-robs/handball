# Acessibilidade dos tokens visuais

Referência normativa: WCAG 2.2 AA. Este documento cobre o que foi
efetivamente validado nesta entrega (contraste de cor dos tokens) e o que
permanece pendente (o restante da checklist da missão de design system §15,
que depende da migração de módulo a módulo na Fase 7).

## O que está validado e testado

`tests/test_design_tokens.py` calcula a razão de contraste WCAG (luminância
relativa sobre sRGB, fórmula padrão) para cada par de cor dos dois temas
existentes e falha se algum ficar abaixo de 4,5:1 (texto normal, AA):

| Tema | Par | Contraste | Resultado |
|---|---|---:|---|
| neutro | texto sobre canvas | 16,55:1 | AAA |
| neutro | texto sobre surface | 17,93:1 | AAA |
| neutro | texto secundário sobre canvas | 4,59:1 | AA (margem estreita) |
| neutro | branco sobre `brand_primary` | 10,35:1 | AAA |
| neutro | branco sobre `brand_primary_hover` | 14,63:1 | AAA |
| neutro | branco sobre success | 5,25:1 | AA |
| neutro | branco sobre warning | 4,58:1 | AA (margem estreita) |
| neutro | branco sobre danger | 10,02:1 | AAA |
| hm-ime | texto sobre canvas | 16,37:1 | AAA |
| hm-ime | texto sobre surface | 17,93:1 | AAA |
| hm-ime | texto secundário sobre canvas | 5,28:1 | AA |
| hm-ime | branco sobre `brand_primary` | 5,19:1 | AA |
| hm-ime | branco sobre `brand_primary_hover` | 7,91:1 | AAA |
| hm-ime | branco sobre success | 5,25:1 | AA |
| hm-ime | branco sobre warning | 4,58:1 | AA (margem estreita) |
| hm-ime | branco sobre danger | 10,02:1 | AAA |
| ambos | branco sobre info (`#1D4ED8`) | 6,70:1 | AAA |

Os valores de `success`/`warning`/`danger`/`info` são idênticos nos dois
temas porque são fundamentos da plataforma, não da marca (ver
`design-system/schemas/theme.schema.json` — um tema de time não pode
redefini-los). `info` (`#1D4ED8`) é uma escolha de engenharia da plataforma,
não uma cor de marca de nenhum time; foi escolhida por já atender AA/AAA
contra branco.

## Limitação conhecida e documentada (não corrigida nesta entrega)

`--color-border` contra `--color-canvas` fica em ~1,2:1 nos dois temas
(`#DDE2E7` sobre `#F4F6F8` no neutro; `#E6DEDB` sobre `#F7F4F2` no HM-IME).
Isso não afeta texto (que não depende dessa combinação), mas fica abaixo do
3:1 exigido pelo WCAG 2.2 SC 1.4.11 (Non-text Contrast) para um elemento que
dependesse *somente* da borda para comunicar seu limite — por exemplo um
campo de formulário sem sombra nem mudança de fundo no foco. Hoje nenhum
componente do produto depende só da borda (cards e campos têm sombra e/ou
mudança de fundo em hover/foco), mas isso deve ser resolvido na fonte
(`design-system/*.json`) antes de qualquer novo componente que dependa
exclusivamente do contorno para ser percebido. Registrado aqui em vez de
alterado sem aprovação, conforme a missão pede para casos em que uma cor não
passa em determinado uso.

## O que ainda não foi validado (Fase 8, pendente)

- Navegação por teclado, ordem de foco e leitor de tela nos módulos ainda
  não migrados (Presenças, Calendário, Playbook, Estatísticas, Consultas,
  Administração) — inalterados nesta entrega.
- Zoom a 200% e largura de 320px nesses mesmos módulos.
- `prefers-reduced-motion` já é respeitado globalmente
  (`static/styles.css`, regra existente antes desta entrega, não tocada).
- Screenshots comparativos entre temas (Playwright) — não executados nesta
  sessão; nenhum resultado de teste visual deve ser declarado sem essa
  execução real.
