# Publicação em `handball.crepaldi.com.br`

## Separação obrigatória

O aplicativo não faz parte de `../site` e não deve ser enviado para
`public_html/roberto/`. O portal permanece estático e sujeito às regras próprias
de publicação manual. O subdomínio apenas encaminha tráfego HTTPS para o serviço
executado neste PC.

O contrato normativo para desenvolvimento sem interferir no portal está em
[SITE-INTEGRATION-CONTRACT.md](SITE-INTEGRATION-CONTRACT.md). Leia-o antes de
alterar hostname, rotas públicas, autenticação, PWA, instalador ou banco.

## 1. Instalar o servidor local

### 1.1 Instalação inicial (`INITIAL_INSTALL`)

Abra o PowerShell 7 como Administrador na pasta do projeto e execute:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-server.ps1
```

O instalador cria a primeira release imutável em
`C:\ProgramData\CrepaldiHandball\releases\<release_id>`, grava o ponteiro atômico
`state\active-release.json`, instala os launchers estáveis em `app\scripts` e o
guard independente em `ops\database-guard.py`. Também cria a conta administradora,
protege a instalação com ACL, registra inicialização no boot e agenda um backup
diário às 03:00, mantendo as 30 cópias mais recentes.

Esse comando é exclusivo de uma raiz vazia. Ele é o único fluxo que cria
`app-config.json`, `presencas.db` e o seed inicial.

### 1.2 Atualização somente da aplicação (`APP_ONLY`)

O instalador é exclusivo da primeira instalação e recusa uma raiz que já tenha
conteúdo. Para uma **atualização comum** de instalação ativa, primeiro valide o
repositório. Todo arquivo de runtime da release — e toda fonte operacional
verificada pelo processo — precisa estar rastreado no Git, sem modificações no
worktree ou no index e contido no commit `HEAD`; o updater recusa fonte suja,
não rastreada ou ainda não commitada.
Depois use o atualizador dedicado:

```powershell
.\scripts\test.ps1
if ($LASTEXITCODE -ne 0) { throw 'Testes falharam; update cancelado.' }
.\scripts\update-server.ps1
```

O updater monta staging somente com fonte aprovada, cria uma `.venv` isolada e
promove o resultado a `releases\<release_id>` sem modificar releases anteriores.
Os scripts em `app\scripts` permanecem launchers operacionais de caminho estável,
e `ops\database-guard.py` permanece um guard independente da aplicação. Em uma
instalação formal existente, `APP_ONLY` valida e preserva esses arquivos; somente
a instalação inicial ou a ponte de um layout legado os publica. O guard recusa
configuração ou banco ausentes, exige `quick_check = ok`, calcula o fingerprint
lógico e cria o backup de marco com SHA-256.

Depois de parar o serviço e confirmar a porta livre, o updater publica a nova
release trocando atomicamente apenas `state\active-release.json`. `/ready` deve
comprovar o `release_id` esperado e o fingerprint do SQLite deve permanecer
idêntico. Em falha com uma release anterior confiável, o rollback restaura somente
o ponteiro/código anterior; o updater nunca restaura, recria, semeia, migra, move
ou substitui banco, configuração, backups ou logs.

Na primeira transição de uma instalação legada, ainda não existe release anterior
confiável apontada por `active-release.json`. Se esse primeiro update falhar depois
da parada, o serviço deve permanecer parado para recuperação manual; o fluxo não
reinicia o código legado, pois seu startup poderia alterar o banco.
Essa ponte inicial também publica a camada operacional, endurece recursivamente
as ACLs da raiz instalada e corrige `ExecutionTimeLimit` da tarefa do servidor
quando necessário. Updates formais posteriores apenas verificam essas invariantes.

`GET /health` permanece somente liveness. `GET /ready` comprova identidade do
release, abertura do SQLite e versão de esquema. A aceitação de `APP_ONLY` em
produção é somente leitura: valide login, assets e consultas já existentes, mas
não crie treino, não sincronize chamada e não faça “gravação de teste”. Qualquer
teste de escrita deve usar uma cópia temporária do banco ou outra manutenção
explicitamente autorizada.

O layout e os contratos persistentes são:

```text
C:\ProgramData\CrepaldiHandball\data\app-config.json
C:\ProgramData\CrepaldiHandball\data\presencas.db
C:\ProgramData\CrepaldiHandball\backups\
C:\ProgramData\CrepaldiHandball\logs\
C:\ProgramData\CrepaldiHandball\releases\<release_id>\
C:\ProgramData\CrepaldiHandball\state\active-release.json
C:\ProgramData\CrepaldiHandball\app\scripts\
C:\ProgramData\CrepaldiHandball\ops\database-guard.py
127.0.0.1:8765
```

`APP_ONLY` adiciona uma release e preserva o código operacional estável já
autenticado; nunca move, substitui, migra, semeia ou restaura os quatro primeiros
caminhos. Ele pode acrescentar seu backup verificado e logs operacionais, sem
remover os existentes. Evolução dos launchers/guard exige manutenção operacional
própria e não deve ser disfarçada como atualização de banco.
O ponteiro escolhe qual release imutável será executada; ele não escolhe outro
banco.

O payload modular obrigatório inclui `handball/`, além de `app.py`,
`requirements.txt`, templates, assets e a fachada transitória `attendance/`.
SQL, conexões, schema e migrations pertencem exclusivamente a
`handball/database/`. A presença de `handball/` é validada pelas allowlists do
instalador e do updater antes da montagem de uma release.

A garantia de neutralidade do SQLite é lógica: mesmo caminho configurado, mesmo
schema e mesmo conteúdo/fingerprint. Parar o processo ou abrir SQLite pode alterar
metadados físicos e a existência/consolidação de `-wal` e `-shm`; não se promete
igualdade byte a byte desses sidecars.

### 1.3 Evolução separada do banco (`DB_MIGRATION`)

Uma melhoria de banco não faz parte do update da aplicação. Primeiro instale uma
release compatível com o schema atual. Em outra janela, no PowerShell 7 como
Administrador, gere o plano sem escrita:

```powershell
.\scripts\migrate-database.ps1
```

Revise o JSON, registre `from_version`, `to_version`, fingerprint e
`plan_sha256`. Somente se o plano estiver correto, aplique exatamente o hash
mostrado:

```powershell
.\scripts\migrate-database.ps1 `
    -Apply `
    -ExpectedPlanSha256 '<plan_sha256 exibido pelo comando anterior>'
```

O fluxo adquire o lock de manutenção, recusa backup concorrente, para o servidor,
confirma a porta livre, recalcula o plano, cria backup SQLite com SHA-256, aplica
DDL e ledger em transação e exige `quick_check` literal `ok`, ausência de violações
de chave estrangeira e `/ready` do mesmo `release_id`. Em falha depois do gate de
escrita, mantém o serviço parado e preserva o backup; não restaura o banco
automaticamente. Restauração é uma decisão operacional separada para evitar
apagar gravações posteriores.

`release_id` e `schema_version` evoluem de forma independente. Para mudanças
maiores, use expand/contract: aplicação compatível com N e N+1, migração explícita
N → N+1 e, somente depois, aplicação que exija N+1.

## 2. Preparar o DNS sem interromper o site

Antes de trocar qualquer nameserver:

1. Exporte ou fotografe todos os registros DNS existentes na Hostinger.
2. Reproduza no Cloudflare cada registro `A`, `AAAA`, `CNAME`, `MX`, `TXT`,
   `CAA`, DKIM, SPF e DMARC, preservando conteúdo e prioridade.
3. Confira especialmente o `A` do site principal e todos os registros de e-mail.
4. Reduza o TTL com antecedência, se o painel permitir.
5. Só então substitua os nameservers no registrador pelos fornecidos pelo Cloudflare.
6. Valide `https://crepaldi.com.br/`, `https://crepaldi.com.br/roberto/` e o
   recebimento/envio de e-mail. Se qualquer item falhar, restaure os nameservers
   anteriores e revise o inventário.

Essa operação é manual e exclusiva do proprietário do domínio.

## 3. Criar o Cloudflare Tunnel

No painel Cloudflare, crie um túnel chamado `crepaldi-handball`. Escolha Windows,
instale `cloudflared` como serviço usando o comando/token mostrado pelo painel e
adicione uma rota de aplicação publicada com:

```text
Hostname: handball.crepaldi.com.br
Service:  http://127.0.0.1:8765
```

Não abra portas no roteador e não exponha a porta `8765` na rede local. Depois
de o túnel ficar saudável, acesse o subdomínio, entre e instale a PWA no Safari
por **Compartilhar > Adicionar à Tela de Início**.

## 4. Operação e recuperação

```powershell
# Ver o estado do servidor
Get-ScheduledTask -TaskName CrepaldiHandball

# Reiniciar o servidor (não existe Restart-ScheduledTask neste ambiente)
Stop-ScheduledTask -TaskName CrepaldiHandball
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName CrepaldiHandball

# Criar backup imediatamente
C:\ProgramData\CrepaldiHandball\app\scripts\backup-server.ps1

# Redefinir senha, parar/iniciar e validar o mesmo release
& 'C:\ProgramData\CrepaldiHandball\app\scripts\reset-password.ps1'
```

O wrapper usa Stop → porta livre → Start → `/ready`; não depende do cmdlet
inexistente `Restart-ScheduledTask`. A CLI gira a chave de sessão, e o restart
real faz a invalidação entrar em vigor no processo.

Restauração de banco não faz parte do updater. Siga o procedimento completo do
runbook: valide antes o backup, pare a tarefa e confirme a porta livre, preserve
o conjunto atual `presencas.db` + `-wal` + `-shm`, restaure e somente reinicie se
o resultado literal de `PRAGMA quick_check` for `ok`. Nunca restaure com o
servidor escrevendo.
