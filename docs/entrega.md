# Entrega da primeira fase

O portal consulta as quatro unidades concorrentes, conserva a última coleta confirmada e atualiza os resultados em segundo plano. A fila de coletas usa buscas reais com preço confirmado. As janelas padrão são 04h e 14h em São Paulo. A área de dispositivos permite manter a sessão e revogar outros acessos. O preço próprio está desativado nesta fase, à espera do catálogo do Pompeia.

## Evidências

- **Linha de base.** 55 testes aprovados. Medição externa de 30 consultas, com p95 de 13,50 s para renderizar a pesquisa original.
- **Banco.** 64 testes aprovados em PostgreSQL. Em SQLite foram executados os mesmos 64, com um ignorado por verificar constraints específicas de PostgreSQL. Transferidos seis registros existentes entre cópias isoladas com contagem e SHA-256 conferidos. As migrations voltaram de 0011 para 0005 e foram reaplicadas com sucesso na cópia.
- **Busca.** P95 de 14 ms para abrir a pesquisa sem registro gravado e 6 ms com registros. Atualização ao vivo completa teve p95 de 16,58 s. Primeira oferta confirmada teve p50 de 4,30 s nas 24 buscas que concluíram com ofertas. A meta da leitura foi atendida. As duas metas da coleta ao vivo ficaram acima do alvo.
- **Navegador.** Playwright sobre Chrome verificou login persistente, busca por nome com ofertas reais de quatro unidades, fila de pesquisas monitoradas, saúde das coletas, dispositivos e a tela mobile sem rolagem horizontal. O fluxo provisório de vigência e aviso de bloqueio foi exercitado em testes de integração. A publicação real fica para depois do catálogo.
- **Configuração.** Ruff, Bandit para achados de severidade e confiança médias ou superiores, pip-audit no lock, `manage.py check --deploy`, validação do Compose e verificação de migrations sem pendências passaram localmente. O daemon do Docker não estava ativo para construir a imagem. A execução de CI remoto e a homologação no servidor do escritório ainda dependem do ambiente.

## Arquivos

- [Auditoria e situação de cada achado](auditoria.md)
- [Benchmark e metodologia](baseline-desempenho.md)
- [Captura desktop](evidencias/pesquisa-desktop.png)
- [Captura mobile](evidencias/pesquisa-mobile.png)
- [Arquitetura e diagramas](adr/0001-portal-e-fila.md)
- [Segurança e lacunas](seguranca.md)
- [Operação e reversão](runbook.md)
- [Documentação JSON](documentacao.json)
- [Decisões em aberto](perguntas-em-aberto.md)
