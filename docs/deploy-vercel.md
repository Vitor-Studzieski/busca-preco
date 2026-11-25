# Deploy na Vercel

O projeto usa o suporte Django da Vercel, detectado pelo `manage.py`. O arquivo `vercel.json` inclui `pricing/markets.sqlite3` na Function e limita cada busca a 60 segundos.

O banco SQLite contém apenas as quatro configurações de mercado e é aberto em modo somente leitura. A Vercel pode ler arquivos do deploy, mas não oferece persistência para alterações no disco da Function; por isso, preços e resultados de busca não são gravados.

Não configure PostgreSQL, Redis, credenciais de banco ou worker. A consulta aos sites ocorre diretamente durante a requisição e pode falhar se a loja bloquear o acesso vindo da infraestrutura da Vercel.
