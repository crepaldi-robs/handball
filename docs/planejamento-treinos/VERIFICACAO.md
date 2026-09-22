# Registro de verificação documental

Data da inspeção: 21/09/2026. Base: `69e87657a9985ed1839833c6984035ade7bba315`.

## Escopo comprovado

- Estado inicial Git sem alterações reportadas; estado após autoria contém apenas `?? docs/planejamento-treinos/`.
- Nenhuma implementação de app, alteração de schema ou migração executada; nenhum banco pessoal, configuração privada ou backup lido.
- Sem commit, push, publicação, envio de mensagem a atletas ou modificação de serviço.
- Recursos existentes descritos por leitura de código; produção e estado operacional não inspecionados.
- Decisão final recebida e incorporada: equilibrado default, modos igualmente destacados, modo ativo na mensagem e quadra. Prioridade entre equilíbrio, posições e participação permanece aberta.

## Verificações

| Verificação | Resultado |
|---|---|
| UTF-8 estrito e ausência de caractere de substituição | Aprovado nos documentos. |
| Links locais do pacote | Aprovado em todos os 8 documentos na verificação final. |
| Caminhos diretos de arquivos existentes no mapa | 27 verificados. Dois caminhos futuros estão explicitamente classificados como propostas, não arquivos existentes. |
| Cercas Markdown e espaços finais | Aprovado. |
| `git diff --check` | Sem erros; como os documentos são novos/não rastreados, complementado pela inspeção direta acima. |
| `python -m compileall -q app.py attendance handball tests` via Python da .venv | Aprovado, código de saída 0. |
| `scripts/test.ps1` | 318 testes aprovados, 1 aviso, 270,87 s; código de saída 0. Aviso de depreciação Starlette/TestClient com httpx; nenhuma dependência alterada. |
| WebKit/PWA | Não executado: Playwright indisponível no Python da .venv e os módulos Node playwright/@playwright/test não resolvem no app. Node existe; não instalar dependências nem iniciar app para esta entrega exclusivamente documental. |

Testes do checkout atual não validam funcionalidades propostas. Não houve inspeção visual de uma prancheta implementada, porque ela não foi criada. O desenho de UX é especificação conceitual, não protótipo navegável. Geometria regulamentar detalhada da quadra deverá ser conferida em fonte oficial na implementação.

## Limitações e continuidade

Método ordinal, goleiros, cobertura incompleta, elegibilidade e prioridade dos objetivos ainda precisam de decisão. O meta-prompt orienta avançar nas partes independentes e perguntar uma questão concreta por vez. Persistência de dimensões e composição exige plano/classificação/autorização próprios; o JSON local_overrides não é exceção a esse gate.
