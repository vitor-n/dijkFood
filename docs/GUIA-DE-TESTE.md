# DijkFood A2 — Guia de Teste (verificação ponta a ponta)

Roteiro para validar **toda** a plataforma (camada analítica + preditiva +
conversacional), exceto o modelo via Bedrock (testamos o fallback determinístico
do assistente). Siga as fases em ordem; cada uma tem um **✅ Checkpoint**.

> Shell: **PowerShell** (Windows). Os comandos `aws`/`terraform` funcionam igual.
> Os outputs do Terraform são lidos com `terraform -chdir=infra\terraform output`.

---

## Fase 0 — Pré-requisitos

1. Credenciais do Learner Lab em `~/.aws/credentials` (AWS Details → AWS CLI → Show).
2. Docker Desktop **aberto** (engine Linux pronto).
3. Ferramentas: `terraform -v`, `aws --version`, `docker info`, `python --version`.
4. Variáveis de banco e tfvars de teste (rápido/barato):
   ```powershell
   $env:DB_USERNAME = "dijkfood_admin"
   $env:DB_PASSWORD = "uma_senha_forte_123"
   $env:TF_VAR_FILE = "dev.tfvars"     # single-AZ, counts=1, pipeline SageMaker OFF
   ```

> **Learner Lab troca de conta a cada sessão.** Se você já rodou um deploy numa
> sessão anterior, o `terraform.tfstate` local está órfão (aponta para a conta
> velha) e o apply falha com `AccountIDs mismatch` / `not a valid ARN`. Nesse
> caso, zere o state antes de deployar:
> ```powershell
> cd infra\terraform
> if (Test-Path terraform.tfstate)        { Move-Item terraform.tfstate        "terraform.tfstate.conta-antiga.bak" -Force }
> if (Test-Path terraform.tfstate.backup) { Move-Item terraform.tfstate.backup "terraform.tfstate.backup.conta-antiga.bak" -Force }
> cd ..\..
> ```

**✅ Checkpoint:** os 4 comandos de versão respondem sem erro e o Docker está "running".

---

## Fase 1 — Deploy completo

```powershell
python deploy.py deploy
```

Isso provisiona a infra (Terraform), inicializa o schema do RDS (via SSM),
sobe o catálogo semântico/scripts ML/Glue no S3, faz build/push das 7 imagens,
redeploya o ECS, atualiza o container do dashboard na EC2 e roda o smoke test.
Leva ~20–30 min.

Ao final, capture os outputs principais:
```powershell
cd infra\terraform
$ALB   = terraform output -raw alb_dns_name
$DASH  = terraform output -raw dashboard_url
$BUCKET= terraform output -raw datalake_bucket_name
$GLUEDB= terraform output -raw glue_database_name
$WG    = terraform output -raw athena_workgroup_name
$SIM   = terraform output -raw load_tester_instance_id
cd ..\..
"ALB=$ALB`nDASHBOARD=$DASH`nBUCKET=$BUCKET`nGLUE_DB=$GLUEDB`nWORKGROUP=$WG"
```

**✅ Checkpoint:** o smoke test imprime status 200/aceitos para core-api, routing,
tracking, order, assistant e prediction; e os outputs acima vêm preenchidos.

---

## Fase 2 — Operação base (A1) no ar

```powershell
# Health da API e documentação interativa
Invoke-RestMethod "http://$ALB/healthz"
Start-Process "http://$ALB/docs"     # abre o Swagger no navegador
```

**✅ Checkpoint:** `/healthz` retorna `{"status":"ok"}` e o Swagger abre com os
endpoints de users/restaurants/couriers/orders.

---

## Fase 3 — Gerar eventos (simulação) → camada analítica

A simulação roda **na EC2 load-tester** (via SSM): primeiro popula
users/restaurants/couriers, depois gera o ciclo de vida de pedidos.

```powershell
$env:SCENARIO = "normal"
python deploy.py simulate
```

O script imprime um link do **CloudWatch Logs** — acompanhe a simulação por lá.
Quando terminar, **aguarde ~5 min** (buffer do Firehose = 300s) para os eventos
caírem no S3.

```powershell
# Eventos brutos (JSON/GZIP) particionados por entidade
aws s3 ls "s3://$BUCKET/raw/service-dumps/" --recursive | Select-Object -First 30
```

**✅ Checkpoint:** aparecem objetos em
`raw/service-dumps/entidade=Order/...`, `entidade=Restaurant/...`,
`entidade=Position/...` etc. → **Firehose + outbox + CDC estão funcionando**.

---

## Fase 4 — Consultar o lake via Athena (Glue Catalog)

Abra o **console do Athena** (região us-east-1):
- Workgroup: `dijkfood-analytics`  ·  Database: `dijkfood_analytics`

Rode:
```sql
-- volume de eventos por tipo
SELECT entidade, acao, count(*) AS n
FROM events GROUP BY 1,2 ORDER BY n DESC;

-- pedidos criados
SELECT count(*) FROM events WHERE entidade='Order' AND acao='CREATE';
```

**✅ Checkpoint:** as queries retornam linhas (Order CREATE/UPDATE, Restaurant,
Courier, Position…). Se vier vazio, espere mais 1–2 min e repita (buffer).

---

## Fase 5 — Dashboard analítico (EC2)

```powershell
start $DASH      # abre http://<dns-da-ec2>
```
> Se a página não abrir de primeira, a EC2 ainda está puxando a imagem do ECR.
> Aguarde ~1–2 min após o deploy e recarregue. Para forçar:
> `python deploy.py update` (rebuild/push + refresh da EC2 via SSM).

**✅ Checkpoint:** o dashboard mostra os **6 indicadores** (volume no tempo, tempo
médio por estado, distribuição por região, heatmap demanda, top restaurantes,
histograma de entrega), os **KPIs** e as **2 métricas instantâneas** (pedidos
abertos por estado, entregadores ativos/disponíveis).

---

## Fase 6 — Capacidade preditiva (ETA)

```powershell
# 1) treina o modelo a partir do histórico no lake
Invoke-RestMethod -Method Post -Uri "http://$ALB/train/eta"

# 2) inspeciona o modelo (MAE do holdout vs. baseline, nº de amostras)
Invoke-RestMethod -Uri "http://$ALB/model/info"

# 3) predição de ETA sob demanda
Invoke-RestMethod -Method Post -Uri "http://$ALB/predict/eta" `
  -ContentType "application/json" -Body '{"id_restaurant": 1}'

# 4) ETA no momento do pedido (vem na resposta da criação)
Invoke-RestMethod -Method Post -Uri "http://$ALB/order" `
  -ContentType "application/json" -Body '{"id_user": 1, "id_restaurant": 1}'
```

**✅ Checkpoint:** `train/eta` retorna `status: trained` com métricas;
`predict/eta` retorna `eta_minutes` + `source: "model"`; a criação de pedido
retorna `eta_minutes` + `eta_source`.

> Observação: se `train/eta` responder 409 (amostras insuficientes), rode mais
> uma simulação (Fase 3) para acumular pedidos **entregues** e tente de novo.

---

## Fase 7 — Batch: demanda + anomalias

```powershell
# (a) GERA anomalias: o cenário 'anomaly' concentra a demanda numa região e
#     injeta entregas lentas nela (vira outlier de ETA detectado por MAD).
$env:SCENARIO="anomaly"; python deploy.py simulate
#     knobs opcionais: SLOW_DELIVERY_PCT, SLOW_DELIVERY_MIN_S/MAX_S, ANOMALY_REGION

# aguarde ~60-90 s (buffer do Firehose) para os eventos caírem no lake.

# (b) computa e materializa as previsões no S3 (o batch também roda sozinho a
#     cada BATCH_INTERVAL_SECONDS=300 s; aqui forçamos na hora)
Invoke-RestMethod -Method Post -Uri "http://$ALB/batch/run"

# lê as previsões
Invoke-RestMethod -Uri "http://$ALB/predict/demand"
Invoke-RestMethod -Uri "http://$ALB/predict/anomalies"

# confirma os arquivos no S3
aws s3 ls "s3://$BUCKET/predictions/" --recursive
```

**✅ Checkpoint:** `batch/run` retorna contagem de regiões/anomalias (> 0 após o
cenário `anomaly`); `predict/anomalies` lista `slow_deliveries` na região
afligida; e no **dashboard** (recarregue) o painel **"Camada Preditiva"** mostra
o forecast + cards de anomalias.

> Pico de demanda (z-score) precisa de série temporal: para demonstrá-lo numa
> janela curta, suba o prediction-service com `ANOMALY_BUCKET_MINUTES=5` (ou
> menor) e rode uma simulação mais longa.

---

## Fase 8 — ETL Glue: curated + marts (Parquet)

```powershell
# dispara o job de transformação
aws glue start-job-run --job-name dijkfood-build-marts --region us-east-1

# acompanha (rode algumas vezes até COMPLETED)
aws glue get-job-runs --job-name dijkfood-build-marts --region us-east-1 `
  --query "JobRuns[0].JobRunState" --output text

# quando COMPLETED, confirma o Parquet
aws s3 ls "s3://$BUCKET/curated/" --recursive | Select-Object -First 10
aws s3 ls "s3://$BUCKET/marts/"   --recursive | Select-Object -First 10
```

No Athena (mesmo workgroup/db):
```sql
SELECT * FROM curated_orders LIMIT 10;
SELECT * FROM mart_daily_volume ORDER BY day;
SELECT * FROM mart_top_restaurants ORDER BY orders DESC;
```

**✅ Checkpoint:** o job chega a `COMPLETED`, há arquivos `.parquet` em
`curated/` e `marts/`, e as tabelas `curated_*`/`mart_*` respondem no Athena.

---

## Fase 9 — Camada conversacional (fallback determinístico, sem Bedrock)

```powershell
start "http://$ALB/chat"      # UI de chat

# via API (o source mostra se foi Bedrock ou determinístico)
Invoke-RestMethod -Method Post -Uri "http://$ALB/chat/ask" `
  -ContentType "application/json" -Body '{"question":"qual o tempo medio de entrega?"}'

Invoke-RestMethod -Method Post -Uri "http://$ALB/chat/ask" `
  -ContentType "application/json" -Body '{"question":"top 5 restaurantes por volume"}'

Invoke-RestMethod -Method Post -Uri "http://$ALB/chat/ask" `
  -ContentType "application/json" -Body '{"question":"quantos pedidos na ultima hora"}'
```

**✅ Checkpoint:** as respostas trazem `answer`, `sql` e `rows`. Sem acesso ao
Bedrock, `source` vem como **"fallback"** (determinístico) — exatamente o esperado.
A UI mostra a resposta, o SQL gerado e uma tabela/gráfico.

---

## Fase 10 — Evidência de SLA (não-regressão) + cenários

```powershell
# carga de pico — relatório com P50/P95/P99 e taxa de erro nos logs (CloudWatch)
$env:SCENARIO = "peak"; python deploy.py simulate

# cenários operacionais parametrizáveis
$env:SCENARIO = "hotspot";       python deploy.py simulate   # concentra demanda numa região
$env:SCENARIO = "concentration"; python deploy.py simulate   # concentra em poucos restaurantes
$env:SCENARIO = "outage";        python deploy.py simulate   # reduz entregadores disponíveis
```

**✅ Checkpoint:** ao fim de cada simulação o relatório (no CloudWatch) mostra
`SLA GLOBAL` com **% sucesso, % erro e P50/P95/P99** (requisito P95 < 500 ms),
além da tabela por rota. Os cenários aparecem refletidos no dashboard
(ex.: heatmap/região mudando no `hotspot`).

---

## Fase 11 — (Opcional) Pipeline gerenciada SageMaker + Model Registry

> Pode falhar no Learner Lab se o treino SageMaker estiver restrito — a
> capacidade de ETA **já é garantida pelo ECS** (Fase 6). Isto é o "managed".

```powershell
$SM = terraform -chdir=infra\terraform output -raw ml_state_machine_arn
aws stepfunctions start-execution --state-machine-arn $SM --region us-east-1

# versões registradas no Model Registry
aws sagemaker list-model-packages --model-package-group-name dijkfood-eta --region us-east-1
```

**✅ Checkpoint (se permitido):** a execução do Step Functions completa e o
`list-model-packages` mostra ao menos uma versão.

---

## Encerramento

```powershell
python deploy.py destroy     # remove toda a infraestrutura
```

**✅ Checkpoint:** Terraform destrói os recursos (evita custo).
