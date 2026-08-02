# Convenções do Handball Design Mirror

Esta biblioteca espelha os componentes compartilhados de uma plataforma
FastAPI + Jinja2 (não React) organizada em três camadas: uma identidade
neutra de plataforma, uma identidade de time por cima dela, e conteúdo de
módulo por cima disso. **Nenhum componente aceita uma prop de cor de
marca.** A cor vem sempre de um atributo no DOM ancestral.

## Aplicar o tema (sem provider)

Não existe `ThemeProvider`. A marca do time é resolvida por CSS puro a
partir de `data-theme`/`data-team` em qualquer elemento ancestral —
normalmente o elemento raiz da composição:

```jsx
<div data-theme="team" data-team="hm-ime">
  <AppBar brand={{ displayName: "HM-IME", monogram: "HM", subtitle: "Calendário" }} />
</div>
```

- `data-team="<slug>"` com um tema cadastrado (hoje só `"hm-ime"`) aplica a
  cor de marca daquele time (`[data-team=hm-ime]` no CSS).
- `data-theme="neutral"` (ou simplesmente nenhum atributo — o `:root`
  já carrega os valores neutros) usa a identidade neutra da plataforma:
  sóbria, sem cor de time. Use isso para telas antes do login ou para
  contas sem vínculo de time.
- Nunca defina cor de marca via prop, `style` inline ou CSS custom
  property direta no componente — o objetivo é que o mesmo componente
  mude de aparência sozinho ao trocar o `data-team` do ancestral.

## Vocabulário de classes

Os componentes já aplicam essas classes internamente — você não as escreve
à mão, mas reconhecê-las ajuda a prever o resultado e a compor variações
que a API não cobrir diretamente:

| Classe | Onde aparece | Uso |
|---|---|---|
| `.button` / `.button-primary` / `.button-danger` / `.button-large` | `Button` | variante e tamanho |
| `.alert` / `.alert-error` / `.alert-success` / `.alert-warning` | `Alert` | estado semântico — nunca dependente só de cor |
| `.module-card` / `.module-card-available` | `ModuleCard` | disponibilidade do módulo (verde = disponível) |
| `.platform-appbar` / `.platform-brand` / `.identity` | `AppBar`, `Brand` | cabeçalho tematizado |
| `.metric` / `.is-active` | `MetricTile` | estado selecionado |
| `.status-badge` / `.online` / `.offline` / `.pending` | `StatusBadge` | indicador de conexão |

## Tokens que importam

- `--color-brand-primary` / `--color-brand-primary-hover` — a única cor que
  muda por time. Tudo que "parece a marca" (botão primário, faixa do app
  bar, ícone de módulo disponível quando não usa `--color-success`) usa
  esses dois tokens.
- `--color-success` / `--color-warning` / `--color-danger` / `--color-info`
  — fundamentos semânticos. **Nunca variam por time** — não proponha um
  componente que os deixe customizáveis.
- `--font-heading` pode variar por time (o HM-IME usa uma condensada para
  títulos esportivos); `--font-interface` nunca varia — é a fonte de toda
  interface operacional.

## Onde está a verdade

Antes de estilizar algo novo, leia `styles.css` (a única folha carregada —
ela importa tokens + `_ds_bundle.css`) e o `<Name>.d.ts` do componente mais
próximo do que você está construindo. Um componente que "quase serve" deve
ser composto (props + children), não reimplementado com `className` cru.

## Exemplo idiomático

```jsx
const { AppBar, Button, StatusBadge, ModuleCard } = window.HandballDesignMirror;

function Hub() {
  return (
    <div data-theme="team" data-team="hm-ime">
      <AppBar
        brand={{ displayName: "HM-IME", monogram: "HM", subtitle: "Calendário" }}
        actions={
          <>
            <StatusBadge variant="online">Online</StatusBadge>
            <Button>Sair</Button>
          </>
        }
      />
      <ModuleCard
        icon="✓"
        status="Disponível"
        available
        title="Presenças"
        description="Confirmações, chamada, histórico, elenco e auditoria."
        href="/app/presencas"
        actionLabel="Abrir módulo"
      />
    </div>
  );
}
```
