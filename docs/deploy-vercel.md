# Implantação na Vercel

## Arquitetura

O projeto permanece como uma aplicação Django completa: templates HTML, CSS e JavaScript são servidos pelo Django, sem necessidade de criar um front-end JavaScript separado. A Vercel reconhece o manage.py, instala requirements.txt, usa Python 3.13 e entrega os arquivos estáticos pelo CDN.

O projeto depende de três componentes:

- **Django na Vercel Functions** para as páginas e requisições do portal.
- **PostgreSQL externo**, recomendado Neon pelo Marketplace da Vercel, para catálogo, usuários, sessões, fila e resultados.
- **Redis externo**, recomendado Upstash pelo Marketplace, para cache e limites compartilhados.

O worker python manage.py collection_worker roda como um Vercel Daemon, usando o Dockerfile do projeto e a mesma base PostgreSQL. Ele continua processando os jobs persistidos sem manter um servidor web ligado. A fila atual já está no PostgreSQL, então não é necessário introduzir outro broker.

A configuração escolhe a região gru1 para as Functions e o worker, perto dos compradores e lojas no Brasil. Selecione sa-east-1 (São Paulo) para o Neon e o Upstash. A região gru1 exige Pro. Daemons estão em beta pública e, por enquanto, rodam somente em Production; não há worker automático nos Preview Deployments. No Preview, use banco e Redis separados, e valide o worker localmente com Docker.

## Requisitos antes do deploy

O projeto Vercel ainda não tem variáveis de ambiente nem banco conectado. Configure os recursos antes de enviar um commit que inicie uma build.

Vercel Hobby é para uso pessoal não comercial; este portal de negócio requer um plano que permita uso comercial. Daemons também consomem memória enquanto aguardam jobs: os limites mensais do Hobby não sustentam uma instância contínua. Confirme o plano e os custos atuais antes de ativar o worker.

## Variáveis de ambiente

Cadastre credenciais no Vercel Marketplace ou nas configurações do projeto; nunca as inclua no Git.

- DJANGO_DEBUG=0
- DJANGO_SECRET_KEY: chave exclusiva com pelo menos 50 caracteres
- PRICING_ADMIN_PATH: caminho administrativo exclusivo que termina em /
- DATABASE_URL: URL PostgreSQL com pooler para as Functions (o código também aceita POSTGRES_URL)
- PRICING_REDIS_URL: URL Redis com TLS acessível pela Vercel (o código também aceita REDIS_URL)
- DJANGO_ALLOWED_HOSTS: domínio próprio, se houver
- DJANGO_CSRF_TRUSTED_ORIGINS: origem https:// do domínio próprio, se houver

Mantenha as variáveis de Preview isoladas das de Production. O Marketplace injeta as credenciais do banco e Redis no projeto. Ative as variáveis de sistema da Vercel; VERCEL_URL, VERCEL_BRANCH_URL e VERCEL_PROJECT_PRODUCTION_URL são usadas para hosts e origens CSRF.

## Migrations e dados

A primeira base PostgreSQL começa sem contas nem histórico. Execute python manage.py migrate --noinput em um ambiente administrativo confiável antes de liberar tráfego. As migrations criam o schema e cadastram as quatro lojas monitoradas. Provisione a conta técnica com createsuperuser e as contas de compradores com create_buyer, usando a conexão de Production. Se o provedor oferecer uma URL direta sem pooler, use-a para as migrations e o provisionamento; mantenha a URL com pooler para as Functions. Não execute migrations em cada build.

A aplicação não usa nem importa o arquivo SQLite local. Jobs, alertas e sessões começam vazios no PostgreSQL novo. O arquivo SQLite não precisa fazer parte do Git ou do deploy.

## Worker de coletas

vercel.json configura uma instância do Daemon collection-worker na região gru1, executando python manage.py collection_worker. O comando trata SIGTERM, termina os jobs em andamento e fecha as conexões antes de encerrar. A fila usa leases e recupera jobs interrompidos.

Daemons só iniciam depois do deploy Production, usam armazenamento efêmero e não rodam em Preview. O estado da aplicação fica em PostgreSQL e Redis, nunca no disco do worker. Acompanhe logs do Daemon no painel Vercel e confirme que os jobs saem de pending para um estado final.

A autenticação Django continua obrigatória. Configure também proteção de acesso apropriada para Production antes de entregar o domínio aos compradores.

## Conexões e custo

A região gru1 (São Paulo) para as Functions está disponível no plano Pro e tem preço regional próprio. A Vercel Daemon está em beta pública nos planos disponíveis, mas no Hobby o limite é de 420 GB-horas de memória e 5 horas de CPU ativa por mês. Uma instância de 2 GiB ligada continuamente ultrapassa a cota de memória em cerca de nove dias. O plano Hobby também se limita a uso pessoal sem finalidade comercial. Confira plano, orçamento e limite de gastos antes de ativar Production.

Use DATABASE_URL com pooler no tráfego das Functions. Quando o provedor disponibilizar uma URL direta sem pooler, use essa URL no ambiente administrativo para executar as migrations; não coloque uma URL direta em código ou Git. O Marketplace injeta credenciais, mas a variável PRICING_REDIS_URL deve apontar para uma URL Redis compatível com redis-py, normalmente rediss:// com TLS, e não somente para a API HTTP REST.

A saída de rede da Vercel para as páginas das redes varejistas precisa ser validada depois de habilitar o worker. As lojas podem aplicar bloqueios ou limites às requisições vindas de datacenters; o painel de saúde registra pausas e falhas por rede.
