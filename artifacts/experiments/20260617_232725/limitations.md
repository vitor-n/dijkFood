# Limitações e falhas registradas

- **resilience**: Teste B reproduz a lógica de fallback do order-service contra endpoint inalcançável (a env var PREDICTION_SERVICE_ENDPOINT do serviço implantado não pode ser trocada em runtime sem redeploy). O Teste A é a evidência end-to-end de que pedidos são criados com eta_source registrado.
