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
- login administrativo, CSRF, rate limit e cookies seguros;
- chamada offline cifrada por PIN no iPhone;
- sincronização idempotente com detecção de conflitos;
- PC sempre preservado como fonte de verdade em conflitos.

## Módulos e rotas

- `/app`: Hub Handebol;
- `/app/presencas`: registro funcional de confirmações e presenças;
- `/app/estatisticas`: módulo autenticado em preparação;
- `/app/calendario`: módulo autenticado em preparação.

Toda a implementação reside em `handball/`. Persistência, conexões,
transações, SQL, schema, migrations e backups ficam exclusivamente em
`handball/database/`; os módulos usam contratos e unidades de trabalho. A
arquitetura e o processo de extensão estão em
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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
