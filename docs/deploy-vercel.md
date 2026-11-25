# Deploy na Vercel

O projeto usa o suporte Django da Vercel, detectado pelo `manage.py`. O arquivo `vercel.json` inclui `pricing/markets.sqlite3` na Function e limita cada busca a 60 segundos.

O banco SQLite contém apenas as cinco configurações de mercado e é aberto em modo somente leitura. A Vercel pode ler arquivos do deploy, mas não oferece persistência para alterações no disco da Function; por isso, preços e resultados de busca não são gravados.

O navegador chama `GET /api/search/?q=<produto>&store=<slug>` em paralelo por unidade. A rota retorna os resultados de uma unidade; para preservar a comparação de produtos compartilhados, uma solicitação das lojas Super Líder retorna as duas filiais. O contrato JSON foi adicionado sem remover a busca HTML existente.

Não configure PostgreSQL, Redis, credenciais de banco ou worker. A consulta aos sites ocorre diretamente durante a requisição e pode falhar se a loja bloquear o acesso vindo da infraestrutura da Vercel.
