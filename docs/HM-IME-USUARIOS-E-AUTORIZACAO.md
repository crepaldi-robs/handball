# HM-IME: usuários, autorização e escopo de dados

## 1. Objetivo e limites

Esta primeira entrega substitui o pressuposto de administrador único por identidades pessoais, papéis cumulativos e sessões revogáveis. O módulo de presenças é o caso de validação: a CT continua operando o time completo, enquanto o jogador recebe apenas sua projeção individual.

Não fazem parte desta entrega jogos, eventos de partida, estatísticas completas, avaliações médicas, rankings, autocadastro, login social, e-mail, recuperação por e-mail, múltiplas organizações ou editor genérico de permissões.

## 2. Organograma lógico

A identidade oficial é centralizada em `handball/core/organization.py`:

- `code`: `HM_IME`;
- `slug`: `hm-ime`;
- `display_name`: `HM-IME`;
- temporada inicial: `2026.2`, ativa e sem datas inventadas.

O modelo separa quatro conceitos:

1. **Pessoa**: identidade humana; pode existir sem conta.
2. **Usuário**: credencial de acesso; pode ser desativado sem apagar a pessoa.
3. **Papel**: autorização cumulativa `DEV`, `CT` ou `PLAYER`.
4. **Vínculo esportivo**: associa pessoa, time e temporada; para jogador, liga a conta ao atleta preexistente em `team_members`.

Posição esportiva, como goleiro, ponta, central, armador ou pivô, não concede permissão.

## 3. Matriz de permissões

As permissões são constantes tipadas em `handball/core/authorization.py`. O mapeamento papel-permissão permanece em código e é coberto por testes.

| Permissão | DEV | CT | PLAYER |
|---|:---:|:---:|:---:|
| `users.manage` | sim | não | não |
| `auth.sessions.revoke` | sim | não | não |
| `attendance.read.self` | não | não | sim |
| `attendance.read.team` | não | sim | não |
| `attendance.write` | não | sim | não |
| `attendance.finalize` | não | sim | não |
| `attendance.reopen` | não | sim | não |
| `members.read.team` | não | sim | não |
| `members.manage` | não | sim | não |
| `audit.read.sport` | não | sim | não |
| `export.read.team` | não | sim | não |
| `backup.download` | não | sim | não |
| `reports.read.self` | não | não | sim |
| `diagnostics.read` | sim | não | não |

`DEV` não implica acesso esportivo. Por compatibilidade, o administrador legado Bob recebe explicitamente `DEV + CT`; assim, preserva a operação anterior sem enfraquecer a separação dos papéis.

## 4. Modelo relacional

A migração v2 acrescenta `people`, `users`, `teams`, `seasons`, `team_memberships`, `membership_roles`, `system_roles`, `player_user_links`, `auth_sessions` e `security_audit_events`.

`team_members` permanece intacta, com os mesmos IDs e referências históricas. A tabela de ligação `player_user_links` associa um usuário a no máximo um atleta e impede duas contas para o mesmo atleta. A migração cria pessoas e vínculos esportivos para os atletas existentes, mas não cria contas, usernames ou senhas para eles.

Somente `handball/database` conhece SQLite, SQL, conexões, transações, caminhos de banco e backups. Os módulos usam repositories e `UnitOfWork`.

## 5. Login e sessões

1. O username é normalizado antes da consulta.
2. A senha é verificada com Argon2 e erros usam mensagem genérica.
3. O rate limit dinâmico, `401`, `429` e `Retry-After` existentes são preservados.
4. O navegador recebe um token opaco em cookie `HttpOnly`, `SameSite=Lax` e `Secure` conforme configuração.
5. O banco armazena somente o SHA-256 do token, nunca o token em texto puro.
6. Em cada requisição, conta, expiração, revogação, `credential_version`, papéis e permissões são reavaliados.

A desativação da conta, a redefinição/troca de senha e a revogação administrativa invalidam as sessões imediatamente. Remover um papel produz efeito na requisição seguinte. Uma senha temporária marca `must_change_password`; até a troca, o usuário pode consultar sua identidade e trocar a senha, mas não exercer permissões funcionais.

Operações mutáveis protegidas exigem o token CSRF associado à sessão. Senhas, hashes, cookies e tokens não são gravados em logs de auditoria.

## 6. Autorização e projeção de dados

`AccessContext` contém `user_id`, `person_id`, `session_id`, times, papéis, permissões e `linked_player_id`. As dependências centrais aplicam autenticação, permissão, time e regra de próprio recurso.

- não autenticado: `401`;
- autenticado sem permissão: `403`;
- recurso de outro atleta: negado sem carregar o conjunto completo no navegador;
- regra ausente: negada por padrão.

As rotas `GET /api/v1/me`, `/api/v1/me/attendance` e `/api/v1/me/report` não recebem `player_id`. O repository resolve o atleta exclusivamente pelo usuário autenticado. O relatório informa período, treinos elegíveis, confirmações, presenças, ausências, pendências, taxa, evolução mensal, histórico e completude.

As rotas coletivas de chamada, sincronização, encerramento, reabertura, observações, elenco, auditoria, exportação e backup exigem permissão CT explícita no backend.

## 7. Administração

O módulo `/app/admin/usuarios`, exclusivo de `DEV`, lista contas e oferece APIs para:

- criar pessoa e conta, ou usar pessoa existente;
- vincular a conta a atleta existente;
- atribuir e remover `DEV`, `CT` e `PLAYER`;
- desativar conta;
- revogar sessões;
- definir senha temporária e exigir troca no próximo acesso;
- consultar auditoria de segurança e diagnóstico.

Não há exclusão de usuário com histórico, exibição de senha/hash ou atribuição de `PLAYER` sem vínculo válido.

## 8. Auditoria

Escritas esportivas recebem `actor_user_id` exclusivamente da sessão. A auditoria registra data/hora, ação, entidade, alvo, origem, `operation_id` quando disponível e valores anteriores/posteriores nos registros de presença. Histórico legado é preservado com autor nulo. Eventos administrativos ficam em `security_audit_events`.

## 9. Cofre offline

O cofre mantém AES-GCM e PIN local independente da senha. O namespace é `user_id + team_id + versão do formato`; o conteúdo cifrado também inclui esses identificadores e é rejeitado se pertencer a outra conta ou time.

Somente CT pode gerar escrita offline. Cada operação registra `creator_user_id`; na sincronização, o servidor compara esse autor com a sessão corrente e revalida conta e permissão CT. Logout apaga a chave em memória e tranca imediatamente o cofre. A remoção dos dados locais é uma ação explícita do usuário.

## 10. Migração v1 para v2

A migração é `DB_MIGRATION`, versionada, transacional e explícita. Ela:

1. valida o banco e o fingerprint esperado;
2. exige username e hash Argon2 do administrador configurado;
3. cria as novas estruturas;
4. materializa organização e temporada;
5. preserva `team_members`, IDs, treinos, presenças e auditoria;
6. persiste Bob com o username/hash existentes e `DEV + CT`;
7. cria pessoas e vínculos para atletas sem criar suas contas;
8. registra o ledger v2 e executa validação posterior.

Startup, backup e atualização `APP_ONLY` não executam a migração nem criam/populam silenciosamente um banco. A aplicação somente reporta schema v2 em `/ready` depois da migração explícita.

Antes de qualquer migração real, o runbook deve ser executado em uma cópia controlada, registrando SHA-256, contagens e fingerprint lógico. Depois, `PRAGMA quick_check` deve retornar literalmente `ok`, `foreign_key_check` deve ser vazio e as contagens/IDs esportivos devem permanecer iguais.

## 11. Limitações e extensão futura

A interface administrativa inicial oferece criação, listagem, alteração de papéis, redefinição de senha temporária, desativação e revogação. PLAYER é somente leitura e não possui fila offline nesta versão.

Jogos e estatísticas futuros devem reutilizar `AccessContext`, permissões tipadas, repositories escopados e autoria de auditoria. Novas permissões devem ser adicionadas de forma explícita e negadas por padrão, sem transformar posições esportivas em papéis de segurança.
