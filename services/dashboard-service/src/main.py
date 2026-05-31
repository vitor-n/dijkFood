"""
dashboard-service — dashboard analítico (Objetivo 3, camada obrigatória).

Serve os 6 indicadores mínimos consultando o Athena sobre a tabela canônica de
eventos (Parquet no data lake). Roteado pelo ALB em /dashboard*.
"""
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .athena import AthenaClient
from .queries import INDICATORS

app = FastAPI(title="DijkFood Dashboard Service")
athena = AthenaClient()


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.get("/dashboard/healthz", tags=["ops"])
async def healthz_prefixed():
    return {"status": "ok"}


@app.get("/dashboard/api/{indicator}", tags=["dashboard"])
async def get_indicator(indicator: str):
    sql = INDICATORS.get(indicator)
    if sql is None:
        raise HTTPException(status_code=404, detail=f"Indicador desconhecido: {indicator}")
    try:
        rows = await athena.query(indicator, sql)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no Athena: {exc}") from exc
    return {"indicator": indicator, "rows": rows}


@app.get("/dashboard/api", tags=["dashboard"])
async def get_all():
    """Executa os 6 indicadores em paralelo (threadpool)."""
    keys = list(INDICATORS.keys())
    results = await asyncio.gather(
        *[athena.query(k, INDICATORS[k]) for k in keys],
        return_exceptions=True,
    )
    out: dict[str, object] = {}
    for k, r in zip(keys, results):
        out[k] = {"error": str(r)} if isinstance(r, Exception) else r
    return JSONResponse(out)


@app.get("/dashboard", response_class=HTMLResponse, tags=["dashboard"])
@app.get("/dashboard/", response_class=HTMLResponse, tags=["dashboard"])
async def index():
    return HTMLResponse(_PAGE)


# ── Página única: carrega /dashboard/api e renderiza com Plotly (CDN) ──
_PAGE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DijkFood — Dashboard Analítico</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background:#0f1117; color:#e6e6e6; }
  header { padding: 16px 24px; background:#161a23; border-bottom:1px solid #262b36; }
  h1 { margin:0; font-size:20px; } .sub { color:#8a93a6; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(2,1fr); gap:16px; padding:16px; }
  .card { background:#161a23; border:1px solid #262b36; border-radius:10px; padding:8px; min-height:340px; }
  .card h2 { font-size:14px; margin:8px 12px; color:#cdd3df; }
  .err { color:#ff6b6b; padding:12px; font-size:13px; }
  @media (max-width:900px){ .grid{ grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>DijkFood — Dashboard Analítico</h1>
  <div class="sub">Objetivo 3 · indicadores agregados sobre o histórico da operação (Athena + data lake)</div>
</header>
<div class="grid">
  <div class="card"><h2>1 · Volume de pedidos no tempo</h2><div id="volume_over_time"></div></div>
  <div class="card"><h2>2 · Tempo médio em cada estado (s)</h2><div id="avg_time_per_state"></div></div>
  <div class="card"><h2>3 · Distribuição de pedidos por região (H3)</h2><div id="orders_by_region"></div></div>
  <div class="card"><h2>4 · Heatmap de demanda (hora × dia da semana)</h2><div id="demand_heatmap"></div></div>
  <div class="card"><h2>5 · Top 10 restaurantes por volume</h2><div id="top_restaurants"></div></div>
  <div class="card"><h2>6 · Histograma do tempo total de entrega (min)</h2><div id="delivery_time_histogram"></div></div>
</div>
<script>
const LAYOUT = { paper_bgcolor:'#161a23', plot_bgcolor:'#161a23', font:{color:'#cdd3df'},
                 margin:{t:10,r:10,b:40,l:50}, height:300 };
const DOW = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];

function err(id, msg){ document.getElementById(id).innerHTML = '<div class="err">'+msg+'</div>'; }

async function load(){
  let data;
  try { data = await (await fetch('/dashboard/api')).json(); }
  catch(e){ document.querySelectorAll('.card div[id]').forEach(d=>err(d.id,'Falha ao carregar.')); return; }

  for (const k in data){ if (data[k] && data[k].error){ err(k, 'Sem dados / erro: '+data[k].error); } }

  // 1 — volume no tempo
  let r = data.volume_over_time;
  if (Array.isArray(r)) Plotly.newPlot('volume_over_time',
    [{x:r.map(x=>x.bucket), y:r.map(x=>+x.n), type:'scatter', mode:'lines', line:{color:'#4dabf7'}}], LAYOUT, {displayModeBar:false});

  // 2 — tempo médio por estado
  r = data.avg_time_per_state;
  if (Array.isArray(r)) Plotly.newPlot('avg_time_per_state',
    [{x:r.map(x=>x.state_name), y:r.map(x=>+x.avg_seconds), type:'bar', marker:{color:'#69db7c'}}], LAYOUT, {displayModeBar:false});

  // 3 — por região
  r = data.orders_by_region;
  if (Array.isArray(r)) Plotly.newPlot('orders_by_region',
    [{x:r.map(x=>x.h3_cell), y:r.map(x=>+x.n), type:'bar', marker:{color:'#ffa94d'}}], {...LAYOUT, xaxis:{showticklabels:false}}, {displayModeBar:false});

  // 4 — heatmap hora x dia
  r = data.demand_heatmap;
  if (Array.isArray(r)){
    const z = Array.from({length:7}, ()=>Array(24).fill(0));
    r.forEach(x=>{ const d=(+x.dow)-1, h=+x.hr; if(d>=0&&d<7&&h>=0&&h<24) z[d][h]=+x.n; });
    Plotly.newPlot('demand_heatmap',
      [{z, x:[...Array(24).keys()], y:DOW, type:'heatmap', colorscale:'YlOrRd'}], LAYOUT, {displayModeBar:false});
  }

  // 5 — top restaurantes
  r = data.top_restaurants;
  if (Array.isArray(r)) Plotly.newPlot('top_restaurants',
    [{x:r.map(x=>+x.n), y:r.map(x=>'Rest '+x.restaurant_id), type:'bar', orientation:'h', marker:{color:'#da77f2'}}],
    {...LAYOUT, yaxis:{autorange:'reversed'}}, {displayModeBar:false});

  // 6 — histograma tempo total
  r = data.delivery_time_histogram;
  if (Array.isArray(r)) Plotly.newPlot('delivery_time_histogram',
    [{x:r.map(x=>+x.minute_bucket), y:r.map(x=>+x.n), type:'bar', marker:{color:'#4dabf7'}}], LAYOUT, {displayModeBar:false});
}
load();
setInterval(load, 60000);
</script>
</body>
</html>"""
