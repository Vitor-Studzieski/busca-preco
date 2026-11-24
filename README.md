# Precificação do Supermercado Pompeia

Portal interno para dois compradores pesquisarem preços no Super Líder de Pompéia e Herculândia, Tauste de Marília e Confiança de Marília. A pesquisa abre com o último preço confirmado no banco e atualiza cada unidade em segundo plano. A primeira fase usa dados dos concorrentes. O catálogo e os preços do Pompeia entram em uma etapa posterior.

- [Operação e migração](docs/runbook.md)
- [Implantação na Vercel](docs/deploy-vercel.md)
- [Auditoria](docs/auditoria.md)
- [Avaliação e plano incremental](docs/melhorias-radar-precos.md)
- [Contexto original da solicitação](docs/contexto/solicitacao-2026-11-24/README.md)
- [Desempenho](docs/baseline-desempenho.md)
- [Segurança](docs/seguranca.md)
- [Arquitetura da fila](docs/adr/0001-portal-e-fila.md)
- [Sessões persistentes](docs/adr/0002-sessoes.md)
- [Arquitetura PostgreSQL e Vercel](docs/adr/0003-postgresql-vercel.md)

## Ambiente de desenvolvimento

O Compose usa Python 3.13, PostgreSQL e Redis. Ele aplica as migrations e inicia o portal e o worker automaticamente. O banco começa novo; os dados do SQLite antigo não são importados.

Com o Docker Desktop aberto, execute na pasta do projeto:

    docker compose -f compose.dev.yaml up --build --wait

Abra [o portal local](http://127.0.0.1:8000/). Na primeira inicialização, crie uma conta administrativa:

    docker compose -f compose.dev.yaml exec web python manage.py createsuperuser

Depois de entrar, cadastre os compradores pela opção de cadastro do portal. Para acompanhar os logs:

    docker compose -f compose.dev.yaml logs -f web worker

Para parar os serviços:

    docker compose -f compose.dev.yaml down

O volume do PostgreSQL continua disponível na próxima inicialização. O arquivo db.sqlite3 local não é usado pela aplicação.
