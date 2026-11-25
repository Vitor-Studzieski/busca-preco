# busca-preço

Busca pública de preços para o Super Pompeia L02, na cidade de Pompéia, e quatro supermercados concorrentes em Marília e região. A interface tem uma única tela de pesquisa; os resultados e as condições promocionais aparecem na mesma página, com os preços do Super Pompeia em destaque.

## Estrutura

- Django 5.2 e Python 3.13 servem as páginas e fazem as consultas.
- `pricing/markets.sqlite3` guarda somente o cadastro das cinco unidades e é aberto em modo somente leitura.
- Cada busca consulta ao vivo os sites oficiais das lojas. Na Pompéia L02, o catálogo público fornece produtos, preços e ofertas. O sistema não armazena preços, histórico ou promoções no servidor.
- As buscas recentes ficam somente no armazenamento local do navegador.
- Não há dashboard interno, login de compradores, fila ou worker contínuo.

O resultado depende de cada supermercado responder às consultas. Uma busca pode levar alguns segundos e uma loja pode limitar o acesso.

## Rodar localmente

Use Python 3.13 e instale as dependências:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.txt
python manage.py runserver 8000
```

Abra <http://127.0.0.1:8000/>. O projeto não precisa de PostgreSQL, Redis, Docker ou variáveis secretas.

Para atualizar os cinco cadastros, edite `pricing/market_data.py` e gere novamente o banco:

```sh
python -m scripts.build_markets_db
```

Esse comando recria `pricing/markets.sqlite3` com apenas as cinco unidades configuradas.

## Vercel

O Django é detectado pelo `manage.py`. O SQLite incluído no repositório é somente de leitura e guarda configuração estática, não dados de usuários ou preços. Não são necessárias variáveis de banco, Redis, migrations de produção ou serviços externos. A consulta aos sites das lojas acontece dentro da requisição; a saída de rede dos supermercados precisa estar acessível à Vercel.
