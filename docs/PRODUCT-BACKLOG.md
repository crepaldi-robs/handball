# Backlog de Produto — Plataforma HM-IME Handball

> Documento vivo. Versão inicial criada em 30/07/2026 a partir da entrevista
> de produto com foco na rotina do CT. Itens ainda não validados estão marcados
> como decisões pendentes, não como requisitos fechados.

## 1. Direção do produto

A plataforma deve reduzir o trabalho operacional do time e transformar
informações dispersas em ações claras. A interface deve favorecer poucos
cliques, leitura rápida, uso por toque e linguagem compreensível para pessoas
com pouca familiaridade tecnológica.

Princípios:

- mostrar primeiro o que exige ação agora;
- respeitar o contexto do papel, do evento e do momento;
- permitir concluir as tarefas principais sem procurar funções em menus;
- explicar erros em linguagem simples, informar a causa e sugerir a correção;
- manter histórico e regras de segurança sem transferir a complexidade da
  auditoria para o usuário;
- evitar cadastrar duas vezes uma informação que já exista em outro módulo;
- começar com integrações simples e reversíveis antes de migrar acervos.

## 2. Sequência aprovada das próximas trilhas

1. [ ] Consolidar a jornada operacional do calendário e da chamada. **Em validação**
2. Implementar o módulo de Playbook.
3. Implementar o módulo dos DMs — Diretores de Modalidade.
4. Avaliar o acervo do Drive quando o arquivo `.zip` for disponibilizado.
5. Decidir entre manter referências ao Drive, importar parte do acervo ou fazer
   uma migração completa.

## 3. Jornada real do CT já identificada

### 3.1 Planejamento sazonal

O planejamento do treino não nasce isoladamente em cada evento. O CT espera
trabalhar uma técnica ou conceito por uma sequência de treinos:

1. começar;
2. melhorar;
3. refinar;
4. aplicar em situação de jogo;
5. revisar a partir do resultado observado.

O ciclo pode ser alterado por:

- característica de um adversário do próximo jogo;
- erro observado em jogo passado;
- disponibilidade real dos atletas;
- necessidade técnica ou física pontual.

### 3.2 Um dia antes do treino

O CT consulta:

- quem confirmou presença;
- quem informou ausência;
- quem ainda não respondeu;
- composição provável do treino por posição;
- objetivo do ciclo sazonal;
- técnicas, exercícios ou jogadas do Playbook ligados ao treino;
- eventual ajuste por adversário ou aprendizado do jogo anterior.

### 3.3 Poucas horas antes

O CT não precisa reler tudo. A interface deve destacar somente:

- quem mudou a resposta;
- novas ausências;
- atletas que continuam sem responder;
- impacto da mudança na composição por posição;
- alteração necessária no plano do treino.

### 3.4 Final do treino

Na conversa final, o CT deve conseguir:

- abrir a chamada do evento em um toque;
- registrar presença e ausência rapidamente;
- registrar uma observação curta sobre o treino;
- indicar o estágio do conteúdo trabalhado: começando, melhorando, refinando ou
  consolidado;
- registrar um problema ou aprendizado que deverá voltar ao planejamento;
- decidir se a técnica ou jogada continua no próximo treino.

### 3.5 Implicação para o produto

O evento do calendário deve funcionar como ponto de encontro entre:

- disponibilidade dos atletas;
- chamada;
- planejamento sazonal;
- conteúdo do Playbook;
- contexto do próximo adversário;
- aprendizado do jogo anterior;
- avaliação pós-treino.

### 3.6 Entregas em execução — Calendário e chamada

- [x] Jornada de eventos: criação, confirmação, cancelamento reversível,
  remarcação, histórico, conflitos e séries recorrentes.
- [x] Vínculo idempotente entre treino oficial e chamada, sem criar chamadas a
  partir de datas arbitrárias.
- [x] Resumo de disponibilidade no detalhe do treino: confirmações, ausências,
  pendências e composição por posição.
- [x] Briefing de poucas horas antes: destacar novas ausências, quem permanece
  sem resposta e a variação da composição por posição.
- [x] Encerramento guiado do treino: observação geral, fechamento explícito da
  chamada e conclusão do evento somente depois de a chamada ser encerrada.
- [ ] Validação de uso autenticado pelo CT em navegador e celular. **Pendente de
  uma sessão CT já autenticada**
- [ ] Objetivo sazonal, estágio de domínio, conteúdo tático e decisão de
  continuidade: dependência da integração PB-3/PB-4 do Playbook.
- [ ] Ajuste por adversário e aprendizado de jogo anterior: dependência da
  trilha DMs e do Playbook.

## 4. Trilha 1 — Playbook do time

### 4.1 Objetivo

Criar uma biblioteca tática e técnica simples de consultar, visual, utilizável
em quadra e diretamente conectada ao planejamento dos treinos.

O Playbook deve comportar:

- jogadas ensaiadas;
- fundamentos e conceitos técnicos;
- exercícios de treino;
- sistemas ofensivos e defensivos;
- transições;
- bolas paradas e situações especiais;
- vídeos de exemplo;
- imagens, diagramas e sequências explicativas;
- explicações textuais;
- apresentações em PowerPoint.

### 4.2 Taxonomia e navegação aprovadas

A árvore descrita nesta seção é a configuração inicial recomendada para o time,
não uma hierarquia fixa no código. Todas as pastas serão entidades dinâmicas,
editáveis por usuários autorizados.

O primeiro nível inicial do Playbook terá duas áreas:

```text
Playbook
├── Técnica
└── Tática
```

#### Técnica

```text
Técnica
├── Handball
│   └── uma pasta para cada fundamento
└── Academia
    └── uma pasta para cada grupo muscular
```

As listas iniciais de fundamentos do Handball e de grupos musculares ainda
serão definidas durante a entrevista.

#### Tática

```text
Tática
├── Ataque
├── Defesa
├── Transição
└── Situações especiais
```

O catálogo inicial de jogadas principais do ataque será:

```text
Ataque
├── X
├── Desdobre
├── Corrida
├── Circulação
├── Roda
├── Islândia
├── Portugal
├── Espanha
├── Cruzamento
└── Amplitude
```

Ataque e defesa também terão uma estrutura espelhada para representar proposta,
resposta e contrarresposta.

Na perspectiva do ataque:

```text
Ataque
├── Jogadas principais
│   ├── X
│   ├── Desdobre
│   ├── Corrida
│   ├── Circulação
│   ├── Roda
│   ├── Islândia
│   ├── Portugal
│   ├── Espanha
│   ├── Cruzamento
│   └── Amplitude
├── Contra esquemas defensivos
│   ├── 6x0
│   │   └── mesmas pastas de jogadas principais
│   └── 5x1
│       └── mesmas pastas de jogadas principais
└── Situações reduzidas e propostas da defesa
    ├── 1x1
    ├── 2x2
    ├── Subida
    ├── Triângulo
    ├── Troca de pivô
    ├── Ímpar
    └── Dissuasão
```

Na perspectiva da defesa:

```text
Defesa
├── 6x0
│   ├── X
│   ├── Desdobre
│   ├── Corrida
│   ├── Circulação
│   ├── Roda
│   ├── Islândia
│   ├── Portugal
│   ├── Espanha
│   ├── Cruzamento
│   └── Amplitude
├── 5x1
│   └── mesmas pastas de jogadas principais
└── Situações reduzidas e respostas defensivas
    ├── 1x1
    ├── 2x2
    ├── Subida
    ├── Triângulo
    ├── Troca de pivô
    ├── Ímpar
    └── Dissuasão
```

Essa lógica deve poder crescer para novos esquemas, jogadas e situações sem
exigir mudança estrutural no código.

#### Regra de modelagem: navegação em pastas, conteúdo relacionado

As pastas são a forma como o usuário encontra o conteúdo. Internamente, o
Playbook não deve criar cópias independentes do mesmo material.

Exemplo:

- `Ataque > Contra 6x0 > X` mostra como o ataque executa ou adapta o X contra
  uma defesa 6x0;
- `Defesa > 6x0 > X` mostra como a defesa reage ao X;
- as duas páginas são perspectivas relacionadas do mesmo confronto tático;
- uma resposta defensiva pode apontar para uma contrarresposta ofensiva;
- o mesmo vídeo pode demonstrar mais de uma jogada, fundamento ou situação sem
  precisar ser enviado novamente.

Cada conteúdo deverá aceitar:

- uma ou mais pastas de navegação;
- perspectiva de ataque ou defesa;
- relação com jogada, esquema e situação;
- vínculos do tipo proposta, resposta, contrarresposta e variação;
- nomes alternativos ou apelidos usados pelo time;
- materiais compartilhados;
- versões e histórico.

#### Requisito central: explorador de pastas dinâmico

O Playbook deve funcionar como um explorador de arquivos. Nenhum nome de pasta,
quantidade de níveis ou caminho tático específico pode ser fixado no código.

Usuários autorizados deverão conseguir:

- criar pasta e subpasta;
- renomear pasta;
- mover pasta para outro ponto da árvore;
- reordenar pastas irmãs;
- mover conteúdos entre pastas;
- selecionar e mover vários conteúdos;
- criar atalhos para um conteúdo aparecer em mais de uma pasta;
- copiar uma estrutura como modelo, sem copiar desnecessariamente os arquivos;
- arquivar uma pasta;
- restaurar uma pasta arquivada;
- excluir definitivamente somente por um fluxo administrativo explícito;
- pesquisar pastas e conteúdos;
- navegar por árvore lateral e trilha de navegação;
- alternar entre visualização em cartões e lista.

No computador, a interface poderá oferecer arrastar e soltar. Em celular e
tablet, a mesma operação também deverá existir por meio de `Mover para...`,
porque arrastar e soltar não pode ser o único caminho.

As operações deverão preservar:

- links existentes em treinos e eventos;
- favoritos;
- histórico e versões;
- relações entre proposta, resposta e contrarresposta;
- materiais compartilhados;
- links externos e apresentações;
- permissões.

Cada pasta deverá possuir um identificador permanente independente do nome e do
caminho. Renomear ou mover a pasta não poderá quebrar links já salvos.

Ao arquivar ou tentar excluir uma pasta, a interface deverá informar:

- quantas subpastas existem;
- quantos conteúdos serão afetados;
- onde esses conteúdos também aparecem;
- quais treinos ou eventos mantêm vínculos;
- qual ação é reversível;
- como restaurar o item.

As pastas `Tática`, `Técnica`, `Ataque`, `Defesa` e todas as demais fazem parte
do modelo inicial, mas não serão constantes técnicas da aplicação. A estrutura
poderá evoluir conforme a linguagem e a metodologia do time.

#### Autoridade máxima do CT no Playbook

Dentro do módulo de Playbook, `CT`, `ADMIN` e `DEV` terão a mesma autoridade
funcional máxima. Qualquer integrante da comissão técnica deverá poder:

- criar, renomear, mover, reordenar, arquivar e restaurar pastas;
- realizar exclusão definitiva pelo fluxo protegido;
- criar, editar, mover, relacionar, publicar, arquivar e restaurar conteúdos;
- incluir, substituir e remover textos, imagens, vídeos e apresentações;
- criar atalhos e modelos;
- reorganizar toda a árvore;
- consultar histórico e restaurar versões anteriores;
- definir relações entre proposta, resposta, contrarresposta e variação.

Não haverá uma permissão adicional de “organizador do Playbook” limitando o CT.
A autoridade máxima vale somente dentro do escopo esportivo e documental do
Playbook; ela não concede ao CT administração técnica do sistema ou acesso
automático a outros módulos.

Confirmação, resumo de impacto, arquivamento e restauração são proteções contra
erros acidentais, não restrições à autonomia do CT.

### 4.3 Release PB-0 — Descoberta e arquitetura de conteúdo

Definir com o CT:

- lista inicial dos fundamentos técnicos de Handball;
- lista inicial dos grupos musculares de Academia;
- demais esquemas defensivos além de 6x0 e 5x1;
- estrutura interna de Transição e Situações especiais;
- outras jogadas e situações reduzidas;
- nomenclatura, significado e apelidos usados pelo time;
- regra para proposta, resposta, contrarresposta e variação;
- se haverá limite recomendado de profundidade;
- regras para atalhos, cópias e conteúdos presentes em várias pastas;
- fluxo de rascunho, revisão, publicação e arquivamento;
- origem e direitos de uso dos vídeos e materiais;
- diferença entre material interno e material compartilhável;
- funcionamento offline na quadra.

Entregável: modelo de conteúdo validado com exemplos reais do time.

### 4.4 Release PB-1 — Biblioteca consultável

Primeira versão de uso:

- tela inicial com conteúdos recentes, mais usados e ligados ao próximo treino;
- busca por nome, apelido e palavra-chave;
- entrada inicial por Tática ou Técnica;
- explorador de pastas totalmente dinâmico;
- árvore lateral recolhível;
- trilha de navegação clicável;
- criação, renomeação, movimentação, reordenação e arquivamento de pastas;
- ação `Mover para...` adequada para touchscreen;
- arrastar e soltar como atalho adicional no computador;
- estados vazios que ensinam a criar a primeira pasta ou conteúdo;
- desfazer imediatamente operações de movimentação e arquivamento;
- filtros por ataque, defesa, transição, situação especial, fundamento e grupo
  muscular;
- acesso espelhado às perspectivas ofensiva e defensiva;
- passagem direta de uma proposta para sua resposta e contrarresposta;
- filtros por posição e nível de domínio;
- cartões grandes e clicáveis;
- página da jogada com texto, imagens, vídeo e arquivos relacionados;
- visualização adequada para celular e tablet;
- favoritos e itens vistos recentemente;
- links para apresentações existentes no Drive;
- download ou abertura do PowerPoint original.

Nesta fase, o Drive pode continuar como repositório de arquivos. A aplicação
organiza a navegação e aponta diretamente para os materiais, sem duplicá-los.

### 4.5 Release PB-2 — Edição e publicação pelo CT

- criar conteúdo a partir de um modelo;
- adicionar objetivo, quando usar e pré-requisitos;
- descrever passo a passo;
- definir responsabilidade por posição;
- incluir variações, respostas e contrarrespostas;
- relacionar a proposta ofensiva com a reação defensiva;
- publicar o mesmo conteúdo em mais de uma pasta sem duplicá-lo;
- cadastrar nomes alternativos e apelidos;
- anexar imagens;
- incorporar ou vincular vídeos;
- vincular um PowerPoint;
- salvar rascunho;
- pré-visualizar como atleta;
- publicar, substituir versão e arquivar;
- manter histórico de versões sem expor complexidade ao atleta.

### 4.6 Release PB-3 — Integração com calendário e treino

- vincular conteúdos do Playbook a um evento;
- montar o plano de treino a partir de blocos;
- reutilizar o plano do treino anterior;
- apresentar o plano junto das confirmações no dia anterior;
- sinalizar impacto de ausências por posição;
- mostrar em quadra somente o roteiro essencial;
- registrar o estágio de domínio após o treino;
- sugerir continuidade no próximo evento;
- distinguir objetivo sazonal de ajuste pontual por adversário ou jogo passado.

### 4.7 Release PB-4 — Ciclos de evolução

- criar ciclos com início, objetivo e previsão de duração;
- associar conteúdos do Playbook ao ciclo;
- acompanhar os estados começando, melhorando, refinando e consolidado;
- registrar evidências e observações dos treinos;
- relacionar falhas de jogos a conteúdos que precisam ser retomados;
- relacionar o próximo adversário a adaptações específicas;
- apresentar uma linha do tempo simples da evolução.

### 4.8 Release PB-5 — Apresentações

Duas capacidades devem ser tratadas separadamente:

1. abrir ou baixar apresentações já existentes;
2. gerar uma apresentação `.pptx` a partir do conteúdo estruturado do Playbook.

A geração automática deve ser posterior à biblioteca e à edição. Ela só terá
boa qualidade quando textos, imagens, passos e posições já estiverem
estruturados.

### 4.9 Critérios de sucesso da trilha

- localizar uma jogada conhecida em até 10 segundos;
- reorganizar a árvore sem alterar código ou executar implantação;
- renomear ou mover uma pasta sem quebrar nenhum vínculo existente;
- executar as operações principais tanto por mouse quanto por touchscreen;
- recuperar facilmente uma pasta movida ou arquivada por engano;
- abrir o conteúdo ligado ao próximo treino em até dois toques;
- montar um plano reaproveitando conteúdo existente sem redigitação;
- atleta compreender objetivo, execução e responsabilidade da sua posição;
- CT registrar o resultado do treino sem abrir uma tela administrativa
  separada.

## 5. Trilha 2 — DMs (Diretores de Modalidade)

### 5.1 Objetivo

Criar um espaço administrativo que organize demandas, prazos, documentos e
comunicação entre atletas, DMs e agentes externos, sem transformar o aplicativo
em um gerenciador burocrático difícil de usar.

Responsabilidades já identificadas:

- pedir trocas de jogos;
- informar restrições aos campeonatos;
- inscrever atletas;
- organizar informações externas para o time;
- organizar informações internas para comunicação externa;
- administrar ou localizar documentos do time.

### 5.2 Release DM-0 — Mapeamento operacional

Antes de implementar fluxos, entrevistar os DMs e mapear:

- campeonatos e entidades com que interagem;
- tipos de demanda;
- canais atuais de comunicação;
- prazos e consequências;
- dados e documentos exigidos;
- quem solicita, quem executa, quem aprova e quem precisa ser informado;
- informações pessoais ou sensíveis;
- estrutura atual do Drive;
- duplicações e pontos de perda de informação.

Entregável: mapa dos fluxos e matriz de responsabilidades.

### 5.3 Release DM-1 — Central de comunicação

Comunicação de atletas para DMs:

- abrir uma solicitação por categoria;
- explicar o pedido em linguagem livre;
- anexar ou apontar documentos;
- acompanhar estado: recebida, em análise, aguardando atleta, resolvida ou
  encerrada;
- saber qual DM é responsável;
- responder no mesmo contexto;
- visualizar prazo e próxima ação.

Comunicação de DMs para atletas:

- publicar aviso para todo o time ou grupo específico;
- informar prazo e ação esperada;
- pedir confirmação de leitura ou resposta;
- destacar o que mudou em uma atualização;
- encerrar um aviso quando perder validade;
- separar comunicado informativo de tarefa obrigatória.

Decisão pendente: começar somente com caixa de entrada dentro do aplicativo ou
integrar posteriormente e-mail e outros canais. A primeira versão não deve
disparar mensagens externas sem regra e autorização explícitas.

### 5.4 Release DM-2 — Restrições e disponibilidade para campeonatos

- coletar restrições dos atletas por competição ou período;
- indicar prazo de resposta;
- mostrar pendências aos atletas;
- consolidar respostas para os DMs;
- distinguir indisponibilidade, preferência e impedimento documental;
- registrar alterações após o prazo;
- gerar visão pronta para comunicação externa.

### 5.5 Release DM-3 — Inscrição de atletas

- checklist por competição;
- situação de cada atleta;
- dados ou documentos faltantes;
- prazo;
- responsável;
- pedido de correção ao atleta;
- confirmação de envio;
- comprovante ou referência do protocolo externo;
- controle de acesso específico para documentos pessoais.

Documentos sensíveis não devem ser copiados para a aplicação antes de uma
decisão explícita sobre segurança, retenção, acesso e exclusão.

### 5.6 Release DM-4 — Trocas de jogos

- registrar jogo original;
- justificar o pedido;
- propor datas e horários alternativos;
- registrar restrições do time;
- acompanhar contato com adversário e organização;
- registrar contraproposta;
- controlar prazo e aprovação;
- atualizar o calendário quando a troca for confirmada;
- comunicar a mudança aos atletas e solicitar ciência.

### 5.7 Release DM-5 — Informações internas e externas

- caixa de entrada de informações recebidas de fora;
- classificação por competição, jogo, inscrição, documento ou prazo;
- transformação de uma mensagem externa em comunicado ou tarefa interna;
- consolidação de respostas internas;
- geração de resumo pronto para envio externo;
- registro do que foi enviado, quando e por quem.

### 5.8 Release DM-6 — Drive e acervo documental

#### V1: apontar para o Drive

- criar um catálogo simples por assunto;
- manter os arquivos no Drive;
- mostrar descrição, responsável, validade e link direto;
- respeitar as permissões já existentes;
- evitar upload e duplicação;
- sinalizar link quebrado ou acesso negado;
- destacar documentos usados com frequência.

#### Avaliação posterior ao recebimento do `.zip`

- inventariar pastas, formatos, tamanhos e duplicações;
- identificar convenções de nomes;
- separar documentos ativos, históricos, modelos e descartáveis;
- localizar dados pessoais ou sensíveis;
- mapear relações com atletas, competições, jogos e temporadas;
- comparar três estratégias:
  - manter tudo no Drive e apenas indexar;
  - importar metadados e manter arquivos no Drive;
  - migrar arquivos e metadados para a plataforma;
- estimar custo operacional, risco, segurança e reversibilidade;
- executar primeiro uma prova de conceito com uma pasta não sensível.

### 5.9 Critérios de sucesso da trilha

- atleta saber onde pedir algo sem descobrir qual canal ou DM procurar;
- DM enxergar pendências, prazos e responsáveis em uma única tela;
- reduzir pedidos repetidos e mensagens perdidas;
- todo comunicado com ação deixar claro quem deve fazer o quê e até quando;
- troca confirmada de jogo atualizar o calendário sem recadastro;
- inscrição mostrar imediatamente o que falta;
- arquivos existentes continuarem utilizáveis durante qualquer migração.

## 6. Fundamentos compartilhados

### 6.1 Papéis e acesso

Prever, no mínimo:

- atleta;
- CT;
- DM;
- administrador técnico.

As permissões devem ser definidas no servidor. A interface pode simplificar o
que cada pessoa vê, mas esconder um botão não substitui autorização.

No Playbook, CT, administrador e DEV possuem autoridade funcional máxima. O
atleta começa com consulta aos conteúdos publicados. As permissões dos demais
módulos continuam independentes.

### 6.2 Busca e navegação

- busca global por evento, jogada, comunicado e documento;
- atalhos contextuais a partir do próximo treino ou jogo;
- histórico recente;
- links entre entidades relacionadas;
- retorno previsível para a tela anterior.

### 6.3 Linguagem e tratamento de erros

Todo erro apresentado ao usuário deve:

1. dizer o que não foi concluído;
2. explicar a causa quando ela for conhecida;
3. preservar os dados já digitados;
4. sugerir uma correção;
5. oferecer uma próxima ação segura.

### 6.4 Touchscreen e acessibilidade

- alvos de toque grandes;
- ações primárias visíveis;
- contraste forte;
- textos curtos;
- estado selecionado evidente;
- confirmação apenas para ações irreversíveis ou de grande impacto;
- navegação completa por teclado;
- compatibilidade com leitor de tela;
- funcionamento responsivo em celular, tablet e computador.

### 6.5 Integração sem duplicação

- calendário fornece eventos e datas;
- presença fornece confirmação e chamada;
- Playbook fornece conteúdos e ciclos;
- DMs fornecem demandas, comunicações e processos administrativos;
- documentos podem permanecer no Drive enquanto a aplicação mantém contexto e
  navegação.

## 7. Próximas decisões da entrevista

As decisões serão respondidas uma por vez e incorporadas a este documento:

1. **Respondida:** o Playbook começa em Tática e Técnica; Técnica se divide em
   Handball e Academia; Tática se divide em Ataque, Defesa, Transição e
   Situações especiais; ataque e defesa possuem visões espelhadas.
2. **Respondida:** todas as pastas serão dinâmicas como em um explorador de
   arquivos; a árvore inicial poderá ser criada, renomeada, movida, reordenada
   e ampliada sem alteração no código.
3. **Respondida:** dentro do Playbook, CT, ADMIN e DEV possuem autoridade
   funcional máxima, inclusive para modificar toda a estrutura de pastas.
4. Quais fundamentos formarão as pastas iniciais de `Técnica > Handball`?
5. Quais grupos musculares formarão as pastas de `Técnica > Academia`?
6. Quais outros esquemas defensivos devem entrar além de 6x0 e 5x1?
7. Como Transição e Situações especiais devem ser subdivididas?
8. Quem cria, revisa, publica e arquiva conteúdo?
9. O que o atleta deve ver antes, durante e depois do treino?
10. Quais materiais precisam funcionar sem internet?
11. Como o time usa hoje vídeos, imagens e apresentações?
12. Quais são os três processos mais frequentes dos DMs?
13. Quais demandas dos DMs mais se perdem ou atrasam hoje?
14. Que informações são sensíveis e quem pode acessá-las?
15. Qual canal atual não pode ser interrompido durante a adoção?
16. Como medir se cada trilha reduziu tempo, dúvidas e retrabalho?

## 8. Fora de escopo até nova decisão

- migração automática do Drive;
- armazenamento de documentos pessoais na aplicação;
- envio automático de mensagens externas;
- geração automática de PowerPoint antes da estruturação do conteúdo;
- mudança do banco persistente sem fluxo separado e autorização explícita de
  `DB_MIGRATION`;
- publicação ou implantação em produção.
