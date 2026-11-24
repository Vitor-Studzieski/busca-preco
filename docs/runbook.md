# Operação do portal

## Servidor do escritório

1. Configure as variáveis requeridas pelo Compose em um ambiente restrito. Defina `PORTAL_HOST`, `PORTAL_OFFICE_CIDRS`, `DJANGO_SECRET_KEY`, as duas credenciais do PostgreSQL e `PRICING_ADMIN_PATH`. Use o IP ou as sub-redes do escritório conforme o ponto onde o proxy recebe a conexão. Certifique-se de que o Caddy recebe o IP real antes de liberar o tráfego.
2. Execute `docker compose config --quiet` e `docker compose up -d --build`. O serviço de migration roda com o papel proprietário. O web e o worker usam um papel de aplicação sem DDL.
3. Confira `docker compose ps` e `docker compose logs --tail=100 worker`. Teste o acesso de dentro e de fora do escritório. Libere a aplicação após confirmar TLS e as restrições.
4. Provisione os compradores com `docker compose exec web python manage.py create_buyer NOME`. Digite a senha diretamente no prompt. Use o mesmo procedimento para a segunda conta. Provisione a conta técnica separadamente usando o comando Django `createsuperuser`.
5. A primeira fase mantém `PRICING_ENABLE_OWN_PRICES=0`. O worker atualiza pesquisas que já tiveram preço confirmado, às 04h e 14h por padrão em São Paulo. Ajuste `PRICING_COLLECTION_HOURS` com dois valores distintos, por exemplo `4,14`. Quando reiniciado depois de uma janela, o worker recupera a janela mais recente do dia.

Para parar os processos use `docker compose stop`, que preserva volumes. Para uma atualização, faça backup, aplique migrations com o serviço de migration e suba as imagens. O endpoint `/healthz/` sinaliza prontidão sem expor o catálogo.

## Dados e reversão

Faça backup do SQLite antes de mudar a base local, usando a API de backup do SQLite em modo somente leitura. O arquivo de validação deve ter acesso restrito. Em PostgreSQL use `pg_dump -Fc`, criptografe o arquivo com a chave de backup da empresa e valide a restauração em uma base isolada antes de autorizar um corte. Defina responsável, custódia de chave e retenção com o escritório.

Para transferir o catálogo legado, migre **uma cópia** do SQLite e a base PostgreSQL de destino para a mesma versão. Com a conexão PostgreSQL configurada, rode `python manage.py migrate_catalog_database CAMINHO_DA_COPIA`. O comando valida contagem e checksum, e reverte a transação quando divergem. Contas e permissões são preservadas. As sessões devem ser iniciadas novamente após a troca de banco.

Para voltar ao código anterior antes do corte, reative a base anterior pelo backup e use a tag `baseline-portal-2026-11-24` em um checkout isolado. Migrations 0006–0011 têm reversão de schema, mas reverter removendo tabelas elimina os registros criados nelas. Se já houve uso na versão nova, preserve o banco novo, restaure em separado e reconcilie dados antes de voltar a servir escrita. Desativar o fluxo de preço próprio por configuração é a reversão preferida dessa função.

## Coleta e falhas

- **Preço ausente.** Veja o estado da unidade e o horário da última coleta. Refine nome e embalagem quando o resultado tiver variações. O portal mantém o último preço confirmado com o estado da fonte.
- **Rede em pausa.** Abra Saúde das coletas e aguarde a janela indicada. Respostas 401, 403 e 429 pausam a rede inteira. Uma nova pesquisa reaproveita a última observação gravada, se houver.
- **Atualização parada.** Confira o processo worker, a saúde do banco e os logs com o identificador do job. O worker recupera reservas abandonadas após dois minutos.
- **Rodar um ciclo avulso.** Use `python manage.py collection_worker --once` para agendar a janela vencida e processar um job. Use `collect_offers --unidade IDENTIFICADOR` somente para anúncios já cadastrados enquanto o worker está parado.
- **Rotacionar segredos.** Atualize os segredos no ambiente, altere as credenciais do banco e reinicie os serviços com a configuração nova. A troca da chave de sessão exige novo login. Mantenha segredos e dumps fora do Git.
- **Catálogo futuro.** Quando o CSV chegar, valide os campos `sku;nome;embalagem;ean;preco_vigente` e importe com `python manage.py import_products ARQUIVO` em uma base de validação antes da carga real.
