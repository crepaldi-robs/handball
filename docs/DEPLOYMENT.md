# Publicação em `handball.crepaldi.com.br`

## Separação obrigatória

O aplicativo não faz parte de `../site` e não deve ser enviado para
`public_html/roberto/`. O portal permanece estático e sujeito às regras próprias
de publicação manual. O subdomínio apenas encaminha tráfego HTTPS para o serviço
executado neste PC.

## 1. Instalar o servidor local

Abra o PowerShell 7 como Administrador na pasta do projeto e execute:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-server.ps1
```

O instalador copia o código para `C:\ProgramData\CrepaldiHandball`, cria a conta
administradora, protege configuração e banco com ACL, registra inicialização no
boot e agenda um backup diário às 03:00, mantendo as 30 cópias mais recentes.

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

# Reiniciar o servidor
Restart-ScheduledTask -TaskName CrepaldiHandball

# Criar backup imediatamente
C:\ProgramData\CrepaldiHandball\app\scripts\backup-server.ps1

# Redefinir senha e invalidar sessões anteriores
C:\ProgramData\CrepaldiHandball\app\scripts\reset-password.ps1
```

Para restaurar, pare a tarefa do servidor, preserve uma cópia do banco atual,
copie um backup escolhido para `data\presencas.db` e reinicie a tarefa. Nunca
restaure com o servidor escrevendo no banco.
