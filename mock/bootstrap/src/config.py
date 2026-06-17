import os
import sys
import logging
from enum import Enum
from dataclasses import dataclass
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("simulator")
log.addHandler(logging.StreamHandler(sys.stdout))

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
load_dotenv()
BASE_URL = os.getenv("BASE_URL", "")
if BASE_URL == "":
    CRUD_URL      = os.getenv("CRUD_URL",      "http://localhost:8000")
    ORDER_URL     = os.getenv("ORDER_URL",     "http://localhost:8001")
    TRACKING_URL  = os.getenv("TRACKING_URL",  "http://localhost:8002")
    ROUTE_URL     = os.getenv("ROUTE_URL",     "http://localhost:8003")
else:
    CRUD_URL      = BASE_URL
    ORDER_URL     = BASE_URL
    TRACKING_URL  = BASE_URL
    ROUTE_URL     = BASE_URL

# Amostragem geográfica: se True, usa dados demográficos dos distritos de SP
USE_DEMOGRAPHIC_SAMPLING = os.getenv(
    "USE_DEMOGRAPHIC_SAMPLING", "true"
).lower() in ("true", "1", "yes")

class OrderState(int, Enum):
    CONFIRMED        = 1
    PREPARING        = 2
    READY_FOR_PICKUP = 3
    PICKED_UP        = 4
    IN_TRANSIT       = 5
    DELIVERED        = 6

SILENT = os.getenv("SILENT", "false").lower() in ("true", "1", "yes")
PLOT_METRICS = os.getenv("PLOT_METRICS", "0").lower() in ("true", "1", "yes")

@dataclass
class SimConfig:
    scenario: str = os.getenv("SCENARIO", "testing")
    orders_per_second: float = float(os.getenv("SIM_ORDERS_PER_SECOND", 0.0))
    duration_seconds: int = int(os.getenv("SIM_DURATION", 10))
    position_report_interval: float = float(os.getenv("POSITION_INTERVAL", 0.1)) # 100ms exigido
    delay_preparing_min: float = float(os.getenv("DELAY_PREPARING_MIN", 5.0))
    delay_preparing_max: float = float(os.getenv("DELAY_PREPARING_MAX", 10.0))
    delay_ready_min: float = float(os.getenv("DELAY_READY_MIN", 5.0))
    delay_ready_max: float = float(os.getenv("DELAY_READY_MAX", 10.0))
    tracking_lifetime: float = float(os.getenv("TRACKING_LIFETIME", 5.0))
    max_concurrent_orders: int = int(os.getenv("SIM_CONCURRENCY", 1000))
    max_retries: int = int(os.getenv("SIM_MAX_RETRIES", 5))
    silent: bool = SILENT
    plot_metrics: bool = PLOT_METRICS

    # - Cenários operacionais parametrizáveis (A2) -
    # Concentração de demanda numa região (célula H3 do restaurante).
    hotspot_region: str = os.getenv("HOTSPOT_REGION", "")
    hotspot_weight: float = float(os.getenv("HOTSPOT_WEIGHT", 0.0))  # fração de pedidos direcionados à região
    # Concentração de pedidos em poucos restaurantes "quentes".
    restaurant_concentration: float = float(os.getenv("RESTAURANT_CONCENTRATION", 0.0))  # fração de pedidos
    hot_restaurant_count: int = int(os.getenv("HOT_RESTAURANT_COUNT", 5))
    # Redução temporária da disponibilidade de entregadores.
    courier_outage_pct: float = float(os.getenv("COURIER_OUTAGE_PCT", 0.0))  # 0..1

    # - Injeção de ANOMALIAS operacionais (A2) -
    # Fração dos pedidos de uma região "afligida" que recebem atraso injetado
    # antes da entrega → vira outlier de ETA (MAD) detectável pela camada
    # preditiva e exibido no dashboard. Concentra a demanda nessa região para
    # também estressar o pico de demanda.
    slow_delivery_pct: float = float(os.getenv("SLOW_DELIVERY_PCT", 0.0))      # 0..1
    slow_delivery_min_s: float = float(os.getenv("SLOW_DELIVERY_MIN_S", 90.0))  # atraso extra mín.
    slow_delivery_max_s: float = float(os.getenv("SLOW_DELIVERY_MAX_S", 180.0)) # atraso extra máx.
    anomaly_region: str = os.getenv("ANOMALY_REGION", "")  # H3 alvo; vazio = auto

    def __post_init__(self):
        # Cenários de volume (A1) + presets de cenário operacional (A2).
        scenarios_mapping = {
            "testing": 5.0,
            "normal": 10.0,
            "peak": 50.0,
            "event": 200.0,
            # presets A2 — herdam volume "peak" e ligam o respectivo knob
            "hotspot": 50.0,
            "concentration": 50.0,
            "outage": 50.0,
            "anomaly": 50.0,
        }
        mapped_rps = scenarios_mapping.get(self.scenario)
        if self.orders_per_second <= 0.0:
            self.orders_per_second = mapped_rps if mapped_rps is not None else 10.0

        # Presets convenientes: ativam o knob se o usuário não o definiu explicitamente.
        if self.scenario == "hotspot" and self.hotspot_weight == 0.0:
            self.hotspot_weight = 0.7
        if self.scenario == "concentration" and self.restaurant_concentration == 0.0:
            self.restaurant_concentration = 0.8
        if self.scenario == "outage" and self.courier_outage_pct == 0.0:
            self.courier_outage_pct = 0.6
        if self.scenario == "anomaly" and self.slow_delivery_pct == 0.0:
            self.slow_delivery_pct = 0.35
