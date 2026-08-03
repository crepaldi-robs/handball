# Identidade visual digital do HM-IME

**Status:** proposta normativa para aprovação e aplicação no produto
**Versão:** 1.0
**Data da pesquisa:** 31 de julho de 2026
**Escopo:** aplicação web HM-IME; não redefine a identidade institucional da AAAMAT nem materiais impressos.

## 1. Decisão executiva

O HM-IME deve parecer um único produto em todas as telas. Hub, Presenças, Calendário, Playbook, Estatísticas, DMs e áreas administrativas devem compartilhar a mesma marca, paleta, tipografia, navegação, comportamento de componentes e linguagem de feedback.

A identidade digital adotada é:

- competitiva, direta e coletiva;
- predominantemente vermelha, preta e branca quente;
- visualmente energética em capas e comunicação esportiva;
- simples, legível e previsível nas tarefas operacionais;
- adequada a celular e touchscreen, inclusive para pessoas pouco habituadas a sistemas administrativos.

Os módulos devem ser diferenciados pelo nome, ícone e conteúdo. Não devem receber paletas independentes que façam cada área parecer um aplicativo diferente.

## 2. Evidências e limites da pesquisa

### 2.1 Fontes observadas

1. Perfil oficial do time: [`@imeusp`](https://www.instagram.com/imeusp/), “Handebol Masculino IME - USP”.
2. Perfil da atlética: [`@atleticaimeusp`](https://www.instagram.com/atleticaimeusp/), “A.A.A. Matemática”.
3. Site institucional da [AAAMAT](https://atletica.ime.usp.br/) e sua página de [modalidades](https://atletica.ime.usp.br/modalidades).
4. Agregador oficial [Times AAAMAT](https://linktr.ee/timesaaamat), no qual o Handebol Masculino aparece como modalidade.
5. Logotipo fornecido pelo time e já armazenado em `static/hm-ime-logo.jpg`.
6. Interface atual do Hub e dos módulos do aplicativo.

### 2.2 O que foi observado

No perfil do HM-IME, as publicações esportivas recentes repetem de forma consistente:

- vermelho saturado, preto e branco quente;
- títulos grandes, fortes, condensados e frequentemente em caixa alta;
- recortes fotográficos, divisão de composição e textura de papel ou retícula;
- placares e informações de jogo com hierarquia visual muito forte;
- escudo da AAAMAT e símbolos dos adversários;
- fotografia real do time como elemento humano e documental.

O perfil da AAAMAT confirma o eixo vermelho, branco e preto e uma linguagem competitiva e irreverente. Já o aplicativo atual apresenta três direções diferentes: o Calendário está próximo dessa identidade; o Playbook usa uma variação bordô; e o Hub, Presenças e outras telas ainda usam azul-marinho e laranja.

### 2.3 O que é padronização de produto

Os valores hexadecimais, regras de componentes, escalas de espaçamento e usos de tipografia abaixo são uma tradução digital consistente das evidências observadas. Não devem ser apresentados como manual institucional, Pantone oficial ou norma histórica da AAAMAT sem validação documental posterior.

## 3. Arquitetura da marca

| Nível | Nome | Uso |
|---|---|---|
| Produto | **HM-IME** | nome principal em app bar, login, ícone instalado e comunicações do sistema |
| Nome formal | **Handebol Masculino IME-USP** | primeira apresentação, documentos, rodapés e contextos externos |
| Organização-mãe | **AAAMAT** | vínculo institucional e comunicações em que a atlética precise ser reconhecida |
| Módulo | Presenças, Calendário, Playbook etc. | subtítulo contextual, nunca substitui a marca HM-IME |

Formato recomendado no topo da aplicação:

> [marca] **HM-IME**
> Calendário

O usuário deve reconhecer primeiro onde está — HM-IME — e depois o que está fazendo — o módulo.

## 4. Sistema de logotipo

### 4.1 Marca digital adotada

O arquivo aprovado `static/hm-ime-logo.jpg` é a marca principal do aplicativo. Ele deve aparecer junto de “HM-IME” nos cabeçalhos persistentes. A imagem de perfil atual do Instagram é uma fotografia da equipe e deve ser tratada como conteúdo, não como logotipo permanente da interface.

O escudo completo da AAAMAT aparece nas publicações, mas não há no repositório um arquivo oficial isolado e aprovado desse escudo. O produto não deve redesenhá-lo, reproduzi-lo a partir de captura de tela ou fabricar uma versão semelhante. Quando um arquivo oficial for fornecido, ele poderá ser incorporado como marca institucional secundária.

### 4.2 Tamanhos e respiro

- favicon ou ícone mínimo: 32 × 32 px;
- app bar mobile: 40 × 40 px;
- app bar desktop: 44 × 44 px;
- destaque de login ou estado vazio: mínimo de 64 × 64 px;
- área livre ao redor: pelo menos 25% da largura visível da marca;
- o nome “HM-IME” deve continuar legível quando a marca estiver abaixo de 44 px.

### 4.3 Usos permitidos

- recorte circular quando a interface exigir avatar;
- aplicação sobre preto, branco ou branco quente, desde que haja contraste;
- marca acompanhada do nome HM-IME em navegação e autenticação;
- fotografia do time em banners, capas e conteúdos, sem substituir a marca funcional.

### 4.4 Usos proibidos

- deformar, inclinar, esticar ou achatar;
- aplicar sombra, brilho, gradiente ou contorno decorativo;
- recolorir de forma arbitrária;
- colocar sobre imagem sem uma superfície de contraste;
- usar somente uma letra “H” quando houver espaço para a marca aprovada;
- reconstruir o escudo da AAAMAT sem o arquivo oficial.

### 4.5 Ativo futuro recomendado

Criar, a partir do arquivo aprovado e sem alterar o desenho, versões derivadas em PNG transparente e SVG vetorial validado. O JPG original deve ser preservado como fonte recebida. Essa melhoria evita fundos indesejados e melhora a nitidez em telas de alta densidade.

## 5. Cores oficiais do produto

Estas variáveis já possuem correspondência no tema HM-IME do código e passam a ser a fonte canônica para todos os módulos.

| Token | Valor | Papel |
|---|---:|---|
| `--hm-primary` | `#D71920` | ação principal, seleção, destaque da marca |
| `--hm-primary-dark` | `#A40E17` | hover, estado pressionado, áreas de maior contraste |
| `--hm-canvas` | `#F7F4F2` | fundo geral branco quente |
| `--hm-surface` | `#FFFFFF` | cartões, formulários, diálogos |
| `--hm-ink` | `#171717` | texto principal e app bar |
| `--hm-muted` | `#6B6464` | texto secundário |
| `--hm-border` | `#E6DEDB` | bordas, divisores e campos |
| `--hm-success` | `#0F7B5A` | confirmação e estado concluído |
| `--hm-warning` | `#B45F06` | atenção e pendência |
| `--hm-destructive` | `#7F1D1D` | exclusão e ação irreversível |

### 5.1 Proporção visual

Usar aproximadamente:

- 60% de branco quente e superfícies claras;
- 30% de preto, cinzas e conteúdo;
- 10% de vermelho para marca, foco e ação.

O vermelho ganha força quando é reservado para o que merece atenção. Páginas inteiramente vermelhas devem ficar restritas a aberturas, placares, campanhas e estados especiais.

### 5.2 Contraste mínimo já verificado

| Combinação | Contraste aproximado | Resultado |
|---|---:|---|
| branco sobre vermelho principal | 5,19:1 | AA para texto normal |
| branco sobre vermelho escuro | 7,91:1 | AAA para texto normal |
| branco sobre preto da marca | 17,93:1 | AAA |
| preto da marca sobre canvas | 16,37:1 | AAA |
| texto secundário sobre branco | 5,78:1 | AA para texto normal |

Estados nunca devem depender apenas da cor. Erro, sucesso, aviso e seleção também precisam de ícone, título ou texto explícito.

## 6. Tipografia

### 6.1 Interface operacional

Usar `Inter`, com fallback para `Segoe UI`, `Arial` e `sans-serif`. É a tipografia para texto, botões, campos, diálogos, tabelas e instruções.

### 6.2 Títulos esportivos

Usar `Roboto Condensed`, com fallback para `Bahnschrift Condensed`, `Arial Narrow` e `sans-serif`. Serve para placares, títulos de campanha, números e chamadas curtas.

### 6.3 Regras

- texto e botões em formato de frase: “Salvar evento”, não “SALVAR EVENTO”;
- caixa alta apenas em placares, etiquetas curtas e títulos promocionais;
- corpo mínimo de 16 px em celular;
- texto auxiliar mínimo de 14 px;
- altura de linha entre 1,4 e 1,6 no conteúdo;
- números tabulares para placares, horários, presença e estatísticas;
- fontes manuscritas ou decorativas somente em campanhas, nunca em tarefas do sistema.

## 7. Forma, textura e composição

### 7.1 Base geométrica

- escala de espaçamento: 4, 8, 12, 16, 24, 32 e 48 px;
- raio de campos e botões: 12 px;
- raio de cartões: 16 px;
- raio de painéis e diálogos grandes: 20 px;
- borda padrão: 1 px em `--hm-border`;
- alvo interativo mínimo: 44 × 44 px;
- largura confortável de texto: entre 45 e 75 caracteres.

### 7.2 Elementos expressivos

Recorte de papel, retícula, faixa diagonal e fotografia recortada são válidos em:

- capa do Hub;
- placar ou resumo de jogo;
- estados vazios importantes;
- destaque de evento;
- capas e miniaturas do Playbook.

Esses elementos não devem aparecer atrás de formulários, tabelas, menus ou textos longos. Na operação diária, clareza e velocidade têm prioridade sobre decoração.

## 8. Casco visual compartilhado

Todo módulo deve reutilizar os mesmos componentes estruturais.

### 8.1 App bar

- fundo `--hm-ink`;
- linha inferior de 3 px em `--hm-primary`;
- logotipo aprovado;
- “HM-IME” como marca principal;
- nome do módulo como subtítulo;
- ações “Hub”, perfil e sair em posições previsíveis;
- em celular, ações secundárias dentro de menu acessível e rotulado.

### 8.2 Navegação

- item ativo indicado por cor, ícone e texto;
- botão voltar deve dizer para onde volta quando houver ambiguidade;
- ações da tela permanecem próximas do conteúdo afetado;
- navegação inferior é aceitável para até cinco destinos principais no modo atleta;
- CT e administração podem usar menu lateral responsivo quando houver mais destinos.

### 8.3 Cartões de módulo no Hub

Cada cartão contém:

- ícone próprio;
- nome curto;
- descrição em uma linha;
- ação principal clara;
- informação de contexto útil, quando existir, como “Treino hoje, 19h”.

O cartão inteiro deve ser clicável. Verde, amarelo e vermelho são reservados aos estados do conteúdo; não são a identidade fixa de um módulo.

### 8.4 Botões

| Tipo | Aparência | Uso |
|---|---|---|
| Primário | fundo vermelho, texto branco | uma ação principal por região |
| Secundário | fundo branco, borda neutra | alternativa segura |
| Fantasma | sem fundo, texto escuro | navegação ou ação de baixa ênfase |
| Destrutivo | vermelho escuro, ícone e verbo explícito | excluir ou remover |

Todos precisam de estados de hover, foco visível, pressionado, carregando e desabilitado. Em touchscreen, uma ação não pode depender de hover.

### 8.5 Formulários

- rótulo sempre visível acima do campo;
- placeholder é exemplo, nunca substitui o rótulo;
- validação próxima do campo e resumo no topo quando houver vários erros;
- manter os dados preenchidos quando o envio falhar;
- oferecer valores padrão coerentes com o contexto;
- mostrar a ação principal na área alcançável pelo polegar em celular;
- confirmar saída quando houver alteração não salva.

### 8.6 Diálogos e feedback

Diálogos servem para decisões que interrompem o fluxo. Para exclusão, apresentar o objeto e a consequência: “Excluir o treino de 12/08 às 19h? As confirmações ligadas a ele deixarão de aparecer.”

Todo erro não previsto deve abrir uma mensagem em linguagem comum com:

1. o que não foi concluído;
2. por que isso pode ter acontecido, quando conhecido;
3. como o usuário pode corrigir ou tentar novamente;
4. um identificador técnico copiável para suporte, sem expor detalhes internos.

Sucessos simples usam toast curto. Ações longas mostram progresso. Exclusões recuperáveis devem oferecer “Desfazer” quando tecnicamente possível.

## 9. Aplicação por módulo

| Área | Elemento contextual | Prioridade de experiência |
|---|---|---|
| Hub | visão da próxima ação e cartões clicáveis | chegar ao destino em um toque |
| Presenças | ícone de pessoas e resumo confirmado/pendente | chamada rápida, nomes legíveis e ordenados |
| Calendário | ícone de calendário e destaque do próximo evento | criar, editar, confirmar e cancelar em poucos toques |
| Playbook | ícone de prancheta e miniaturas de mídia | explorar pastas dinâmicas sem perder o caminho |
| Estatísticas | ícone de gráfico e números tabulares | comparação clara e filtros simples |
| DMs | ícone de organização ou comunicação | transformar solicitações em fluxo acompanhável |
| Administração | ícone de ajustes ou escudo | segurança e clareza sem trocar de identidade visual |
| SQL interno | ícone de banco de dados | aparência técnica, mas dentro do mesmo casco HM-IME |

Um módulo pode possuir ilustrações, miniaturas e padrões próprios. Não pode redefinir vermelho, tipografia, app bar, botões, campos ou feedback global.

## 10. Fotografia, vídeo e mídia

- priorizar fotografias reais de treino, jogo e grupo;
- manter tons de pele naturais; vermelho pode entrar em moldura, faixa ou sobreposição moderada;
- não cobrir rostos com texto ou controles;
- usar enquadramento documental e sensação de proximidade;
- capas de vídeo preferencialmente em 16:9, com título curto e selo da categoria;
- miniaturas do Playbook devem indicar tipo de mídia, duração e fundamento ou jogada;
- imagens explicativas devem ter alternativa textual;
- vídeos precisam de legenda ou resumo textual para consulta rápida e acessibilidade.

## 11. Voz e microtexto

A voz do produto é curta, ativa e orientada à ação. O sistema fala como auxiliar do time, não como auditor.

| Situação | Preferir | Evitar |
|---|---|---|
| criação | “Criar evento” | “Efetuar inclusão de registro” |
| edição | “Salvar alterações” | “Submeter edição” |
| presença | “Vou” / “Não vou” | códigos ou estados técnicos |
| chamada | “Abrir chamada” | “Inicializar aferição” |
| erro | “Não foi possível salvar. Confira a conexão e tente novamente.” | “Erro 500” como única explicação |
| confirmação | “Evento criado” | mensagem genérica sem dizer o que ocorreu |

Termos de auditoria, IDs e detalhes de servidor ficam em uma área secundária ou copiável. Eles não devem dominar a tarefa do atleta ou da CT.

## 12. Acessibilidade e interação

- conformidade mínima WCAG 2.2 AA;
- foco visível em toda ação de teclado;
- ordem de foco igual à ordem visual;
- rótulo acessível para ícones;
- não usar gesto como única forma de executar uma ação;
- oferecer alternativa a arrastar e soltar no Playbook, como “Mover para…”;
- respeitar `prefers-reduced-motion`;
- animações funcionais entre 120 e 240 ms;
- não bloquear zoom do navegador;
- testar em largura de 320 px e com texto ampliado a 200%;
- mensagens importantes anunciadas por tecnologias assistivas.

## 13. Diagnóstico da interface atual

| Área atual | Situação | Correção necessária |
|---|---|---|
| Calendário | mais aderente à identidade HM-IME | transformar seus bons padrões em componentes compartilhados |
| Playbook | marca parcialmente aplicada, com bordô e casco próprio | adotar tokens canônicos, logotipo e app bar compartilhada |
| Hub | azul-marinho, laranja e monograma “H” | redesenhar como porta de entrada HM-IME |
| Presenças e visão do atleta | linguagem visual legada | aplicar casco, botões, campos e feedback compartilhados |
| Estatísticas, relatórios e usuários | funcionais, mas visualmente separados | migrar sem perder densidade informacional |
| Administração e SQL | aparência de ferramenta isolada | manter segurança técnica dentro da mesma identidade |

O problema principal não é a falta de personalidade; é a personalidade estar concentrada em uma área e competir com estilos antigos nas demais.

## 14. Contrato técnico de implementação

### 14.1 Fonte única de verdade

Os valores de `handball/core/team_theme.py` devem alimentar variáveis CSS globais no elemento raiz. Nenhum módulo deve copiar os hexadecimais para criar uma paleta paralela.

Contrato mínimo:

```css
:root {
  --hm-primary: #D71920;
  --hm-primary-dark: #A40E17;
  --hm-canvas: #F7F4F2;
  --hm-surface: #FFFFFF;
  --hm-ink: #171717;
  --hm-muted: #6B6464;
  --hm-border: #E6DEDB;
  --hm-success: #0F7B5A;
  --hm-warning: #B45F06;
  --hm-destructive: #7F1D1D;
}
```

### 14.2 Componentes compartilhados obrigatórios

- `platform-shell`;
- `platform-appbar`;
- `platform-brand`;
- `module-card`;
- `button` e suas variantes;
- `field`, `select` e `textarea`;
- `tabs` e `filter-chip`;
- `dialog` e `confirmation-dialog`;
- `toast` e `inline-alert`;
- `empty-state`, `loading-state` e `error-state`.

Classes específicas de módulo podem controlar layout e conteúdo, mas não redefinir os fundamentos acima.

### 14.3 Natureza da mudança

A aplicação desta diretriz é uma atualização `APP_ONLY`: templates, CSS, JavaScript e ativos. Não exige alteração de esquema nem migração do banco de dados. Mudanças funcionais descobertas durante o redesenho devem ser planejadas e testadas separadamente.

## 15. Trilha de implementação

### Release 1 — Fundação visual

- centralizar tokens do tema;
- criar os componentes compartilhados;
- incluir tipografia e foco acessível;
- adicionar testes visuais básicos e exemplos de estado.

### Release 2 — Entrada do produto

- migrar login e Hub;
- substituir o monograma “H” pela marca aprovada;
- tornar cartões inteiros clicáveis;
- destacar próxima ação relevante por perfil.

### Release 3 — Operação diária

- migrar Presenças, visão do atleta e relatórios;
- padronizar diálogos, toasts, erros e confirmações;
- validar uso em celular durante treino.

### Release 4 — Conteúdo esportivo

- alinhar Calendário ao casco definitivo;
- migrar Playbook sem perder a navegação de explorador de arquivos;
- criar padrão de miniatura para vídeo, imagem, texto e apresentação.

### Release 5 — Análise e administração

- migrar Estatísticas, DMs, Usuários e SQL;
- conservar densidade e controles de segurança;
- diferenciar permissões por conteúdo e ação, não por outra identidade.

### Release 6 — Homologação

- validar celular, tablet, desktop, teclado e leitor de tela;
- comparar todas as telas em mosaico para detectar divergências;
- conferir contraste, zoom, carregamento, vazio, sucesso e erro;
- validar a linguagem com CT e atletas em tarefas reais.

## 16. Critérios de aceite

Uma tela só está aderente quando:

- exibe marca HM-IME e nome do módulo de forma consistente;
- usa exclusivamente os tokens canônicos para fundamentos visuais;
- oferece alvo de toque mínimo de 44 × 44 px;
- funciona por toque e teclado, sem depender de hover;
- mantém ação principal clara e no máximo uma por região;
- usa ícone e texto, além da cor, para comunicar estado;
- explica falhas em linguagem comum e sugere a próxima ação;
- preserva dados preenchidos após erro;
- possui estados de carregamento, vazio, sucesso e falha;
- foi verificada em 320 px, desktop e zoom de 200%;
- não cria outra paleta, app bar ou família de botões dentro do módulo.

## 17. Próxima decisão recomendada

O próximo item de backlog deve ser a **Fundação visual HM-IME**: transformar esta diretriz em tokens e componentes compartilhados e aplicá-los primeiro ao Hub. Essa etapa gera o maior ganho perceptível, reduz a duplicação de CSS e cria a base para migrar cada módulo em releases pequenos e verificáveis.
