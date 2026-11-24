# Especificação funcional e regras de negócio
## Comparativo de preços, promoções e alertas

**Status:** especificação funcional; implementação inicial integrada ao projeto Django  
**Fuso de negócio:** America/Sao_Paulo  
**Volume de referência:** cerca de 130 produtos em promoção por dia; estimativa operacional, sem limite rígido.

## 1. Objetivo

Dar suporte à precificação feita pelos compradores, comparando nossos preços com os de outros supermercados com dados recentes, permitindo consultar os resultados pelo espelho do banco de dados e acompanhar promoções, métricas e alertas em uma dashboard.

Esta especificação define regras de negócio e componentes lógicos. A escolha de frameworks, banco de dados, fila e mecanismo de coleta depende da arquitetura e das fontes disponíveis no sistema atual.

### 1.1 Decisão de arquitetura e escopo

- A aplicação existente em `/Users/vitorstudzieski/Projetos/precos` é o projeto único de pesquisa e dashboard. Não manter uma dashboard paralela como Site independente.
- A aplicação é interna e destinada aos compradores. A navegação operacional não inclui uma área ou dashboard de gestor; todas as páginas exigem login e a permissão de consulta de produtos.
- A página inicial é a pesquisa. Visão geral, comparativos, promoções, mercadológico e alertas têm páginas próprias dentro da mesma aplicação e consomem registros reais.
- A base local consultada em 23/11/2026 tinha 4 supermercados cadastrados e nenhum produto, anúncio monitorado, preço observado ou rascunho de preço. As métricas devem refletir essa base vazia, sem registros de demonstração.
- A busca de concorrentes que já existe no Django consulta as fontes configuradas em tempo real. A busca pelo espelho ainda depende da integração e carga desse espelho; não se deve descrever a busca atual como originada nele.
- O modelo atual não registra vigência de promoções próprias nem hierarquia mercadológica. As páginas correspondentes devem indicar essa ausência até os dados e campos reais serem integrados.

### 1.2 Escopo confirmado da primeira fase em 24/11/2026

A primeira fase atende dois compradores e consulta preços dos concorrentes. O portal será hospedado no servidor local com acesso restrito ao escritório. A busca lê a última coleta disponível no banco do portal e atualiza as unidades em segundo plano. A rotina dos concorrentes tem duas janelas, às 04h e 14h no fuso America/Sao_Paulo. O segundo horário é configurável. A carteira inicial vem das consultas reais em que houve preço confirmado. A integração ao banco do Pompeia e a publicação de preços próprios ficam para a etapa posterior, quando o catálogo estiver disponível.

O registro atual do sistema fica em `documentacao-completa.json`. As regras de vigência e integração nas seções posteriores continuam como requisitos da próxima fase.

## 2. Requisitos confirmados

1. Os compradores decidem quais produtos entram em oferta e em quais datas. Não existe calendário fixo de promoções.
2. Os compradores lançam e alteram preços, e podem fazer isso a qualquer horário.
3. O preço pode ser cadastrado dias antes da mudança entrar em vigor ou no próprio dia.
4. A comparação de preços deve considerar dados dos concorrentes atualizados no dia da decisão de preço.
5. Deve existir uma rotina diária às 4h para atualizar ou reconciliar os preços relevantes.
6. Uma promoção deve permanecer em alerta durante sua vigência.
7. A busca de produtos deve consultar o espelho do banco de dados.
8. Os resultados devem incluir um espaço explícito para o preço do Superpompéia.
9. A visualização completa do produto deve exibir os logos dos supermercados junto aos respectivos preços.
10. Deve existir dashboard com métricas, alertas de comparação e separação pela hierarquia mercadológica.
11. A dashboard deve exibir exclusivamente dados reais da fonte conectada. É proibido preencher preços, métricas, lojas, logos, categorias, alertas ou atividade com valores inventados ou de demonstração.
12. Cada aba da dashboard deve apresentar conteúdo próprio, alinhado à sua finalidade, sem repetir a mesma tela ou os mesmos blocos de visão geral.

## 3. Fluxo funcional proposto

### 3.1 Cadastro ou alteração de preço pelo comprador

1. O comprador inicia o cadastro ou a edição do preço de um produto.
2. O sistema consulta os preços concorrentes no espelho e verifica a data da última coleta de cada preço.
3. Se os dados não tiverem coleta bem-sucedida na data corrente de São Paulo, o sistema solicita uma atualização para o produto e seus concorrentes.
4. A tela mostra os preços comparados, a loja de origem e o horário/data de coleta. Dados antigos ou indisponíveis são identificados como tal.
5. O sistema registra o preço do comprador, seu autor, a data de cadastro/alteração e a vigência planejada.
6. Se a vigência começar em data futura, uma nova atualização é agendada para o dia de início, pois a coleta feita no cadastro pode já estar desatualizada.

### 3.2 Rotina diária das 4h

Às 4h, no fuso America/Sao_Paulo, a rotina deve localizar:

- promoções vigentes sem coleta concorrente bem-sucedida na data corrente;
- promoções programadas para começar naquele dia;
- alterações de preço programadas para entrar em vigor naquele dia;
- itens relevantes cuja última comparação esteja ausente ou desatualizada.

O volume de 130 itens por dia serve para estimar capacidade. A rotina deve processar a lista real de itens, sem truncá-la nesse número. Itens cadastrados ou alterados depois das 4h entram pelo fluxo disparado pela ação do comprador.

### 3.3 Consulta de preços

A busca consulta o espelho e retorna preços próprios e concorrentes usando identificadores de produto consistentes. O resultado inclui o preço do Superpompéia e, para cada preço concorrente, a loja, o logo, o valor e a data/hora da coleta.

O espelho é a fonte de consulta solicitada. O mecanismo que alimenta ou atualiza esse espelho precisa ser integrado conforme a arquitetura existente; a tela de busca não deve tratar um dado antigo como preço atualizado.

## 4. Regras de negócio

### RB-01 — Decisão de oferta

Cada promoção nasce de uma ação de um comprador autorizado. O sistema não presume um calendário semanal ou dias fixos de oferta.

### RB-02 — Vigência do preço

Cada preço promocional precisa ter início de vigência. Para fechar automaticamente a promoção, deve haver uma data/hora final ou um evento explícito de encerramento/cancelamento. Um preço programado para o futuro não é uma promoção ativa antes do início da vigência.

### RB-03 — Estado da promoção

Estados lógicos recomendados:

- **Rascunho:** preço ainda não confirmado para vigência.
- **Programada:** preço confirmado, com início futuro.
- **Ativa:** horário atual dentro da vigência e promoção não cancelada.
- **Encerrada:** vigência concluída.
- **Cancelada:** comprador ou usuário autorizado cancelou a promoção antes ou durante a vigência.

A regra de atividade é: início da vigência menor ou igual ao horário atual, horário atual anterior ao fim da vigência, e estado não cancelado.

### RB-04 — Atualização por ação do comprador

O cadastro ou a alteração de um preço deve acionar a verificação de atualização dos preços concorrentes a qualquer horário. A comparação só pode receber o rótulo “atualizada hoje” se houver coleta bem-sucedida na data corrente do fuso de negócio.

Se o produto tiver início futuro, a coleta deve ser repetida no dia de início. A rotina das 4h também cobre promoções ativas e programadas para aquele dia.

### RB-05 — Rotina idempotente e recuperação

A rotina das 4h e as atualizações disparadas por compradores devem poder ser repetidas sem duplicar preços ou alertas. Cada execução deve registrar início, fim, quantidade processada, falhas e última coleta bem-sucedida por produto e supermercado. Falhas devem permitir nova tentativa e aparecer como dado pendente/desatualizado.

### RB-06 — Correspondência de produtos

Comparações devem usar primeiro um identificador exato disponível, como SKU interno ou GTIN/EAN mapeado. Quando a correspondência não puder ser confirmada, o resultado deve indicar que o preço comparável está indisponível; não deve assumir que produtos diferentes são equivalentes.

Produtos com embalagens ou quantidades diferentes não devem ser comparados pelo preço total sem normalização. Se houver conversão confiável, mostrar também o preço por unidade padrão e identificar a base usada.

### RB-07 — Ausência de preço

Preço ausente, coleta falha ou produto sem correspondência deve ser representado como indisponível, nunca como zero. A interface deve distinguir, quando possível, “sem preço encontrado”, “produto sem correspondência” e “coleta pendente/falhou”.

### RB-08 — Alerta de promoção

O alerta de promoção deve abrir automaticamente quando a promoção passar a ativa e permanecer aberto até o encerramento ou cancelamento. Reconhecer/visualizar um alerta não encerra sua condição. Deve existir no máximo um alerta aberto do tipo “promoção ativa” por registro de promoção.

### RB-09 — Alertas de comparação

A dashboard deve suportar alertas para dados concorrentes desatualizados ou ausentes. Também deve suportar alertas de diferença de preço depois que o negócio definir limites, direção e período de avaliação. Até esses parâmetros serem definidos, o sistema deve exibir a comparação e as métricas sem inventar um limite de alerta.

Uma condição resolvida deve encerrar o alerta aberto correspondente; se voltar a ocorrer, deve gerar novo evento ou reabrir o alerta com histórico preservado.

### RB-10 — Superpompéia e demais supermercados

Superpompéia deve ser tratado como um supermercado do catálogo de lojas e, ao mesmo tempo, ocupar um campo/posição explícita nos resultados de busca. As demais lojas seguem o mesmo modelo de dados e aparecem na visão completa.

Logos pertencem ao cadastro da loja, não ao registro de preço. Se um logo não estiver cadastrado, a interface deve usar um identificador visual substituto e continuar exibindo o nome e o preço.

### RB-11 — Métricas e separação mercadológica

A dashboard deve permitir filtros pela hierarquia mercadológica disponível no cadastro de produtos, além de período, loja e estado da promoção.

Métricas iniciais:

- quantidade de promoções programadas e ativas;
- quantidade e percentual de produtos com ao menos um preço concorrente comparável e atualizado hoje;
- quantidade de preços ausentes ou desatualizados;
- nosso preço promocional versus o menor preço concorrente comparável;
- diferença absoluta e percentual, quando houver preços válidos;
- alertas abertos por tipo e categoria mercadológica.

O denominador de cobertura deve ser explícito. Proposta inicial: produtos com promoção ativa ou programada para iniciar no dia selecionado.

### RB-12 — Histórico e auditoria

Manter histórico de quem lançou/alterou o preço, valores anteriores e novos, vigência, cancelamento e motivo de eventual exceção. Cada preço concorrente deve manter sua data/hora de coleta e origem. Uma coleta nova atualiza o valor vigente para consulta, sem apagar o histórico.

### RB-13 — Integridade dos dados exibidos

A interface não deve usar dados seed, exemplos ou valores fabricados. Quando a fonte não estiver conectada ou não retornar determinado dado, exibir estado de indisponibilidade/aguardando conexão, sem converter a ausência em zero. O zero só representa uma contagem efetivamente calculada igual a zero a partir da fonte real. Exibir a origem e a data/hora de atualização para dados carregados.

### RB-14 — Conteúdo específico por aba

A navegação deve trocar a área principal para uma visão própria por domínio: visão geral operacional, comparativos por produto/loja, promoções e vigências lançadas pelos compradores, classificação mercadológica e fila/regras de alertas. O cabeçalho e a navegação podem ser compartilhados; os blocos centrais e controles devem refletir a tarefa de cada aba e não duplicar a mesma dashboard.

## 5. Entidades lógicas mínimas

| Entidade | Dados principais |
|---|---|
| Produto | identificador interno, SKU/GTIN, descrição, unidade/embalagem e classificação mercadológica |
| Loja | identificador, nome, logo e status |
| Preço próprio | produto, valor, tipo (regular/promocional), vigência, estado, comprador e datas de auditoria |
| Observação de preço concorrente | produto mapeado, loja, valor, unidade, coletado em, origem e estado da coleta |
| Execução de atualização | horário, estado, itens processados, falhas e tentativas |
| Alerta | produto/preço associado, tipo, estado, abertura, reconhecimento e resolução |

## 6. Componentes lógicos

1. **Cadastro de preço:** recebe lançamentos e alterações dos compradores, registra autoria e vigência.
2. **Orquestrador de atualização:** reage a lançamentos/alterações e executa a rotina diária das 4h; agenda a revalidação de preços futuros.
3. **Camada de comparação:** normaliza identificadores e unidades, seleciona a observação concorrente válida mais recente e calcula diferenças.
4. **Consulta/API:** atende busca e dashboard usando o espelho como fonte de leitura.
5. **Motor de alertas:** abre, atualiza e encerra alertas de promoção, atualização e diferenças configuradas.
6. **Cadastro de supermercados:** centraliza nomes e logos exibidos na interface.

## 7. Critérios de aceite funcionais

- Um comprador consegue lançar ou alterar preço em qualquer horário, com autoria e vigência registradas.
- Um preço planejado para data futura aparece como programado e é revalidado no dia de início.
- Uma ação do comprador não depende da execução das 4h para solicitar comparação atualizada.
- A rotina das 4h reprocessa ofertas ativas e as que começam naquele dia, sem duplicar registros ou alertas.
- A interface diferencia preços atualizados hoje de preços antigos, ausentes ou não comparáveis.
- O resultado da busca inclui o preço do Superpompéia e mostra os logos disponíveis junto aos demais preços na visão completa.
- O alerta de promoção permanece aberto durante toda a vigência e encerra ao fim/cancelamento.
- A dashboard permite separar as métricas pela hierarquia mercadológica existente.

## 8. Decisões de negócio ainda pendentes

Estas decisões não devem ser codificadas como constantes sem validação:

1. Qual sistema ou fornecedor fornece os preços dos concorrentes e como atualiza o espelho.
2. Se “atualizado hoje” (data local) é suficiente ou se haverá um limite máximo de idade em horas.
3. Quais limites, direção e severidade abrem alertas de diferença de preço.
4. Se o comprador pode confirmar/publicar preço quando a coleta concorrente falha; proposta: permitir salvar como rascunho, exibir a pendência e exigir justificativa autorizada para confirmar sem comparação atualizada.
5. Quais níveis da classificação mercadológica serão usados na dashboard.
6. Quais canais, além da dashboard, devem receber alertas.
7. Como serão mantidos os mapeamentos de SKU/GTIN entre nosso catálogo e os concorrentes.
8. Se datas de vigência são informadas com hora ou apenas com dia e qual regra visual de inclusão do último dia será usada.

## 9. Ordem sugerida de implementação

1. Confirmar fontes de dados, espelho, identificadores de produto e classificação mercadológica.
2. Registrar preços próprios com comprador, estado e vigência.
3. Implementar atualização por evento, revalidação de preços futuros e rotina diária das 4h com histórico de execução.
4. Implementar comparação, regra de atualização diária e busca pelo espelho.
5. Exibir Superpompéia, demais lojas e logos.
6. Implementar estados de alertas e dashboard com filtros e métricas.
7. Configurar limites de diferença e canais de notificação após decisão do negócio.
