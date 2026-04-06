**Variáveis de ambiente disponíveis:**

| Variável | Default | Descrição |
|---|---|---|
| `CORE_API_BASE_URL` | `http://localhost:8000` | URL da core-api |
| `ORDER_API_BASE_URL` | `http://localhost:8003` | URL do order-service |
| `TRACKING_API_BASE_URL` | `http://localhost:8002` | URL do tracking-service |
| `ORDERS_PER_SECOND` | `10` | Taxa de emissão de pedidos |
| `TOTAL_ORDERS` | *(vazio = ilimitado)* | Quantidade total de pedidos |
| `MAX_CONCURRENT_ORDERS` | `200` | Pedidos simultâneos máximos |
| `POSITION_REPORT_INTERVAL` | `0.1` | Intervalo de report de posição (s) |
| `DELAY_PREPARING_MIN/MAX` | `5` / `15` | Delay simulado para preparação |
| `DELAY_READY_MIN/MAX` | `5` / `10` | Delay simulado para ficar pronto |

**Uso para cada cenário do trabalho:**

```bash
# Build
docker build -t dijkfood-simulator .

# Operação normal (10 pedidos/s)
docker run -e API_BASE_URL=http://<endpoint> dijkfood-simulator

# Pico (50 pedidos/s)
docker run -e API_BASE_URL=http://<endpoint> -e ORDERS_PER_SECOND=50 dijkfood-simulator

# Evento especial (200 pedidos/s)
docker run -e API_BASE_URL=http://<endpoint> -e ORDERS_PER_SECOND=200 -e MAX_CONCURRENT_ORDERS=1000 dijkfood-simulator
```
