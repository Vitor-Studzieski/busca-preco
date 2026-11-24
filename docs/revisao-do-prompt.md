# Revisão do portal · 24/11/2026

O redesenho substitui o cabeçalho horizontal com cartões repetidos por uma área de trabalho com menu lateral, busca fixa, ofertas por unidade e estados de coleta. As quatro áreas têm estruturas próprias. No celular, a navegação fica no topo e as ofertas se empilham.

| Item do prompt | Entrega e verificação |
|---|---|
| Pesquisa e comparativos na mesma tarefa | Busca com atalho, sugestões e histórico da sessão. Resposta do banco, ofertas em grupos por unidade, filtro de promoção e clube, fonte, hora e atualização individual. O estado da última tentativa aparece junto ao último preço válido. |
| Catálogo, vínculo e preço próprio | Busca por SKU e GTIN com precedência, comparação com motivo de indisponibilidade, série histórica e tabela, prévia de diferença, rascunho e confirmação de publicação. Quem tem permissão pode confirmar um vínculo com GTIN ou desfazê-lo com auditoria. Fluxo validado em teste e controlado por `PRICING_ENABLE_OWN_PRICES`, desativado na operação inicial. |
| Fila do dia | Contagem real, ordenação, filtros salvos na sessão, paginação, atualização em lote confirmada e ações de revisão no modo catálogo. Sem catálogo, a fila mostra consultas dos concorrentes que já retornaram preços. |
| Alertas | Abertos, não reconhecidos e resolvidos. Plantão de coleta e vigência continuam persistentes. O mecanismo de diferença usa somente regras editadas e ativadas com limites válidos. Nenhuma regra comercial foi cadastrada. |
| Saúde | Próxima janela, tarefas pendentes, tarefas em execução, estado por rede e histórico real de execuções. Janelas atuais de 04h e 14h. |
| Identidade visual | Logo Pompeia existente. Espaço para logos concorrentes aprovados com validação de arquivo estático, extensão e tamanho. As redes sem arquivo aprovado ficam identificadas pelo nome e iniciais. |
| Banco e segurança | Constraints PostgreSQL, auditoria imutável existente, sessão e revogação. Administração técnica exige TOTP no perfil de produção. O token de acompanhamento segue em cabeçalho para ficar fora da URL e dos logs de acesso. |
| Operação | Imagem web sem root e com estáticos na build, arquivos de execução em leitura no Compose, papéis de banco separados e script de backup criptografado. Validado em Docker local fechado, com migrations, PostgreSQL, Redis, worker e web. O servidor do escritório ainda será configurado. |

## Evidências

- 75 testes em PostgreSQL, incluindo vigência futura, filtros e lote, vínculo auditado, regras opt-in e condução de sessão. Em SQLite, o teste de constraint específico de PostgreSQL fica ignorado.
- Playwright em Chrome confirmou login persistente, busca por nome com preços reais em quatro unidades, filtro de promoção e clube, navegação, fila, alertas, saúde, dispositivos e viewport móvel sem estouro horizontal. Busca por GTIN e publicação futura foram verificadas por integração Django com dados de teste isolados.
- Cobertura medida no código de produção ficou em 80%. A meta de 85% ainda não foi atingida. Ruff, pip-audit, Bandit no perfil de achados médios ou superiores e `check --deploy` passaram.
- A rodada anterior mediu 14 ms no p95 da leitura e 6 ms com dados gravados. Os alvos ao vivo continuam em aberto: 16,58 s no p95 da atualização completa, com fornecedores externos. Os dados do benchmark estão em [Desempenho](baseline-desempenho.md).

## Telas

- [Pesquisa em desktop](evidencias/pesquisa-redesenho-desktop.png)
- [Pesquisa no celular](evidencias/pesquisa-redesenho-mobile.png)
- [Fila do dia](evidencias/fila-redesenho.png)
- [Alertas](evidencias/alertas-redesenho.png)
- [Saúde das coletas](evidencias/saude-redesenho.png)

## Dependências da próxima etapa

Catálogo e espelho do Pompeia, taxonomia, logos aprovados e limites comerciais dependem dos dados e das decisões do escritório. O perfil de produção depende do hostname, TLS, rede autorizada, credenciais, autenticador técnico e chave de backup. A imagem e a configuração foram validadas localmente. A restauração do backup criptografado, a certificação ASVS/WCAG completas e a execução do CI remoto não foram validadas no servidor do escritório.
