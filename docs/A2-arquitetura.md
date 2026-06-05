# DijkFood A2 — Arquitetura (Objetivo 3: camada preditiva e conversacional)

Extensão da plataforma DijkFood (A1) com a **camada analítica** obrigatória e o
**Objetivo 3** (capacidades preditiva e conversacional). Todos os requisitos
funcionais e não-funcionais da A1 continuam atendidos; a evolução é **aditiva** e
desacoplada do caminho crítico da operação.

## 1. Visão geral

```
Usuários ─HTTP─▶ ALB ─▶ core-api / order-service / tracking-service / routing-service (A1)
                          │ (mesma transação)            │ (DynamoDB Streams · CDC)
                          ▼                               ▼
                   RDS: outbox_events            Lambda position-forwarder
                          │ (poll + retry)               │
                   Lambda outbox-publisher ──────────────┴────▶ Kinesis Firehose ──▶ S3 raw (JSON)
                                                                                         │
                                                              Glue Job (CTAS)  raw ─▶ curated ─▶ marts  (PARQUET)
                                                                                         │
                                                              Glue Data Catalog + Athena
                                                  ┌──────────────────┼─────────────────────┐
                                          dashboard-service   prediction-service     assistant-service
                                          (6 indicadores +    (ETA sync + batch        (NL → SQL,
                                           preditivo)          demanda/anomalia)        Bedrock+fallback)
                                                                     │  │
                            EventBridge → Step Functions → SageMaker Training → Model Registry
                                                                     │  └─▶ SNS (alertas de anomalia)
                                                              S3 models/eta + predictions/
```

## 2. Camada analítica durável (eventos → lake)

### 2.1 Outbox transacional (durabilidade forte)
Eventos de domínio originados no RDS (**criação de pedidos** e **transições de
estado** no order-service; **usuários/restaurantes/entregadores/itens** no
core-api) são gravados numa tabela **`outbox_events` na MESMA transação** do dado
de domínio. Um relay — **Lambda `outbox-publisher`** (na VPC, driver puro-Python
pg8000) — varre as linhas pendentes (`FOR UPDATE SKIP LOCKED`), publica no
**Firehose** com retry e marca como publicadas. Garantias:

- **Atomicidade**: o evento existe se, e somente se, a operação foi persistida.
- **At-least-once**: se o Firehose falhar, a linha permanece pendente e é
  reprocessada (sem perda de evento) — resolvendo a fragilidade do envio direto.
- **Sem regressão de SLA**: a publicação é assíncrona (fora do request).

As **posições reportadas** dos entregadores vivem no DynamoDB; entram no lake por
**CDC**: DynamoDB Streams → Lambda `position-forwarder` → mesmo Firehose
(at-least-once nativo do stream).

### 2.2 Medallion: raw → curated → marts
- **raw** (Firehose → S3): JSON/GZIP, partição dinâmica `entidade/year/month/day`.
- **curated** (Glue Job, **Parquet**): `curated_orders`, `curated_deliveries`,
  `curated_positions` — fatos limpos/conformados.
- **marts** (Glue Job, **Parquet**): `mart_daily_volume`, `mart_region_distribution`,
  `mart_top_restaurants`, `mart_demand_heatmap`, `mart_delivery_histogram`,
  `mart_state_avg_seconds` — agregados prontos.

O job é **Glue Python Shell** (`infra/glue/build_marts.py`) que executa Athena
**CTAS** (cada tabela vira Parquet registrado no Glue Catalog), agendado por um
Glue Trigger. Escolhemos CTAS+Python Shell (em vez de Spark) por custo e por
casar com a restrição de só termos a LabRole. O **raw permanece JSON** (formato
nativo do Firehose para payload heterogêneo); **curated/marts são Parquet** — é
exatamente o que o diagrama indica.

### 2.3 Dashboard
`dashboard-service` (ECS/Fargate, Plotly) computa via Athena os 6 indicadores
obrigatórios + 2 métricas de estado instantâneo (pedidos abertos por estado;
entregadores ativos/disponíveis), e um **painel preditivo** (forecast de demanda
+ anomalias). UI escura, responsiva, com auto-refresh e cache server-side.

## 3. Capacidade preditiva (ciclo de vida completo)

| Fase | Implementação real |
|------|--------------------|
| Coleta | features via Athena (camada analítica) |
| Treino | RandomForest (ETA) + target-encoding restaurante/região |
| **Registro** | **SageMaker Model Registry** (Model Package Group `dijkfood-eta`, versão *Approved* por execução) |
| Implantação | artefato `joblib` no S3 (`models/eta/model.joblib`), servido em memória pelo ECS, hot-reload |
| **Monitoramento** | `/model/info` (MAE holdout vs. baseline) + **CloudWatch alarms** nas Lambdas → **SNS** |
| **Alertas** | anomalias de severidade alta publicadas no **SNS** pelo batch |
| Integração | `order-service` chama `/predict/eta` (concorrente, timeout+fallback) |

- **ETA fora do caminho serial**: a predição é disparada com
  `asyncio.create_task` no início de `create_order`, **sobrepondo-se** à
  atribuição de entregador e à escrita no banco — não adiciona latência serial.
  Internamente tem timeout curto (400 ms) + fallback determinístico; em qualquer
  falha a operação segue normalmente. O ETA volta na resposta e no evento.
- **Demanda por região/horário** e **detecção de anomalias** (z-score de demanda;
  MAD para entregas lentas) são geradas em **batch** → `s3://…/predictions/`.
  Anomalias altas → **SNS** (alerta real, com alarme no CloudWatch também).
- **Retreino gerenciado**: `EventBridge Scheduler → Step Functions →
  SageMaker Training Job → Lambda ml-callback` (promove o artefato para serving,
  **registra a versão no Model Registry**, recarrega o modelo no ECS e roda o
  batch).

### Decisão: serving em ECS, treino/registro/batch no SageMaker
O serving do SageMaker foi instável no Learner Lab. **Servimos o ETA no ECS**
(latência baixa, alta disponibilidade, fallback local) e usamos o **SageMaker
para treino + Model Registry + batch** (gerenciado, agendado). O
`prediction-service` faz auto-treino no startup, garantindo a capacidade mesmo se
a pipeline gerenciada estiver restrita. Esse é o alinhamento honesto com o
diagrama: **SageMaker Training/Registry/Batch existem de fato**; o *serving* é ECS
por decisão de robustez (documentado, não “Serverless Inference”).

## 4. Capacidade conversacional

`assistant-service` (ECS/Fargate): **text-to-SQL via Bedrock**  sobre um **catálogo semântico** (schema das views + dicionário +
few-shots, sobrescrevível em `s3://…/semantic/`), com **guard** (SELECT-only,
allowlist de views curadas, LIMIT) e **fallback determinístico** (intents → SQL)
que mantém a capacidade sem acesso ao Bedrock. Execução no Athena + resumo em
linguagem natural + sugestão de gráfico. UI de chat em `/chat`.

## 5. Não-regressão de SLA — evidência experimental

A não-regressão é **comprovável** com o simulador estendido, que agora reporta
**taxa de sucesso, taxa de erro (HTTP + rede/timeout) e P50/P95/P99 global e por
rota** (requisito: P95 < 500 ms). Metodologia sugerida para o relatório:

1. **Baseline (A1)**: rodar `SCENARIO=peak` antes da camada analítica (branch/commit A1) e capturar P95/P99/erro.
2. **Com camada analítica (A2)**: rodar o mesmo cenário; a operação não deve
   regredir, pois (a) eventos vão por outbox/CDC assíncronos e (b) o ETA é
   concorrente com timeout+fallback.
3. **Cenários operacionais**: `hotspot`, `concentration`, `outage` para estressar
   regiões/restaurantes/disponibilidade e observar o comportamento.

Os números (P50/P95/P99, % erro) saem no `metrics.report()` do simulador e
alimentam a tabela comparativa do relatório.

### Comparação batch × tempo real (relatório)
| Critério | Batch/near-real-time (implementado) | Tempo real (Obj. 1, não escolhido) |
|---|---|---|
| Latência | s–min (buffer Firehose + Athena) | ms |
| Custo | baixo (Athena/S3) | maior (stream + estado quente) |
| Complexidade | baixa (schema-on-read + CTAS) | alta |
| Serviços | Firehose, S3, Glue, Athena | Kinesis/WS, cache |

## 6. Infraestrutura (IaC) e deploy

Módulos Terraform: `datalake` (Firehose + Glue Catalog + Athena + **Glue Job
curated/marts**), `lambda` (position-forwarder + **outbox-publisher na VPC**),
`app-service` (genérico ECS+ALB), `ml` (Step Functions + SageMaker + EventBridge
+ callback). Recursos raiz: **SNS** + **CloudWatch alarms** + **SageMaker Model
Package Group**. Toda compute usa a **LabRole** (sem criação de IAM).

`deploy.py` estende o fluxo da A1: build/push das 3 novas imagens; upload do
`ml/sourcedir.tar.gz` (treino), do `glue/build_marts.py` (ETL) e do catálogo
semântico para o S3; redeploy e smoke test.

## 7. Simulador — cenários parametrizáveis
`SCENARIO=hotspot|concentration|outage` (ou knobs `HOTSPOT_REGION/HOTSPOT_WEIGHT`,
`RESTAURANT_CONCENTRATION/HOT_RESTAURANT_COUNT`, `COURIER_OUTAGE_PCT`). Mantém os
volumes da A1 (`normal/peak/event`).

## 8. Como executar
```bash
python deploy.py deploy                      # provisiona + build/push + smoke
SCENARIO=peak python deploy.py simulate      # carga (evidência de SLA)
SCENARIO=hotspot python deploy.py simulate   # cenário operacional
```
Endpoints: `/dashboard` · `/chat` · `POST /predict/eta` · `GET /model/info` ·
`POST /batch/run` · `GET /predict/demand` · `GET /predict/anomalies`.

## 9. Reconciliação diagrama ↔ implementação
- **Outbox/CDC**: implementado (tabela + Lambda publisher) — não é mais envio direto.
- **Parquet**: curated/marts são Parquet (Glue CTAS); raw é JSON (Firehose).
- **Model Registry / Training / Batch**: SageMaker de fato (registry + training job + batch via prediction-service).
- **Serving**: ECS (decisão de robustez) — não Serverless Inference.
- **SNS**: tópico real + alarmes CloudWatch + publicação de anomalias.
- **Frontend**: SPA server-rendered (FastAPI+Plotly) unificando dashboard +
  preditivo + chat — escolhido por robustez sob carga (alternativa React/Streamlit
  descrita no relatório).

## 10. Testes
`tests/` cobre a lógica pura (guard de SQL, intents do fallback, sugestão de
gráfico, features/predição do ETA, parsing do batch, envelope do outbox,
ponderação de cenários do simulador). Rodar: `python tests/test_*.py`.
Infra: `terraform validate`. Código: `py_compile`.
