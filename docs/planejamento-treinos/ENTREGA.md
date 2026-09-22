# Fases, aceite e governança

## Sequência

| Fase | Entrega | Dependência/classificação |
|---|---|---|
| 0 | Decisões abertas, contratos e protótipo manual sintético | Documentação/protótipo APP_ONLY sem gravação instalada. |
| 1 | Avaliações habituais independentes, legado e cobertura | Persistência nova é DB_MIGRATION, com autorização própria. |
| 2 | Composição manual/assistida, fixações, dois modos e diagnósticos | Política aprovada para sugestão definitiva. |
| 3 | Prancheta, revisão e mensagem coerentes; concorrência | Primeira fatia útil conecta participantes→revisão→mensagem. |
| 4 | Modelo/instância temporal e reprodução determinística | IDs/slots/coordenadas previstos desde V1. |
| 5 | Vídeo automático da revisão escolhida | Timeline, orçamento, codec e validação Windows. |
| 6 | Rotação automática, metas de minutos e atributos adicionais | Decisão de prioridades e demanda real; não bloqueia prancheta inicial. |

Separar fases não permite omitir modelo/instância, versões ou dimensões na fundação. Reservar interfaces também não justifica construir todo o vídeo antes de entregar composição útil.

## Persistência e compatibilidade

APP_ONLY: documentos, apresentação, funções puras e código compatível com contratos atuais, sem DDL/seed/reescrita. DB_MIGRATION: dimensões persistentes novas, schema/constraints, contrato de JSON persistido e conversão de dados. Coluna JSON existente e feature flag não dispensam governança. Preparar migração em código e testá-la em fixture descartável requer que a futura tarefa autorize esse escopo; esta entrega não autoriza.

Manutenção futura autorizada: release compatível separada da aplicação ao banco; plano somente leitura, backup consistente, hash do plano validado, aplicação explícita, ledger e pós-condições. Nunca bootstrap/seed no startup. Não deduzir versão instalada da migration mais recente no checkout. Cliente legado mantém fluxos antigos ou recebe bloqueio claro sem perda; preservar adaptadores por evento. LINE não vira ATTACK/DEFENSE automaticamente.

Sem autorização persistente, entregar somente parte independente permitida e declarar fluxo incompleto. Não improvisar arquivo paralelo/localStorage como banco definitivo. Rollback de código não é downgrade de schema; recuperação de dados é decisão separada.

## Aceite futuro

| Cenário | Evidência |
|---|---|
| Avaliação | Pergunta habitual; atualizar ataque não muda defesa; “não sei” não cria nota. |
| Legado | LINE preservado; novas dimensões desconhecidas até avaliação. |
| Escalas | Nenhum cálculo iguala capacidade ofensiva e defensiva; fortes/fracos em ambas permitidos. |
| Cobertura | null em API/UI, sem imputação ou certificação indevida. |
| Modos | Equilibrado inicialmente selecionado; igual hierarquia/acesso/destaque em bloco e coletivo; modo ativo na mensagem e quadra. |
| Direcionado | Foco ataque forte versus defesa forte, inverso visível; não reinterpretado como times desiguais. |
| Fixações | Mantidas ao recalcular; conflitos resolvidos explicitamente. |
| Busca | Truncamento declarado, resultado repetível para entrada/método iguais. |
| Elegibilidade | Sem duplicidade simultânea; exceções rastreáveis. |
| Goleiros | Zero/um/dois/híbrido; sem soma indevida à defesa de linha. |
| Participação | Banco visível, tempo previsto separado do real, prioridade não inventada. |
| Presença | Planejamento não modifica confirmação/presença; falta invalida snapshot explicitamente. |
| Edição | Clique substitui, drag reposiciona; teclado equivalente e undo/redo. |
| Revisão | Mensagem/quadra derivadas da mesma revisão, inclusive após troca. |
| Concorrência | Dois clientes, revisão antiga, retry e timeout sem perda/duplicação. |
| Segurança | Escopo time/CT; ranks ausentes de respostas/exportações para atletas. |
| Compatibilidade | Fixtures novas/legadas e falhas transacionais; nunca banco pessoal. |
| UX | Desktop/celular/tablet, WebKit, zoom/teclado e movimento reduzido. |
| Timeline | Seek/replay determinísticos, posse/passe/finalização consistentes. |
| Vídeo | Mesma revisão/timeline, duração/formato corretos; cancelar não corrompe sessão. |

## Verificação futura

Na raiz do app, PowerShell 7, sem CMD; testes sintéticos e bancos temporários:

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance handball tests
```

Iteração específica: `tests/test_roster_ranking.py`, `tests/test_tactical_planner.py`, `tests/test_playbook.py`. Suíte exigida antes de concluir implementação. WebKit quando disponível; reportar ambiente indisponível separadamente de falha do produto. Novos assets exigem revisão das allowlists e cache/PWA, sem tocar serviço instalado.

Verificações desta documentação ficam em [VERIFICACAO.md](VERIFICACAO.md). Critério futuro listado não é critério aprovado.
