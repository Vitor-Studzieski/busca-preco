# Precificação do Supermercado Pompeia

Portal interno para dois compradores pesquisarem preços no Super Líder de Pompéia e Herculândia, Tauste de Marília e Confiança de Marília. A pesquisa abre com o último preço confirmado no banco e atualiza cada unidade em segundo plano. A primeira fase usa dados dos concorrentes. O catálogo e os preços do Pompeia entram em uma etapa posterior.

- [Operação, implantação no escritório e migração de dados](docs/runbook.md)
- [Auditoria](docs/auditoria.md)
- [Desempenho](docs/baseline-desempenho.md)
- [Segurança](docs/seguranca.md)
- [Arquitetura da fila](docs/adr/0001-portal-e-fila.md)
- [Sessões persistentes](docs/adr/0002-sessoes.md)

## Ambiente de desenvolvimento

Use Python 3.13 ou 3.14. PostgreSQL e Redis são obrigatórios no perfil de produção. Em desenvolvimento, o Django aceita a base SQLite local para compatibilidade com a instalação anterior.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.txt
export DJANGO_SECRET_KEY="$(python -c 'from secrets import token_urlsafe; print(token_urlsafe(64))')"
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Abra [o portal local](http://127.0.0.1:8000/). Execute `python manage.py collection_worker` em outro terminal com a mesma configuração de banco para processar as coletas. A opção de manter a sessão funciona entre reinícios quando a mesma chave de desenvolvimento é fornecida pelo ambiente. Em produção use a configuração do [runbook](docs/runbook.md).

```sh
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```
