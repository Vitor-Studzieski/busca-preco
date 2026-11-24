# ADR 0003 · PostgreSQL e execução na Vercel

## Decisão

Usar PostgreSQL como único banco de execução em desenvolvimento e produção. O SQLite local não é usado nem importado; o PostgreSQL começa novo, sem os dados antigos. As migrations existentes já definem o schema PostgreSQL e as constraints específicas desse banco.

Manter o monólito Django e suas páginas HTML, CSS e JavaScript. A Vercel executa as requisições pelo runtime Python; Neon fornece PostgreSQL e Upstash fornece Redis para cache e limites compartilhados. Configurar as três partes na região de São Paulo quando disponível e usar conexão PostgreSQL com pooler nas Functions.

A fila atual permanece persistida no PostgreSQL. Uma instância Vercel Daemon executa o comando collection_worker a partir do Dockerfile, na mesma região e com os mesmos segredos de Production. O worker recebe SIGTERM, conclui os jobs em andamento e fecha conexões. O Compose local continua disponível para PostgreSQL e Redis.

## Consequências

- O desenvolvimento também precisa de PostgreSQL e Redis, iniciados por compose.dev.yaml.
- Variáveis PostgreSQL são obrigatórias mesmo quando DEBUG está ativo; isso impede que uma configuração ausente crie silenciosamente um banco SQLite novo.
- O worker Vercel Daemon está em beta pública e opera somente em Production. Preview não processa a fila, não há autoscaling e o disco do contêiner é efêmero. Todos os dados que precisam sobreviver ficam em PostgreSQL ou Redis.
- A instância contínua consome memória provisionada. O limite de Hobby não comporta um worker ligado o mês todo; o uso empresarial também exige um plano adequado. A região gru1 para Functions tem cobrança regional Pro.
- A inicialização não importa contas nem histórico do SQLite. Contas são provisionadas novamente no PostgreSQL e as coletas começam sem jobs ou alertas antigos.
- Neon e Upstash são escolhas recomendadas, não dependências do código. Outros serviços PostgreSQL e Redis com TLS podem ser usados através das mesmas variáveis.

## Alternativas consideradas

- SQLite em produção: rejeitado porque o disco de uma Function/Daemon não é persistente e as instâncias não compartilham um arquivo local.
- Reescrever o frontend em JavaScript: rejeitado porque o runtime Python da Vercel executa Django e o problema de operação é o banco e o worker contínuo. Uma segunda aplicação acrescentaria build, deploy e integrações sem remover esses requisitos.
- Worker externo permanente: alternativa operacional caso o beta, quotas ou custos do Daemon não atendam ao uso real. Nesse caso, o web segue na Vercel e o worker externo usa o mesmo PostgreSQL e Redis.
