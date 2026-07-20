# Registro Oficial de Presenças

Aplicação local em Streamlit com banco SQLite para registrar:

- situação da confirmação antes do treino;
- presença real no treino;
- observações individuais e gerais;
- histórico completo por data;
- trilha de auditoria de todas as alterações;
- exportação em CSV;
- mensagem pronta para envio ao técnico.

## Situações disponíveis

- Pendente;
- Confirmou com mais de 24 horas;
- Confirmou dentro de 24 horas;
- Desmarcou com mais de 24 horas;
- Desmarcou dentro de 24 horas;
- Sem resposta.

A categoria “desmarcou dentro de 24 horas” foi incluída para evitar que
cancelamentos tardios fiquem sem classificação.

## Estrutura do projeto

```text
registrador-presencas/
├── app.py
├── attendance/
│   ├── database.py
│   ├── models.py
│   └── services.py
├── data/
│   └── presencas.db           # criado automaticamente
├── scripts/
│   ├── setup.ps1
│   ├── run.ps1
│   └── test.ps1
├── tests/
│   └── test_database.py
├── AGENTS.md
├── requirements.txt
└── README.md
```

## Instalação no Windows pelo VSCode

1. Extraia a pasta.
2. Abra a pasta no VSCode.
3. Abra o terminal PowerShell integrado.
4. Execute:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\run.ps1
```

O navegador abrirá a aplicação. O banco será criado em:

```text
data\presencas.db
```

## Fluxo operacional

### Antes do treino

1. Escolha a data.
2. Atualize a situação de confirmação de cada atleta.
3. Clique em **Salvar alterações**.
4. Abra **Resumo para o técnico** e copie a mensagem.

### Durante ou depois do treino

1. Marque apenas os atletas presentes.
2. Salve as alterações.
3. Clique em **Encerrar chamada**.
4. Os demais atletas serão registrados como ausentes.
5. Exporte o CSV, se necessário.


## Acesso pelo celular na mesma rede Wi-Fi

Depois da instalação, execute:

```powershell
.\scripts\run-network.ps1
```

O terminal mostrará um endereço semelhante a:

```text
http://192.168.0.15:8501
```

Abra esse endereço no celular conectado à mesma rede. Esse modo não possui
login próprio; use somente em rede privada e confiável. O Firewall do Windows
pode solicitar autorização para o Python acessar a rede privada.

## Testes

```powershell
.\scripts\test.ps1
```

## Criar repositório remoto no GitHub

Com o GitHub CLI instalado e autenticado:

```powershell
git init
git add .
git commit -m "feat: cria registrador oficial de presencas"
gh repo create registrador-presencas --private --source=. --remote=origin --push
```

Sem o GitHub CLI:

1. Crie um repositório privado vazio no GitHub.
2. Copie a URL HTTPS.
3. Execute:

```powershell
git init
git add .
git commit -m "feat: cria registrador oficial de presencas"
git branch -M main
git remote add origin URL_DO_REPOSITORIO
git push -u origin main
```

## Uso com Codex

O arquivo `AGENTS.md` informa ao Codex as regras do sistema. Depois de conectar
ou abrir o repositório no Codex, use tarefas como:

```text
Leia AGENTS.md, execute os testes e melhore o registrador sem alterar as regras
de domínio nem apagar o banco SQLite existente.
```

## Backup

O arquivo essencial é:

```text
data\presencas.db
```

Faça cópias periódicas desse arquivo com a aplicação fechada. Para versionamento,
o banco está ignorado pelo Git para evitar publicar dados pessoais e gerar
conflitos binários.
