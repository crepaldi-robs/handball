# Instruções para agentes de código

## Objetivo

Manter um registrador local, simples e auditável para confirmações e presenças
nos treinos.

## Regras de domínio

1. Situação da confirmação e presença real são campos diferentes.
2. Uma chamada aberta não transforma automaticamente caixa desmarcada em ausência.
3. O botão de encerramento transforma todos os registros ainda não apurados em ausência.
4. Toda mudança em confirmação, presença ou observação deve gerar auditoria.
5. O banco SQLite do usuário não deve ser apagado nem recriado durante migrações.
6. Manter compatibilidade com Windows, VSCode e PowerShell.
7. Textos e arquivos devem permanecer em UTF-8.
8. O PC/servidor é a fonte de verdade; conflitos offline não o sobrescrevem.
9. Operações móveis precisam ser idempotentes e versionadas.
10. Não expor a porta local diretamente nem misturar este projeto com `../site`.
11. Configuração, hash de senha, banco e backups não entram no Git.
12. Ler `docs/SITE-INTEGRATION-CONTRACT.md` antes de alterar hostname, rotas
    públicas, autenticação, PWA, instalador, banco ou qualquer vínculo com o
    portal. O único vínculo permitido com `/roberto/` é um link HTTPS comum.
13. Atualização comum troca somente código e dependências: não executa DDL,
    migration ou seed sobre banco existente. Mudança de esquema é manutenção
    separada, explícita e previamente autorizada, sempre precedida de backup.
14. Startup e backup de instalação existente devem falhar se o SQLite estiver
    ausente ou incompatível; nunca criar silenciosamente uma base vazia.

## Agentes automatizados

15. Todo agente age **sob demanda humana**. Nada roda em cron ou por conta
    própria; o gatilho é sempre uma pessoa, por comentário no GitHub ou por
    chamada direta na máquina.
16. Na nuvem, o agente **nunca** faz push em `main`: trabalha em `agente/<n>-<slug>`
    e abre PR, que só é mergeável depois do portão de testes.
17. O agente não lê nem escreve `data/*.db`, `data/app-config.json`, `backups/`,
    nem qualquer caminho fora deste repositório. Ele não tem por que ver dados
    de atleta nem segredo de instalação.
18. Chave de API e segredo não aparecem em log, comentário, commit ou PR.
19. Pedido que implique DDL, migration ou seed deve ser recusado com referência à
    regra 13: mudança de esquema é `DB_MIGRATION`, decidida por uma pessoa.
20. Neste repositório, o agente principal usa a assinatura do ChatGPT/Codex
    somente para planejar, decompor, comparar pareceres e coordenar. Ele não usa
    ferramentas locais para ler, escrever, executar comandos ou testar.
21. Toda leitura, escrita, busca, comando e teste local deve ser delegado a um
    dos perfis `free_*`, cujo modelo é obrigatoriamente
    `auto/coding:free` no provedor `omniroute_project`.
22. Apenas `free_worker` escreve código e só um `free_worker` pode escrever por
    vez. Exploração e revisão somente leitura podem ocorrer em paralelo; testes
    começam depois de estabilizado o conjunto de arquivos.
23. `free_explorer`, `free_worker`, `free_tester`, `free_reviewer` e
    `free_peer_coordinator` são os únicos perfis delegáveis. Um executor
    gratuito não cria outros subagentes.
24. **No fluxo OmniRoute/Codex**, Claude Pro e Antigravity/Gemini são
    pareceristas de planejamento. São consultados exclusivamente por
    `free_peer_coordinator`, por meio de `scripts/consultar_planejadores.py`,
    sem ferramentas e a partir de um diretório vazio fora da árvore de código.
    As regras 20 a 24 governam esse fluxo; elas não descrevem o uso direto
    descrito na regra 28.
25. Credenciais de assinatura do ChatGPT, Claude ou Antigravity nunca passam
    pelo OmniRoute. O gateway aceita somente chaves de API com cota gratuita e
    deve falhar quando a rota `auto/coding:free` não tiver candidato.
26. O usuário opera este ecossistema apenas pelo lançador
    `scripts/codex-handball.ps1`. A configuração e o estado ficam em
    `%LOCALAPPDATA%\cpx\<hash-do-projeto>`, vinculados a este repositório por
    marcador e fora do OneDrive e do Git.
27. Nenhum agente cria commit, faz push, abre PR, publica release ou altera
    serviço externo sem uma autorização humana explícita e específica.

## Uso direto de um agente pago

28. Existem dois modos de uso, e só o primeiro é restringido pelas regras 20 a 24:

    - **Modo parecerista** — Claude Code ou Antigravity acionados de dentro do
      fluxo OmniRoute/Codex, por `free_peer_coordinator`. Continuam sem
      ferramentas, rodando em `planner-sandbox`, com `ANTHROPIC_BASE_URL`,
      `OMNIROUTE_*` e segredos removidos do ambiente-filho.
    - **Modo direto** — Claude Code ou Codex invocados pelo próprio usuário na
      raiz do repositório. Aqui o agente tem plenas capacidades de leitura,
      escrita e execução, e responde às demais regras deste arquivo como
      qualquer agente de código.

29. As duas ferramentas podem falar com o servidor MCP do OmniRoute deste
    projeto, em `http://127.0.0.1:32128/api/mcp/stream`. Configuração
    versionada em `.mcp.json` (Claude Code) e no bloco
    `[mcp_servers.omniroute_project]` de `.codex/codex-home.config.toml`
    (Codex). Requer `mcpEnabled=true` e `mcpTransport="streamable-http"` no
    OmniRoute.

    Esse MCP expõe **99 ferramentas**, e nem todas são de gestão do gateway.
    Nenhuma lê ou escreve arquivos deste repositório, mas existem superfícies
    de escrita e execução fora dele: `obsidian_*` (16 ferramentas, incluindo
    `obsidian_write_note`, `obsidian_delete_note` e `obsidian_execute_command`),
    `notion_*`, `plugin_install`/`plugin_activate`,
    `omniroute_github_skills_install` e `omniroute_skills_execute`. Na
    instalação atual as famílias `obsidian_*` e `notion_*` estão inertes por
    falta de credencial e não há plugin instalado, mas o `status` do MCP reporta
    `scopesEnforced: false` — não há restrição de escopo ativa. Antes de deixar
    um agente usar esse MCP sem supervisão, restrinja os escopos
    (`omniroute mcp scopes`).

30. A regra 25 continua valendo nos dois modos: credencial de assinatura nunca
    entra no gateway. Apontar um cliente **para** o OmniRoute é permitido;
    entregar a credencial da assinatura **ao** OmniRoute, não.

## Verificação obrigatória

Antes de concluir uma alteração:

```powershell
.\scripts\test.ps1
```

Também execute `python -m compileall -q app.py attendance handball tests` e valide a PWA
em WebKit quando Node.js/Playwright estiverem disponíveis.

## Histórico Git

Preservar um histórico legível com Conventional Commits em português. Cada
commit deve representar uma mudança lógica, manter `main` utilizável e excluir
banco, configuração, senhas, backups, exportações e ambiente virtual. Antes de
commitar, revisar `git diff --cached` e executar as verificações acima. Não
reescrever histórico já publicado sem autorização explícita.
