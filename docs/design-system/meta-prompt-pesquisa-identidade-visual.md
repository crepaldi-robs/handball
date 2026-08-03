Pesquisa de identidade visual — [nome do time/marca]

Faça uma pesquisa sobre a identidade visual pública de @[handle_principal] (conta oficial) e, se existir, da organização-mãe @[handle_guarda-chuva]. Para cada elemento abaixo, sempre separe confirmado com fonte vs proposta/inferência minha — nunca misture os dois sem rótulo.

Cores: hex/RGB exatos se existir manual de marca oficial; senão, hex aproximado observado + nível de confiança (alta/média/baixa). Calcule contraste WCAG AA para cada par texto/fundo proposto e marque aprovado/reprovado.
Tipografia: família, peso, se é fonte paga/licenciada ou gratuita (Google Fonts), e se pode ser embutida via CDN sem problema de licença.
Metadados de marca (para virar JSON de config direto): slug (kebab-case), nome de exibição curto, nome formal completo, organização-mãe/endosso, monograma (1-3 letras), path do logo se já existir arquivo aprovado.
Tom de voz: 3-5 registros observados (ex.: competitivo, afetivo, informal) com um exemplo curto de frase para cada situação (chamada de jogo, resultado, apresentação de atleta, conquista).
Iconografia/símbolos recorrentes e o que NÃO existe (mascote, escudo formal, grade fixa) — declare explicitamente "não observado" em vez de omitir.
Fontes usadas: liste cada fonte (perfil oficial, site institucional, manual de marca) com data de acesso e o que ela confirma.
Formato de saída: markdown com uma tabela final "Tokens prontos para aplicação" (papel | cor | hex | fonte da decisão) que eu possa copiar direto para um arquivo de tema.