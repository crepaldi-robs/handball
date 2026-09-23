# Decisões e pontos cegos

## Confirmado

| Tema | Decisão |
|---|---|
| Avaliação | Ataque e defesa independentes; nível habitual ao longo dos treinos. |
| Coleta | Preservar perguntas/comparações e ranks, orientando sobre desempenho médio habitual. |
| Não avaliado | Desconhecido, nunca zero ou pior camada. |
| Escalas | Não presumir anticorrelação nem equivalência numérica entre ataque e defesa. |
| Equilibrado | Aproximar força ofensiva entre equipes e força defensiva entre equipes; examinar ambos os sentidos. |
| Direcionado | Ataque forte contra defesa forte; confronto inverso secundário e visível. |
| Disponibilidade | Ambos os modos em blocos e coletivo final. |
| Controle humano | Ajustar, substituir, reposicionar, fixar e recalcular o restante sem sobrescrita silenciosa. |
| Consistência | Mensagem e jogadas usam a mesma versão revisada. |
| Reutilização | Separar perfil habitual, treino específico e jogada por função/posição. |
| Horizonte | Etapas com duração, movimentos, passes e finalizações; reprodução e vídeo automático em fases posteriores. |
| Primeira etapa | Sem obrigatoriedade de atributos específicos adicionais. |

## Atualização de 23/09/2026

Registrada em [CHAMADA-TREINO.md](CHAMADA-TREINO.md). O padrão do coletivo
passa a ser **ataque forte × defesa forte** (Time A melhor ataque, Time B
melhor defesa), e a prancheta começa com a sugestão; Equilibrado continua com
o mesmo acesso. A hierarquia de linha passa a ser a de ataque, e a defesa
ganha ordenação própria, geral, sem refino por posição. Isso substitui o
"Equilibrado é o default" da seção seguinte.

## Atualização confirmada no encerramento da voz

Equilibrado é o default, apenas primeiro selecionado/apresentado. Ambos os modos têm **igual importância, hierarquia visual, acesso e destaque**. Direcionado não fica em menu avançado ou secundário. Modo ativo deve aparecer na mensagem e no mapinha/quadra do coletivo, mantendo consistência também nos blocos.

O usuário usou coloquialmente “forte contra fraco” ao final; isso não substitui a semântica antes aprovada: ataque forte contra defesa forte, com inverso secundário explícito. Nome final do modo pode ser confirmado; não implementar times desiguais por inferência.

Permanece aberta a prioridade quando **equilíbrio competitivo, posições e participação/tempo de quadra entram em conflito**. Proteções e rotação também estão em discussão. As recomendações abaixo são propostas, não decisões aprovadas.

## Defaults recomendados, reversíveis

| Ponto cego | Proposta | Limite/questão |
|---|---|---|
| Goleiros | Preservar avaliação própria GOALKEEPER, separada da defesa de linha. | Decidir influência na sugestão; não inventar peso de soma. Híbrido pode ter avaliações distintas. |
| Posições | Reusar posições existentes e seleção para o treino. | Definir quais exigências são rígidas e quais permitem exceção explícita. |
| Lateralidade | Não adicionar campo obrigatório. | Não localizada nos módulos inspecionados; não inferir mão dominante pela posição. |
| Participantes | Começar com confirmados e permitir inclusão/exclusão planejada explícita. | Previsão não altera confirmação nem presença real. |
| Falta de última hora | Mostrar diferença da fonte e oferecer novo preview. | Fixado ausente gera conflito, nunca substituição invisível. |
| Suplentes | Banco visível e rotação manual por bloco. | Tempo previsto não é tempo efetivo; igualdade de minutos não prometida na V1. |
| Elenco incompleto | Salvar rascunho com vagas e explicação. | Adaptação de formato exige ação; um goleiro exige rodízio explícito. |
| Fixações | Fixar ocupante por papel/bloco, coordenada separadamente. | Duplicidade simultânea e inelegibilidade devem ser resolvidas antes de aplicar. |
| Notas | Somente CT autorizada; mensagem de atletas sem ranks. | Revisar API, não apenas tela. Acesso às próprias notas permanece aberto. |
| Modelo/instância | Referência à revisão do modelo mais alterações locais. | Atualizar modelo não muda sessão já revisada; adoção explícita. |
| Offline | Primeira edição tática conectada, falha preserva rascunho. | Integração posterior versionada, sem sobrescrever servidor. |
| Vídeo | Renderização determinística local da timeline. | Formato, qualidade, retenção e orçamento a decidir na fase própria. |

## Fundamentos agora, funcionalidades depois

Desde o início: IDs estáveis de blocos/papéis; dimensão explícita; null para desconhecido; escopo por time; revisão-base e idempotência; snapshots; origem manual/automática; fixações; modelo versus instância; unidade espacial; separação de relatório da CT e mensagem pública.

Depois: atributos detalhados, lateralidade, rotação automática com metas, registro de tempo real, timeline completa, reprodução e vídeo. Reservar contratos sem tornar campos futuros obrigatórios.

Bloqueiam a política automatizada definitiva: prioridade de objetivos, elegibilidade rígida/flexível, tratamento de goleiros, cobertura parcial e aceitação da transformação ordinal. Não bloqueiam mapa do código, contratos propostos, protótipo sintético ou prancheta manual.

## Entrevista recomendada

Uma pergunta concreta por vez, com opções e consequências. Próxima questão sugerida: “Há equipes mais equilibradas se alguém jogar fora da posição habitual; você prefere preservar posições, equilibrar ou decidir caso a caso?” Só então discutir participação e goleiros. Registrar resposta literal, consequência e itens ainda abertos; não usar a ausência de resposta como aprovação.
