# Integração Google do time — arquitetura e ativação

## 1. Estado desta entrega

A implementação local cobre Google Calendar, OAuth, cofre, central da CT,
ajuda guiada, outbox e testes. Ela **não** autoriza nem executa por si só:

- configuração no Google Cloud;
- migração do banco persistente para V14;
- ativação em produção;
- conexão de um Gmail real;
- edição do portal estático, Cloudflare, DNS ou Hostinger.

Esses passos continuam separados porque envolvem conta externa, credencial e
dado persistente.

## 2. Modelo adotado

- um único `@gmail.com` oficial por time;
- um cliente OAuth web central da plataforma;
- uma conexão independente por `team_id`;
- somente a CT possui `integrations.google.manage`;
- fluxo OAuth Authorization Code no servidor, com `state`, PKCE e acesso
  offline;
- escopos mínimos da V1:
  - `openid`;
  - `email`;
  - `https://www.googleapis.com/auth/calendar.app.created`;
  - `https://www.googleapis.com/auth/calendar.acls`;
- token renovável criptografado por DPAPI, fora do SQLite, do Git e da release;
- Calendar do Handball como fonte da verdade, em sentido único;
- agenda secundária pública por link; a agenda pessoal do Gmail não é lida;
- Drive, Sheets, Gmail e login Google fora da V1.

O escopo `calendar.app.created` permite criar calendários secundários e operar
somente os eventos criados pela aplicação. A alteração da regra pública usa
`calendar.acls`. Referências oficiais: [escopos do Calendar](https://developers.google.com/workspace/calendar/api/auth),
[criação de evento](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
e [ACL pública](https://developers.google.com/workspace/calendar/api/v3/reference/acl/insert).

## 3. Preparação única do mantenedor

Esta seção não deve ser executada pela CT.

1. Criar projetos Google Cloud distintos para teste e produção.
2. Ativar a **Google Calendar API** no projeto.
3. Configurar a tela de consentimento como aplicação externa.
4. Informar o domínio público controlado pela plataforma.
5. Cadastrar como página inicial pública:
   `https://<dominio>/google-integration`.
6. Cadastrar como política:
   `https://<dominio>/privacy/google-integration`.
7. Cadastrar como termos:
   `https://<dominio>/terms/google-integration`.
8. Declarar exatamente os quatro escopos da seção 2.
9. Criar um cliente OAuth do tipo **Web application**.
10. Cadastrar a URI exata:
    `https://<dominio>/api/v1/integrations/google/oauth/callback`.
11. Guardar o Client ID e o Client Secret somente no servidor.
12. Submeter a aplicação pública à verificação antes de entregar o fluxo a uma
    CT não técnica.

A URI precisa coincidir integralmente, inclusive `https`, maiúsculas,
minúsculas e barra final. O Google descreve esse requisito e o acesso offline
em [OAuth para aplicações web](https://developers.google.com/identity/protocols/oauth2/web-server).

Não é adequado manter o projeto real em `Testing`: nesse estado, autorizações
de usuários de teste expiram depois de sete dias. Para um fluxo trivial à CT,
o objetivo operacional é produção/verificação, com página inicial, política e
termos públicos. Referências: [audiência e status de publicação](https://support.google.com/cloud/answer/15549945)
e [políticas OAuth](https://developers.google.com/identity/protocols/oauth2/policies).

## 4. Configuração do servidor

Variáveis reconhecidas:

```text
GOOGLE_INTEGRATION_ENABLED=true
GOOGLE_OAUTH_CLIENT_ID=<client-id-do-projeto>
GOOGLE_OAUTH_CLIENT_SECRET=<segredo-do-cliente>
GOOGLE_OAUTH_REDIRECT_URI=https://<dominio>/api/v1/integrations/google/oauth/callback
GOOGLE_TOKEN_VAULT_ROOT=C:\ProgramData\CrepaldiHandball\data\google-secrets
```

Alternativamente, os campos homônimos em minúsculas podem ficar no
`app-config.json` privado do servidor. O segredo não deve aparecer em chat,
commit, log, captura de tela, pacote da release ou arquivo do portal.

O cofre precisa ficar no volume persistente e fora da release. Ele contém
somente blobs DPAPI vinculados ao servidor Windows. O SQLite guarda uma
referência opaca, nunca `access_token`, `refresh_token` ou Client Secret.

## 5. Ativação controlada

1. Gerar backup pelo rito oficial.
2. Validar V14 numa cópia do banco.
3. Confirmar `PRAGMA quick_check = ok` e `foreign_key_check` vazio.
4. Aplicar `DB_MIGRATION` V14 pelo script oficial, com autorização explícita.
5. Instalar a release de código separadamente.
6. Configurar as variáveis/segredos no servidor.
7. Validar `/ready` com `schema_version = 14`.
8. Testar primeiro com um Gmail descartável do time de homologação.
9. Conferir criação, edição, cancelamento e remarcação.
10. Desconectar o Gmail de teste e verificar que a agenda ficou privada.
11. Somente então conectar o Gmail oficial.

## 6. Jornada da CT

1. Abrir **Hub > Integração Google**.
2. Ler o pop-up do passo 1 e separar o Gmail oficial.
3. Clicar em **Ir para o Google**.
4. Na página do Google, conferir o endereço `@gmail.com` e aceitar as duas
   permissões de agenda.
5. Ao voltar, clicar em **Criar e sincronizar agenda**.
6. Abrir o link público e conferir os compromissos.
7. Escolher Treinos, Jogos e Campeonatos na central.

O assistente aparece automaticamente quando a conexão ainda não existe. Todos
os grupos e controles críticos possuem ajuda contextual própria.

## 7. Dados e falhas

Publicados: tipo/título, início, fim, local, adversário e situação.

Nunca publicados: notas, atletas, presenças, justificativas, auditoria,
Playbook ou dados financeiros.

A gravação local não depende do Google. Mudanças entram numa outbox na mesma
transação do Calendário e são reenviadas com identificador determinístico. Ao
desmarcar um tipo, seus eventos já vinculados são retirados da agenda; ao
marcar novamente, voltam sem duplicação.

Se a autorização expirar, o painel muda para **Precisa reconectar**. A troca
por outro Gmail é recusada enquanto a conta anterior estiver ativa: a CT deve
desconectar primeiro, garantindo que a agenda antiga seja tornada privada.

## 8. Diagnóstico rápido

- **Integração ainda não liberada:** configuração técnica ou V14 ausente.
- **`redirect_uri_mismatch`:** URI do Console difere da variável do servidor.
- **Permissão obrigatória ausente:** a CT não aceitou um dos dois escopos.
- **Escolha um `@gmail.com`:** foi usada uma conta fora do modelo aprovado.
- **Precisa reconectar:** refresh token expirado ou revogado.
- **Itens aguardando envio:** indisponibilidade temporária; usar
  **Sincronizar agora** depois.
- **Erro persistente:** preservar o código de suporte exibido e consultar os
  registros sanitizados; nunca registrar token ou resposta secreta.
