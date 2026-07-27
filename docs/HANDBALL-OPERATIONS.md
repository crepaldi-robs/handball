# Runbook operacional — Registro de Presenças de Handebol

| Campo | Valor |
|---|---|
| Ambiente | Windows, PowerShell 7, FastAPI, SQLite e Cloudflare Tunnel |
| URL pública | `https://handball.crepaldi.com.br/` |
| URL local | `http://127.0.0.1:8765/` |
| Banco | `C:\ProgramData\CrepaldiHandball\data\presencas.db` |
| Relatório de implantação | [`HANDBALL-DEPLOY-AUDIT-2026-07-21.md`](HANDBALL-DEPLOY-AUDIT-2026-07-21.md) |
| Handoff do portal | [`HANDOFF-HANDBALL.md`](HANDOFF-HANDBALL.md) |

## 1. Propósito

Este é o manual vivo para operar, verificar, atualizar e recuperar a aplicação.
Ele deve continuar útil mesmo quando a conversa original não estiver
disponível. O relatório de auditoria guarda o que aconteceu; este runbook guarda
o que fazer daqui em diante.

Princípios:

1. o computador Windows é o servidor;
2. o SQLite local é a fonte oficial dos dados;
3. a Cloudflare fornece o caminho público, não a persistência;
4. o código-fonte e a instalação de produção são cópias diferentes;
5. mudanças de código exigem teste, backup, instalação e verificação;
6. mudanças no portal `/roberto/` seguem publicação manual independente;
7. nunca registrar senha, token, cookie ou conteúdo secreto em terminal
   compartilhado, Git ou documentação.

### 1.1 Legenda de autoridade

Os procedimentos deste documento não ampliam a autorização de um agente:

| Marca | Executor permitido | Exemplos |
|---|---|---|
| `[LEITURA]` | proprietário ou agente | health, status, Git, inventário local |
| `[APP-LOCAL]` | desenvolvedor no repositório do app | código, testes e docs sem produção |
| `[ADMIN-PC]` | proprietário em PowerShell 7 como Administrador | instalar, tarefa, senha, backup protegido, restauração |
| `[EXTERNO]` | proprietário nos painéis autenticados | Cloudflare, DNS, Registro.br, Hostinger |

Um agente no repositório `site` fica limitado a `[LEITURA]` e à documentação ou
preparação local autorizada por `AGENTS.md`. Blocos `[ADMIN-PC]` e `[EXTERNO]`
são instruções para o proprietário, não autorização de execução pelo agente.

## 2. Mapa rápido do ambiente após a primeira transição aceita

| Componente | Local/identificador | Função |
|---|---|---|
| fonte do aplicativo | `C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas` | desenvolvimento, testes e Git |
| release ativa | `C:\ProgramData\CrepaldiHandball\releases\<release_id>` | código e `.venv` imutáveis em execução |
| ponteiro ativo | `C:\ProgramData\CrepaldiHandball\state\active-release.json` | seleciona atomicamente a release, nunca o banco |
| launchers operacionais | `C:\ProgramData\CrepaldiHandball\app\scripts` | caminhos estáveis para servidor e manutenção |
| guard do banco | `C:\ProgramData\CrepaldiHandball\ops\database-guard.py` | verifica, identifica e copia SQLite sem importar a aplicação |
| configuração | `C:\ProgramData\CrepaldiHandball\data\app-config.json` | usuário, hash e configuração privada |
| banco principal | `C:\ProgramData\CrepaldiHandball\data\presencas.db` | fonte oficial de presenças e auditoria |
| backups | `C:\ProgramData\CrepaldiHandball\backups` | cópias locais, retenção conhecida de 30 |
| tarefa do servidor | `CrepaldiHandball` | inicia no startup do Windows, como SYSTEM |
| tarefa de backup | `CrepaldiHandballBackup` | backup programado, conhecido para 03:00 |
| serviço do túnel | normalmente `cloudflared` | mantém conexão de saída com a Cloudflare |
| túnel | `crepaldi-handball` | liga hostname público à origem local |
| origem | `http://127.0.0.1:8765` | serviço visível apenas no próprio PC |

## 3. Rotina diária

### 3.1 Antes de um treino importante

Faça estes testes no PC servidor, em PowerShell. Eles não exigem terminal como
administrador:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health |
    ConvertTo-Json -Compress

Get-ScheduledTask -TaskName CrepaldiHandball,CrepaldiHandballBackup |
    Select-Object TaskName, State

Get-Service -Name cloudflared -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType

Invoke-RestMethod https://handball.crepaldi.com.br/health |
    ConvertTo-Json -Compress
```

Resultado esperado:

```text
{"status":"ok"}
CrepaldiHandball       Running
CrepaldiHandballBackup Ready
cloudflared            Running
{"status":"ok"}
```

`CrepaldiHandballBackup` em `Ready` é normal quando não está executando. Se o
nome do serviço `cloudflared` não for encontrado, descubra o nome real sem
alterar nada:

```powershell
Get-Service |
    Where-Object { $_.Name -like '*cloudflared*' -or $_.DisplayName -like '*cloudflared*' } |
    Select-Object Name, DisplayName, Status, StartType
```

Depois, abra uma janela privada do navegador e confirme:

1. `https://handball.crepaldi.com.br/login`;
2. login com a conta administrativa;
3. página `/app` com indicador `Online`;
4. data correta do treino;
5. histórico/auditoria acessíveis.

Nunca cole a senha em conversa, captura de tela, issue ou comando que fique no
histórico do shell.

### 3.2 Depois do treino

1. confirme que as alterações foram salvas;
2. abra Histórico ou Auditoria e confira o evento esperado;
3. faça um backup manual quando a sessão for relevante;
4. anote qualquer operação offline ainda não sincronizada antes de fechar o
   navegador ou limpar dados do aplicativo.

## 4. Backup manual consistente `[ADMIN-PC]`

Abra PowerShell 7 **como Administrador**, pois toda a raiz instalada — releases,
`state`, `app`, `ops`, `data`, `backups` e logs — tem ACL para SYSTEM e
Administradores. Não use uma cópia simples do `.db` enquanto o servidor pode
estar gravando.

Para um backup operacional comum sujeito à retenção de 30, prefira o script
oficial instalado, que usa a API SQLite:

```powershell
& 'C:\ProgramData\CrepaldiHandball\app\scripts\backup-server.ps1'
```

Esse launcher tem caminho estável. Ele resolve a release imutável indicada por
`state\active-release.json` e delega `quick_check`, fingerprint e cópia SQLite a
`ops\database-guard.py`, que não importa a aplicação nem executa DDL ou seed.

Para um marco que não deve entrar no glob automático `presencas-*.db`, use o
procedimento abaixo. O prefixo `marco-presencas-` é intencional; um nome
`presencas-manual-*` também seria contado e poderia ser removido pela rotação.

Abra PowerShell e execute o bloco completo:

```powershell
$handballRoot = 'C:\ProgramData\CrepaldiHandball'
$databasePath = Join-Path $handballRoot 'data\presencas.db'
$backupFolder = Join-Path $handballRoot 'backups'
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = Join-Path $backupFolder "marco-presencas-$backupStamp.db"
$opsManifestPath = Join-Path $handballRoot 'ops\ops-manifest.json'
$guardPath = Join-Path $handballRoot 'ops\database-guard.py'
$configPath = Join-Path $handballRoot 'data\app-config.json'

$opsManifest = Get-Content -Raw -LiteralPath $opsManifestPath |
    ConvertFrom-Json
$pythonPath = [IO.Path]::GetFullPath([string]$opsManifest.guard_python_path)
$guardEntry = @(
    $opsManifest.files | Where-Object path -CEQ 'ops/database-guard.py'
)

if (-not (Test-Path -LiteralPath $databasePath)) {
    throw "Banco não encontrado: $databasePath"
}
foreach ($requiredFile in @($configPath, $pythonPath, $guardPath, $opsManifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Arquivo operacional não encontrado: $requiredFile"
    }
}
if (
    [int]$opsManifest.format -ne 1 -or
    [int]$opsManifest.protocol -ne 1 -or
    $guardEntry.Count -ne 1 -or
    (Get-FileHash $pythonPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$opsManifest.guard_python_sha256 -or
    (Get-FileHash $guardPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$guardEntry[0].sha256
) {
    throw 'Runtime operacional não corresponde ao manifesto.'
}
New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null

$verifyText = @(
    & $pythonPath -I -S $guardPath fingerprint `
        --config-path $configPath `
        --expected-database-path $databasePath 2>&1
) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "O guard recusou o banco: $verifyText"
}
$verify = $verifyText | ConvertFrom-Json

$backupText = @(
    & $pythonPath -I -S $guardPath backup `
        --config-path $configPath `
        --expected-database-path $databasePath `
        --expected-backup-root $backupFolder `
        --destination $backupPath `
        --expected-fingerprint $verify.logical_fingerprint 2>&1
) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "O backup SQLite foi recusado: $backupText"
}
$backupResult = $backupText | ConvertFrom-Json

$backupInfo = Get-Item -LiteralPath $backupPath
$backupHash = Get-FileHash -LiteralPath $backupPath -Algorithm SHA256
[pscustomobject]@{
    Path = $backupInfo.FullName
    Bytes = $backupInfo.Length
    LastWriteTime = $backupInfo.LastWriteTime
    SHA256 = $backupHash.Hash.ToLowerInvariant()
    Fingerprint = $backupResult.logical_fingerprint
}
```

Copie para o registro operacional somente caminho, tamanho, data e hash. Não
adicione o arquivo ao Git, ao OneDrive do portal, ao ZIP público ou a mensagens.

### 4.1 Verificar integridade do banco em leitura `[ADMIN-PC]`

```powershell
$handballRoot = 'C:\ProgramData\CrepaldiHandball'
$opsManifest = Get-Content -Raw `
    -LiteralPath (Join-Path $handballRoot 'ops\ops-manifest.json') |
    ConvertFrom-Json
$pythonPath = [IO.Path]::GetFullPath([string]$opsManifest.guard_python_path)
$guardPath = Join-Path $handballRoot 'ops\database-guard.py'
$guardEntry = @($opsManifest.files | Where-Object path -CEQ 'ops/database-guard.py')
if (
    [int]$opsManifest.format -ne 1 -or
    [int]$opsManifest.protocol -ne 1 -or
    $guardEntry.Count -ne 1 -or
    (Get-FileHash $pythonPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$opsManifest.guard_python_sha256 -or
    (Get-FileHash $guardPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$guardEntry[0].sha256
) { throw 'Runtime operacional não corresponde ao manifesto.' }
& $pythonPath -I -S $guardPath verify `
    --config-path (Join-Path $handballRoot 'data\app-config.json') `
    --expected-database-path (Join-Path $handballRoot 'data\presencas.db')
```

Resultado esperado: JSON com `"ok": true`, `"quick_check": "ok"`, lista vazia
em `foreign_key_check` e um `logical_fingerprint` SHA-256.

Se o JSON não satisfizer todas essas condições, pare alterações no aplicativo, faça uma
cópia de preservação e siga a seção de incidente de banco. Não tente “consertar”
o arquivo original por tentativa e erro.

### 4.2 Inspecionar os backups existentes `[ADMIN-PC]`

```powershell
Get-ChildItem -LiteralPath 'C:\ProgramData\CrepaldiHandball\backups' -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 15 Name, Length, LastWriteTime
```

Para verificar o hash de uma cópia específica:

```powershell
Get-FileHash -LiteralPath 'C:\ProgramData\CrepaldiHandball\backups\NOME-EXATO.db' -Algorithm SHA256
```

Substitua `NOME-EXATO.db` por um nome que realmente apareceu na listagem.

## 5. Atualizar o código do aplicativo `[APP-LOCAL]` + `[ADMIN-PC]`

### 5.1 O que não é automático

Salvar uma alteração no VSCode muda somente o repositório fonte. Fazer commit
também não atualiza a instalação. A URL pública continua executando a release
imutável em `releases\<release_id>` indicada por
`C:\ProgramData\CrepaldiHandball\state\active-release.json` até o updater publicar
outro ponteiro.

Não use sincronização automática do repositório para `C:\ProgramData`. O gate
manual protege o banco e permite validar cada versão.

### 5.2 Pré-condições

- PC conectado à energia e internet;
- nenhum treino sendo editado naquele momento;
- PowerShell 7 disponível;
- worktree compreendido, sem apagar alterações de terceiros;
- todos os arquivos de runtime/operação rastreados, limpos e contidos no commit
  `HEAD`; fonte modificada, staged ou não rastreada bloqueia o updater;
- backup manual concluído e hash registrado;
- versão anterior/commit conhecido para rollback.

### 5.3 Validação no repositório fonte

Abra PowerShell 7 normal:

```powershell
Set-Location -LiteralPath 'C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas'
Set-ExecutionPolicy -Scope Process Bypass

.\scripts\test.ps1
if ($LASTEXITCODE -ne 0) { throw 'Testes falharam; instalação cancelada.' }

.\.venv\Scripts\python.exe -m compileall -q app.py attendance tests
if ($LASTEXITCODE -ne 0) { throw 'Compilação falhou; instalação cancelada.' }

git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check falhou; instalação cancelada.' }

git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'O diff staged contém erro; instalação cancelada.' }

git diff --cached --stat
git status --short
git log -3 --oneline
```

Interprete o `git status` antes de qualquer janela de produção. A revisão pode
acontecer com alterações locais, mas a execução do updater exige que toda fonte
incluída no runtime ou na camada operacional esteja rastreada, sem diferença no
worktree/index e registrada em um commit descritivo. O updater verifica novamente
essa condição e recusa o update se ela não for satisfeita.

O marco conhecido de 21/07/2026 é:

```text
72cb9e3 fix: flexibiliza senha e corrige instalação no Windows
```

### 5.4 Backup imediatamente antes da atualização

`update-server.ps1` cria o backup de marco depois de parar o servidor e antes de
avançar o ponteiro. O guard independente exige `quick_check = ok`, vincula o
backup ao fingerprint esperado, registra tamanho e SHA-256 e usa o prefixo
`app-only-`, fora da rotação diária `presencas-*`. O backup externo cifrado da seção
4 continua sendo uma proteção separada contra perda do computador.

### 5.5 Atualização `[ADMIN-PC]`

#### Comando canônico para mudanças do aplicativo

Use **PowerShell 7 como Administrador**, nunca CMD. Antes de executar, classifique
a mudança: código/interface somente usa `APP_ONLY`; qualquer alteração em schema,
migration ou dado persistente usa `DB_MIGRATION`. O comando canônico é:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas\atualizar-aplicativo.ps1' -Modo DB_MIGRATION -InstallRoot 'C:\ProgramData\CrepaldiHandball'
```

Para `APP_ONLY`, use o mesmo comando sem `-Modo DB_MIGRATION`. O launcher valida
testes, compileall e Git, ativa a release e, no modo de banco, planeja e aplica
somente o `plan_sha256` que ele próprio acabou de conferir. Não execute
`install-server.ps1` em atualização e não rode a migration isoladamente sem uma
janela de manutenção autorizada.

Abra **PowerShell 7 como Administrador**, volte ao repositório e execute:

```powershell
Set-Location -LiteralPath 'C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas'
Set-ExecutionPolicy -Scope Process Bypass

.\scripts\update-server.ps1
```

O instalador `install-server.ps1` é somente bootstrap e recusa instalação
existente. O updater dedicado:

1. aceita apenas runtime e componentes operacionais rastreados, limpos e
   commitados no Git;
2. prepara staging e `.venv` isolados sem tocar no serviço;
3. recusa `app-config.json` ou `presencas.db` ausentes;
4. usa o mesmo lock exclusivo da tarefa de backup;
5. para a tarefa e confirma a porta `8765` livre;
6. usa `ops\database-guard.py` para `quick_check`, fingerprint e backup de marco
   com SHA-256;
7. promove o staging a uma nova release imutável em `releases\<release_id>`;
8. mantém launchers/resolver em `app\scripts` e o guard em `ops`, ambos em
   caminhos operacionais estáveis, autenticados e preservados;
9. troca atomicamente apenas `state\active-release.json`;
10. exige `/ready` com o `release_id` novo e fingerprint idêntico;
11. em falha, restaura somente ponteiro/código anterior confiável, sem restaurar
    o SQLite.

Atualização comum não chama bootstrap, seed ou migration e nunca troca, move ou
restaura `data`, `app-config.json`, `presencas.db`, `backups` ou `logs`. Mudança
futura de esquema é manutenção separada e explicitamente autorizada.

Exceção fail-closed: na primeira passagem do layout legado para o layout com
ponteiro ainda não existe release anterior confiável. Se houver falha depois que o
serviço for parado, ele deve permanecer parado para recuperação manual. Não
reinicie o release legado automaticamente, pois seu startup pode modificar dados.
Essa primeira ponte também instala os launchers/guard, endurece recursivamente a
ACL da raiz e corrige `ExecutionTimeLimit` do servidor quando necessário. Uma
release formal posterior apenas verifica essas invariantes.

### 5.6 Verificação após atualização

Ainda no PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health |
    ConvertTo-Json -Compress

Invoke-RestMethod http://127.0.0.1:8765/ready |
    ConvertTo-Json -Compress

Get-ScheduledTask -TaskName CrepaldiHandball,CrepaldiHandballBackup |
    Select-Object TaskName, State

Invoke-RestMethod https://handball.crepaldi.com.br/health |
    ConvertTo-Json -Compress
```

Depois faça no navegador:

1. login pela URL pública;
2. leitura de uma chamada/histórico conhecido;
3. navegação autenticada e carregamento de assets;
4. logout;
5. recarregamento forte se houve alteração de frontend;
6. teste no celular se houve mudança de PWA ou layout.

O aceite de `APP_ONLY` é somente leitura. Qualquer teste de escrita deve usar
uma cópia temporária do banco ou outra manutenção explicitamente autorizada.

Registre commit, horário, backup, resultados e eventual rollback.

## 6. Redefinir a senha administrativa `[ADMIN-PC]`

No layout com releases imutáveis, use somente o launcher operacional estável. Ele
resolve a release ativa, altera a configuração persistente e faz Stop → confirmação
da porta livre → Start → `/ready` sem depender de `Restart-ScheduledTask`:

```powershell
& 'C:\ProgramData\CrepaldiHandball\app\scripts\reset-password.ps1'
```

Regras atuais:

- a senha pode ter qualquer comprimento, mas não pode ser vazia;
- a confirmação deve ser idêntica;
- a configuração persiste somente o hash Argon2id;
- a CLI gira a chave de sessão; as sessões só ficam efetivamente inválidas
  depois que o processo é parado e iniciado com a nova configuração;
- por estar exposto à internet, use na prática uma senha longa, exclusiva e
  gerenciada com segurança.

Depois valide saúde local, login em janela privada, logout e saúde pública. Não
copie a senha para este runbook.

## 7. Ligar, desligar e reiniciar o computador `[ADMIN-PC]`

### 7.1 Antes de desligar

1. confirme que ninguém está salvando chamada;
2. verifique se não existe operação offline pendente no navegador usado;
3. faça backup manual se houver dados recentes importantes;
4. desligue normalmente o Windows.

### 7.2 Enquanto estiver desligado

O subdomínio de handebol fica indisponível porque não há origem nem conector. O
site principal, o portal estático e o e-mail continuam em seus provedores e não
dependem desse PC.

### 7.3 Após ligar

Aguarde a rede e execute:

```powershell
Get-ScheduledTask -TaskName CrepaldiHandball,CrepaldiHandballBackup |
    Select-Object TaskName, State

Get-Service -Name cloudflared -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType

Invoke-RestMethod http://127.0.0.1:8765/health |
    ConvertTo-Json -Compress

Invoke-RestMethod https://handball.crepaldi.com.br/health |
    ConvertTo-Json -Compress
```

Se a tarefa do servidor estiver parada, em PowerShell como Administrador:

```powershell
Start-ScheduledTask -TaskName CrepaldiHandball
Start-Sleep -Seconds 3
```

Se o serviço do túnel estiver parado e o nome confirmado for `cloudflared`:

```powershell
Start-Service -Name cloudflared
Start-Sleep -Seconds 3
```

Não automatize correções adicionais antes de identificar qual camada falhou.

## 8. Diagnóstico por camadas

Sempre teste de dentro para fora:

### Camada 1 — arquivos

```powershell
Test-Path 'C:\ProgramData\CrepaldiHandball\data\presencas.db'
Test-Path 'C:\ProgramData\CrepaldiHandball\data\app-config.json'
Test-Path 'C:\ProgramData\CrepaldiHandball\backups'
```

Todos devem retornar `True`. Nunca exiba o conteúdo de `app-config.json` em
conversa ou log compartilhado.

### Camada 2 — processo local

```powershell
Get-ScheduledTask -TaskName CrepaldiHandball |
    Select-Object TaskName, State

Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, State, OwningProcess

Invoke-RestMethod http://127.0.0.1:8765/health |
    ConvertTo-Json -Compress
```

Se não responder, o problema está no servidor local ou na instalação; DNS não é
a causa primária.

### Camada 3 — conector

```powershell
Get-Service -Name cloudflared -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType
```

Se a saúde local funciona e o serviço está parado, inicie o serviço. Se ele
para novamente, examine os logs do Windows e a configuração do serviço sem
copiar o token.

### Camada 4 — DNS `[LEITURA]`

```powershell
Resolve-DnsName -Name handball.crepaldi.com.br -Type A -Server 1.1.1.1
Resolve-DnsName -Name handball.crepaldi.com.br -Type AAAA -Server 1.1.1.1
Resolve-DnsName -Name crepaldi.com.br -Type NS -Server 1.1.1.1 |
    Select-Object -ExpandProperty NameHost
```

Nameservers esperados:

```text
dawn.ns.cloudflare.com
nash.ns.cloudflare.com
```

Como o hostname é proxied, o DNS público pode retornar A/AAAA da Cloudflare e
ocultar o CNAME `cfargotunnel.com`; isso é esperado. O destino lógico do túnel
só deve ser conferido no painel pelo proprietário (`[EXTERNO]`). Ausência de
CNAME numa consulta pública não prova falha. Não mude registros de site ou
e-mail para corrigir uma falha exclusiva do túnel.

### Camada 5 — borda pública

```powershell
Invoke-WebRequest https://handball.crepaldi.com.br/health -UseBasicParsing |
    Select-Object StatusCode, Content
```

Esperado: HTTP 200 e conteúdo `{"status":"ok"}`.

### Camada 6 — função de negócio

Mesmo com `/health` verde, teste login, leitura, gravação, auditoria e logout. A
saúde técnica não substitui o teste de persistência.

## 9. Tabela de incidentes

| Sintoma | Causa mais provável | Primeira verificação | Ação inicial segura |
|---|---|---|---|
| site principal e e-mail normais; handball fora | PC, backend ou túnel | saúde local | ligar PC; checar tarefa e serviço |
| saúde local falha | tarefa/backend | estado da tarefa e porta 8765 | iniciar tarefa; revisar instalação/log |
| saúde local funciona; pública falha | cloudflared, rota ou DNS | serviço, A/AAAA público e HTTPS | iniciar serviço; proprietário confere painel/rota |
| login abre, senha não funciona | credencial ou configuração | tentar com cuidado; evitar bloqueio | redefinir senha pelo script aprovado |
| interface abre, gravação falha | API, SQLite ou permissão | Auditoria e integridade | parar novas edições; fazer preservação |
| dados parecem antigos no frontend | cache/PWA ou data selecionada | janela privada e data do treino | recarregamento forte; conferir service worker |
| e-mail falha após mudança DNS | MX/SPF/DKIM/DMARC | registros DNS only | comparar com export, sem apagar registros |
| backup diário ausente | PC desligado às 03:00 ou tarefa | histórico da tarefa | backup manual; revisar `StartWhenAvailable` |
| túnel pede novo token | token rotacionado/inválido | painel da Cloudflare | gerar e instalar novo token sem registrá-lo |

## 10. Preservação e recuperação do banco `[ADMIN-PC]`

### 10.1 Regra de ouro

Nunca sobrescreva o único banco existente. Antes de restaurar, preserve o
arquivo atual com timestamp. Faça a operação em janela de manutenção e como
administrador.

### 10.2 Exercício seguro recomendado

Antes de um incidente real, copie um backup para uma pasta temporária controlada
e rode `PRAGMA quick_check` nessa cópia. Não aponte o aplicativo de produção para
ela. Documente se o backup abre e qual hash foi testado.

### 10.3 Restauração de produção

Este procedimento muda dados e deve ser executado somente pelo proprietário
depois de escolher conscientemente o backup correto:

```powershell
$handballRoot = 'C:\ProgramData\CrepaldiHandball'
$databasePath = Join-Path $handballRoot 'data\presencas.db'
$recoveryStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$recoveryFolder = Join-Path $handballRoot "data\recovery-$recoveryStamp"
$selectedBackup = 'C:\ProgramData\CrepaldiHandball\backups\SUBSTITUA-PELO-BACKUP-ESCOLHIDO.db'
$opsManifest = Get-Content -Raw `
    -LiteralPath (Join-Path $handballRoot 'ops\ops-manifest.json') |
    ConvertFrom-Json
$pythonPath = [IO.Path]::GetFullPath([string]$opsManifest.guard_python_path)
$guardPath = Join-Path $handballRoot 'ops\database-guard.py'
$guardEntry = @($opsManifest.files | Where-Object path -CEQ 'ops/database-guard.py')

if (-not (Test-Path -LiteralPath $databasePath)) {
    throw "Banco atual não encontrado: $databasePath"
}
if (-not (Test-Path -LiteralPath $selectedBackup)) {
    throw "Backup escolhido não encontrado: $selectedBackup"
}
if (
    -not (Test-Path -LiteralPath $pythonPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $guardPath -PathType Leaf) -or
    [int]$opsManifest.format -ne 1 -or
    [int]$opsManifest.protocol -ne 1 -or
    $guardEntry.Count -ne 1 -or
    (Get-FileHash $pythonPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$opsManifest.guard_python_sha256 -or
    (Get-FileHash $guardPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        [string]$guardEntry[0].sha256
) {
    throw 'Runtime operacional não corresponde ao manifesto.'
}

# Validar o backup escolhido antes de tocar na produção. Exit code zero não
# basta: PRAGMA quick_check precisa retornar literalmente "ok".
$backupCheck = & $pythonPath -I -S -c "import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()" $selectedBackup
if ($LASTEXITCODE -ne 0 -or (($backupCheck -join "`n").Trim() -ne 'ok')) {
    throw "Backup reprovado no quick_check: $($backupCheck -join '; ')"
}
$backupForeignKeys = & $pythonPath -I -S -c "import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print(len(list(c.execute('PRAGMA foreign_key_check')))); c.close()" $selectedBackup
if ($LASTEXITCODE -ne 0 -or (($backupForeignKeys -join "`n").Trim() -ne '0')) {
    throw "Backup possui violação de chave estrangeira: $($backupForeignKeys -join '; ')"
}

Stop-ScheduledTask -TaskName CrepaldiHandball
for ($attempt = 1; $attempt -le 20; $attempt++) {
    $taskState = (Get-ScheduledTask -TaskName CrepaldiHandball).State
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($taskState -ne 'Running' -and -not $listener) { break }
    Start-Sleep -Seconds 1
}
if ((Get-ScheduledTask -TaskName CrepaldiHandball).State -eq 'Running') {
    throw 'A tarefa continua em execução; restauração cancelada.'
}
if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
    throw 'A porta 8765 continua ocupada; restauração cancelada.'
}

New-Item -ItemType Directory -Path $recoveryFolder -ErrorAction Stop | Out-Null
foreach ($currentFile in @(
    $databasePath,
    "$databasePath-wal",
    "$databasePath-shm"
)) {
    if (Test-Path -LiteralPath $currentFile) {
        Move-Item -LiteralPath $currentFile -Destination $recoveryFolder -ErrorAction Stop
    }
}
Copy-Item -LiteralPath $selectedBackup -Destination $databasePath

$restoredCheck = & $pythonPath -I -S -c "import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print(c.execute('PRAGMA quick_check').fetchone()[0]); c.close()" $databasePath
if ($LASTEXITCODE -ne 0 -or (($restoredCheck -join "`n").Trim() -ne 'ok')) {
    throw "Banco restaurado reprovado no quick_check. Servidor permanece parado: $($restoredCheck -join '; ')"
}
$restoredForeignKeys = & $pythonPath -I -S -c "import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(f'file:{p}?mode=ro', uri=True); print(len(list(c.execute('PRAGMA foreign_key_check')))); c.close()" $databasePath
if ($LASTEXITCODE -ne 0 -or (($restoredForeignKeys -join "`n").Trim() -ne '0')) {
    throw "Banco restaurado possui violação de chave estrangeira; servidor permanece parado."
}

Start-ScheduledTask -TaskName CrepaldiHandball
Start-Sleep -Seconds 3
Invoke-RestMethod http://127.0.0.1:8765/health |
    ConvertTo-Json -Compress
```

Antes de executar, substitua literalmente o placeholder do backup. O diretório
`recovery-*` preserva `presencas.db` e eventuais sidecars `-wal`/`-shm` como
conjunto. Depois, teste login, dados conhecidos, gravação controlada e
auditoria. Guarde o conjunto preservado até validar a recuperação.

Se qualquer comando falhar após o `Stop-ScheduledTask`, não improvise uma
segunda substituição: preserve todos os arquivos e registre o erro exato.

### 10.4 Desastre do computador

Backups em `C:\ProgramData` ficam no mesmo PC e não protegem contra perda do
disco, furto ou ransomware. Deve existir uma política separada de cópia externa
cifrada: periodicidade, destino, chave sob custódia do proprietário, retenção,
hash e teste de restauração. Não usar a Hostinger como banco e não sincronizar
por cópia bruta um SQLite aberto.

## 11. Cloudflare e DNS: governança `[EXTERNO]`

### 11.1 Estado-base conhecido

- zona: `crepaldi.com.br`, plano Free;
- nameservers: `dawn.ns.cloudflare.com` e `nash.ns.cloudflare.com`;
- registros preexistentes: DNS only durante a migração;
- handball: CNAME gerado pelo Tunnel e proxy ativo por projeto;
- DNSSEC: não habilitado no marco inicial;
- export anterior: arquivo local em Downloads, SHA-256 registrado no relatório.

### 11.2 Antes de mudar qualquer registro

1. exporte a zona atual;
2. registre data e SHA-256 do export;
3. compare A, AAAA, CNAME, MX, TXT, CAA e SRV;
4. identifique impacto em site, FTP e e-mail;
5. altere uma variável por vez;
6. valide com 1.1.1.1 e 8.8.8.8;
7. teste site principal, `/roberto/`, envio e recebimento de e-mail.

Não torne MX, SPF, DKIM, DMARC, `autoconfig` ou `autodiscover` proxied. Registros
de protocolos não HTTP devem permanecer DNS only, salvo decisão técnica
específica e documentada.

### 11.3 DNSSEC

Habilite somente após a zona permanecer estável. A ordem deve ser a indicada
pela Cloudflare: habilitar/obter os dados na Cloudflare, publicar DS no
registrador e depois validar externamente. Um DS incorreto pode tornar todo o
domínio irresolúvel.

### 11.4 Token do túnel

O token concede acesso ao túnel. Não o armazene neste repositório. Se houver
suspeita de exposição:

1. rotacione o token no painel;
2. atualize todas as réplicas autorizadas;
3. confirme que a réplica antiga deixa de conectar;
4. valide saúde pública;
5. registre somente a data da rotação, nunca o token.

## 12. PWA, cache e modo offline

O service worker conhecido usa `handball-shell-v2`. O aplicativo prefere rede
para páginas e arquivos estáticos e pode usar cache como fallback. APIs não
devem ser interpretadas como disponíveis apenas porque a interface abriu.

Após alterar frontend ou service worker:

1. abra a aplicação com o PC e o túnel online;
2. faça recarregamento forte no desktop;
3. feche e reabra a PWA no celular;
4. confirme a versão visual/funcional esperada;
5. valide online antes do teste offline;
6. ative modo avião somente depois de confirmar que o fluxo offline foi
   preparado;
7. gere uma chamada de teste offline;
8. reconecte e confirme sincronização e auditoria;
9. não limpe dados do site antes de confirmar que não há operação pendente.

No iPhone, a instalação é manual por Safari:

```text
Compartilhar -> Adicionar à Tela de Início
```

O PIN offline não deve ser a senha administrativa e não deve ser reutilizado em
outros serviços.

## 13. Integração e publicação do portal `/roberto/`

O link do handball ainda precisa ser implementado. O fluxo permitido é:

- preparação e validação local: agente do `site`, sujeito a `[APP-LOCAL]` e
  `AGENTS.md`;
- inventário, backup remoto e upload: proprietário, sob `[EXTERNO]`.

1. trabalhar somente no repositório
   `C:\Users\rober\OneDrive\Área de Trabalho\site`;
2. preservar todas as alterações locais existentes;
3. adicionar ação secundária discreta em `privado/index.html` apontando para
   `https://handball.crepaldi.com.br/`;
4. informar que existe login próprio;
5. não usar iframe, script externo ou mudança desnecessária de CSP;
6. preservar 50/50, cofre, canonical, `noindex`, acessibilidade e 44 px;
7. executar:

```powershell
pwsh -NoProfile -File .\scripts\test-vault.ps1
pwsh -NoProfile -File .\scripts\validate.ps1
pwsh -NoProfile -File .\scripts\package-release.ps1
git diff --check
git status --short
```

8. revisar diff, ZIP e `MANIFEST-SHA256.txt`;
9. confirmar imediatamente antes da publicação a existência de
   `public_html/roberto/`, inventário remoto e backup restaurável;
10. o proprietário faz upload manual somente da allowlist.

Allowlist atual:

```text
index.html
styles.css
publico/index.html
privado/index.html
privado/vault.js
privado/vault.json
```

`MANIFEST-SHA256.txt` é comprovante local e não é enviado. Documentos em
`docs/`, banco, configuração, logs e backups jamais entram no pacote público.

## 14. Registro mínimo de cada manutenção

Para cada atualização, acrescente ao log interno um bloco com:

```text
Data/hora e fuso:
Operador:
Objetivo:
Tipo da operação (INITIAL_INSTALL, APP_ONLY, DB_MIGRATION ou manutenção):
Commit anterior:
Commit instalado:
release_id antes/depois:
schema_version antes/depois:
Caminho exato de app-config.json e presencas.db:
Fingerprint lógico do banco antes/depois:
Backup anterior (caminho, bytes, SHA-256):
Testes executados e resultados:
Saúde local:
Saúde pública:
Login/leitura/auditoria:
Validação de escrita (NÃO APLICÁVEL ao APP_ONLY, salvo manutenção separada):
PWA/celular, se aplicável:
Problemas observados:
Rollback necessário:
Estado final:
Segredos registrados: NÃO
```

Sem esse registro, uma atualização pode funcionar, mas não será auditável.

## 15. Checklist mensal

- [ ] `/health` local e público respondem `ok`;
- [ ] login, leitura, gravação, auditoria e logout funcionam;
- [ ] `PRAGMA quick_check` retorna `ok`;
- [ ] backups recentes existem e seus tamanhos são plausíveis;
- [ ] ao menos um backup do mês teve hash registrado;
- [ ] histórico da tarefa de backup não mostra falhas repetidas;
- [ ] serviço cloudflared está automático e saudável;
- [ ] Windows e dependências têm atualizações de segurança planejadas;
- [ ] não há segredos ou banco rastreados no Git;
- [ ] site principal, portal e e-mail continuam normais;
- [ ] registros DNS continuam coerentes com o inventário aprovado;
- [ ] a conta Cloudflare usa autenticação forte;
- [ ] contato e procedimento de recuperação continuam acessíveis ao proprietário;
- [ ] nenhuma operação offline ficou esquecida num aparelho.

## 16. Melhorias futuras recomendadas

1. exercitar periodicamente, em ambiente controlado, rollback do ponteiro
   `active-release.json` e falha do primeiro update sobre layout legado;
2. aplicar e verificar `StartWhenAvailable` na tarefa legada de backup;
3. criar teste automatizado de restauração em cópia temporária;
4. adicionar monitoramento externo de disponibilidade com alerta, sem autenticar
   nem coletar dados pessoais;
5. exibir `release_id` e `schema_version` na interface autenticada; `/ready` já os
   fornece tecnicamente no código candidato;
6. testar a política de cache em atualização real de frontend;
7. definir requisito de disponibilidade: “quando o PC estiver ligado” ou 24/7;
8. se 24/7 for necessário, considerar máquina dedicada, UPS e segunda réplica;
9. acompanhar a depreciação Starlette/httpx e atualizar somente com suíte verde;
10. separar dependências de runtime/desenvolvimento e criar lock reproduzível;
11. definir retenção e ACL dos logs e validar o IP usado pelo rate limit no túnel;
12. revisar periodicamente usuários, sessões, logs e retenção de backups.

## 17. Encerramento de incidente

Um incidente só está encerrado quando:

- causa raiz foi identificada, não apenas o sintoma removido;
- banco foi preservado e integridade verificada;
- saúde local e pública estão verdes;
- login, leitura, gravação e auditoria foram testados;
- site principal e e-mail permanecem normais se DNS foi envolvido;
- ação corretiva e evidências foram registradas;
- nenhum segredo foi colado no registro;
- prevenção ou teste de regressão foi criado quando aplicável.
