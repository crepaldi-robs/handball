# Experiência visual proposta

## Fluxo e organização

Na sessão do Playbook: “Preparar treino”. Cabeçalho com título/data, revisão salva, estado do rascunho e participantes. Fluxo curto: Participantes → Composição → Prancheta → Revisar mensagem. Blocos/coletivo compartilham seletor Equilibrado/Direcionado; direcionado identifica sentido principal. Equilibrado começa selecionado. Ambos têm igual hierarquia visual, acesso e destaque: dois controles lado a lado, sem esconder direcionado em menu avançado. Mostrar o modo ativo no cabeçalho da quadra e na mensagem.

Desktop: blocos à esquerda, quadra central, contexto à direita; ações salvar/preview/desfazer no rodapé. Celular: uma coluna, quadra proporcional, detalhes em painel inferior sem ocultar alvo. Tablet horizontal pode usar duas colunas. Reusar tokens/temas/fontes locais; não criar identidade visual concorrente.

## Prancheta

Meia quadra, gol no topo, goleiro à frente da linha de gol, área de seis metros, atacantes/defensores numerados. Área com trecho central e arcos laterais, não círculo genérico de basquete. SVG responsivo recomendado; coordenadas lógicas em metros, linha de fundo y=0 e eixo central x=0. Conferir geometria regulamentar em fonte oficial IHF antes de implementar; esquema abaixo é conceitual, sem escala.

```text
             ┌── GOL ──┐
─────────────┴─────────┴──────────── linha de fundo
                  G
          ╭────────────────╮
        ╭─╯   área de 6 m   ╰─╮
        └────────────────────┘
          D1 D2 D3 D4 D5 D6
     A1          A6            A5
           A2    A3    A4

 Banco: [suplente] [suplente]   Ataque A → defesa B
```

Cor + forma/letra diferenciam grupos; nome curto legível e detalhes por seleção. Goleiro distinto, vaga com contorno e rótulo “Vaga”. Badge textual de fixação. Notas individuais não aparecem por padrão na quadra. Painel CT mostra ataque e defesa separadamente, cobertura e impacto da alteração, nunca uma barra única de força total.

## Gestos distintos

- Toque/clique seleciona papel e abre “Substituir ocupante”, lista elegível e impedimentos; não move token.
- Arrastar altera coordenadas; limiar distingue gesto de clique e impede abrir substituição no fim do drag. Pointer Events/captura sem sequestrar scroll fora da quadra.
- Teclado seleciona token, abre substituição por botão e reposiciona por controles direcionais; Escape cancela. Toda ação de drag tem alternativa sem arrastar.
- Fixar ocupante e fixar posição são independentes. Origem manual visível, com desfazer.
- Recalcular mostra diff/conflitos/impacto e permite aplicar/cancelar; nunca move fixado incompatível em silêncio.

Alvos recomendados de 44×44 CSS px, foco visível, ordem lógica, nomes acessíveis e anúncios de alteração/salvamento. Respeitar movimento reduzido. Não depender de cor/hover. Testar zoom 200%, nomes longos, orientação e teclado. Arrastar defensor não altera perfil funcional.

## Estados

| Estado | Resposta |
|---|---|
| Sem sessão/participantes | Orientar criar/selecionar sessão e incluir previstos. |
| Não avaliado | “Ataque não avaliado” / “Defesa não avaliada”; nunca 0. |
| Cobertura parcial | “4 de 6 avaliados em defesa”; sem selo de equilíbrio. |
| Sem goleiro/vagas | Vaga explícita, rascunho permitido, adaptação por ação humana. |
| Restrições impossíveis | Listar fixações/posições conflitantes e resolução. |
| Calculando | Cancelável; preservar composição válida anterior. |
| Rascunho alterado | “Não salvo” e ação salvar. |
| Salvando/falha | Impedir duplicação; preservar rascunho e retry idempotente. |
| Conflito 409 | Comparar servidor/rascunho sem perder nenhum. |
| Fonte mudou | Avisar participantes/perfis alterados; preview antes de adotar. |
| Mensagem antiga | Revisão de origem visível; regenerar após salvar. |
| Sem permissão | Bloqueio no servidor e explicação curta. |

Mensagem pública: sessão, horário conhecido, blocos, ocupantes, rotação planejada se definida, instruções públicas, modo ativo e revisão. Relatório CT em aba separada, nunca concatenado automaticamente. Copiar/exportar usa revisão da prancheta. Nenhum envio automático autorizado.
