import os
import time
import random
import argparse
import requests
import statistics

# Coordenadas aproximadas de São Paulo para evitar gerar pontos no meio do oceano,
# o que causaria muitos erros 422 (rota não encontrada) do OSRM.
MIN_LAT = -23.65
MAX_LAT = -23.45
MIN_LON = -46.80
MAX_LON = -46.50

def get_random_coordinate():
    lat = random.uniform(MIN_LAT, MAX_LAT)
    lon = random.uniform(MIN_LON, MAX_LON)
    return lat, lon

def run_unit_tests(base_url):
    print("--- Executando Testes Unitários Básicos ---")
    
    # Teste 1: Healthcheck
    try:
        r = requests.get(f"{base_url}/routes/healthz", timeout=5)
        assert r.status_code == 200, f"Healthcheck falhou com status {r.status_code}"
        print("✓ Healthcheck: OK")
    except Exception as e:
        print(f"✗ Healthcheck falhou: {e}")

    # Teste 2: Cálculo de rota válido
    # Centro de SP a Av. Paulista, por exemplo
    orig_lat, orig_lon = -23.5505, -46.6333
    dest_lat, dest_lon = -23.5615, -46.6560
    payload = {
        "orig_lat": orig_lat,
        "orig_lon": orig_lon,
        "dest_lat": dest_lat,
        "dest_lon": dest_lon
    }
    
    try:
        r = requests.post(f"{base_url}/routes/calculate", json=payload, timeout=10)
        assert r.status_code == 200, f"Cálculo de rota falhou com status {r.status_code}. Response: {r.text}"
        data = r.json()
        assert "distance_meters" in data, "Faltando distance_meters na resposta"
        assert "estimated_time_seconds" in data, "Faltando estimated_time_seconds na resposta"
        assert "path_nodes" in data, "Faltando path_nodes na resposta"
        print("✓ Cálculo de rota válido: OK")
    except Exception as e:
        print(f"✗ Cálculo de rota válido falhou: {e}")

def run_load_test(base_url, num_requests):
    print(f"\n--- Executando Teste de Carga/Latência ({num_requests} requisições sequenciais) ---")
    latencies = []
    success_count = 0
    error_count = 0

    for i in range(num_requests):
        orig_lat, orig_lon = get_random_coordinate()
        dest_lat, dest_lon = get_random_coordinate()
        payload = {
            "orig_lat": orig_lat,
            "orig_lon": orig_lon,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon
        }
        
        start_time = time.time()
        try:
            r = requests.post(f"{base_url}/routes/calculate", json=payload, timeout=10)
            latency = (time.time() - start_time) * 1000  # em ms
            
            if r.status_code == 200:
                success_count += 1
                latencies.append(latency)
                print(f"[{i+1}/{num_requests}] Sucesso ({latency:.0f}ms). Conteúdo da resposta:")
                # print(r.text)
                # print("-" * 40)
            else:
                error_count += 1
        except Exception as e:
            error_count += 1
    
    print(f"Requisições bem sucedidas: {success_count}")
    print(f"Requisições com erro (ex: 422 sem rota ou falha): {error_count}")
    
    if latencies:
        latencies.sort()
        mean_lat = statistics.mean(latencies)
        
        def percentile(data, p):
            k = (len(data) - 1) * (p / 100.0)
            f = int(k)
            c = f + 1
            if f == c or c >= len(data):
                return data[f]
            return data[f] + (data[c] - data[f]) * (k - f)

        p50 = percentile(latencies, 50)
        p90 = percentile(latencies, 90)
        p95 = percentile(latencies, 95)
        p99 = percentile(latencies, 99)

        print("\n--- Resultados de Latência (ms) ---")
        print(f"Média: {mean_lat:.2f} ms")
        print(f"p50:   {p50:.2f} ms")
        print(f"p90:   {p90:.2f} ms")
        print(f"p95:   {p95:.2f} ms")
        print(f"p99:   {p99:.2f} ms")
    else:
        print("\nNenhuma requisição bem sucedida para calcular latência.")

def main():
    parser = argparse.ArgumentParser(description="Testa o serviço de routing.")
    parser.add_argument("--url", type=str, default="http://localhost:8000", help="URL base do Routing Service (ex: https://meu-routing-cloud.com)")
    parser.add_argument("--requests", type=int, default=50, help="Número de requisições aleatórias em sequência")
    
    args = parser.parse_args()
    
    print(f"Testando URL: {args.url}")
    run_unit_tests(args.url)
    run_load_test(args.url, args.requests)

if __name__ == "__main__":
    main()
