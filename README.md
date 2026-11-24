# Precificação do Supermercado Pompeia

Aplicação interna em Python e Django para pesquisar ofertas nos sites das três redes concorrentes e registrar rascunhos de preço para o catálogo do Pompeia. As duas unidades do Super Líder são consultadas separadamente.

## Executar localmente

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Abra `http://127.0.0.1:8000/`. Em uma instalação local nova, o navegador exibe **Criar primeira conta** para definir o usuário e a senha do administrador. Depois disso, use **Entrar** com uma conta existente.

O portal é voltado aos compradores; a gestão de acessos fica fora da dashboard operacional. A gestão dos produtos e anúncios fica em `http://127.0.0.1:8000/admin/`.

O ambiente local usa SQLite por padrão. Para PostgreSQL, defina `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` e, se necessário, `POSTGRES_HOST` e `POSTGRES_PORT`. Em produção, configure `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, HTTPS e o serviço de arquivos estáticos. O servidor embutido do Django atende ao desenvolvimento local.

## Dashboard do comprador

A página inicial é a pesquisa de preços e inclui o preço vigente do Pompeia quando o produto existe no catálogo. As áreas de visão geral, comparativos, promoções, mercadológico e alertas fazem parte deste mesmo projeto e exigem login com permissão de consulta. A navegação não inclui uma dashboard de gestor.

Cada área consulta registros reais. Promoções próprias e classificação mercadológica aparecem como indisponíveis porque o modelo atual ainda não guarda vigência promocional nem hierarquia de departamento/categoria. O painel não preenche esses campos com amostras.

## Acesso por perfil

| Rota | Visitante | Comprador | Administrador |
| --- | --- | --- | --- |
| `/entrar/` | Formulário de login | Redireciona à aplicação | Redireciona à aplicação |
| `/configurar-acesso/` | Cria a primeira conta apenas em localhost, no modo de desenvolvimento, com banco sem usuários e configuração inicial disponível | Redireciona ao login | Redireciona ao login |
| `/` | Exige login | Consulta preços com a permissão de visualizar produto | Consulta preços |
| `/produtos/<id>/` | Exige login | Consulta com permissão de visualizar produto. Salva rascunho com a permissão de adicionar rascunho | Consulta e salva rascunho |
| `/compradores/novo/` | Exige login | Acesso negado | Cadastra compradores |
| `/admin/` | Exige login administrativo | Acesso negado | Acessa o painel administrativo |
| `/sair/` | Exige login | Encerra a sessão com POST | Encerra a sessão com POST |

As ações de cadastro, precificação, entrada e saída usam POST com CSRF. O Django valida o destino de retorno do login. Para operações de precificação, o perfil de comprador é a conta criada pela tela de cadastro, com permissões restritas de pesquisa e rascunho.

## Desempenho da busca

O sistema compartilha consultas simultâneas equivalentes para a mesma unidade e mantém até oito consultas de unidade em andamento. O prazo da tela é de 15 segundos e uma fonte que atinge o limite recebe um aviso próprio. A coleta repete uma vez respostas HTTP 500, 502, 503 ou 504 quando ainda há tempo de consulta. O cache preserva a hora da coleta. Ele mantém ofertas por 90 segundos, buscas concluídas sem correspondência por 30 segundos e falhas ou consultas sem preço confirmado por 10 segundos.

Cada conta pode realizar 20 buscas por minuto. A resposta ao exceder o limite é HTTP 429 e inclui `Retry-After`. O cache e o contador padrão são locais ao processo Django. Se o sistema for executado com múltiplos processos ou instâncias, configure os aliases `pricing_search` e `pricing_limits` com um cache compartilhado que ofereça incremento atômico para os contadores, e valide os limites nesse ambiente.

## Primeiro fluxo de trabalho

1. Para consultar o mercado, pesquise pelo nome e pela embalagem, por exemplo **Coca Cola 2 litros**. A tela consulta os sites das redes com variações de nome e medida e mostra até três ofertas por unidade. Ofertas por quilo trazem `/kg` junto do valor. Se a loja listar o produto sem um preço que o coletor consiga confirmar, a tela mostra o link do anúncio. O catálogo próprio pode ser utilizado depois para registrar rascunhos.
2. Cadastre os produtos Pompeia pelo painel administrativo ou importe um CSV UTF-8 com `python manage.py import_products produtos.csv`. Use o cabeçalho `sku;nome;embalagem;ean;preco_vigente`. EAN e preço vigente podem ficar vazios. O valor pode usar vírgula ou ponto decimal, sem separador de milhares. A importação atualiza por SKU e preserva zeros de códigos armazenados no CSV.
3. Descubra os links publicados na página inicial de uma unidade com `python manage.py discover_listings --unidade lider-pompeia --limite 15`. Também é possível cadastrar diretamente a URL pública de um produto no painel de **Anúncios monitorados**. A descoberta inicial tem a cobertura da vitrine. Para itens fora dela, use os links diretos.
4. Rode `python manage.py collect_offers --unidade lider-pompeia`. Os dois comandos aceitam omitir `--unidade` para processar as quatro fontes já cadastradas. A coleta pode ser agendada externamente, por exemplo uma vez ao dia. Uma rede com HTTP 401, 403 ou 429 é pausada até o fim daquela execução e as demais ainda podem ser processadas.
5. Quando a página expõe um GTIN válido que aponta para um único produto do catálogo, a coleta confirma o vínculo. Para os demais anúncios, confira a descrição e a embalagem, e selecione o produto Pompeia no painel administrativo.
6. Abra um item do catálogo Pompeia para consultar seu histórico. A página do produto mostra o preço vigente do Pompeia, os preços observados por unidade, códigos externos, condição, data e fonte. O comprador pode registrar um preço proposto com justificativa.

## Identidade dos produtos

- `Product` usa o SKU do Pompeia como chave de negócio. O GTIN é uma evidência de correspondência e pode estar ausente.
- `Listing` conserva separadamente a URL do anúncio e o código publicado pelo concorrente. O código externo é único dentro de uma unidade e pode ser diferente do identificador na URL. A mesma unidade pode ter um vínculo confirmado por SKU Pompeia.
- `Observation` guarda cada preço observado e suas condições. Mudanças inesperadas de código ou GTIN geram uma divergência para revisão. O painel identifica ofertas com mais de 36 horas.
- `PriceDraft` registra a decisão preliminar do comprador, com autor e data. As regras de preço e a integração de lançamento com o ERP são etapas posteriores.

Os coletores registram valores por apresentação ou por peso e volume quando a unidade é informada no preço. Preços com unidade comercial ambígua ficam para revisão. Para o Confiança, a coleta usa a lista de preços de Marília publicada no catálogo e guarda o desconto de clube em um campo próprio quando houver valor distinto.

## Verificação

```sh
python manage.py check
python manage.py test
```

Os testes usam páginas e dados sintéticos. Cobrem identificadores diferentes por rede e unidade, busca por SKU/EAN/nome, alterações na origem e permissões de rascunho.
