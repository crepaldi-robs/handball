# Registro Oficial de Presenças — PWA

Aplicação privada para administrar confirmações e presença real nos treinos de
handebol. O backend FastAPI mantém o SQLite como fonte oficial; a interface
responsiva funciona no computador e pode ser instalada na Tela de Início do
iPhone.

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

## Preparar no Windows pelo VSCode

No PowerShell integrado:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

O primeiro comando solicitará usuário e uma senha com pelo menos 12 caracteres.
Acesse `http://127.0.0.1:8765`. A senha não é salva; somente seu hash Argon2id é
gravado em `data\app-config.json`, arquivo ignorado pelo Git.

## Uso no iPhone

Depois da publicação em `https://handball.crepaldi.com.br`, abra o endereço no
Safari, faça login e use **Compartilhar > Adicionar à Tela de Início**. No botão
de proteção offline do cabeçalho, crie um PIN local de pelo menos seis dígitos.

Somente chamada, confirmação e observações individuais funcionam offline. Elenco,
histórico, auditoria, exportações, encerramento e reabertura exigem o servidor.
Se um registro tiver mudado no PC, a edição offline não o sobrescreve.

## Servidor permanente e domínio

O roteiro completo está em [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Em resumo:

1. `scripts\install-server.ps1` instala a aplicação em
   `C:\ProgramData\CrepaldiHandball` e registra tarefas de servidor e backup.
2. O Cloudflare Tunnel publica apenas `127.0.0.1:8765` em
   `handball.crepaldi.com.br`, sem abrir portas do roteador.
3. DNS e Hostinger são configurados manualmente pelo proprietário.

O projeto vizinho `../site` permanece exclusivo de
`https://crepaldi.com.br/roberto/`. Nenhum arquivo deste aplicativo deve ser
enviado para `public_html/roberto/`.

## Testes

```powershell
.\scripts\test.ps1
```

Os testes cobrem regras de domínio, migrações, auditoria, backup, autenticação,
CSRF, sincronização idempotente e conflitos de versão.

## Dados e recuperação

Em desenvolvimento, o banco fica em `data\presencas.db`. Na instalação permanente:

```text
C:\ProgramData\CrepaldiHandball\data\presencas.db
```

Backups diários consistentes ficam em `C:\ProgramData\CrepaldiHandball\backups`.
Não copie nem substitua o banco enquanto o servidor estiver escrevendo nele;
use a rotina de backup fornecida.
