# Ecossistema de agentes do projeto

Esta é a configuração operacional do `registrador-presencas`. Ela não muda o
Codex global, não altera `../site`, não toca no banco persistente e não coloca
credenciais no Git.

Última revisão: **26/07/2026**.

## Resultado pretendido

Dentro do fluxo OmniRoute/Codex, o usuário conversa somente com o Codex. A
separação é:

| Papel | Cliente e conta | Pode acessar o repositório? |
| --- | --- | --- |
| Planner principal | Codex com login da assinatura ChatGPT | Não; apenas coordena |
| Segundo parecer | Claude Code com Claude Pro | Não; modo `plan`, sem tools |
| Segundo parecer | Antigravity com a conta Google | Não; modo `plan` e sandbox |
| Exploração | `free_explorer` via OmniRoute | Sim, somente leitura |
| Implementação | `free_worker` via OmniRoute | Sim, leitura e escrita |
| Testes | `free_tester` via OmniRoute | Sim, sem editar código-fonte |
| Revisão | `free_reviewer` via OmniRoute | Sim, somente leitura |

Essa tabela descreve **apenas** o fluxo acima. Ela não proíbe o uso direto: o
usuário também pode abrir o Claude Code ou o Codex na raiz do repositório e
trabalhar com plenas capacidades, sem passar por `free_peer_coordinator`. Nesse
modo direto valem as demais regras do `AGENTS.md`, não a linha "sem tools" da
tabela. A distinção está formalizada na regra 28 do `AGENTS.md`.

Os executores usam exclusivamente `auto/coding:free`. Essa rota do OmniRoute
3.8.48 falha quando não existe candidato gratuito; não cai silenciosamente no
pool pago. As credenciais de ChatGPT, Claude e Antigravity nunca são entregues
ao gateway.

Na instalação validada, o OmniRoute já expôs gratuitamente `oc/big-pickle`,
`oc/qwen3.6-plus-free`, `oc/deepseek-v4-flash-free`,
`oc/minimax-m2.5-free`, `oc/minimax-m3-free` e outras rotas temporárias. O
smoke test via Responses API respondeu e reportou custo
`0.0000000000`. Portanto, o sistema começa funcionando sem nova conta de API;
as contas abaixo aumentam diversidade e resiliência.

## Instalação inicial, na ordem

Abra **PowerShell 7** no VSCode e cole:

```powershell
cd "C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\ecossistema-agentes.ps1 -Acao Configurar
```

O script faz quatro coisas:

1. cria um runtime curto e hashado em `%LOCALAPPDATA%\cpx`, fora do OneDrive;
2. cria um armazenamento OmniRoute exclusivo na porta `32128`;
3. cria um `CODEX_HOME` exclusivo com os cinco perfis `free_*`;
4. abre o login do Codex se essa instalação isolada ainda não estiver
   autenticada. Escolha **Sign in with ChatGPT** e use a conta paga.

Node.js, OmniRoute, Claude Code e Antigravity já são detectados por caminho
absoluto; nada é adicionado permanentemente ao `PATH`.

## Contas gratuitas para aumentar a redundância

Abra o painel:

```powershell
.\scripts\ecossistema-agentes.ps1 -Acao AbrirPainel
```

Cadastre os provedores abaixo em **Providers > Add provider**. Quando existir
um conector nativo, use-o; caso contrário, escolha o conector
OpenAI-compatible e preencha `Base URL`, chave e modelos.

### 1. Z.AI — primeira prioridade chinesa

1. Crie ou acesse a conta na
   [Z.AI Open Platform](https://z.ai/manage-apikey/apikey-list).
2. Crie uma API key.
3. No OmniRoute, use:
   - Base URL: `https://api.z.ai/api/paas/v4/`
   - Modelo gratuito: `glm-4.7-flash`
4. Não cadastre `glm-5.2`, `glm-5.1`, `glm-5` ou `glm-4.7` comum: são pagos.
5. Teste a conexão no OmniRoute.

A tabela oficial marca `GLM-4.7-Flash` e `GLM-4.5-Flash` como gratuitos;
“cached input storage grátis” em outros modelos não significa inferência
grátis: [preços Z.AI](https://docs.z.ai/guides/overview/pricing).

### 2. Alibaba Model Studio — segunda prioridade chinesa

1. Crie a conta no Alibaba Cloud.
2. Ative o **Model Studio na região Singapore**.
3. Na página **Free Quota**, ligue **Free Quota Only** para cada modelo que
   será usado. Essa opção faz a API parar com `403` quando a cota acaba e evita
   cobrança posterior.
4. Crie uma API key na mesma região.
5. No OmniRoute, use:
   - Base URL:
     `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
   - somente os modelos que a página Free Quota da sua conta mostrar com saldo;
   - nunca habilite fallback para um modelo fora da quota.
6. Teste a conexão.

Referências oficiais: [obter a API
key](https://www.alibabacloud.com/help/en/model-studio/get-api-key),
[quota gratuita](https://www.alibabacloud.com/help/en/model-studio/new-free-quota),
[Free Quota
Only](https://www.alibabacloud.com/help/en/model-studio/model-usage-statistics)
e [Base URL de
Singapore](https://www.alibabacloud.com/help/en/model-studio/base-url).

### 3. OpenRouter — agregador recomendado

1. Crie uma conta e uma API key em
   [OpenRouter Keys](https://openrouter.ai/settings/keys).
2. Não faça top-up e não adicione forma de pagamento.
3. No OmniRoute, use:
   - Base URL: `https://openrouter.ai/api/v1`
   - Modelo: `openrouter/free`
   - modelos específicos: apenas IDs terminados em `:free`.
4. Teste a conexão.

O Free Models Router é gratuito, mas os modelos disponíveis e os limites mudam.
Ele costuma incluir famílias Qwen e DeepSeek; use-o também para Kimi, MiniMax
ou GLM apenas quando o catálogo mostrar explicitamente `:free`. Referências:
[roteador gratuito](https://openrouter.ai/docs/guides/routing/routers/free-router)
e [sufixo `:free`](https://openrouter.ai/docs/guides/routing/model-variants/free).

### 4. Google AI Studio — recomendável

A assinatura educacional usada no Antigravity não é uma cota de API e não deve
ser colocada no OmniRoute. Para execução:

1. crie uma chave separada em
   [Google AI Studio](https://aistudio.google.com/app/apikey);
2. confirme que o projeto aparece como **Free Tier**;
3. não clique em **Set up billing** e não vincule uma conta de cobrança;
4. adicione o conector Google/Gemini no OmniRoute e selecione apenas modelos
   marcados como gratuitos na conta;
5. teste a conexão.

Contas novas começam no Free Tier; vincular billing muda a condição:
[documentação de billing do Gemini
API](https://ai.google.dev/gemini-api/docs/billing).

### 5. Groq — recomendável

1. crie uma chave no [Groq
   Console](https://console.groq.com/keys);
2. adicione o conector Groq no OmniRoute;
3. se precisar do modo genérico, use
   `https://api.groq.com/openai/v1`;
4. habilite somente modelos que o console disponibilizar sem cobrança;
5. teste a conexão.

A Base URL é a indicada na [compatibilidade OpenAI da
Groq](https://console.groq.com/docs/openai).

## Como tratar as empresas chinesas mais fortes

O Artificial Analysis ranqueia **modelos**, não empresas. Em 26/07/2026, o
líder open-weights era o GLM-5.2 da Z.AI; MiniMax-M3, DeepSeek V4 Pro e Kimi
K2.6 também estavam no grupo de fronteira
([leaderboard](https://artificialanalysis.ai/models/),
[análise do GLM-5.2](https://artificialanalysis.ai/articles/glm-5-2-is-the-new-leading-open-weights-model-on-the-artificial-analysis-intelligence-index/)).
Alibaba/Qwen e Xiaomi também aparecem no conjunto de organizações comparadas.

Isso não significa que seus melhores modelos tenham API gratuita. A política
correta é:

| Empresa/família | Caminho neste projeto |
| --- | --- |
| Z.AI / GLM | API nativa, somente `glm-4.7-flash` |
| Alibaba / Qwen | Model Studio Singapore com `Free Quota Only` |
| DeepSeek | OpenRouter, somente variante `:free` |
| Moonshot / Kimi | OpenRouter, somente se houver variante `:free` |
| MiniMax | OpenRouter, somente se houver variante `:free` |
| Xiaomi / MiMo | OpenRouter, somente se houver variante `:free` |

Não cadastre as APIs diretas de DeepSeek, Kimi, MiniMax ou Xiaomi se elas
exigirem saldo, cartão, prepay ou cobrança por token. “Modelo aberto” não
significa “API grátis”.

## Primeira abertura do Codex

O ecossistema básico já pode ser usado. Execute:

```powershell
.\scripts\codex-handball.ps1
```

Na primeira sessão:

1. digite `/hooks`;
2. selecione o hook vindo de `.codex/hooks.json`;
3. revise e marque-o como confiável;
4. volte à conversa.

Essa confirmação única não é automatizada: o Codex registra confiança pelo
hash exato do hook para impedir que um repositório altere comandos de segurança
sem avisar ([documentação oficial de
hooks](https://learn.chatgpt.com/docs/hooks)).

Depois, use um pedido normal, por exemplo:

```text
Faça uma peer-review completa do estado atual para preparar o próximo commit.
Use os pareceres do Claude e do Antigravity no planejamento, mas delegue toda
leitura, escrita e execução aos agentes gratuitos. Não faça o commit.
```

O fluxo esperado é:

1. `free_explorer` levanta estado, diff e arquitetura;
2. o Codex pago formula uma hipótese de plano;
3. `free_peer_coordinator` consulta Claude Pro e Antigravity sem expor o repo;
4. o Codex reconcilia os pareceres;
5. um único `free_worker` implementa o escopo autorizado;
6. `free_tester` e `free_reviewer` verificam o resultado;
7. o Codex entrega a revisão final; commit continua sendo decisão humana.

## Diagnóstico e operação diária

Verificar tudo:

```powershell
.\scripts\ecossistema-agentes.ps1 -Acao Diagnosticar
```

Abrir o Codex:

```powershell
.\scripts\codex-handball.ps1
```

Encerrar somente o OmniRoute deste projeto:

```powershell
.\scripts\ecossistema-agentes.ps1 -Acao Parar
```

O lançador antigo continua funcionando como ponte:

```powershell
.\scripts\agente.ps1 -Pedido "revise o próximo commit"
```

## Servidor MCP do OmniRoute

O mesmo OmniRoute da porta `32128` expõe um servidor MCP em
`http://127.0.0.1:32128/api/mcp/stream`, com **99 ferramentas** (`tools/list` do
servidor ao vivo; `GET /api/mcp/tools` mostra só as 36 mapeadas para endpoints
REST).

A maioria é de gestão do próprio gateway — saúde, combos, quota, custo, cache,
compressão, catálogo de modelos. Nenhuma lê ou escreve arquivos deste
repositório. Mas há superfícies de escrita e execução **fora** dele que valem
atenção antes de liberar uso não supervisionado:

| Família | Risco |
| --- | --- |
| `obsidian_*` (16) | escreve, apaga e move notas; `obsidian_execute_command` |
| `notion_*` (6) | lê e anexa blocos em bases do Notion |
| `plugin_*` (8) | instala, ativa e desinstala plugins |
| `omniroute_github_skills_install` | instala skills vindas do GitHub |
| `omniroute_skills_execute` | executa skills |
| `omniroute_web_search`, `omniroute_web_fetch` | saída de rede |

Na instalação atual, `obsidian_*` e `notion_*` estão inertes por falta de
credencial (`obsidian_check_status` retorna "API token not configured") e
`plugin_list` volta vazio. Ainda assim, `GET /api/mcp/status` reporta
`scopesEnforced: false`: não há restrição de escopo ativa. Para restringir, veja
`omniroute mcp scopes`.

Ele **não vem ligado**. Sem as duas chaves abaixo o endpoint responde `503`
(desabilitado) ou `400` (`MCP transport is set to "stdio"`):

```powershell
Invoke-WebRequest -Method Patch -Uri "http://127.0.0.1:32128/api/settings" `
  -ContentType "application/json" -Body '{"mcpEnabled":true}'
Invoke-WebRequest -Method Patch -Uri "http://127.0.0.1:32128/api/settings" `
  -ContentType "application/json" -Body '{"mcpTransport":"streamable-http"}'
Invoke-RestMethod "http://127.0.0.1:32128/api/mcp/status"   # espera online=True
```

As configurações dos clientes são versionadas: `.mcp.json` para o Claude Code e
`[mcp_servers.omniroute_project]` em `.codex/codex-home.config.toml` para o
Codex. O bloco do Codex precisa ficar no repositório porque
`ecossistema-agentes.ps1` recopia esse arquivo sobre o `CODEX_HOME` isolado a
cada execução — um `codex mcp add` direto seria sobrescrito.

Servidor vindo de `.mcp.json` aparece como `⏸ Pending approval` até ser aprovado
uma vez numa sessão interativa do Claude Code. Isso é do próprio Claude Code e
não é contornável.

## Limitações conhecidas do diagnóstico

Duas falhas de `scripts/ecossistema-agentes.ps1` afetam **apenas o relatório**,
não o gateway:

1. `Test-OmniReady` usa `-TimeoutSec 3`, mas `/v1/models` responde em 6,6–11 s
   nesta máquina (265 modelos). O diagnóstico conclui "OmniRoute do projeto nao
   esta ativo" mesmo com o servidor no ar e **pula em silêncio** o catálogo, o
   smoke test de custo zero e a lista de provedores.
2. `Show-Diagnostics` chama `omniroute providers list` sem antes rodar
   `Set-OmniProcessEnvironment`. Sem `DATA_DIR`, a CLI lê o armazenamento
   **global** e imprime "No providers configured", em vez dos 10 provedores
   deste projeto.

Enquanto isso não for corrigido, verifique manualmente com `-TimeoutSec` maior e
com `DATA_DIR` apontando para `%LOCALAPPDATA%\cpx\<hash>\omniroute`.

## Garantias e limitações

- `%LOCALAPPDATA%\cpx\<hash-do-projeto>` contém estado, chaves e autenticação.
  Um marcador com o caminho absoluto impede que o mesmo runtime seja aceito por
  outro projeto. Nada sensível fica no OneDrive ou no Git.
- A porta `32128` e o `DATA_DIR` são exclusivos deste projeto.
- O Codex global e o OmniRoute global não são modificados.
- O planner principal começa em sandbox `read-only`; o hook bloqueia também
  leitura por ferramentas e permite apenas coordenação.
- O hook é uma barreira determinística útil, não uma fronteira absoluta contra
  toda possível especialização de ferramenta. `AGENTS.md`, sandbox e perfis
  separados formam as camadas adicionais.
- Se todos os provedores gratuitos estiverem sem cota, a execução para. Essa
  falha é intencional e é preferível a uma cobrança.
- Modelos gratuitos do OpenCode Zen são temporários e podem usar prompts e
  respostas para melhoria durante o período grátis. Por isso os agentes não
  recebem dados pessoais, banco, configuração de instalação ou segredos. Veja
  a política e a lista corrente em
  [OpenCode Zen](https://opencode.ai/docs/zen).
- Cotas, catálogos e preços mudam. Antes de adicionar um modelo, confirme que o
  preço de entrada **e** saída é zero ou que existe um bloqueio de
  “free-quota-only”.

## Arquivos que definem a política

- `.codex/config.toml`: ativa hooks e multiagente no projeto.
- `.codex/codex-home.config.toml`: provedor local e servidor MCP copiados para o
  CODEX_HOME isolado.
- `.mcp.json`: servidor MCP do OmniRoute para o Claude Code.
- `.codex/agent-templates/*.toml`: perfis gratuitos.
- `.codex/hooks.json` e `.codex/hooks/enforce_planner_policy.py`: bloqueio
  planner/executor.
- `scripts/ecossistema-agentes.ps1`: bootstrap, diagnóstico e processo local.
- `scripts/codex-handball.ps1`: única entrada de uso cotidiano.
- `scripts/consultar_planejadores.py`: Claude e Antigravity em modo de plano.
- `AGENTS.md`: regras obrigatórias do repositório.

O `CODEX_HOME` separado é necessário porque, por segurança, o Codex ignora
`model_provider` e `model_providers` em `.codex/config.toml` de projeto. A
limitação e a precedência de configuração estão na [documentação oficial do
Codex](https://learn.chatgpt.com/docs/config-file/config-basic).
