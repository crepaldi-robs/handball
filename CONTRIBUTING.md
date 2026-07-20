# Convenções de desenvolvimento

## Histórico Git

- A branch `main` deve permanecer utilizável e com testes aprovados.
- Cada commit deve tratar de uma única mudança lógica.
- Use mensagens no formato Conventional Commits, em português:
  `tipo(escopo): descrição curta`.
- Tipos preferenciais: `feat`, `fix`, `refactor`, `test`, `docs`, `ops`,
  `security` e `chore`.
- Não misture mudanças funcionais com reformatação ou documentação extensa.
- Não reescreva commits já publicados sem coordenação explícita.

Exemplos:

```text
feat(chamada): permite reabrir treino encerrado
fix(sync): preserva edição do servidor em conflito
docs(deploy): detalha restauração de backup
```

## Verificação antes do commit

No PowerShell integrado do VSCode:

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m compileall -q app.py attendance tests
git diff --check
git status --short
```

Banco SQLite, configuração local, hash de senha, backups, exportações e `.venv`
nunca devem ser adicionados ao Git. Antes de confirmar um commit, use
`git diff --cached --name-only` para revisar exatamente o que será registrado.
