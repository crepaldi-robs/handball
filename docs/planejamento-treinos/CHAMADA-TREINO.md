# Chamada → treino do dia

Decisões da conversa de 22–23/09/2026 com o usuário e o que foi implementado
a partir delas. Completa [DECISOES.md](DECISOES.md); quando divergir, este
arquivo registra a decisão mais recente.

## Princípio

O app é para quem está na quadra. Some da mensagem e da tela principal tudo
que não muda o que acontece no treino. Nada é obrigatório: faltou dado, a
parte correspondente simplesmente não aparece.

## Decidido e implementado

| Decisão | Onde está |
|---|---|
| **Exercícios de hoje**: botão na chamada abre a biblioteca, a CT marca, ordena, põe minutos e pode incluir o coletivo sem cadastrar nada. | `static/today-plan.js`, `PUT /api/v1/playbook/events/{id}/today` |
| **Treino ≠ coletivo.** Exercício = posições com filas; coletivo = times. | `handball/modules/presencas/training_day.py` |
| **Filas**: todo confirmado entra em alguma fila; não existe "fora do exercício". | `build_queues` |
| **Encaixe clássico** para quem não joga a posição pedida, desempate pela hierarquia (a mais forte escolhe primeiro). | `ATTACK_FALLBACK`, `DEFENSE_FALLBACK` |
| **Rodízio no sentido horário** por padrão. | `CLOCKWISE_ORDER` |
| **Filas não se equilibram em tamanho.** O aviso "Só X em Y" mostra a fila sem rodízio. | `_queue_alerts` |
| **Goleiro em exercício sem gol**: trabalho à parte. | `build_queues` |
| **Coletivo = ataque forte × defesa forte** por padrão: Time A com o melhor ataque, Time B com a melhor defesa; Equilibrado continua disponível na prancheta. | `build_directed_scrimmage`, `playbook/composition.py` |
| **Prancheta começa com a sugestão**; o que a CT fixa nunca muda. | `suggest_assignments`, botão "Sugerir de novo" |
| **Quem vê o quê**: CT com planejamento e controle completos; atleta vê só o planejamento final do time (conteúdos publicados, sem camadas, notas ou avisos). | `GET /api/v1/me/training-plan`, `static/player-plan.js` |
| **Mensagem enxuta**: roteiro com horário, filas, times e no máximo dois alertas. Viabilidade, robustez, combinações e cadastros incompletos saíram da mensagem e ficaram em "Análise técnica da CT", recolhida. | `render_training_message` |

## Entrevista sobre ataque × defesa (respostas de 23/09/2026)

1. **A hierarquia de Linha vira a de ataque.** O código continua `LINE` (sem
   converter dados); a tela mostra "Ataque".
2. **Defesa começa com todo mundo "não avaliado".** Nada é copiado da linha.
3. **Geral primeiro, posição depois.** Com elenco pequeno, uma ordem geral de
   defesa distribuída por posição na hora de montar o treino faz mais sentido
   que um ranking por posição. Por isso a defesa não tem refino por posição.
4. Não avaliado entra **depois** dos avaliados, sem contar como fraco.
5. Nível não importa nas filas; **só no coletivo**.
6. Rodízio no **sentido horário**.
7. Tabela de encaixe abaixo aprovada; hierarquia desempata.
8. Filas **não** se equilibram em tamanho.
9. Goleiro sem gol no exercício: **trabalho à parte**.
10. Ataque forte × defesa forte **vira o padrão** no coletivo.
11. Formato (a): Time A melhor ataque, Time B melhor defesa.
12. Modelos iniciais de jogada: catálogo do `PRODUCT-BACKLOG.md` contra 6x0.

### Encaixe clássico

| Joga | 1ª opção | 2ª | 3ª |
|---|---|---|---|
| PE | PD | ME | PV |
| PD | PE | MD | PV |
| ME | MD | C | PE |
| MD | ME | C | PD |
| C | ME | MD | PV |
| PV | C | ME / MD | pontas |
| M1 | M2 | M3 | — |
| M2 | M1 / M3 | AVANÇADO | — |
| M3 | AVANÇADO | M2 | — |
| AVANÇADO | M3 | M2 | — |

Quem não tem nenhuma posição próxima entra na fila mais curta, marcado como
"sem posição".

### Sentido horário (interpretação a confirmar em quadra)

Visto de cima com o gol no alto: ponta direita → meia direita → central →
meia esquerda → ponta esquerda → pivô → defesa → volta para a próxima fila.
Se o time gira ao contrário, basta inverter `CLOCKWISE_ORDER`.

## Coletivo ataque × defesa: como a sugestão decide

- Posição domina: primeiro quem joga a posição, depois o encaixe clássico.
- Dentro disso, maximiza a força de **ataque** no Time A e de **defesa** no
  Time B, cada uma na sua escala (normalizada entre os confirmados). Ataque e
  defesa nunca são somados nem comparados entre si.
- O melhor goleiro vai para o Time B (defesa forte); com um só, ele reveza.
- Quem sobra vai para o banco do time em que rende mais.
- Não avaliados aparecem num aviso só para a CT.

## Banco de dados

A hierarquia de defesa e as jogadas desenhadas usam a migração **v15**
(`defense_hierarchy_and_play_diagrams`). Ela reconstrói as quatro tabelas
de hierarquia para aceitar o escopo `DEFENSE` (procedimento oficial do
SQLite, com `foreign_key_check` ao final, sem perder camadas, refinos nem
comparações) e cria `playbook_play_diagrams` com histórico append-only.

Aplicar só em janela `DB_MIGRATION` autorizada, com backup, pelo comando
canônico de `docs/HANDBALL-OPERATIONS.md` §5.5. Até lá, a instalação v14
continua funcionando: o Elenco mostra só ataque e goleiros, e as jogadas
aparecem como "dependem da manutenção v15". O roteiro, as filas, a mensagem
enxuta e a prancheta com sugestão funcionam na v14.

## Em aberto

- Conferir em quadra o sentido do rodízio.
- As medidas da IHF foram tiradas de resumos da Regra 1; conferir no PDF
  oficial.
- WebKit não estava disponível no ambiente de desenvolvimento; a PWA foi
  conferida em Chromium.
