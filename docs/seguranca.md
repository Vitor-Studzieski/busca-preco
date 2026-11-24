# Segurança do portal

O alvo é OWASP ASVS nível 2. A tabela reúne os controles auditados para esta entrega, com verificação funcional, leitura da configuração ou pendência operacional. As referências são o [OWASP ASVS](https://asvs.owasp.org/) e o [checklist de implantação do Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

| Ameaça STRIDE | Superfície | Controle e evidência |
|---|---|---|
| Falsificação | Login e sessão | Argon2, requisitos mínimos de senha, limite por IP e por conta + IP, sessão no banco, revogação com confirmação de senha. Testes de sessão persistente e revogação. |
| Adulteração | Proposta, preço, alertas, catálogo | POST com CSRF e permissões verificadas no servidor. Validação do CSV, preço positivo e vigência com constraint. Templates escapam conteúdo externo. |
| Repúdio | Publicação, cancelamento e conta | Auditoria com ator, ação e metadados no banco. Atualização e remoção bloqueadas por trigger PostgreSQL. Pendente política de retenção e auditoria dos eventos administrativos de infraestrutura. |
| Divulgação | Cookie, credenciais e coleta | Cookies seguros em produção, configuração por ambiente, exposição limitada ao escritório no proxy, HTTP externo só por HTTPS com host, caminho e DNS validados. TLS do servidor real ainda depende da implantação. |
| Negação de serviço | Busca e fontes | Limites compartilhados, fila por unidade, timeout, pausas por rede e limite de 8 MiB por resposta. Pendente validação de capacidade no servidor de uso. |
| Elevação de privilégio | Rotas de compra e manutenção | Verificação de autorização no servidor, provisionamento CLI em produção e caminho administrativo próprio. TOTP administrativo é exigido no perfil de produção. Validação por VPN/IP permanece pendente no servidor. |

| Área ASVS | Evidência | Estado |
|---|---|---|
| Autenticação e sessão | `pricing/accounts.py`, `pricing/access.py`, testes do fluxo | Implementado para compradores. A duração final é uma decisão do escritório. O perfil de produção protege o painel técnico com TOTP. |
| Controle de acesso | Testes de visitantes e compradores, token de progresso vinculado ao usuário | Cobertura das rotas principais. Revisar a matriz completa antes do deploy. |
| Entrada e saída | Escapamento Django, montagem do DOM com textContent e validação de protocolo | Implementado. Cadastro de logos oficiais adiado. |
| Comunicação | HTTPS obrigatório no perfil de produção, Caddy, HSTS e CSRF configuráveis | Configuração preparada. Certificado e perímetro reais pendentes. |
| Dependências e configuração | Lock com hashes, Ruff, Bandit, pip-audit e `manage.py check --deploy` no pipeline | Auditoria local registrada no relatório. CI remoto ainda depende do repositório hospedado. |
| Operação e dados | Papéis de banco separados no Compose, healthcheck, plano de backup e restauração | Transferência local validada separadamente. Automatização e custódia de backups de produção pendentes. |
