# Avaliação e evolução incremental do Radar de Preços

**Data da revisão:** 24/11/2026  
**Aplicação principal:** Django em /Users/vitorstudzieski/Projetos/precos  
**Escopo desta revisão:** leitura do código, configuração e banco SQLite local. Após autorização explícita para escrever no repositório Django, foram aplicadas melhorias incrementais à saúde das coletas e à identificação visual das lojas.

## Resumo da implementação observada

O projeto principal é um portal Django interno. A pesquisa de concorrentes já consulta quatro unidades, lê resultados gravados no banco e enfileira atualizações em segundo plano. O código inclui fila persistente, chave única por execução, recuperação de tarefas abandonadas, registro de observações, histórico de execuções, alertas operacionais, controles de acesso e identificação explícita de dados ausentes ou desatualizados.

O catálogo próprio e o espelho ainda não estão conectados. Na cópia SQLite local examinada havia 4 lojas, 0 produtos, 0 anúncios monitorados, 0 observações, 0 preços próprios e 0 alertas; também havia pesquisas monitoradas e tarefas de coleta. Esses números descrevem apenas essa cópia local, não uma base de produção. O flag PRICING_ENABLE_OWN_PRICES continua desligado por padrão.

Durante a revisão, a pasta de apoio continha documentos de contexto e um `index.html` estático de preparação. Esse protótipo mostrava estados de espera e controles desativados, sem consultar o Django. A pedido do usuário, ele foi removido da pasta de apoio; o portal Django permanece como aplicação operacional única.

## Situação e propostas

### IMP-01 — Integrar catálogo e espelho

- **Situação atual com evidência:** os modelos Product, Listing e Observation existem, mas a base local não tem produtos nem anúncios. Há importador CSV; não há conector ao espelho. A configuração mantém a publicação de preços próprios desligada.
- **Mudança sugerida:** definir contrato de leitura para catálogo, lojas, preços e taxonomia; adicionar sincronização incremental, reconciliação e relatório de divergências. Manter a busca concorrente atual durante essa etapa.
- **Benefício esperado:** produtos e preços próprios passam a ser comparáveis por identificadores rastreáveis.
- **Prioridade / estado:** **P0 — bloqueia comparação completa; pendente de dados e decisão sobre a origem.**
- **Dependências:** fornecedor/sistema do espelho, acesso e esquema, catálogo real com SKU/GTIN, frequência e política de atualização.
- **Critério de aceite:** uma carga real e repetível informa itens novos, alterados, ausentes e com erro, não duplica produtos e só apresenta a integração como ativa após uma carga verificada.
- **Evidência:** pricing/models.py:12-43; pricing/management/commands/import_products.py:12-35; project/settings.py:121-122; banco SQLite local sem produtos.

### IMP-02 — Confirmar correspondência de produtos

- **Situação atual com evidência:** GTIN válido é normalizado e a coleta só associa automaticamente um produto quando há um GTIN exato e não ambíguo. Existe confirmação manual auditada por compradores com permissão, mas depende de catálogo ativo e da configuração para vínculos sem GTIN. SearchAlias expande termos de busca; não é um mapeamento de produto.
- **Mudança sugerida:** após integrar o catálogo, criar uma fila para anúncios sem correspondência e para conflitos de embalagem/unidade. Reaproveitar confirmação e desvinculação auditadas; registrar o identificador usado e preservar observações históricas.
- **Benefício esperado:** aumentar cobertura sem comparar produtos diferentes ou unidades incompatíveis.
- **Prioridade / estado:** **P0 — regras automáticas parciais; fila operacional depende do catálogo.**
- **Dependências:** catálogo próprio, política de SKU/GTIN, conversão de unidades e autorização para exceções sem GTIN.
- **Critério de aceite:** item sem vínculo confirmado permanece indisponível para comparação; cada confirmação ou remoção identifica autor, motivo e data, sem reescrever observações antigas.
- **Evidência:** pricing/identifiers.py:4-13; pricing/jobs.py:39-44, 210-251; pricing/links.py:17-67; pricing/templates/pricing/components/links.html.

### IMP-03 — Frescor e estado das coletas por unidade

- **Situação atual com evidência:** a tela de pesquisa mostra estado, horário, motivo e botão de atualização por loja. /coletas/ mostrava saúde agregada por rede; a etapa aplicada acrescentou tentativa concluída, última resposta válida, contagens e causa por unidade, além do atalho para reabrir uma busca. A idade ainda é rotulada pelo dia local de São Paulo; um limite máximo em horas depende de decisão de negócio.
- **Mudança sugerida:** manter o resumo por unidade aplicado e, após definição do negócio, usar o limite de idade aprovado para diferenciar “atualizada” de “desatualizada”. Preservar o fluxo existente de atualização por loja.
- **Benefício esperado:** o comprador identifica rapidamente qual filial está com resposta antiga ou erro e consegue retomar uma consulta sem procurar primeiro pela tela de pesquisa.
- **Prioridade / estado:** **P1 — fila e visibilidade por unidade implementadas; worker contínuo, operação no servidor e limite máximo de idade pendentes.**
- **Dependências:** worker ativo no servidor, fontes acessíveis e decisão sobre a idade máxima considerada aceitável.
- **Critério de aceite:** a página lista as quatro unidades com estado e horário da última tentativa e da última resposta válida; falhas mostram o motivo; tentativas sem sucesso não apagam o último preço confirmado; ausência de registro aparece como ausência, não como zero.
- **Evidência:** pricing/portal.py:235-294; pricing/templates/pricing/health.html:4-61; pricing/templates/pricing/workbench.html:68-86; pricing/jobs.py:56-80, 99-130, 315-331; constraint única de observação por execução em pricing/models.py:152-158.

### IMP-04 — Exibir logos oficiais das redes

- **Situação atual com evidência:** Store já tinha campo logo; a busca e a comparação agora exibem os assets oficiais versionados, mantendo o nome da unidade como identificação textual. A migração associa o mesmo logo Super Líder às unidades de Pompéia e Herculândia, além dos logos Tauste, Confiança e Pompéia às respectivas lojas.
- **Mudança aplicada:** os quatro arquivos originais fornecidos foram copiados sem conversão para `pricing/static/pricing/stores/`; a migração reversível `0012_logos_oficiais` preenche apenas campos logo vazios. O formulário permite o SVG oficial do Tauste, com validação restrita a esse arquivo e bloqueio de scripts, conteúdo incorporado e referências externas. Manifesto registra fonte, data e SHA-256; fallback visual neutro permanece disponível se a imagem falhar.
- **Benefício esperado:** reduzir confusão entre redes e unidades sem perder identificação textual quando uma imagem não carregar.
- **Prioridade / estado:** **P1 — aplicado no código e na cópia SQLite local; validar a apresentação no servidor real.**
- **Dependências:** confirmar visualmente em produção e decidir o limite de idade de coleta que será exibido como desatualizado. O site oficial do Super Líder lista Pompéia e Herculândia sob a mesma marca.
- **Critério de aceite:** originais preservados e conferidos por hash; cada loja mostra logo e nome; interface permanece identificável por texto se a imagem falhar.
- **Evidência:** `pricing/forms.py:90-121`; `pricing/migrations/0012_logos_oficiais.py`; `pricing/templates/pricing/workbench.html:70-74`; `pricing/templates/pricing/components/comparison.html:1-28`; manifesto `pricing/static/pricing/stores/README.md`. [Site oficial do Super Líder](https://www.smlider.com.br/).

### IMP-05 — Promoções e preços próprios

- **Situação atual com evidência:** existem modelos, vigência, auditoria, rascunho, publicação, cancelamento e alertas de promoção. A publicação exige comparação válida hoje em todas as lojas ativas, e o fluxo fica oculto quando o flag está desligado. A base local não tem catálogo nem preços próprios.
- **Mudança sugerida:** manter o fluxo desativado até a carga real do catálogo e a validação do processo pelos compradores. Depois, homologar rascunho, programação, vigência, revalidação no dia de início e auditoria. Não fixar limites de alerta sem decisão comercial.
- **Benefício esperado:** preservar autoria e vigência sem apresentar preço planejado como promoção ativa.
- **Prioridade / estado:** **P2 — fluxo parcial preparado; não ativar nesta etapa.**
- **Dependências:** IMP-01, permissões dos compradores e decisões de publicação, fim de vigência, exceções e alertas comerciais.
- **Critério de aceite:** preço futuro só aparece como programado; publicar exige comparação conforme política aprovada; falha de coleta nunca vira preço zero.
- **Evidência:** pricing/workflow_models.py:7-40; pricing/price_workflow.py:25-64; project/settings.py:122; pricing/portal.py:303-310.

### IMP-06 — Segurança e continuidade no servidor do escritório

- **Situação atual com evidência:** há configuração de proxy, HTTPS, allowlist, controles de sessão e runbook para backup e recuperação. Hostname, certificado, limites de rede, worker contínuo, custódia e restauração de backups ainda precisam de validação no ambiente real.
- **Mudança sugerida:** validar o deploy com a infraestrutura do escritório, automatizar backups criptografados e demonstrar uma restauração isolada antes da entrada em produção.
- **Benefício esperado:** proteger contas e preços e reduzir o tempo de recuperação.
- **Prioridade / estado:** **P1 — preparação de código/documentação parcial; operação real pendente.**
- **Dependências:** servidor, hostname, certificado, CIDRs observados pelo proxy, destino seguro para backup e responsáveis operacionais.
- **Critério de aceite:** acesso fora da rede autorizada é bloqueado; TLS está válido; backup recente restaura em ambiente isolado; health check confirma banco e fila.
- **Evidência:** docs/seguranca.md; docs/runbook.md; deployment/Caddyfile; compose.yaml.

### IMP-07 — Uma única aplicação operacional

- **Situação atual com evidência:** Django é o portal autenticado. Durante a revisão, a pasta de apoio ainda continha um Site estático sem dados conectados e com controles desativados.
- **Mudança aplicada:** por solicitação do usuário, o protótipo desconectado foi removido da pasta de apoio; o portal Django permanece como a única aplicação operacional.
- **Benefício esperado:** manter acesso, regras e dados em uma única fonte operacional.
- **Prioridade / estado:** **P2 — limpeza do protótipo concluída como solicitada.**
- **Dependências:** validação do fluxo Django pelos dois compradores antes da implantação operacional.
- **Critério de aceite:** pesquisa e operação ocorrem no portal Django autenticado; nenhuma tela paralela exibe dados ou regras próprias.
- **Evidência:** `docs/contexto/solicitacao-2026-11-24/especificacao-tecnica-regras-de-negocio.md`, seção 1.1; `pricing/urls.py`.

## Etapa incremental aplicada

A tela Saúde das coletas lista cada unidade ativa com a última tentativa concluída, a última resposta válida, as contagens do ciclo mais recente e o motivo registrado. Quando há uma consulta textual, a linha inclui um atalho para reabri-la e usar a atualização por unidade já existente. Também foram adicionados os logos oficiais às telas de busca e comparação, com associação feita por migração reversível e fallback para imagem ausente. A atualização não ativa preços próprios nem altera a fila ou o mecanismo de coleta.

## Limites desta revisão

- A migração foi aplicada à cópia SQLite local para preencher os quatro campos de logo que estavam vazios. Não foram alterados produtos, anúncios, observações ou preços. Isso não demonstra a aplicação da migração no banco de produção.
- O espelho continua sem conector; a integração depende do sistema de origem, credenciais, esquema e regras de reconciliação. Os logos oficiais foram baixados, preservados e versionados; os hashes estão no manifesto.
- **Verificação local:** `manage.py check` apontou zero problemas; `makemigrations --check --dry-run` não encontrou alterações; a suíte executou 75 testes, com 1 ignorado. Não executei benchmarks. A migração local e os hashes dos arquivos também foram conferidos. Os valores de desempenho continuam como referências históricas, não garantias.
- A validação do worker, TLS, backup e acesso depende do servidor real.
