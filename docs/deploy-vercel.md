# Implantação na Vercel

## O que vai para a Vercel

O portal usa Django e o runtime Python nativo da Vercel. O deploy detecta o projeto pelo arquivo manage.py e pelo requirements.txt; não precisa de vercel.json, Dockerfile ou comando de build personalizado. As regras do Ruff ficam em ruff.toml, separado do manifesto de dependências. O arquivo .python-version mantém a mesma versão Python 3.13 usada pela imagem local. A Vercel executa a coleta dos arquivos estáticos porque o projeto define STATIC_ROOT.

Conecte o repositório Vitor-Studzieski/busca-preco com o diretório raiz padrão. Como DEBUG fica desativado na Vercel, as variáveis obrigatórias precisam existir durante cada build em Preview e Production. Defina DJANGO_SECRET_KEY, PRICING_ADMIN_PATH, DATABASE_URL e PRICING_REDIS_URL para cada ambiente usado. Mantenha banco e Redis de Preview isolados dos dados de Production.

## Variáveis de ambiente

Cadastre os segredos nas configurações da Vercel, nunca no Git:

- DJANGO_DEBUG=0
- DJANGO_SECRET_KEY: chave aleatória exclusiva, com pelo menos 50 caracteres
- PRICING_ADMIN_PATH: caminho administrativo exclusivo, terminando em /
- DATABASE_URL: URL PostgreSQL do provedor (ou POSTGRES_URL); prefira a URL com pooler para o tráfego da aplicação
- PRICING_REDIS_URL: URL Redis redis:// ou rediss:// acessível pela Vercel
- DJANGO_ALLOWED_HOSTS: inclua o domínio próprio, se houver
- DJANGO_CSRF_TRUSTED_ORIGINS: inclua https:// seguido do domínio próprio, se houver
- PRICING_COLLECTION_HOURS=4,14 e PRICING_SESSION_IDLE_DAYS=30 podem manter os valores padrão

Ative as variáveis de sistema da Vercel. O projeto usa VERCEL_URL, VERCEL_BRANCH_URL e VERCEL_PROJECT_PRODUCTION_URL para aceitar os domínios de deploy e incluí-los nas origens CSRF. Configure banco e Redis separados para Preview se os previews puderem receber alterações.

Rode as migrations uma vez, em um ambiente administrativo confiável com as mesmas variáveis de banco. Não execute migrations automaticamente durante cada build, pois builds de preview e produção podem ocorrer ao mesmo tempo.

## Acesso ao portal

A configuração local limita o acesso pelo Caddy usando os IPs do escritório. Esse bloqueio não é transferido para a Vercel. Antes de colocar o domínio de produção em uso, configure a proteção de acesso da Vercel para os ambientes necessários, incluindo a produção, e confirme que usuários fora da rede autorizada não conseguem abrir o portal. A disponibilidade de proteção por IP depende do plano e da configuração da conta.

## Worker de coletas

A aplicação grava pesquisas e coletas em PostgreSQL e precisa de um processo contínuo executando python manage.py collection_worker. Funções da Vercel atendem requisições e não mantêm esse loop ativo. Portanto, hospede esse worker em um serviço permanente separado, com acesso ao mesmo PostgreSQL, Redis e às lojas monitoradas. Sem o worker, o site e o login podem abrir, mas pesquisas e atualizações ficam na fila sem serem processadas.

O Compose atual continua sendo o caminho completo para executar portal, banco, Redis e worker juntos em um servidor próprio. Consulte também o runbook operacional (docs/runbook.md).
