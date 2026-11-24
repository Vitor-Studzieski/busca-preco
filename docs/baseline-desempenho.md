# Desempenho da pesquisa

Medição em 24/11/2026, com a mesma lista de 30 termos nos catálogos públicos e pausas entre termos. O teste do portal usou Django Client e PostgreSQL local isolado. Os tempos de banco incluem sessão, consultas e renderização no processo, sem rede entre o navegador e o servidor. Os tempos ao vivo incluem espera pelo worker e pelos concorrentes.

| Medida | Amostras | p50 | p95 |
|---|---:|---:|---:|
| Tela original com busca externa síncrona | 30 | 11,37 s | 13,50 s |
| Nova tela sem coleta gravada | 30 | 11 ms | 14 ms |
| Nova tela após atualização do banco | 30 | 5 ms | 6 ms |
| Primeira unidade com nova oferta confirmada, entre buscas que a obtiveram | 24 | 4,30 s | — |
| Atualização ao vivo completa, inclusive erros e pausas | 30 | 14,86 s | 16,58 s |

| Unidade | Original p50 / p95 | Worker p50 / p95 | Jobs com tempo de coleta medido |
|---|---:|---:|---:|
| Super Líder Pompéia | 10,54 s / 12,39 s | 8,02 s / 8,38 s | 20 |
| Super Líder Herculândia | 10,03 s / 12,01 s | 8,01 s / 8,38 s | 19 |
| Tauste Marília | 9,31 s / 12,04 s | 3,50 s / 8,04 s | 30 |
| Confiança Marília | 4,87 s / 10,18 s | 4,76 s / 8,03 s | 30 |

O tempo da rede no original mede execução do coletor por unidade. Depois da mudança mede execução do job por unidade, excluindo espera na fila e pausas do circuito. Com rede em pausa, o job devolve seu estado sem fazer uma chamada nova. A versão original registrou 14 timeouts. Na nova execução, 66 unidades retornaram ofertas atualizadas, 20 não tiveram correspondência, 13 retornaram erro e 21 ficaram bloqueadas ou em pausa. Oscilações externas impedem atribuir todas as diferenças à mudança de código.

A resposta do banco atingiu a meta de 300 ms. As metas ao vivo de primeira oferta em 3 s e conclusão em 8 s ficaram acima do alvo. Os dois endereços do Super Líder são consultados separadamente e em sequência dentro da rede, com pausa após bloqueio ou falhas consecutivas. A pré-coleta duas vezes por dia reduz a dependência desta etapa durante o trabalho dos compradores. Quando uma consulta ainda não está na carteira de pré-coleta, seus resultados continuam dependentes dos catálogos ao vivo.

## Reproduzir

- Original: `PYTHONPATH=. python scripts/benchmark.py` com os módulos da tag de linha de base.
- Portal: execute `PYTHONPATH=. python scripts/benchmark_portal.py` com PostgreSQL vazio, migrado, em banco isolado chamado `pompeia_benchmark`.
- Os arquivos JSON de evidências trazem as durações, a classificação e o resumo de cada fonte. Não contêm credenciais nem valores de preço.
