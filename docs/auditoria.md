# Auditoria do portal de preços

Auditoria em 24/11/2026. O estado original está em `baseline-portal-2026-11-24`. O projeto atendia quatro unidades em três redes, com checkout Git sem histórico e base SQLite com quatro lojas e nenhum produto, anúncio, observação ou rascunho. O catálogo do Pompeia fica para uma etapa posterior e a primeira versão cobre apenas os concorrentes.

| ID | Área e grau | Evidência e causa no código original | Correção e estado | Esforço |
|---|---|---|---|---|
| E-01 | Dados · crítica | `pricing/views.py` usava Product e Observation para comparativos, mas não havia linhas na base. | A pesquisa por concorrentes funciona com catálogo próprio vazio. Consultas com oferta confirmada formam a carteira real de pré-coleta. Catálogo próprio pendente. | Alto |
| E-02 | Tempo de resposta · crítica | `pricing/views.py` aguardava `search_stores` em cada request. P95 de 13,50 s em 30 buscas. | GET consulta o banco. POST enfileira. O navegador recebe resultado e estado por unidade sem bloquear a navegação. | Alto |
| E-03 | Coleta · alta | `pricing/offer_search.py` limitava tempo na requisição e a pausa não era compartilhada entre processos. Houve 14 timeouts. | Estado explícito por unidade, preservação da última coleta, isolamento de falhas, pausa por rede e backoff. Timeout do terceiro continua possível. | Alto |
| E-04 | Estado compartilhado · alta | `project/settings.py` usava LocMemCache inclusive para contar buscas. | Redis em produção. Desenvolvimento sem Redis usa contador em banco para o fluxo atual. A busca original continua disponível para benchmark, com cache isolado no processo. | Médio |
| E-05 | Operação · alta | `pricing/management/commands/collect_offers.py` rodava apenas por invocação. | Worker e agenda de duas janelas, com chave por dia e hora, teste de idempotência e registro de execução. Ativação contínua depende do servidor. | Alto |
| E-06 | Preço próprio · alta | `pricing/models.py` guardava apenas preço legado e proposta. | Modelos e serviços para vigência, sobreposição, auditoria e cancelamento testados. Fluxo inicial por concorrentes, com preço próprio desativado. | Alto |
| E-07 | Alertas · média | A antiga dashboard calculava pendências em leitura, sem reconhecimento. | Alertas persistentes por rede, anúncio e vigência. Reconhecimento é por comprador. Regras comerciais permanecem desativadas. | Médio |
| E-08 | Mercadológico · média | A aba anterior mostrava uma lista sem taxonomia. | Navegação focada na tarefa e catálogo futuro condicionado à integração real. | Baixo |
| E-09 | UX · alta | Pesquisa, comparativos e visão geral duplicavam pontos de entrada. | Pesquisa concentrada na inicial, fila do dia, alertas, saúde das coletas e dispositivos. | Alto |
| E-10 | Unidades · média | `Store` sem ativo, ordem ou referência a logo. | Campos adicionados. Unidades aparecem identificadas pelo nome. Logos oficiais foram versionados em pricing/static/pricing/stores/ e associados às lojas pela migration 0012. | Baixo |
| E-11 | Acesso · alta | A configuração original usava uma chave de desenvolvimento fixa e provisionamento por tela. | Chave por ambiente em produção, provisionamento por CLI, sessão segura e revogável, política de cookies e acesso por rede na configuração do proxy. TOTP administrativo e validação operacional permanecem em aberto. | Alto |
| E-12 | Operação · média | Não havia registro durável de fila, healthcheck ou Compose. | Compose, CI, healthcheck, logs estruturados e runbook. Build e CI remotos dependem do ambiente. | Alto |
| E-13 | Qualidade · média | A documentação anterior não registrou uma execução da suíte. | Linha de base com 55 testes aprovados e cobertura ampliada. Site estático legado aguarda decisão. | Médio |
| E-14 | Integridade de fonte · alta | `collectors/http.py` validava URLs e redirecionamentos, mas não vinculava a conexão às respostas DNS validadas. | O transporte resolve o host, rejeita endereços privados e usa o próprio IP validado com validação TLS para o host. | Médio |
| E-15 | Acesso · alta | O portal original desconhecia dispositivo e não limitava o login. | Contadores por IP e conta + IP, sessões no servidor, revogação com reautenticação e invalidação ao trocar senha. | Médio |
| E-16 | Histórico · alta | Remover anúncio podia apagar observações por cascata. | Relacionamento protegido e flag ativo. PostgreSQL também impede alteração e remoção em linhas de auditoria. | Médio |

O commit inicial preserva a implementação original para comparação. A branch de entrega contém o commit de implementação e a documentação de evidências. Os detalhes de desempenho ficam em [baseline-desempenho.md](baseline-desempenho.md). Os controles e lacunas de segurança ficam em [seguranca.md](seguranca.md).
