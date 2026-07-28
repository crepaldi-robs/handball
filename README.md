# Plataforma Handball — PWA modular

Aplicação privada modular para administrar o handebol. Um único backend
FastAPI, uma sessão e um cookie atendem o hub e seus módulos. O SQLite continua
como fonte oficial; a interface responsiva funciona no computador e pode ser
instalada na Tela de Início do iPhone.

## Recursos

- confirmação prévia e presença real como informações independentes;
- chamada aberta, encerramento e reabertura;
- observações individuais e gerais;
- mensagem pronta para o técnico;
- histórico, elenco, auditoria, CSV e backup SQLite;
- contas pessoais com papéis `DEV`, `CT` e `PLAYER`;
- sessões revogáveis, CSRF, rate limit e cookies seguros;
- relatório individual de presença com escopo aplicado no backend;
- chamada offline cifrada por PIN no iPhone;
- sincronização idempotente com detecção de conflitos;
- PC sempre preservado como fonte de verdade em conflitos.

## Módulos e rotas

- `/app`: Hub Handebol;
- `/app/presencas`: registro funcional de confirmações e presenças;
- `/app/meu-relatorio`: projeção individual para jogadores;
- `/app/admin/usuarios`: administração mínima exclusiva de DEV;
- `/app/estatisticas`: módulo autenticado em preparação;
- `/app/calendario`: módulo autenticado em preparação.

Toda a implementação reside em `handball/`. Persistência, conexões,
transações, SQL, schema, migrations e backups ficam exclusivamente em
`handball/database/`; os módulos usam contratos e unidades de trabalho. A
arquitetura e o processo de extensão estão em
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
O modelo de identidade, a matriz de permissões e o procedimento da migração
v2 estão em
[docs/HM-IME-USUARIOS-E-AUTORIZACAO.md](docs/HM-IME-USUARIOS-E-AUTORIZACAO.md).

## Preparar no Windows pelo VSCode

No PowerShell integrado:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

O primeiro comando solicitará usuário e uma senha, que pode ter qualquer
conteúdo não vazio. Acesse `http://127.0.0.1:8765`. A senha não é salva; somente
seu hash Argon2id é gravado em `data\app-config.json`, arquivo ignorado pelo Git.

## Uso no iPhone

Depois da publicação em `https://handball.crepaldi.com.br`, abra o endereço no
Safari, faça login e use **Compartilhar > Adicionar à Tela de Início**. No botão
de proteção offline do cabeçalho, crie um PIN local de pelo menos seis dígitos.

Somente a chamada em `/app/presencas`, confirmação e observações individuais
funcionam offline. Hub, estatísticas, calendário, elenco, histórico, auditoria,
exportações, encerramento e reabertura exigem o servidor.
Se um registro tiver mudado no PC, a edição offline não o sobrescreve.

## Servidor permanente e domínio

O roteiro completo está em [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Em resumo:

## Comandos administrativos: atualizar e iniciar

Abra o **PowerShell 7 como Administrador**. Cole cada bloco completo, um de
cada vez. Os comandos usam caminhos absolutos, portanto podem ser executados
de qualquer pasta do terminal.

### Atualização comum (APP_ONLY)

Este é o procedimento normal. Atualiza código, dependências e arquivos do
aplicativo, sem criar, alterar ou popular o banco SQLite existente:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas\atualizar-aplicativo.ps1" -Modo APP_ONLY
```

### Atualização com migração do banco (DB_MIGRATION)

Use somente quando a versão informar expressamente que há uma migração SQLite
aprovada. O comando executa primeiro o update compatível `APP_ONLY`, gera o
plano sem escrita e aplica exatamente o `plan_sha256` confirmado:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\rober\OneDrive\Área de Trabalho\handball\registrador-presencas\atualizar-aplicativo.ps1" -Modo DB_MIGRATION
```

### Iniciar o aplicativo

Use este procedimento após ligar o computador, após uma parada do serviço ou
depois de uma atualização. `Start-ScheduledTask` apenas pede o início da tarefa
e retorna imediatamente; por isso, sempre aguarde a porta local e confirme
`/ready` antes de abrir o site.

```powershell
$tarefa = Get-ScheduledTask -TaskName "CrepaldiHandball"
if ($tarefa.State -ne "Running") {
    Start-ScheduledTask -TaskName "CrepaldiHandball"
}
else {
    Write-Host "A tarefa CrepaldiHandball já está em execução."
}
```

```powershell
$portaAberta = $false
for ($tentativa = 1; $tentativa -le 60; $tentativa++) {
    $listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $portaAberta = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $portaAberta) {
    throw "O servidor não abriu a porta 127.0.0.1:8765 em 60 segundos. Execute o diagnóstico desta seção."
}
```

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8765/ready"
```

Se o último comando retornar um objeto de readiness, abra
`http://127.0.0.1:8765/app` ou `https://handball.crepaldi.com.br/app`.

### Diagnóstico de indisponibilidade ou erro 502

O erro **502** no domínio significa que o Cloudflare Tunnel não conseguiu
alcançar o aplicativo local. Antes de investigar o Tunnel, confirme o serviço
local. Cole os blocos abaixo, um por vez:

```powershell
Get-ScheduledTask -TaskName "CrepaldiHandball" | Select-Object TaskName, State
```

```powershell
Get-ScheduledTaskInfo -TaskName "CrepaldiHandball" | Select-Object LastRunTime, LastTaskResult
```

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess, State
```

O estado saudável é: tarefa `Running`, porta `127.0.0.1:8765` em `Listen` e
`/ready` respondendo. Uma tarefa `Running` sem a porta em `Listen` não é um
servidor saudável.

Para ler o motivo de uma falha recente, liste os logs:

```powershell
Get-ChildItem "C:\ProgramData\CrepaldiHandball\logs" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName, LastWriteTime, Length
```

Em seguida, substitua `<arquivo-do-log-mais-recente>` pelo caminho exibido
acima:

```powershell
Get-Content "<arquivo-do-log-mais-recente>" -Tail 120
```

Para converter `LastTaskResult` para hexadecimal, o formato normalmente usado
nas mensagens do Windows, execute:

```powershell
$resultado = (Get-ScheduledTaskInfo -TaskName "CrepaldiHandball").LastTaskResult
"Decimal: $resultado | Hexadecimal: {0:X8}" -f $resultado
```

### Reinicialização segura do serviço

Se a tarefa estiver `Running`, mas a porta 8765 não estiver em `Listen`, ou se
o site estiver em 502, reinicie somente a tarefa. Isto não atualiza código, não
reinstala o serviço e não altera o banco SQLite.

```powershell
Stop-ScheduledTask -TaskName "CrepaldiHandball"
```

```powershell
Start-Sleep -Seconds 8
Get-CimInstance Win32_Process | Where-Object { $_.Name -in "pwsh.exe", "python.exe", "pythonw.exe" -and $_.CommandLine -match "CrepaldiHandball|uvicorn|run-server" } | Select-Object ProcessId, Name, CommandLine
```

O segundo comando deve retornar vazio. Então inicie novamente e repita a
verificação de porta e `/ready` da seção anterior:

```powershell
Start-ScheduledTask -TaskName "CrepaldiHandball"
```

Não encerre processos com `Stop-Process`, não execute `install-server.ps1` em
uma instalação existente e não rode `DB_MIGRATION` para corrigir um 502. Se a
porta continuar indisponível após a reinicialização, preserve os logs e use o
diagnóstico acima antes de qualquer outra ação.

Testes, compilação, verificações Git, backup, integridade, readiness e rollback
de código permanecem obrigatórios e são executados pelos runners formais durante
a atualização.

1. `scripts\install-server.ps1` cria a primeira release imutável em
   `C:\ProgramData\CrepaldiHandball\releases\<release_id>`, publica
   `state\active-release.json` como ponteiro atômico e registra as tarefas de
   servidor e backup. Os launchers ficam nos caminhos estáveis `app\scripts` e o
   guard independente do SQLite fica em `ops`.
2. `scripts\update-server.ps1` aceita somente fonte rastreada, limpa e já
   registrada em commit, prepara outra release imutável e usa o guard para
   `quick_check`, fingerprint e backup antes de avançar o ponteiro ativo. Em
   falha, o rollback é somente de ponteiro/código; `data`, configuração, logs e
   backups nunca entram na troca.
3. `scripts\migrate-database.ps1` trata evolução do SQLite como manutenção
   separada: primeiro mostra um plano sem escrita e só aplica esse plano mediante
   confirmação explícita, com serviço parado e backup verificado.
4. O Cloudflare Tunnel publica apenas `127.0.0.1:8765` em
   `handball.crepaldi.com.br`, sem abrir portas do roteador.
5. DNS e Hostinger são configurados manualmente pelo proprietário.

O projeto vizinho `../site` permanece exclusivo de
`https://crepaldi.com.br/roberto/`. Nenhum arquivo deste aplicativo deve ser
enviado para `public_html/roberto/`.

Antes de desenvolver ou alterar qualquer interface entre os dois produtos, leia
o [contrato de integração e isolamento](docs/SITE-INTEGRATION-CONTRACT.md). O
único vínculo permitido é um link HTTPS comum no portal: não há iframe, API,
CORS, autenticação, cookie, cofre, service worker, banco ou release compartilhado.

## Testes

```powershell
.\scripts\test.ps1
```

Os testes cobrem regras de domínio, auditoria, backup inclusive com WAL,
autenticação, CSRF, sincronização idempotente, conflitos de versão, fronteiras
arquiteturais e a garantia de que startup/update não recriam nem modificam
implicitamente uma base existente.

## Dados e recuperação

Em desenvolvimento, o banco fica em `data\presencas.db`. Na instalação permanente:

```text
C:\ProgramData\CrepaldiHandball\data\presencas.db
```

Backups diários consistentes ficam em `C:\ProgramData\CrepaldiHandball\backups`.
Não copie nem substitua o banco enquanto o servidor estiver escrevendo nele;
use a rotina de backup fornecida.

O banco é estado permanente, não parte de uma release. Startup e backup abrem
uma instalação existente em modo de validação e falham se o arquivo ou o esquema
esperado estiver ausente; somente `handball.cli init-database`, chamado na
primeira instalação, tem permissão para criar a base.

Após uma instalação nova ou a primeira transição legada aceita, o layout separa
explicitamente código e estado:

```text
C:\ProgramData\CrepaldiHandball\releases\<release_id>\   # código e .venv imutáveis
C:\ProgramData\CrepaldiHandball\state\active-release.json # ponteiro atômico
C:\ProgramData\CrepaldiHandball\app\scripts\              # launchers estáveis
C:\ProgramData\CrepaldiHandball\ops\database-guard.py     # guard independente
C:\ProgramData\CrepaldiHandball\data\                     # configuração e SQLite
C:\ProgramData\CrepaldiHandball\backups\                  # backups persistentes
C:\ProgramData\CrepaldiHandball\logs\                     # logs persistentes
```

Existem duas identidades independentes: `release_id` identifica o código em
execução e `schema_version` identifica a estrutura do SQLite. Uma atualização
`APP_ONLY` nunca executa DDL, migration ou seed e mantém os mesmos caminhos de
`app-config.json`, banco, backups e logs. Quando uma melhoria exigir mudança do
schema, use exclusivamente o fluxo `DB_MIGRATION` documentado em
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), em outra janela operacional.
