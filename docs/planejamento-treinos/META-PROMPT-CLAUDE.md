# Meta-prompt · implementação futura

Este texto orienta uma tarefa futura de Claude em uso direto. A documentação atual não concede autorização de implementação, migração ou implantação; a solicitação humana que acompanhar este prompt define o escopo permitido.

---

Trabalhe em `C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas`, Windows/PowerShell 7, UTF-8. Leia AGENTS.md e docs/SITE-INTEGRATION-CONTRACT.md. Observe regra 28 para uso direto, sem se apresentar como executor gratuito OmniRoute. Preserve alterações locais. Não leia data/*.db, configuração privada, backups ou segredos. Sem commit, push, PR, publicação, migração persistente ou serviço externo sem autorização explícita específica.

Leia docs/planejamento-treinos/README.md, DECISOES.md, MAPA-DO-CODIGO.md, ARQUITETURA.md, UX.md, ENTREGA.md e VERIFICACAO.md. Revalide contra checkout real; base documental: 69e87657a9985ed1839833c6984035ade7bba315, não produção. Decisão confirmada, recomendação e questão aberta são categorias distintas. Atualize documentos quando houver nova resposta humana.

## Resultado

No Playbook: participantes previstos → proposta → ajustes/fixações do técnico → revisão salva → mensagem e prancheta consistentes. Não criar taxonomia de jogadores/arquétipos.

Ataque e defesa independentes representam nível habitual. Preservar perguntas/ranks, contextualizando desempenho ao longo dos treinos. Desconhecido é null, nunca zero; não copiar LINE para duas dimensões nem impor anticorrelação. Goleiro tem tratamento próprio, separado da defesa de linha.

**Equilibrado é o default, apenas primeiro selecionado/apresentado. Os dois modos têm igual hierarquia visual, acesso e destaque.** Direcionado não é opção avançada/secundária. Ambos existem em blocos e coletivo final; modo ativo aparece explicitamente na mensagem e na quadra/mapinha.

Equilibrado aproxima ataques entre equipes e defesas entre equipes e examina ambos os sentidos. Direcionado significa ataque forte contra defesa forte, inverso secundário explícito. Expressão coloquial posterior “forte contra fraco” não autoriza redefinir como times desiguais; confirmar nomenclatura sem alterar semântica. Não igualar escalas nem prometer probabilidade/ótimo global. Expor método, cobertura e truncamento.

A prioridade entre equilíbrio, posições e participação/tempo de quadra está aberta. Não herdar pesos do legado nem decidir silenciosamente. Também validar goleiros, cobertura parcial, elegibilidade e transformação ordinal antes da política automatizada definitiva. Perguntar somente o necessário para a etapa dependente, uma questão concreta por vez, opções e consequências; continuar trabalho independente autorizado.

## Integração

Inspecione ranking/service/schemas/router do Elenco; presencas/planner.py/service.py; playbook/schemas.py/service.py/router.py; repositories/roster.py/playbook.py; migrations/contracts/guard; templates/scripts do mapa. Reuse planos, sessões, séries, papéis e revisões. Histórico não equivale a controle de concorrência. Preserve adaptadores por evento e distinga sessão de presença de Playbook.

Separe perfil habitual, instância de treino e jogada por papel. IDs de slots, coordenadas lógicas, revisão de modelo e mapeamento de ocupantes existem desde a fundação. Clique substitui; drag reposiciona; teclado faz ambos. Fixação de ocupante e posição são distintas. Recálculo preserva fixações e mostra diff/impacto. Vagas/conflitos são estados explícitos.

Snapshot salvo alimenta mensagem/prancheta. Edição posterior gera rascunho/nova revisão e marca mensagem antiga. Ranks/notas internas não entram na mensagem nem em payload de atleta. Sem envio automático.

## Execução

1. Inspecione regras, estado Git e referências sem dados privados; registre plano curto e classificação.
2. Confirme o escopo humano que acompanha este prompt. Não trate esta especificação como autorização de DDL, seed, conversão ou contrato persistente novo.
3. Defina contratos tipados, legado, autorização por time, base_revision/idempotência e diagnóstico antes de integrar persistência. Não esconder estrutura em texto/JSON para fugir a DB_MIGRATION.
4. Entregue fatias: participantes/prancheta manual; avaliação/composição assistida após decisões; revisão/mensagem. Aproveite módulos existentes e documente arquivos novos.
5. Use fixtures fictícias: nulls/empates, forte/fraco nas duas dimensões, goleiros, fixações impossíveis, última hora, concorrência e acesso entre times.
6. Reuse design system, valide desktop/móvel/tablet e WebKit disponível. Tokens não comprovam acessibilidade integral.
7. Execute verificações de AGENTS.md em testes sem banco instalado; separe falhas preexistentes. Revise diff/segredos/escopo.
8. Relate arquivos absolutos, alterações, resultados de testes, pendências, decisões abertas e classe APP_ONLY/DB_MIGRATION. Local não significa instalado/migrado/publicado.

Persistência nova sem autorização: conclua trabalho independente permitido e apresente plano concreto de compatibilidade, migração, backup, verificação e reversão para decisão separada. Nunca aplique sobre base pessoal ou crie banco paralelo para contornar o gate. Não toque portal/site, DNS, Tunnel ou serviço.

## Horizonte completo

Após composição: etapas com duração, movimentos, passe/posse/finalização e reprodução determinística. Vídeo automático fica explicitamente planejado como fase posterior, mesma timeline/revisão, limites/cancelamento/custos CPU/armazenamento e validação Windows. Imagem estática não define tempo. Não instalar renderizador sem escopo aprovado. Atributos específicos, lateralidade, rotação automática e tempo real não são campos obrigatórios da V1.

Pronto para a fatia: modos igualmente acessíveis, default e modo ativo corretos; desconhecidos preservados; fixações respeitadas; mensagem/quadra na mesma revisão; troca não altera modelo; falha não perde rascunho; autorização no backend; verificações reportadas. Dependência bloqueada deve ser declarada, sem chamar fluxo incompleto de concluído.
