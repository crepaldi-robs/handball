# Auditoria de implantação — Registro de Presenças de Handebol

| Campo | Valor |
|---|---|
| Data de consolidação | 21 de julho de 2026 |
| Fuso de referência | America/Sao_Paulo (UTC−03:00) |
| Classificação | documentação operacional interna; não publicável |
| Portal estático | `https://crepaldi.com.br/roberto/` |
| Aplicação dinâmica | `https://handball.crepaldi.com.br/` |
| Fonte da aplicação | `C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas` |
| Instalação de produção | `C:\ProgramData\CrepaldiHandball` |
| Documento operacional | [`HANDBALL-OPERATIONS.md`](HANDBALL-OPERATIONS.md) |
| Handoff de integração | [`HANDOFF-HANDBALL.md`](HANDOFF-HANDBALL.md) |

## 1. Finalidade e conclusão executiva

Este documento registra, de forma auditável, o trabalho realizado para colocar
o Registro Oficial de Presenças de Handebol na internet sem mover o banco de
dados para a Hostinger e sem abrir porta de entrada no roteador. Ele consolida
as decisões, comandos, resultados, falhas, correções, evidências, limites de
verificação, riscos, procedimentos de atualização e itens ainda pendentes.

**Conclusão em 21/07/2026:** a aplicação dinâmica está instalada no computador
Windows, responde localmente em `127.0.0.1:8765`, está publicada por um
Cloudflare Tunnel saudável e respondeu publicamente em HTTPS pelo subdomínio
`handball.crepaldi.com.br`. A migração autoritativa do DNS de
`crepaldi.com.br` para a Cloudflare propagou pelos resolvedores públicos
consultados. O proprietário confirmou que o site principal, o portal
`/roberto/` e o envio e recebimento de e-mail continuaram funcionando.

A integração ainda **não está integralmente encerrada**. Permanecem pendentes:

1. validar um login autenticado pelo endereço público e uma gravação de teste;
2. executar `PRAGMA quick_check` no SQLite e criar um backup manual de marco;
3. testar reinicialização automática após um reboot planejado do computador;
4. adicionar ao portal privado o link discreto para o aplicativo;
5. validar, empacotar e publicar manualmente essa alteração do portal;
6. testar a PWA e o modo offline no iPhone;
7. revisar as configurações finais de robôs/IA e, após estabilidade, decidir
   sobre habilitar DNSSEC.

Não houve, nesta sessão, upload de conteúdo do portal para a Hostinger. Este
arquivo não autoriza acesso, upload ou alteração remota por um agente.

## 2. Escopo, autoridades e separação de sistemas

### 2.1 Sistemas envolvidos

Há dois produtos diferentes e deliberadamente desacoplados:

1. **Portal estático `/roberto/`** — HTML, CSS e JavaScript hospedados na
   Hostinger. O processo de publicação é manual e limitado pela allowlist de
   `deploy-manifest.txt`.
2. **Aplicação de handebol** — FastAPI, SQLite, autenticação, auditoria e PWA
   executados no computador Windows do proprietário. A Cloudflare apenas
   encaminha o tráfego HTTPS até o serviço local pelo túnel.

O portal não contém o backend, o SQLite, a configuração do aplicativo, a senha,
os logs ou os backups. O aplicativo não substitui o cofre privado do portal.
Cada um possui autenticação, ciclo de atualização, persistência e rollback
próprios.

### 2.2 Limites de autoridade desta documentação

As regras permanentes do repositório `site` continuam válidas:

- nenhum agente deve acessar ou modificar a Hostinger;
- nenhum agente deve publicar, sincronizar ou apagar conteúdo remoto;
- credenciais, tokens e senhas não devem ser solicitados, lidos nem armazenados;
- DNS, e-mail, SSL, `.htaccess`, PHP e configurações globais são operações
  exclusivas do proprietário;
- uma futura publicação do portal deve ser manual, revisada e restrita a
  `public_html/roberto/`.

As ações remotas descritas neste relatório foram executadas diretamente pelo
proprietário, seguindo orientação passo a passo. O relatório preserva apenas
metadados não secretos necessários à continuidade operacional.

## 3. Topologia final conhecida

```text
Visitante
   |
   | HTTPS
   v
Cloudflare: handball.crepaldi.com.br
   |
   | Cloudflare Tunnel, conexão iniciada de dentro para fora
   v
Serviço cloudflared no PC Windows
   |
   | HTTP local
   v
127.0.0.1:8765
   |
   +-- FastAPI / Uvicorn
   +-- autenticação e sessões
   +-- auditoria da aplicação
   +-- SQLite: C:\ProgramData\CrepaldiHandball\data\presencas.db
   +-- backups: C:\ProgramData\CrepaldiHandball\backups
```

O domínio principal e o e-mail continuam apontando para seus serviços
anteriores por registros DNS preservados. A Hostinger hospeda o conteúdo
estático; ela não executa o backend de handebol nessa arquitetura.

### 3.1 Identificadores operacionais não secretos

| Item | Valor conhecido |
|---|---|
| Túnel | `crepaldi-handball` |
| Tunnel ID | `fa61f74d-c109-4284-8636-8ba21b38d20c` |
| Hostname publicado | `handball.crepaldi.com.br` |
| Destino DNS do hostname | `fa61f74d-c109-4284-8636-8ba21b38d20c.cfargotunnel.com` |
| Serviço de origem | `http://127.0.0.1:8765` |
| Rota | hostname completo, caminho vazio, portanto todos os caminhos |
| Réplicas observadas | 1 |
| Nameserver 1 | `dawn.ns.cloudflare.com` |
| Nameserver 2 | `nash.ns.cloudflare.com` |

O token usado para instalar o conector é um segredo de conta e foi
deliberadamente excluído. Se ele tiver sido copiado para um local inseguro, deve
ser rotacionado no painel da Cloudflare e atualizado no serviço do computador.

### 3.2 Independência de dados e acoplamento residual de controle

Portal e aplicativo são independentes em código, dados, autenticação, runtime,
release e rollback. Porém não são totalmente independentes no plano de controle:
site, e-mail e handball compartilham a zona autoritativa `crepaldi.com.br` e a
conta Cloudflare. Uma mudança errada de nameserver ou perda da conta pode atingir
os três.

| Mudança | Site principal/portal | E-mail | Handball |
|---|---:|---:|---:|
| código do aplicativo | não | não | sim |
| SQLite/configuração | não | não | sim |
| HTML privado do portal | sim | não | somente o link exibido |
| rota/CNAME `handball` | não | não | sim |
| registro A/AAAA/`www` | sim | não | normalmente não |
| MX/SPF/DKIM/DMARC | não | sim | não |
| nameservers da zona | sim | sim | sim |
| conta Cloudflare indisponível/comprometida | potencialmente | potencialmente | sim |

Por isso, desenvolvimento comum do app não toca DNS. Qualquer alteração da zona
é operação externa do proprietário e exige regressão de site, `/roberto/`, envio
e recebimento de e-mail e handball.

## 4. Modelo de evidência

As afirmações abaixo usam quatro classes de evidência:

| Código | Classe | Interpretação |
|---|---|---|
| E1 | saída de terminal fornecida pelo proprietário | resultado literal de comando executado no computador, preservado na conversa |
| E2 | captura de tela fornecida pelo proprietário | estado visual do navegador ou painel autenticado naquela ocasião |
| E3 | inspeção local do Codex | leitura de arquivos, Git ou comando local não destrutivo no workspace |
| E4 | inferência arquitetural | consequência técnica derivada dos componentes; não equivale a teste de produção |
| E5 | declaração funcional do proprietário | teste manual relatado pelo proprietário, sem captura/saída integral preservada |

Limitações importantes:

- o Codex não acessou de forma independente a conta da Hostinger, a conta da
  Cloudflare ou o Registro.br;
- capturas comprovam o estado exibido no momento, não disponibilidade contínua;
- uma resposta `GET /health` comprova processo e roteamento, mas não comprova
  sozinha integridade do SQLite, login, gravação, restauração ou funcionamento
  offline;
- a ausência de encaminhamento de porta decorre do fluxo de implantação seguido
  e da arquitetura outbound-only, mas o roteador não foi inventariado de forma
  independente;
- nenhum segredo foi reproduzido para “completude” da auditoria.

## 5. Linha do tempo consolidada

### 5.1 Validação inicial do aplicativo

No repositório da aplicação, o proprietário executou:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance tests
git status --short
git log -1 --oneline
```

Resultados observados (E1):

- `8 passed` em 35,98 segundos;
- uma advertência de depreciação entre `starlette.testclient` e `httpx`, sem
  falha funcional;
- `compileall` terminou sem mensagem de erro;
- worktree limpo;
- branch `main` no commit
  `0f0baf7 docs: define operacao e convencoes do projeto`.

A advertência é dívida técnica não bloqueante. Deve ser reavaliada quando as
dependências forem atualizadas, sem forçar uma troca precipitada em produção.

### 5.2 Necessidade de senha livre e primeira tentativa de instalação

O proprietário solicitou que a senha administrativa pudesse ser qualquer valor
escolhido. A política anterior exigia no mínimo 12 caracteres. O código foi
alterado para aceitar **qualquer senha não vazia**, tanto na inicialização quanto
na redefinição, mantendo a exigência de confirmação idêntica.

A senha continua sendo armazenada apenas como hash Argon2id. Ela não é escrita
em texto puro no repositório, no portal ou neste relatório. Aceitar senhas curtas
é uma escolha funcional; como o aplicativo agora é acessível pela internet, a
recomendação operacional permanece usar uma senha única, longa e não reutilizada.

Na primeira execução do instalador:

- um usuário administrativo escolhido pelo proprietário foi configurado;
- `C:\ProgramData\CrepaldiHandball\data\app-config.json` foi criado;
- a senha informada foi aceita;
- o instalador falhou ao aplicar ACL porque usava o nome em inglês
  `Administrators` num Windows em português;
- o `icacls` informou que não foi possível mapear o nome de conta para uma
  identificação de segurança;
- como consequência, o serviço não iniciou e o teste de saúde subsequente
  falhou.

Diagnóstico: a falha não tinha relação com a senha. Tratava-se de dependência
indevida do idioma do sistema operacional.

### 5.3 Correção do instalador e testes de regressão

Foram alterados exatamente cinco arquivos no repositório da aplicação:

| Arquivo | Mudança essencial |
|---|---|
| `README.md` | documentação da nova regra de senha e operação |
| `attendance/cli.py` | remove mínimo de 12 caracteres e rejeita somente senha vazia ou confirmação divergente |
| `scripts/install-server.ps1` | cria `Set-PrivateDirectoryAcl`, usa SIDs conhecidos e verifica código de saída do `icacls` |
| `tests/test_cli.py` | cobre inicialização e redefinição com senha de um caractere |
| `tests/test_install_server.py` | regressão estática para ACL independente do idioma |

SIDs utilizados:

- `S-1-5-18`: conta Local System;
- `S-1-5-32-544`: grupo interno Administrators, independente do nome
  localizado exibido pelo Windows.

Validação após a correção (E3):

- `11 passed`;
- a mesma advertência de depreciação, sem falha;
- `compileall` com código de saída zero;
- parser do PowerShell retornou `PARSE_OK`;
- `git diff --check` sem erro de whitespace; apenas aviso esperado de conversão
  futura de LF para CRLF no script PowerShell.

O proprietário adicionou os cinco arquivos e criou o commit (E1):

```text
72cb9e3 fix: flexibiliza senha e corrige instalação no Windows
```

Resumo do commit: 5 arquivos alterados, 98 inserções, 10 remoções e criação dos
dois testes. Depois do commit, o worktree da aplicação estava limpo.

### 5.4 Segunda instalação e validação local

A nova execução de `scripts\install-server.ps1` concluiu com sucesso. O
instalador informou que o servidor estava disponível em
`http://127.0.0.1:8765`.

Evidências do proprietário (E1):

```text
GET http://127.0.0.1:8765/health -> {"status":"ok"}
CrepaldiHandball                 -> Running
CrepaldiHandballBackup           -> Ready
presencas.db                     -> existe
diretório backups                -> existe
```

O login local foi realizado com sucesso no navegador e a interface exibiu o
estado `Online`, com 19 atletas pendentes na chamada mostrada (E2). O valor
“19” é apenas o conteúdo observado naquele momento, não uma garantia de estado
atual do banco.

Uma nova consulta local feita pelo Codex em 21/07/2026 às 01:19:25, horário
local, voltou a responder `{"status":"ok"}` (E3). Isso demonstra continuidade
do processo até aquele instante.

### 5.5 Preservação e migração do DNS autoritativo

Antes da mudança de nameservers, o proprietário exportou os registros DNS da
Hostinger. O arquivo local de evidência ficou em:

```text
C:\Users\rober\Downloads\crepaldi.com.br.txt
```

Metadados inspecionados localmente (E3):

| Propriedade | Valor |
|---|---|
| Tamanho | 1.315 bytes |
| Modificado | 20/07/2026 23:54 |
| SHA-256 | `de61e2d8f18d58c965e6e1404598e342f9be2d3d0d7aaf0dc478a2b66c238165` |

O conteúdo integral não foi copiado para o repositório porque registros TXT
podem carregar informações operacionais que não devem ser replicadas sem
necessidade. Foi preservado apenas o inventário sanitizado:

| Tipo | Quantidade no export | Observação |
|---|---:|---|
| A | 2 | ápice e `ftp` |
| AAAA | 1 | ápice |
| CNAME | 6 | `autoconfig`, `autodiscover`, três seletores de e-mail e `www` |
| MX | 2 | prioridades 5 e 10 |
| TXT | 2 | SPF no ápice e DMARC em `_dmarc` |
| NS | 2 | delegação antiga; não é registro de conteúdo a importar na nova zona |
| CAA | 0 | nenhum observado |
| SRV | 0 | nenhum observado |

Os nameservers anteriores eram:

```text
ns1.dns-parking.com
ns2.dns-parking.com
```

A zona `crepaldi.com.br` foi adicionada ao plano gratuito da Cloudflare. A
varredura encontrou exatamente 2 A, 1 AAAA, 6 CNAME, 2 MX e 2 TXT, coerentes com
o export sanitizado. Todos esses registros preexistentes foram colocados em
**DNS only** durante a migração para reduzir mudança simultânea de comportamento.
Isso incluiu web, FTP e registros auxiliares de e-mail. O CNAME do subdomínio
`handball`, criado depois pelo Tunnel, é proxy por projeto.

No onboarding de robôs/IA, Search e Agent foram mantidos em `Allow`, Training
foi mudado para `Allow (do not block)` e o bloqueio de treinamento via
`robots.txt` foi desligado. Após a ativação da zona, o painel exibiu controles
genéricos adicionais de IA/robots. O estado efetivo final dessas políticas não
foi auditado novamente; consta como pendência.

Uma consulta de DS não encontrou registro DS para o domínio, retornando apenas
a autoridade SOA do pai. A evidência indica que DNSSEC estava desligado antes da
migração, evitando uma quebra por assinatura antiga.

O proprietário alterou a delegação no Registro.br para:

```text
dawn.ns.cloudflare.com
nash.ns.cloudflare.com
```

As consultas seguintes confirmaram propagação pelos dois resolvedores (E1):

```powershell
Resolve-DnsName -Name crepaldi.com.br -Type NS -Server 1.1.1.1
Resolve-DnsName -Name crepaldi.com.br -Type NS -Server 8.8.8.8
```

Ambos retornaram os dois nameservers da Cloudflare. O painel também passou a
mostrar a zona como ativa (E2). O Registro.br exibiu o domínio como publicado e
com expiração em 22/02/2028 (E2); essa data é evidência histórica e deve ser
consultada novamente quando houver necessidade administrativa.

Depois da troca, o proprietário confirmou manualmente (E5):

- site principal funcionando normalmente;
- `https://crepaldi.com.br/roberto/` funcionando normalmente;
- envio de e-mail funcionando;
- recebimento de e-mail funcionando.

### 5.6 Instalação do Cloudflare Tunnel

No painel de Tunnels, foi criado o túnel `crepaldi-handball`. O proprietário:

1. selecionou Windows 64-bit;
2. baixou o instalador oficial `cloudflared-windows-amd64.msi`;
3. instalou o conector;
4. executou como administrador o comando de instalação do serviço, contendo um
   token secreto gerado pela Cloudflare;
5. recebeu a confirmação `Tunnel connected successfully`.

O painel mostrou (E2):

- status `Healthy`;
- uma réplica ativa;
- arquitetura `windows_amd64`;
- tipo `cloudflared`.

Foi criada uma rota do tipo **Published application** com:

```text
Subdomain:   handball
Domain:      crepaldi.com.br
Path:        vazio
Service URL: http://127.0.0.1:8765
```

A Cloudflare confirmou `Route added successfully` e criou o CNAME para o
destino do túnel. Nenhum IP público residencial foi registrado nesta
documentação, pois ele é desnecessário para operar a arquitetura.

### 5.7 Verificação pública

O proprietário abriu no navegador (E2):

```text
https://handball.crepaldi.com.br/health
```

e recebeu:

```json
{"status":"ok"}
```

Também abriu:

```text
https://handball.crepaldi.com.br/login
```

A página de login foi carregada corretamente por HTTPS. Isso comprova, naquele
momento, resolução DNS, certificado, borda Cloudflare, conexão do túnel, acesso
ao processo FastAPI e renderização do frontend.

Não foi preservada evidência de login autenticado pela URL pública nem de uma
gravação de teste após a criação da rota. Portanto, não se deve elevar o estado
de `/health` para “banco integralmente validado”.

## 6. Matriz de verificação atual

| Controle | Estado | Evidência | Observação |
|---|---|---|---|
| testes da aplicação | aprovado | E1/E3 | 11 testes após a correção |
| compilação Python | aprovada | E1/E3 | `compileall` sem erro |
| commit da correção | aprovado | E1/E3 | `72cb9e3` |
| worktree da aplicação | limpo na última inspeção | E1/E3 | revalidar antes de atualizar |
| serviço local | aprovado | E1/E3 | `/health` retornou `ok` |
| tarefa do servidor | aprovada | E1 | `Running` |
| tarefa de backup | configurada | E1 | estado `Ready`; restauração não testada |
| arquivo SQLite | existe | E1 | integridade ainda não checada nesta etapa |
| diretório de backups | existe | E1 | backup manual de marco pendente |
| login local | aprovado | E2 | interface carregada e autenticada |
| DNS autoritativo | aprovado | E1/E2 | 1.1.1.1 e 8.8.8.8 retornaram Cloudflare |
| site principal | confirmado pelo proprietário | E5 | pós-migração |
| portal `/roberto/` | confirmado pelo proprietário | E5 | pós-migração |
| e-mail de saída | confirmado pelo proprietário | E5 | teste funcional manual |
| e-mail de entrada | confirmado pelo proprietário | E5 | teste funcional manual |
| túnel | aprovado no momento observado | E2 | `Healthy`, uma réplica |
| HTTPS `/health` público | aprovado | E2 | `{"status":"ok"}` |
| página pública de login | aprovada | E2 | carregamento visual correto |
| login público autenticado | pendente | — | testar em janela normal e móvel |
| escrita e leitura pública no banco | pendente | — | usar registro de teste controlado |
| `PRAGMA quick_check` | pendente | — | executar em leitura |
| restauração de backup | não testada | — | planejar exercício controlado |
| auto-start após reboot | não testado | — | fazer janela de manutenção |
| ausência de port forwarding | não auditada diretamente | E4 | túnel não exige porta aberta |
| link no portal privado | não implementado | E3 | próximo passo do projeto `site` |
| pacote/Hostinger do link | não realizado | E3 | publicação continua manual |
| PWA iPhone/offline | pendente | — | requer aparelho real |
| política final de robôs/IA | pendente | E2 | revisar painel após ativação |
| DNSSEC na Cloudflare | não habilitado | E1/E2 | decidir somente após estabilidade |

## 7. Persistência, banco de dados e significado de “está funcionando”

### 7.1 Onde ficam os dados

O banco principal é:

```text
C:\ProgramData\CrepaldiHandball\data\presencas.db
```

Os backups ficam em:

```text
C:\ProgramData\CrepaldiHandball\backups
```

A instalação conhecida mantém 30 cópias e agenda o backup para 03:00. O banco
não está na Hostinger nem na Cloudflare. A Cloudflare encaminha requisições; ela
não substitui a persistência local.

Uma alteração feita pela interface e salva no servidor deve ser gravada no
SQLite imediatamente segundo o comportamento do aplicativo. Isso é diferente
de alterar o código-fonte. O arquivo no repositório e a cópia instalada em
`C:\ProgramData` são árvores separadas.

### 7.2 Níveis de saúde

É útil distinguir:

1. **processo vivo:** `/health` responde;
2. **interface disponível:** `/login` ou `/app` renderiza;
3. **autenticação funcional:** credenciais válidas criam uma sessão;
4. **persistência funcional:** uma alteração controlada é gravada, lida e
   aparece no histórico/auditoria;
5. **integridade:** `PRAGMA quick_check` retorna `ok`;
6. **recuperabilidade:** um backup conhecido pode ser restaurado em exercício
   controlado.

Nesta auditoria, os níveis 1 e 2 foram comprovados publicamente; login foi
comprovado localmente. Os níveis 3 a 6 ainda precisam de evidência pública ou de
manutenção específica, conforme a matriz.

## 8. Como atualizações funcionam

### 8.1 Alterar dados no uso diário

Salvar chamada, presença, justificativa, atleta ou outra informação pela
interface é uma operação de dados. Não exige Git, reinstalação nem publicação na
Hostinger. Exige que o computador, o servidor e o túnel estejam disponíveis.

### 8.2 Alterar o programa

Editar arquivos no repositório da aplicação **não atualiza automaticamente** o
site público. O código em produção é a cópia instalada em
`C:\ProgramData\CrepaldiHandball\app`. Uma atualização segura deve:

1. alterar e revisar a fonte;
2. executar testes e compilação;
3. criar ou verificar backup consistente do banco;
4. registrar a alteração no Git;
5. executar novamente o instalador ou o procedimento de atualização aprovado;
6. reiniciar a tarefa do servidor;
7. validar saúde local, login e saúde pública.

O runbook contém os comandos exatos. Não se recomenda automatizar deploy a cada
`git commit`: uma falha de código poderia interromper o serviço e o banco merece
um gate explícito de backup.

### 8.3 Alterar o portal `/roberto/`

É um fluxo separado. As mudanças são feitas no repositório `site`, validadas e
empacotadas localmente. Somente o proprietário pode publicar manualmente os seis
caminhos autorizados na Hostinger. Atualizar o aplicativo não atualiza o portal;
atualizar o portal não reinstala o aplicativo.

## 9. O que acontece quando o computador é desligado

Quando o computador servidor está desligado, dormindo ou hibernando:

- o FastAPI para;
- o serviço `cloudflared` deixa de manter a conexão;
- `handball.crepaldi.com.br` pode continuar resolvendo, mas não alcança uma
  origem saudável;
- login, sincronização, gravação, histórico remoto e auditoria do servidor ficam
  indisponíveis;
- o site principal, `/roberto/` e o e-mail continuam independentes e não devem
  parar por esse motivo;
- uma PWA previamente instalada pode carregar partes em cache e, se o fluxo
  offline tiver sido preparado no aparelho, trabalhar com o cofre/chamada local
  cifrada dentro dos limites do aplicativo; ela não transforma o PC desligado em
  servidor disponível.

Ao ligar o PC, a tarefa agendada `CrepaldiHandball` e o serviço do `cloudflared`
devem iniciar automaticamente. Esse comportamento é esperado pela configuração,
mas ainda precisa de um reboot controlado para ser classificado como testado.

O service worker conhecido usa o cache `handball-shell-v2`, estratégia
network-first para `/app` e `/static` e fallback em cache. Rotas de API não
devem ser tratadas como cache confiável do servidor. Depois de atualização de
frontend, pode haver uma versão antiga temporária até a atualização do service
worker ou recarregamento do navegador.

## 10. Segurança e privacidade

### 10.1 Controles presentes

- backend escuta somente em loopback (`127.0.0.1`);
- conexão pública ocorre por túnel iniciado de dentro para fora;
- HTTPS termina na Cloudflare;
- senha é verificada por hash Argon2id;
- banco, configuração, logs e backups permanecem fora do repositório do portal;
- diretórios privados usam ACL baseada em SID, independente do idioma do
  Windows;
- portal e aplicativo têm autenticações separadas;
- registros de e-mail foram preservados como DNS only durante a migração;
- o token do túnel não foi documentado.

### 10.2 Riscos residuais

- o PC doméstico é ponto único de falha;
- há somente uma réplica do túnel;
- disponibilidade depende de energia, internet, Windows, tarefa do servidor e
  serviço cloudflared;
- permitir qualquer senha não vazia aumenta o risco se o proprietário escolher
  senha fraca;
- a recuperação ainda não foi exercitada;
- o backup agendado às 03:00 pode ser perdido se o PC estiver desligado nesse
  horário, dependendo das opções efetivas da tarefa;
- a advertência de compatibilidade Starlette/httpx deve ser acompanhada;
- a aplicação pública deve receber atualizações de dependências de forma
  controlada, nunca sem backup e testes;
- uma URL pública não deve conter dados sensíveis em parâmetros ou logs.

### 10.3 Achados de continuidade no código da aplicação

Uma revisão cruzada do código acrescentou os riscos abaixo. Eles são fatos
documentados ou dívidas; não foram corrigidos por esta tarefa de documentação.
O tratamento completo para desenvolvedores está em:

```text
C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas\docs\SITE-INTEGRATION-CONTRACT.md
```

| Prioridade | Achado | Consequência |
|---|---|---|
| P0 | instalador copia em-place, não para/reinicia tarefa já ativa e `/health` não informa versão | health verde pode vir do processo antigo; release não é transacional |
| P0 | `Restart-ScheduledTask` não existe no módulo desta máquina, mas é chamado no reset | novo hash/secret pode ser gravado enquanto processo antigo continua ativo |
| P0 | `/health` retorna JSON fixo | não comprova SQLite, migration, leitura, gravação, auditoria ou versão |
| P1 | 19 nomes/apelidos e posições iniciais estão em `attendance/models.py` | repositório contém elenco identificável; deve permanecer privado |
| P1 | seed executa UPSERT de posição em toda inicialização | restart pode desfazer posição editada pelo usuário |
| P1 | auditoria cobre registros individuais, não todas as ações administrativas | reabertura, nota geral e elenco não têm trilha completa |
| P1 | servidor e backup executam como SYSTEM/Highest | vulnerabilidade web teria impacto local ampliado |
| P1 | banco e backups estão no mesmo PC/volume | não cobrem falha física, furto ou ransomware |
| P1 | backup das 03:00 não recebe explicitamente `StartWhenAvailable` | PC desligado pode perder a janela diária |
| P1 | migrations não têm versão formal | upgrade/downgrade futuro pode ficar ambíguo |
| P2 | dependências usam intervalos e ferramentas de teste entram na produção | installs não são plenamente reproduzíveis e ampliam superfície |
| P2 | logs diários não têm retenção | crescimento indefinido e risco de dados operacionais |
| P2 | validação do InstallRoot usa prefixo textual | caminho vizinho com mesmo prefixo pode ser aceito |
| P2 | rate limit é em memória e por `request.client.host` | precisa validar IP observado atrás do túnel e risco de bloqueio coletivo |
| P2 | PIN offline numérico mínimo de seis dígitos | proteção local tem entropia limitada apesar de PBKDF2/AES-GCM |

Qualificação de privacidade: chamadas, histórico, auditoria e alterações
operacionais ficam no SQLite local; porém o bootstrap identificável do elenco
está atualmente no Git do handball. A frase “dados ficam no PC” não significa
“nenhum dado identificável está no código”. Nada desse repositório deve ser
copiado para o portal ou publicado na Hostinger.

Também não existe hoje um artefato persistente na instalação que prove o commit
carregado. O commit `72cb9e3` é o marco esperado, não uma identidade consultável
do processo. Recomenda-se `DEPLOYED-VERSION.json` ou equivalente com commit,
data, Python, dependências e hashes não secretos.

### 10.4 Segredos deliberadamente ausentes

Este registro não contém:

- senha administrativa;
- hash da senha;
- token de instalação ou credencial do Cloudflare Tunnel;
- credencial da Hostinger, Registro.br ou e-mail;
- conteúdo integral dos registros TXT;
- cookies, chaves de sessão ou conteúdo do cofre;
- cópia do SQLite ou dos backups;
- endereço IP residencial observado no painel.

## 11. Rollback e recuperação

### 11.1 DNS

O inventário exportado e seu hash constituem a referência pré-migração. Os
nameservers anteriores eram `ns1.dns-parking.com` e `ns2.dns-parking.com`.
Retornar a eles só deve ocorrer em incidente confirmado, com revisão de que a
zona anterior continua completa. Uma reversão de nameserver sofre propagação e
não é o primeiro remédio para falha exclusiva do aplicativo.

### 11.2 Túnel

Desabilitar ou remover a rota pública interrompe a exposição externa sem apagar
o SQLite. Não rotacionar token, excluir túnel ou registro DNS durante diagnóstico
inicial sem preservar o estado e entender a causa.

### 11.3 Código do aplicativo

O commit `72cb9e3` é o marco conhecido da correção Windows/senha. Um rollback de
código deve selecionar conscientemente uma revisão testada, reinstalar a cópia
de produção e validar compatibilidade com o esquema do banco. Nunca usar
`git reset --hard` como rotina operacional e nunca substituir o banco por uma
cópia do repositório.

### 11.4 Banco de dados

Para restaurar SQLite:

1. interromper o servidor para cessar gravações;
2. preservar o banco atual com nome e timestamp, mesmo que pareça corrompido;
3. identificar um backup consistente e não apenas o mais recente por nome;
4. copiar a restauração para o caminho esperado;
5. verificar integridade;
6. reiniciar o servidor;
7. validar login, leitura, gravação e auditoria.

O procedimento detalhado está no runbook. Como restauração não foi testada
nesta sessão, deve primeiro ser exercitada em cópia isolada ou janela de
manutenção.

### 11.5 Portal

O rollback do portal é independente: restaurar manualmente somente os arquivos
alterados sob `public_html/roberto/`, usando backup remoto identificável. Não
usar espelhamento destrutivo, purge ou sincronização com exclusão.

## 12. Pendências ordenadas por prioridade

### P0 — fechar a validação funcional

- [ ] entrar pelo endereço público com a conta administrativa;
- [ ] criar uma alteração de teste claramente identificada;
- [ ] confirmar a leitura no histórico/auditoria;
- [ ] desfazer ou encerrar o dado de teste conforme a regra funcional;
- [ ] executar `PRAGMA quick_check` em modo leitura;
- [ ] criar backup manual de marco e registrar nome, tamanho, timestamp e hash.

### P1 — provar recuperação e inicialização

- [ ] inspecionar as opções efetivas das duas tarefas agendadas;
- [ ] confirmar se o backup atrasado inicia quando o PC liga após as 03:00;
- [ ] realizar reboot controlado;
- [ ] confirmar tarefa do servidor, serviço cloudflared, saúde local e saúde
  pública sem intervenção manual;
- [ ] testar restauração numa cópia isolada antes de qualquer incidente real.

### P1 — integrar o portal

- [ ] adicionar link secundário em `privado/index.html` para
  `https://handball.crepaldi.com.br/`;
- [ ] declarar que o aplicativo usa login próprio;
- [ ] preservar composição 50/50, cofre, CSP, canonical, `noindex`, teclado,
  contraste e alvos de toque;
- [ ] executar testes do cofre, validação, empacotamento e revisão de hashes;
- [ ] inventariar e fazer backup restaurável do destino remoto imediatamente
  antes da publicação;
- [ ] proprietário publicar manualmente somente os caminhos da allowlist;
- [ ] verificar o portal após o upload.

### P2 — dispositivos, cache e hardening

- [ ] testar Safari/iPhone e “Adicionar à Tela de Início”;
- [ ] validar PIN e fluxo offline sem expor senha administrativa;
- [ ] verificar atualização do service worker após nova versão;
- [ ] revisar controles finais de bots/IA e `robots.txt` na Cloudflare;
- [ ] após período estável, avaliar e, se escolhido, habilitar DNSSEC seguindo a
  sequência correta Cloudflare → Registro.br;
- [ ] considerar monitoramento externo de `/health` sem conteúdo sensível;
- [ ] considerar energia ininterrupta ou host sempre ligado se disponibilidade
  se tornar requisito forte.

## 13. Estado do repositório do portal no momento da consolidação

O repositório `site` já continha numerosas alterações locais antes da criação
desta auditoria. Elas pertencem ao proprietário e não devem ser limpas,
resetadas ou confundidas com o trabalho documental. O HEAD observado era:

```text
e711413 Harden UTF-8 validation for project files
```

Entre os itens locais estavam alterações no portal, documentação, scripts e
arquivos novos do cofre. O handoff do handball também era arquivo não rastreado.
Esta auditoria não conclui que essas alterações estejam prontas para publicação.

O manifesto público observado contém exatamente seis caminhos:

```text
index.html
styles.css
publico/index.html
privado/index.html
privado/vault.js
privado/vault.json
```

Este relatório, o runbook e o handoff são documentação interna e não devem ser
adicionados ao manifesto nem ao ZIP público.

No momento da inspeção, `handball.crepaldi.com.br` aparecia apenas na
documentação de handoff. Portanto, o link visual no portal ainda não estava
implementado. Pacotes `.release` preexistentes antecedem essa futura integração
e não devem ser publicados como se já a contivessem.

## 14. Critério de encerramento futuro

O projeto pode ser considerado operacionalmente encerrado quando:

1. todos os itens P0 tiverem evidência registrada;
2. o auto-start e pelo menos uma recuperação controlada tiverem sido testados;
3. o portal tiver o link aprovado, validado, empacotado e publicado manualmente;
4. o link, login, gravação, histórico, logout e PWA tiverem sido testados nos
   dispositivos de uso;
5. nenhuma credencial, banco ou backup tiver entrado no Git ou no pacote;
6. um operador futuro conseguir atualizar e recuperar o sistema apenas com o
   runbook, sem depender da lembrança desta conversa.

## 15. Cadeia de custódia documental

Para futuras revisões:

- trate este arquivo como fotografia de 21/07/2026, não como monitoramento vivo;
- acrescente novos eventos com data, comando, resultado e classe de evidência;
- não reescreva falhas históricas depois de corrigi-las;
- preserve hashes de artefatos relevantes sem copiar material secreto;
- referencie commits Git para mudanças de código;
- marque explicitamente o que foi testado, relatado, inferido ou ainda não
  verificado;
- nunca cole tokens ou senhas em documentação, issues, commits ou capturas;
- mantenha o runbook como instrução atual e este relatório como trilha histórica.
