# Design system multi-time — índice

Leia nesta ordem:

1. [`AUDIT.md`](AUDIT.md) — diagnóstico do estado anterior a esta entrega
   (Fase 1). Não reflete mais o código atual em tudo (o hub e o login já
   foram migrados), mas continua sendo o registro do que motivou cada
   decisão de arquitetura.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — as três camadas, a fonte única de
   tokens, a resolução de time ativo por sessão e o que ainda está
   pendente.
3. [`ACCESSIBILITY.md`](ACCESSIBILITY.md) — contraste validado por teste
   automatizado e limitações conhecidas.
4. [`DESIGN-SYNC.md`](DESIGN-SYNC.md) — estado da sincronização com Claude
   Design (pendente de execução manual nesta sessão).
5. [`teams/hm-ime/RESEARCH.md`](teams/hm-ime/RESEARCH.md) — evidências que
   fundamentam o tema do HM-IME.
6. [`teams/hm-ime/THEME.md`](teams/hm-ime/THEME.md) — os tokens do HM-IME e
   como atualizá-los.

Regras normativas (não duplicadas aqui): `AGENTS.md` na raiz do repositório,
`docs/SITE-INTEGRATION-CONTRACT.md`.

## Como cadastrar um novo time

1. Reunir os insumos do proprietário (nome, atlética, Instagram oficial,
   logotipo aprovado) no formato descrito na missão original (contrato
   `team:` com `slug`, `display_name`, `formal_name`, `athletics_name`,
   `approved_assets`).
2. Pesquisar fontes oficiais seguindo a hierarquia de evidências (ver
   `teams/hm-ime/RESEARCH.md` como exemplo de formato) e registrar em
   `docs/design-system/teams/<slug>/RESEARCH.md`. Não usar scraping
   agressivo, conta privada ou captura de tela para reconstruir um escudo.
3. Criar `design-system/themes/<slug>.json` só com os campos permitidos por
   `design-system/schemas/theme.schema.json` (marca + `fonts.heading`;
   nunca `success`/`warning`/`danger`/`info`).
4. Rodar `scripts/build_design_tokens.py` e
   `pytest tests/test_design_tokens.py` — o teste de contraste roda
   automaticamente contra o novo tema assim que ele existir (adicionar o
   par ao `@pytest.mark.parametrize` de
   `test_theme_color_pairs_meet_wcag_aa_for_normal_text`).
5. Cadastrar o time de verdade no banco (rota administrativa de times, DEV)
   — isso não é uma migration; a tabela `teams` já existe desde o schema v2.
6. Obter aprovação humana do tema antes de qualquer usuário real ver essa
   identidade.
7. Documentar em `docs/design-system/teams/<slug>/THEME.md`.

Nenhuma pesquisa automática publica uma identidade sem essa aprovação
humana explícita.
