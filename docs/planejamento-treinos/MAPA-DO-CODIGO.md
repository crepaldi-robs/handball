# Mapa verificado do checkout

Caminhos relativos à raiz `registrador-presencas`; referências por símbolo resistem a deslocamento de linhas. Inspeção estática, sem banco de instalação.

| Recurso | Arquivos/símbolos verificados | Implicação |
|---|---|---|
| Ranking | `handball/modules/elenco/ranking.py`: RANK_SCOPES, apply_answer, choose_representative, question_text | LINE/GOALKEEPER; BETTER/WORSE/EQUAL; busca binária por camadas com empates. Pergunta atual genérica “Quem é melhor em quadra”. |
| API de ranking | `handball/modules/elenco/router.py`, `schemas.py`, `service.py`; RankingSessionCreate, RankingAnswer | POST `/api/v1/elenco/ranking/sessions`, POST `.../{session_id}/answers`, DELETE `.../{session_id}`; refino posicional existente. |
| Ranking persistido | `handball/database/repositories/roster.py`, `handball/database/migrations.py` | Camadas, sessões e comparações existentes; novas dimensões exigem revisão formal de contrato. |
| Posições | `handball/core/positions.py`; MemberCreate/MemberUpdate em `elenco/schemas.py` | GOL/PE/ME/C/MD/PD/PV; M1/M2/M3/AVANCADO. Lateralidade não localizada em handball/static/templates. |
| Motor | `handball/modules/presencas/planner.py`: enumerate_assignments, _full_scrimmages, _layer_balance, build_coach_report | Confirmados, posição do treino ou perfil, papéis, cobertura 6x0/5x1 e goleiros. |
| Limitação | `_layer_balance`, `_full_scrimmages` | Soma ordinal+1; não avaliados sem peso. Busca limitada; prioriza cobertura, penalidade posicional e camada. Não é otimização global nem ataque/defesa independente. |
| Mensagem/painel | `handball/modules/presencas/service.py`, `planner.py:render_coach_report`, `static/coach-report.js` | Serviço monta coach_report e texto dos registros; painel usado por chamada e hub. Texto futuro revisado deve vir do snapshot. |
| Presença | `handball/modules/presencas/domain.py`: CONFIRMED_CODES; `router.py` | CONFIRMED_EARLY/LATE; GET `/api/v1/sessions/{session_id}` é sessão de presença, não sessão Playbook. |
| Exercícios | `handball/modules/playbook/schemas.py`: ContentInput, ExerciseRoleInput, ExerciseVariantInput | Papéis ATTACK/DEFENSE/GOALKEEPER/NEUTRAL, posições e quantidades. `steps` é texto, não timeline. |
| Planos/sessões | Mesmo schemas: IndependentPlanInput, PlaybookSeriesInput, PlaybookSessionInput | Plano independente, série, sessão, local_overrides e vínculo opcional com calendário. |
| Rotas | `handball/modules/playbook/router.py` | GET/POST `/api/v1/playbook/plans`; GET/PUT `.../plans/{plan_id}`; GET/POST `/api/v1/playbook/sessions`; GET/PUT `.../sessions/{session_id}`; POST `.../sessions/{session_id}/revisions/{revision_id}/restore`. |
| Compatibilidade | Mesmo router: GET/PUT `/api/v1/playbook/events/{event_id}/plan` | Adaptadores por evento devem continuar. |
| Histórico | `handball/database/repositories/playbook.py`: _v10_session_snapshot, _v10_write_session_revision, save_session, restore_session_revision | Snapshots/revisões existem. save_session atualiza por id; entrada não exige revisão esperada. Histórico não comprova proteção de concorrência. |
| Viabilidade | `handball/modules/playbook/service.py`: integração com exercise_fit | Reutiliza perfis de confirmados. Evitar cálculo paralelo divergente no JS. |
| Interface | `templates/playbook/index.html`, `static/playbook.js`, `static/playbook-player.js`, `static/elenco.js`, `templates/elenco/index.html` | Biblioteca/editor e interface jogador; vídeo anexado não é timeline nem geração automática. |
| Autorização | `handball/core/authorization.py` e router Playbook | PLAYBOOK_READ/PLAYBOOK_MANAGE; preservar time/CSRF, revisar proteção específica das avaliações. |
| Design | `docs/design-system/README.md`, `ARCHITECTURE.md`, `ACCESSIBILITY.md`, `static/css/tokens.generated.css` | Reusar temas/tokens; documento registra limitações, não conformidade integral. |
| Testes | `tests/test_roster_ranking.py`, `tests/test_tactical_planner.py`, `tests/test_playbook.py` | Ampliar cenários existentes. |
| Operação | `AGENTS.md`, `docs/SITE-INTEGRATION-CONTRACT.md`, `scripts/test.ps1`, `handball/database/contracts.py`, `guard.py`, `maintenance.py` | Gates de persistência e atualização obrigatórios. |

Não foram identificados nos módulos inspecionados contratos tipados de prancheta com ocupantes/fixações, timeline ou exportador de vídeo. Essa conclusão não cobre artefatos externos ao app.

## Arquivos futuros propostos, não implementados

Avaliações ficam no Elenco; integração de propostas parte de `presencas/planner.py`. Considerar `handball/modules/playbook/composition.py` para domínio puro da composição e `static/playbook-board.js` para interação, sem framework novo por padrão. Entrada em `playbook/schemas.py`, coordenação em serviço/repositório existentes. Nomes finais dependem da inspeção na implementação. Novos arquivos de runtime exigem revisar allowlists.
