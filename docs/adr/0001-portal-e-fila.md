# ADR 0001 · Portal Django e fila em PostgreSQL

O portal preserva os modelos e nomes de tabelas do app Django. A lógica de portal, seleção de preços, fila, acesso e publicação fica em módulos separados no mesmo app. O PostgreSQL guarda a fila e o progresso para que o trabalho sobreviva a reinícios e os resultados possam ser reproduzidos. O Redis guarda contadores compartilhados em produção. A consulta de progresso usa polling autenticado a cada 1,25 s durante uma busca.

O worker usa até três threads no PostgreSQL e serializa as duas unidades do Super Líder por rede. A transação de claim é curta. A operação HTTP ocorre fora dela. Para o volume atual isso reduz o número de serviços em comparação com um broker e um serviço separado de agendamento. O monitoramento registra execuções e pausas de cada rede. A escolha implica manter o worker ativo e acompanhar o crescimento das tabelas de jobs e resultados.

```mermaid
flowchart LR
  B[Comprador] --> W[Portal Django]
  W --> P[(PostgreSQL)]
  W --> R[(Redis)]
  P --> Q[Worker de coleta]
  Q --> L[Super Líder]
  Q --> T[Tauste]
  Q --> C[Confiança]
  Q --> P
```

```mermaid
sequenceDiagram
  participant B as Navegador
  participant W as Portal
  participant D as PostgreSQL
  participant C as Worker
  B->>W: GET pesquisa
  W->>D: Consulta última coleta por unidade
  W-->>B: Renderiza preços gravados ou indisponibilidade
  B->>W: POST atualização
  W->>D: Registra ou reutiliza jobs
  W-->>B: Token de acompanhamento
  C->>D: Assume job e publica resultado
  B->>W: GET progresso autenticado
  W-->>B: Atualiza o cartão da unidade
```

```mermaid
erDiagram
  PRODUCT ||--o{ LISTING : vincula
  STORE ||--o{ LISTING : publica
  LISTING ||--o{ OBSERVATION : recebe
  STORE ||--o{ COLLECTIONJOB : consulta
  COLLECTIONRUN o|--o{ COLLECTIONJOB : agrupa
  COLLECTIONRUN o|--o{ OBSERVATION : registra
  PRODUCT ||--o{ OWNPRICE : recebe
  PRODUCT ||--o{ DAYITEM : entra
  OWNPRICE o|--o{ ALERT : aciona
  ALERT ||--o{ ALERTACKNOWLEDGMENT : recebe
```
