"""Testes da lógica de cenários do simulador (sem rede)."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mock", "bootstrap", "src"))

# Stub `utils` (depende de shapely/geo) — não é necessário para a lógica de cenários.
_fake_utils = types.ModuleType("utils")
_fake_utils.get_random_sp_coordinate = lambda *a, **k: (-23.55, -46.63)
sys.modules["utils"] = _fake_utils

import simulator as S  # noqa: E402


def test_scenario_presets():
    cfg = S.SimConfig(scenario="hotspot")
    assert cfg.orders_per_second == 50.0 and cfg.hotspot_weight > 0
    cfg = S.SimConfig(scenario="concentration")
    assert cfg.restaurant_concentration > 0
    cfg = S.SimConfig(scenario="outage")
    assert cfg.courier_outage_pct > 0


def test_hotspot_weighting():
    meta = [{"id": i, "h3": 100 if i < 3 else 200} for i in range(10)]
    cfg = S.SimConfig()
    cfg.hotspot_region = "100"
    cfg.hotspot_weight = 0.7
    cfg.restaurant_concentration = 0.0
    pop, w = S.build_restaurant_population(meta, cfg)
    assert len(pop) == 10 and abs(sum(w) - 1.0) < 1e-6
    mass_target = sum(w[i] for i, m in enumerate(meta) if str(m["h3"]) == "100")
    assert abs(mass_target - 0.7) < 1e-6


def test_concentration_weighting():
    meta = [{"id": i, "h3": None} for i in range(20)]
    cfg = S.SimConfig()
    cfg.hotspot_region = ""
    cfg.restaurant_concentration = 0.8
    cfg.hot_restaurant_count = 4
    pop, w = S.build_restaurant_population(meta, cfg)
    assert abs(sum(w) - 1.0) < 1e-6
    # os 4 mais quentes concentram ~0.8
    top4 = sum(sorted(w, reverse=True)[:4])
    assert abs(top4 - 0.8) < 1e-6


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  [ok] " + name)
    print("test_simulator OK")
