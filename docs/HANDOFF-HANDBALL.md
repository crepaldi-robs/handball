# Handoff de publicação — Registro de Handebol

| Campo | Valor |
|---|---|
| Data do handoff | 20 de julho de 2026 |
| Última atualização de estado | 21 de julho de 2026 |
| Leitor esperado | agente trabalhando em `C:\Users\rober\OneDrive\Área de Trabalho\site` |
| Aplicação | `..\handball\registrador-presencas` |
| URL pública operacional no último teste | `https://handball.crepaldi.com.br/` |
| Auditoria da implantação | [`HANDBALL-DEPLOY-AUDIT-2026-07-21.md`](HANDBALL-DEPLOY-AUDIT-2026-07-21.md) |
| Runbook operacional | [`HANDBALL-OPERATIONS.md`](HANDBALL-OPERATIONS.md) |
| Contrato no repositório do app | `..\..\handball\registrador-presencas\docs\SITE-INTEGRATION-CONTRACT.md` |

## 0. Atualização de estado em 21/07/2026

Este handoff nasceu antes da instalação. A execução posterior foi consolidada
no relatório de auditoria vinculado acima. O estado conhecido na última
verificação é:

- correção de senha/ACL aprovada em 11 testes e registrada no commit `72cb9e3`;
- servidor instalado em `C:\ProgramData\CrepaldiHandball` e saudável em
  `http://127.0.0.1:8765/health`;
- tarefa `CrepaldiHandball` em execução, tarefa de backup configurada, SQLite e
  diretório de backups existentes;
- delegação de `crepaldi.com.br` migrada para
  `dawn.ns.cloudflare.com` e `nash.ns.cloudflare.com`, confirmada por 1.1.1.1 e
  8.8.8.8;
- site principal, `/roberto/`, envio e recebimento de e-mail confirmados pelo
  proprietário após a migração;
- túnel `crepaldi-handball` saudável, com uma réplica e rota publicada para
  `http://127.0.0.1:8765`;
- `https://handball.crepaldi.com.br/health` e a página pública de login
  carregaram corretamente;
- o link no portal `/roberto/` **ainda não foi implementado nem publicado**;
- login autenticado pela URL pública, gravação de teste, integridade SQLite,
  backup manual de marco, reboot/auto-start e PWA no iPhone continuam pendentes.

As seções de sequência abaixo continuam válidas como procedimento, mas toda
afirmação temporal anterior deve ser lida à luz deste estado e da matriz de
evidência da auditoria. O runbook é a fonte atual para operação e atualização.

## 1. Objetivo

Preparar a integração segura do Registro Oficial de Presenças com a casa de
Roberto na internet. A integração consiste em:

1. publicar o aplicativo dinâmico em um subdomínio próprio;
2. adicionar ao portal `/roberto/` apenas um acesso visual para esse subdomínio;
3. preservar integralmente o cofre, o desenho 50/50, o `noindex` e o processo
   manual de publicação do portal.

Este documento não autoriza o agente a acessar Hostinger, alterar DNS ou fazer
upload remoto. `AGENTS.md` continua sendo a autoridade superior deste
repositório.

## 2. Decisão de arquitetura

O aplicativo **não pode ser copiado para `public_html/roberto/`**. O portal é
HTML/CSS/JavaScript estático; o registro de handebol depende de FastAPI, SQLite,
autenticação, cookies, auditoria e sincronização offline.

Arquitetura aprovada:

```text
https://crepaldi.com.br/roberto/
        |
        +-- Hostinger: portal estático e cofre cifrado
        |
        +-- link para https://handball.crepaldi.com.br/
                            |
                            +-- Cloudflare Tunnel
                                  |
                                  +-- http://127.0.0.1:8765
                                        |
                                        +-- FastAPI + SQLite no PC Windows
```

Consequências:

- os dados dos atletas permanecem no PC, não no repositório do site;
- nenhuma porta do roteador deve ser aberta;
- desligar o PC ou o serviço torna o servidor indisponível;
- uma PWA já instalada pode usar a chamada cifrada offline, mas operações de
  servidor continuam indisponíveis;
- a aplicação atual usa caminhos absolutos como `/api/`, `/static/` e `/sw.js`.
  Hospedá-la em `/roberto/handball/` exigiria refatoração e não faz parte deste
  escopo.

## 3. Estado recebido

### Aplicativo de handebol

- Fonte: `..\handball\registrador-presencas`.
- Branch esperada: `main`.
- Commit de referência atualizado: `72cb9e3`.
- Suíte conhecida após a correção: 11 testes aprovados.
- Backend: FastAPI em `127.0.0.1:8765`.
- Saúde: `GET /health` deve responder `{"status":"ok"}`.
- Instalação permanente: `scripts\install-server.ps1`.
- Operação e domínio: `docs\DEPLOYMENT.md` no projeto do aplicativo.
- Banco de produção: `C:\ProgramData\CrepaldiHandball\data\presencas.db`.
- Backups: `C:\ProgramData\CrepaldiHandball\backups`, retenção de 30 cópias.

Servidor e subdomínio foram publicados e testados em 21/07/2026, mas isso é uma
fotografia, não monitoramento contínuo. Confirme novamente commit, testes e
saúde antes de integração, atualização ou publicação do portal.

### Portal `/roberto/`

- O worktree já contém alterações locais: não limpar, resetar, sobrescrever ou
  assumir que são descartáveis.
- O portal possui duas entradas equivalentes, pública e privada.
- O cofre é estático e cifrado localmente; não substituí-lo pela autenticação do
  aplicativo.
- A publicação é manual e limitada aos seis caminhos de
  `deploy-manifest.txt`.
- Não existe `.openai/hosting.json`. Não migrar o portal para OpenAI Sites apenas
  para incorporar o aplicativo.

## 4. Divisão de responsabilidades

### Agente deste repositório (`../site`)

Pode:

- inspecionar o projeto do aplicativo em modo somente leitura;
- preparar uma ligação visual para o subdomínio;
- atualizar documentação local estritamente necessária;
- executar testes, validação, empacotamento e dry-run locais;
- entregar ao proprietário o pacote e a lista exata de alterações.

Não pode:

- instalar ou iniciar o servidor de produção;
- acessar Hostinger ou suas credenciais;
- criar túnel, alterar nameservers ou registros DNS;
- fazer upload, deploy, sincronização ou exclusão remota;
- copiar código Python, banco, configuração, logs ou backups para este projeto.

### Proprietário

É responsável por:

- executar a instalação administrativa do servidor;
- definir a senha administrativa;
- inventariar e preservar DNS e e-mail;
- configurar o Cloudflare Tunnel e o hostname;
- realizar o upload manual do pacote `/roberto/` após revisar o dry-run;
- manter o PC ligado quando desejar acesso online.

## 5. Sequência de execução

### Fase A — verificar o aplicativo

No projeto `..\handball\registrador-presencas`, apenas para validação local:

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance tests
git status --short
git log -1 --oneline
```

Não avance se os testes falharem, houver segredo rastreado ou o estado do
aplicativo não puder ser explicado.

### Fase B — instalação do servidor pelo proprietário

O proprietário abre PowerShell 7 como Administrador no projeto do aplicativo e
executa:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-server.ps1
```

O instalador deve criar e iniciar as tarefas `CrepaldiHandball` e
`CrepaldiHandballBackup`. Validar localmente:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
Get-ScheduledTask -TaskName CrepaldiHandball,CrepaldiHandballBackup
```

### Fase C — túnel e DNS pelo proprietário

Antes de mudar nameservers, inventariar e preservar todos os registros `A`,
`AAAA`, `CNAME`, `MX`, `TXT`, `CAA`, SPF, DKIM e DMARC. Não comprometer o site
principal nem o e-mail.

Configuração lógica esperada no Cloudflare Tunnel:

```text
Nome do túnel: crepaldi-handball
Hostname:       handball.crepaldi.com.br
Serviço:        http://127.0.0.1:8765
```

O agente deve tratar Cloudflare, DNS e Hostinger como um gate externo. Não
simular sucesso e não alterar esses sistemas.

Antes de adicionar o link ao portal, o proprietário deve confirmar:

```text
https://handball.crepaldi.com.br/health  -> HTTP 200 e {"status":"ok"}
https://handball.crepaldi.com.br/        -> redireciona para login ou app
```

### Fase D — integração visual no portal

Somente após o subdomínio funcionar:

1. preservar as duas portas da raiz `index.html`; não criar uma terceira porta
   que rompa a composição 50/50;
2. incluir uma ação secundária discreta na área privada, com texto como
   **Registro de handebol** e destino exato
   `https://handball.crepaldi.com.br/`;
3. implementar o link como HTML estático em `privado/index.html`, fora do
   conteúdo cifrado de `vault.json`, disponível mesmo com o cofre trancado;
4. deixar explícito que o aplicativo possui login próprio e que o PC servidor
   precisa estar ligado para o acesso online;
5. usar navegação comum por link. Não incorporar por `iframe`;
6. não consultar `/health` pelo portal, não mostrar status ao vivo e não criar
   dependência de CORS, telemetria ou disponibilidade do backend;
7. não adicionar scripts externos, bibliotecas ou rastreamento;
8. não alterar `connect-src` da CSP: um link comum não exige essa permissão;
9. preservar `noindex, nofollow, noarchive`, canonical, foco por teclado,
   contraste e alvo de toque de pelo menos 44 px;
10. alterar `styles.css` apenas se a nova ação precisar de estilo próprio.

O endereço do aplicativo pode aparecer no HTML do portal: isso não concede
acesso aos dados, pois o aplicativo possui autenticação própria. `noindex`
também não é controle de acesso.

Arquivos publicáveis provavelmente afetados:

```text
privado/index.html
styles.css              # somente se necessário
```

O presente arquivo `docs/HANDOFF-HANDBALL.md` é documentação local e **não deve
ser adicionado** a `deploy-manifest.txt` nem ao ZIP público.

### Fase E — validação e pacote local

No repositório `site`, com PowerShell 7:

```powershell
pwsh -NoProfile -File .\scripts\test-vault.ps1
pwsh -NoProfile -File .\scripts\validate.ps1
pwsh -NoProfile -File .\scripts\package-release.ps1
git diff --check
git status --short
```

Revisar o diff e o `MANIFEST-SHA256.txt`. O pacote deve continuar contendo
exatamente:

```text
index.html
styles.css
publico/index.html
privado/index.html
privado/vault.js
privado/vault.json
MANIFEST-SHA256.txt      # comprovante local; não enviar ao servidor
```

O agente entrega pacote e dry-run ao proprietário. O proprietário confirma o
destino `public_html/roberto/`, cria backup restaurável e faz a atualização
manual conforme `docs/DEPLOY.md`.

### Fase F — verificação pós-publicação

Após a atualização manual do portal:

```powershell
pwsh -NoProfile -File .\scripts\verify-remote.ps1
```

Além da verificação existente, conferir manualmente:

- a raiz continua com as portas Público e Privado equilibradas;
- a área privada mantém o cofre funcional;
- o link Registro de handebol abre o hostname HTTPS correto;
- login, chamada e logout funcionam;
- no Safari, **Compartilhar > Adicionar à Tela de Início** instala a PWA;
- o PIN offline pode ser criado sem expor a senha administrativa;
- site principal, `/roberto/`, e-mail e SSL permanecem operacionais.

## 6. Critérios de aceite

A integração só está concluída quando todos os itens forem verdadeiros:

- [x] aplicação aprovada nos testes e compilação;
- [x] banco, configuração e senha ausentes do Git e do pacote do portal na
  inspeção registrada;
- [x] servidor saudável em `127.0.0.1:8765`;
- [x] túnel saudável e hostname HTTPS público;
- [ ] nenhum encaminhamento de porta no roteador;
- [x] nenhuma aplicação dinâmica copiada para `/roberto/`;
- [ ] desenho 50/50, cofre, CSP, canonical e `noindex` preservados;
- [ ] validação local do portal aprovada;
- [ ] pacote local com allowlist exata e hashes revisados;
- [ ] backup remoto restaurável confirmado pelo proprietário;
- [ ] upload manual limitado a `public_html/roberto/`;
- [ ] link, login e instalação no iPhone verificados;
- [ ] nenhuma alteração fora de `/roberto/`.

## 7. Rollback

Os dois sistemas possuem rollback independente:

- **Portal:** restaurar manualmente apenas os arquivos alterados dentro de
  `public_html/roberto/`, usando o backup identificado antes do upload.
- **Aplicativo:** remover ou desativar temporariamente a rota pública do túnel
  não modifica o banco. A restauração do SQLite exige parar o servidor, preservar
  o banco atual, copiar um backup consistente e reiniciar a tarefa.

Não usar sincronização destrutiva, purge ou exclusão remota como rollback.

## 8. Prompt sugerido para o agente de `../site`

```text
Leia AGENTS.md e docs/HANDOFF-HANDBALL.md integralmente. Preserve todas as
alterações locais existentes. Não acesse Hostinger, Cloudflare ou DNS e não
publique remotamente. Confirme primeiro os gates externos documentados. Quando
o subdomínio estiver saudável, implemente somente a integração visual permitida
na área privada, preserve o portal 50/50, o cofre e o noindex, execute toda a
validação local, gere o pacote em .release e apresente o dry-run exato para a
publicação manual do proprietário.
```
