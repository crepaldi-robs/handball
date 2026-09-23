# Criação de jogadas · Playbook

**Especificação e estado da implementação (23/09/2026).** J0–J4 estão
implementados (ver §7). A persistência usa a migração v15, autorizada pelo
usuário em 23/09/2026 e aplicável só em janela `DB_MIGRATION` com backup
(regras 12 e 16 do [AGENTS.md](../../AGENTS.md)).

## 1. Objetivo

A CT desenha uma jogada de handebol no celular ou no PC, passo a passo, e o
app anima. A mesma jogada:

- entra no treino do dia como exercício, sem precisar cadastrar papéis à mão:
  as posições da jogada **são** os papéis do exercício;
- aparece para as atletas no planejamento final, animada, com os nomes reais
  sobre as bolinhas;
- liga-se às jogadas relacionadas (ataque × resposta da defesa) pela relação
  proposta/resposta/contrarresposta que o Playbook já tem.

Critério de sucesso: a CT desenha uma jogada de 3 passos em menos de 2 minutos
sem ler instrução; uma atleta entende a jogada vendo a animação uma vez.

## 2. Pesquisa: o que as ferramentas existentes fazem

| Ferramenta | O que vale copiar | O que evitar |
|---|---|---|
| [My Handball System](https://myhandballsystem.com/en/program-2/) | Desenha-se só o **estado final de cada fase**; o programa gera as trajetórias. Numeração, cor das linhas e orientação da atleta para a bola são automáticas. | Software de desktop, pesado. |
| [Coach Tactic Board: Handball](https://apps.apple.com/us/app/coach-tactic-board-handball/id861263196) | Animação de jogadas, vários estilos de linha (sólida, pontilhada, curva), material de treino. | Muita opção de desenho livre, sem noção de passe/posse. |
| [Handball Tactic Board (Android)](https://play.google.com/store/apps/details?id=com.blackstar.apps.handballboard&hl=en) | Quadra inteira, meia quadra e terços; animação quadro a quadro. | Quadro a quadro manual é trabalhoso. |
| [Tactical Board Online](https://tactical-board.com/uk/handball) | Esquema estático como imagem e animação exportável em vídeo; biblioteca com jogadas clássicas (cruzamento, bloqueio duplo do pivô, 7º jogador de linha). | — |
| [planet.training](https://planet.training/drawing-tool-handball) | Formação inicial e depois **cenas** (até 30) animadas. | — |
| [Tactic3D](https://www.tactic3d.com/handball/tactic/handball-3D-tactic-plays.html) / [SportDraw](http://www.sportcode.co.rs/drawh.htm) | Compartilhar com as atletas em um clique; exportar MP4. | 3D não ajuda quem está na quadra. |

Conclusões:

1. **Passos (fases), não quadros.** A CT diz "onde cada uma termina" e "quem
   passa para quem"; o app interpola. É o padrão que mais reduz trabalho.
2. **Posse de bola é do modelo, não um desenho.** Passe liga duas atletas; o
   app sabe com quem a bola está em cada passo e impede passe de quem não tem
   a bola.
3. **Legenda fixa e universal** dos diagramas de treino: seta cheia =
   deslocamento, seta tracejada = passe, seta em zigue-zague = drible
   ([referência de convenções](https://hobbit.football/tools/soccer-drill-diagram-symbols-explained)).
   Para handebol somam-se arremesso, bloqueio e cortina.
4. **Vocabulário do handebol brasileiro.** As condutas táticas ofensivas mais
   descritas na literatura nacional são cruzamento, finta, bloqueio, cortina,
   desmarcação, engajamento, tabela e permuta
   ([Brazilian Journal of Development](https://ojs.brazilianjournals.com.br/ojs/index.php/BRJD/article/view/67784)).
   As ações do editor usam esses nomes.

## 3. Quadra (geometria IHF)

Fonte: [Regras do Jogo IHF, Regra 1](https://www.ihf.info/sites/default/files/2025-02/09A%20-%20Rules%20of%20the%20Game_Indoor%20Handball_E.pdf)
(conferir o PDF oficial antes de implementar; a rede deste ambiente não abriu o
arquivo, os números abaixo vêm de resumos que o citam).

- Quadra 40 m × 20 m; meia quadra 20 m × 20 m é a vista padrão do editor.
- Gol 3 m de largura.
- Linha da área (6 m): segmento reto de 3 m, paralelo e a 6 m da linha de
  gol, ligado à linha de fundo por dois quartos de círculo de raio 6 m
  centrados no canto interno posterior de cada trave.
- Linha de tiro livre (9 m): mesma construção com raio 9 m, tracejada
  (traços e espaços de 15 cm).
- Linha de 7 m: 1 m de comprimento, a 7 m.
- Linha do goleiro (4 m): 15 cm, a 4 m.

Coordenadas lógicas em **metros**: origem no centro da linha de gol,
`x ∈ [-10, 10]` (esquerda→direita de quem ataca), `y ≥ 0` em direção ao meio
da quadra. O SVG só escala. A prancheta de composição
(`static/playbook-board.js`) usa a mesma geometria. A versão do esquema
(`schema_version`) fica na coluna da tabela, não dentro do JSON.

## 4. Modelo da jogada

Uma jogada é um conteúdo do Playbook com `content_kind = "JOGADA"`, o mesmo
tipo que o editor guiado já usava (`PLAY` também é aceito). O desenho vive num
documento versionado, validado por `PlayDiagram` em
`handball/modules/playbook/schemas.py`:

```json
{
  "court": "HALF",
  "defense_system": "6x0",
  "actors": [
    {"id": "a-c",  "side": "ATTACK",  "position": "C",  "start": {"x": 0,    "y": 10.5}},
    {"id": "a-md", "side": "ATTACK",  "position": "MD", "start": {"x": 5.5,  "y": 9.5}},
    {"id": "d-m2", "side": "DEFENSE", "position": "M2", "start": {"x": 1.8,  "y": 6.6}},
    {"id": "g",    "side": "DEFENSE", "position": "GOL","start": {"x": 0,    "y": 1.0}}
  ],
  "ball": {"holder": "a-c"},
  "steps": [
    {
      "id": "s1",
      "label": "Cruzamento C→MD",
      "duration_s": 2.0,
      "note": "Central ataca o espaço M2–M3 e entrega nas costas.",
      "actions": [
        {"type": "MOVE", "actor": "a-c",  "to": {"x": 2.5, "y": 8.0}},
        {"type": "MOVE", "actor": "a-md", "to": {"x": 1.0, "y": 9.0}, "via": [{"x": 3.5, "y": 10.0}]},
        {"type": "PASS", "actor": "a-c", "target": "a-md", "at": 0.7, "kind": "DIRECT"}
      ]
    }
  ]
}
```

Regras do modelo:

- **IDs estáveis** para ator e passo, para que treino, instância e revisões
  apontem para o mesmo objeto (princípio já fixado em
  [ARQUITETURA.md](ARQUITETURA.md)).
- Posição do ator usa os códigos que já existem (`PE ME C MD PD PV GOL`;
  defesa `M1 M2 M3 AVANCADO`). É isso que liga a jogada às filas do treino.
- O estado final de um passo é o inicial do seguinte. Quem não tem ação fica
  parado.
- `at` (0–1) diz em que momento do passo o passe/arremesso acontece; por
  padrão, depois dos deslocamentos.
- Validação no servidor: passe só de quem tem a bola; um ator por ação de
  deslocamento por passo; coordenadas dentro da quadra; ator de linha não
  termina dentro da área de 6 m (aviso, não erro: a CT pode desenhar uma
  infiltração com salto).

### Ações

| Ação | Desenho | Uso |
|---|---|---|
| `MOVE` deslocamento | seta cheia, reta ou curva (`via`) | corrida, desmarcação, permuta, subida/deslize da defesa |
| `PASS` passe | seta tracejada entre atletas; `kind`: direto, picado, por cima | tabela, entrega no cruzamento |
| `DRIBBLE` drible | zigue-zague | progressão com bola |
| `SHOT` arremesso | seta dupla até o gol; zona do gol 1–9 opcional | finalização |
| `SCREEN` bloqueio | traço em "T" na frente da defensora | bloqueio do pivô |
| `CURTAIN` cortina | traço duplo | cortina para arremesso de fora |
| `FEINT` finta | marcador na atleta | finta, engajamento |

Defesa usa `MOVE` (deslize, subida, troca) e tem, opcional, posição inicial
automática pelo sistema (`6x0`, `5x1`; `3x2` e `4x2` depois).

## 5. Experiência de uso

Pensado para a CT na beira da quadra, no celular.

1. **Começar**: "Nova jogada" oferece modelos: *Ataque posicional × 6x0*,
   *× 5x1*, *Contra-ataque*, *Tiro de 7 m*, *Ataque sem defesa* e as
   jogadas do catálogo. Nunca uma quadra vazia sem ninguém.
2. **Desenhar um passo**: tocar numa atleta abre uma barra curta com
   *Correr · Passar · Driblar · Arremessar · Bloqueio · Cortina*.
   Correr = arrastar até o destino (trajetória curva, `via`, só pelos
   modelos por enquanto).
   Passar = tocar em quem recebe. O app só oferece "Passar" para quem tem a bola.
3. **Próximo passo**: botão grande "+ Passo" congela o final como início do
   seguinte. Cada passo tem um nome curto opcional ("Cruzamento C→MD").
4. **Ver**: ▶ toca tudo; ◀ ▶ navegam passo a passo; velocidade 0,5× / 1×.
   Com "movimento reduzido" ligado no sistema, só passo a passo.
5. **Salvar**: salvar cria revisão (o Playbook já versiona conteúdo).
   Desfazer/refazer dentro do rascunho.
6. **Legenda sempre visível** logo abaixo da quadra.

Acessibilidade: toda ação por arraste tem alternativa por botões e teclado
(Tab chega às atletas, Enter seleciona ou conclui passe/bloqueio, setas movem
0,5 m, Esc cancela, Ctrl+Z desfaz); botões com 44 px; nada depende só de cor
(ataque = círculo cheio com a sigla, defesa = círculo vazado, goleiro =
triângulo). Limite conhecido: no celular, a atleta desenhada na quadra de
20 m tem cerca de 2 cm de área de toque, abaixo dos 44 px recomendados; a
alternativa é o teclado ou um tablet.

## 6. Integração com o treino e a chamada

- **Exercícios de hoje** (botão na chamada) lista jogadas junto com os
  exercícios. Uma jogada escolhida vira bloco do roteiro.
- **Papéis automáticos**: as posições de ataque da jogada viram as filas; as
  posições de defesa viram as filas da defesa. Nada a preencher.
- **Instância com nomes** (pendente): aberta a partir do treino, a quadra
  mostraria o nome de quem está na frente de cada fila. O player já aceita
  nomes; falta a ligação com as filas.
- **Atleta**: vê o roteiro com as filas e abre a jogada animada ("▶ Ver
  jogada"). Não vê camadas, rascunhos nem notas da CT.
- **Relações**: "Ataque > contra 6x0 > X" e "Defesa > 6x0 > X" são conteúdos
  ligados por `RESPONSE`/`COUNTERRESPONSE`; a página da jogada mostra
  "resposta da defesa ▶" e abre a outra animação.
- **Imagem estática**: cada passo exporta PNG (para a mensagem do grupo, se a
  CT quiser). Vídeo MP4 fica para a fase de vídeo já prevista em
  [ENTREGA.md](ENTREGA.md).

## 7. Persistência e fases

| Fase | Entrega | Classificação | Estado |
|---|---|---|---|
| J0 | Geometria IHF (`static/court-ihf.js`) na prancheta e no editor; renderizador e animação (`static/play-diagram.js`). | APP_ONLY | feito |
| J1 | Tabelas `playbook_play_diagrams` e `playbook_play_diagram_revisions` (v15) + `GET/PUT /api/v1/playbook/contents/{id}/diagram` com revisão-base (409 em conflito). | **DB_MIGRATION** | feito |
| J2 | Editor (`/app/playbook/jogadas/nova`, `/app/playbook/jogadas/{id}`), 15 modelos iniciais (`play_templates.py`), validação de posse no servidor. | APP_ONLY sobre J1 | feito |
| J3 | Jogada como bloco do treino, filas pelas posições desenhadas, visão animada para a atleta. | APP_ONLY sobre J1 | feito |
| J4 | Relações ataque × defesa: já navegáveis pelo Playbook. Exportar PNG por passo. | APP_ONLY | PNG pendente |
| J5 | Vídeo MP4 da jogada. | Fase de vídeo da ENTREGA | pendente |

Pendências conhecidas: nomes reais sobre as bolinhas quando a jogada é aberta
a partir do treino (o player já aceita `names`, falta ligar a primeira onda
de cada fila); exportação PNG; zona do arremesso escolhida no editor (hoje
só pelo JSON). Os modelos com nome do catálogo (X, Desdobre, Islândia…)
chegam só com a formação contra 6x0, porque o movimento é do time; o
cruzamento C → MD vem com passos de exemplo.

Não usar `notes`, `steps`, anexo `.json` ou `playbook_exercise_specs.spec_json`
como atalho para guardar o desenho: mudar o contrato de um JSON persistido
também é `DB_MIGRATION` (ver [ENTREGA.md](ENTREGA.md)). Se a ordenação de
defesa (ver [CHAMADA-TREINO.md](CHAMADA-TREINO.md)) também for aprovada, as
duas mudanças podem sair na **mesma** manutenção, com um único backup.

## 8. Aceite

| Cenário | Evidência |
|---|---|
| Desenho rápido | Jogada de 3 passos desenhada no celular sem instrução. |
| Posse | Passe de quem não tem a bola é recusado na tela e no servidor. |
| Determinismo | Mesmo JSON gera a mesma animação em Chromium e WebKit. |
| Geometria | Linhas de 6 m, 9 m, 7 m e 4 m nas medidas IHF, conferidas por teste de coordenadas. |
| Treino | Jogada escolhida no dia gera filas pelas posições, sem papel digitado. |
| Atleta | Vê jogada publicada com nomes; não vê rascunho, camada nem nota. |
| Revisão | Duas edições simultâneas: a segunda recebe 409 e não perde o rascunho. |
| Acessibilidade | Teclado cria passe e deslocamento; movimento reduzido respeitado. |
