# Resultados experimentais — DijkFood (branch `improve-latency`)

Gerado em 2026-06-18T02:27:25.574398+00:00 · base-url `http://dijkfood-g3-dev-alb-365502577.us-east-1.elb.amazonaws.com`

## 1. Carga e latência

| Cenário | Criados | Concl. | Falhos | Sucesso % | P95 global | P95 /order | P95 /track | P95 /routes | Throughput | SLA |
|---|---|---|---|---|---|---|---|---|---|---|
| normal | 204 | 204 | 0 | 100.0 | 259.16010001674294ms | 565.7337500015274ms | 250.54002999095246ms | 177.18594998586923ms | 182.7/s | VIOLADO |
| peak | 981 | 970 | 11 | 99.89 | 2706.193920056103ms | 4753.830850007944ms | 2323.6877500545233ms | 234.06067996984348ms | 492.1/s | VIOLADO |
| event | 563 | 280 | 283 | 89.25 | 10263.624579971656ms | 19610.699499957263ms | 446.47760001244023ms | 188.3075200021267ms | 106.9/s | VIOLADO |

## 2. Camada analítica

- Order CREATE: **2993** · Order UPDATE: **10330** · Posições: **1753089**
- Total de eventos: **1785412** · status: **OK**
- Primeiro: 2026-06-18T01:36:43.495631+00:00 · Último: 2026-06-18T02:32:35.221393+00:00

## 3. Predição de ETA

- Modelo pronto: **False** · amostras treino: None · MAE: None min · baseline: None min
- Chamadas: 20 · ETA p95: 578.9ms · % modelo: 0.0% · % fallback: 100.0% · ETA médio: 35.0min

## 4. Resiliência

- Teste A (ETA normal): 4/5 pedidos criados · eta_source: {'fallback_constant': 4}
- Teste B (ETA indisponível): fallback_ok=**True** · pedido ainda criado: True

## Síntese

Cenários executados: normal, peak, event (taxa de sucesso mín. 89.2%). A disponibilidade funcional foi preservada, mas a meta estrita de P95 < 500 ms não foi atingida em todos os endpoints/cenários (normal, peak, event). O principal gargalo observado foi POST /order (P95 19611 ms no cenário event). A camada analítica recebeu 1785412 eventos operacionais (criação de pedidos, transições de estado e posições), confirmando a persistência. O ETA permaneceu integrado ao fluxo de pedidos, mas 100% das respostas usaram fallback — confirma resiliência operacional, embora indique que o modelo ainda precisa de maior disponibilidade/pré-carregamento. A criação de pedido não depende criticamente do modelo: sob ETA indisponível, o fluxo recai em fallback determinístico sem perder o pedido.
