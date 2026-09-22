# Integração dos PRs 3, 5 e 6

## Escopo e atualização

Integração sobre `ea53f28`, sem alterar schema, migrações ou dados operacionais.
Classificação: **APP_ONLY**. O endpoint local `/ready` reportou schema 14 em
22/09/2026; o código continua suportando versões 1 a 14, com versão mais recente
14. A migração Google Calendar V14 já existia antes desta integração.

- PR #3: incorpora `69e8765` (exclusão de treinos cancelados na seleção da CT)
  e `6608bf9` (planejamento documentado). Os três commits anteriores de Google
  Calendar e Playbook já estavam na main.
- PR #5: incorpora `c328111`, removendo a orquestração antiga.
- PR #6: incorpora `b19f0c5`, com prévia manual da composição na prancheta.

A prancheta é um rascunho em memória: não salva composição, não implementa
sugestão automática nem ranking independente por ataque/defesa. Esses itens
continuam sendo trabalho futuro descrito em `planejamento-treinos/`.
Google Calendar mantém seus requisitos de configuração e autorização OAuth.

## Correções de integração

- Descarta respostas de preview obsoletas, inclusive após trocar de sessão
  ou remover todos os blocos.
- Reinclusão remove a exclusão anterior; exclusão explícita funciona também
  para um confirmado que tenha sido reincluído manualmente.
- Falha ao carregar elenco permite nova tentativa.
- Redistribui posições automáticas quando muda o número de blocos, preservando
  as posições movidas manualmente.
- Cache PWA v19 inclui JavaScript e CSS da prancheta.
- Preserva exclusões de artefatos locais e estado antigo do gateway no Git.

## Verificação reproduzível

Resultado local: 333 testes aprovados; compileall, sintaxe JavaScript e
`git diff --check` aprovados. O cenário WebKit passou em oito etapas, sem
exceções JavaScript, incluindo resposta fora de ordem e layout móvel. O console
WebKit registrou bloqueios de estilo inline pela CSP; os fluxos e o desenho
da prancheta foram verificados sem flexibilizar essa política.

Suíte: `scripts/test.ps1`; compilação: `.venv/Scripts/python.exe -m compileall
-q app.py attendance handball tests`; JavaScript: `node --check
static/playbook-board.js`; whitespace: `git diff --check`.

O cenário WebKit usa uma base fictícia criada sob `output/playwright/`, sem
ler a configuração ou o banco real. O proxy autenticado só escuta em loopback;
encerre-o com Ctrl+C ao terminar. Execute na raiz do repositório:

```powershell
# Terminal 1: fixture isolada, com contas e senha exclusivamente de teste.
.\.venv\Scripts\python.exe -X utf8 tests/browser/serve_playbook_fixture.py

# Terminal 2: navegador e verificações.
npx --yes --package @playwright/cli playwright-cli -s=handball-merge open http://127.0.0.1:8879/app/playbook --browser webkit
npx --yes --package @playwright/cli playwright-cli -s=handball-merge run-code --filename tests/browser/check-playbook-board.js
npx --yes --package @playwright/cli playwright-cli -s=handball-merge close
```

Se necessário, instale o navegador com `playwright-cli install-browser webkit`
pelo mesmo pacote npx. O cenário verifica slots, inclusão/exclusão/reinclusão,
respostas fora de ordem, troca de modo, adição de blocos e captura móvel.
Artefatos ficam em `output/playwright/`, ignorados pelo Git.

Essa validação de código não equivale à ativação da release no servidor nem
a teste autenticado em um iPhone físico ou na conta Google real.
