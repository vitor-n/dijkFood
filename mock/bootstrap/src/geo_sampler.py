"""
GeoSampler — Amostragem geográfica ponderada por dados demográficos.
====================================================================

Gera coordenadas aleatórias dentro de São Paulo com probabilidade
proporcional à população de cada distrito (Censo 2022 / IBGE).

Opcionalmente, aplica um viés comercial para posicionar restaurantes
em distritos com maior atividade comercial.
"""

import json
import logging
import os
import random
from pathlib import Path
from typing import Optional

import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.prepared import prep

log = logging.getLogger(__name__)

# Caminho padrão do arquivo de dados dos distritos
_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "distritos_sp.json"
)


class District:
    """Representa um distrito de São Paulo com metadados demográficos."""

    __slots__ = (
        "nome",
        "populacao",
        "zona",
        "indice_comercial",
        "polygon",
        "_prepared",
        "bounds",
    )

    def __init__(self, feature: dict):
        props = feature["properties"]
        self.nome: str = props["nome"]
        self.populacao: int = int(props.get("populacao", 0))
        self.zona: str = props.get("zona", "")
        self.indice_comercial: float = float(props.get("indice_comercial", 0.5))
        self.polygon = shape(feature["geometry"])
        self._prepared = prep(self.polygon)
        self.bounds = self.polygon.bounds  # (minx, miny, maxx, maxy)

    def contains(self, point: Point) -> bool:
        """Verifica se o ponto está dentro do polígono (usa prepared geometry)."""
        return self._prepared.contains(point)


class GeoSampler:
    """
    Amostrador geográfico ponderado por população dos distritos de São Paulo.

    Uso básico:
        sampler = GeoSampler()
        coord = sampler.sample_coordinate()
        # coord = {"lat": -23.55, "lon": -46.63}

    Uso para restaurantes (com viés comercial):
        coord = sampler.sample_restaurant_coordinate()
    """

    def __init__(self, data_path: Optional[str] = None):
        self._data_path = data_path or _DEFAULT_DATA_PATH
        self._districts: list[District] = []
        self._pop_weights: list[float] = []
        self._commercial_weights: list[float] = []
        self._total_population: int = 0
        self._load_data()

    def _load_data(self):
        """Carrega os distritos do arquivo GeoJSON e pré-computa os pesos."""
        if not os.path.exists(self._data_path):
            raise FileNotFoundError(
                f"Arquivo de distritos não encontrado: {self._data_path}. "
                f"Execute scripts/prepare_geodata.py para gerá-lo."
            )

        with open(self._data_path, "r", encoding="utf-8") as f:
            geojson = json.load(f)

        for feature in geojson.get("features", []):
            try:
                district = District(feature)
                if district.populacao > 0:
                    self._districts.append(district)
            except Exception as e:
                nome = feature.get("properties", {}).get("nome", "?")
                log.warning(f"Erro ao carregar distrito '{nome}': {e}")

        if not self._districts:
            raise ValueError("Nenhum distrito válido encontrado no arquivo de dados.")

        self._total_population = sum(d.populacao for d in self._districts)

        # Pesos populacionais normalizados
        self._pop_weights = [
            d.populacao / self._total_population for d in self._districts
        ]

        # Pesos comerciais: combina população com índice comercial
        # Fórmula: peso = pop * (1 + indice_comercial * boost)
        # Isso desloca a distribuição em favor de áreas comerciais
        _COMMERCIAL_BOOST = 2.0
        raw_commercial = [
            d.populacao * (1.0 + d.indice_comercial * _COMMERCIAL_BOOST)
            for d in self._districts
        ]
        total_commercial = sum(raw_commercial)
        self._commercial_weights = [w / total_commercial for w in raw_commercial]

        log.info(
            f"GeoSampler carregado: {len(self._districts)} distritos, "
            f"população total = {self._total_population:,}"
        )

    def _sample_point_in_district(self, district: District) -> dict[str, float]:
        """Gera um ponto aleatório dentro do polígono do distrito via rejection sampling."""
        minx, miny, maxx, maxy = district.bounds
        for _ in range(1000):  # limite de tentativas (segurança)
            point = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
            if district.contains(point):
                return {"lat": point.y, "lon": point.x}
        # Fallback extremo: centroide do distrito
        centroid = district.polygon.centroid
        log.warning(
            f"Falha no rejection sampling para '{district.nome}'. "
            f"Usando centróide."
        )
        return {"lat": centroid.y, "lon": centroid.x}

    def sample_coordinate(self) -> dict[str, float]:
        """
        Amostra uma coordenada ponderada pela população do distrito.

        Returns:
            {"lat": float, "lon": float}
        """
        (district,) = random.choices(self._districts, weights=self._pop_weights, k=1)
        return self._sample_point_in_district(district)

    def sample_restaurant_coordinate(self) -> dict[str, float]:
        """
        Amostra uma coordenada com viés comercial (para posicionar restaurantes).
        Distritos com maior índice comercial têm peso elevado.

        Returns:
            {"lat": float, "lon": float}
        """
        (district,) = random.choices(
            self._districts, weights=self._commercial_weights, k=1
        )
        return self._sample_point_in_district(district)

    def sample_coordinates(self, n: int, use_commercial_weights: bool = False) -> list[dict[str, float]]:
        """
        Amostra N coordenadas de forma eficiente, distribuindo proporcionalmente
        pelos distritos em vez de sortear um por um.

        Args:
            n: Número de coordenadas a gerar.
            use_commercial_weights: Se True, usa pesos comerciais em vez de populacionais.

        Returns:
            Lista de {"lat": float, "lon": float}
        """
        weights = self._commercial_weights if use_commercial_weights else self._pop_weights

        # Aloca N pontos proporcionalmente pelos distritos
        allocation = [0] * len(self._districts)
        for i, w in enumerate(weights):
            allocation[i] = int(n * w)

        # Distribui pontos restantes (arredondamento) nos distritos de maior peso
        remainder = n - sum(allocation)
        if remainder > 0:
            # Sorteia os distritos para os pontos extras
            extras = random.choices(
                range(len(self._districts)), weights=weights, k=remainder
            )
            for idx in extras:
                allocation[idx] += 1

        # Gera os pontos
        coordinates = []
        for i, district in enumerate(self._districts):
            for _ in range(allocation[i]):
                coordinates.append(self._sample_point_in_district(district))

        random.shuffle(coordinates)
        return coordinates

    def get_district_for_coordinate(self, lat: float, lon: float) -> Optional[str]:
        """
        Retorna o nome do distrito para uma coordenada (point-in-polygon).

        Returns:
            Nome do distrito ou None se a coordenada não pertence a nenhum distrito.
        """
        point = Point(lon, lat)
        for district in self._districts:
            if district.contains(point):
                return district.nome
        return None

    @property
    def district_names(self) -> list[str]:
        """Lista com os nomes dos 96 distritos."""
        return [d.nome for d in self._districts]

    @property
    def population_distribution(self) -> dict[str, int]:
        """Dict {nome_distrito: populacao}."""
        return {d.nome: d.populacao for d in self._districts}

    @property
    def total_population(self) -> int:
        """População total de todos os distritos."""
        return self._total_population

    def __repr__(self) -> str:
        return (
            f"GeoSampler(districts={len(self._districts)}, "
            f"population={self._total_population:,})"
        )
