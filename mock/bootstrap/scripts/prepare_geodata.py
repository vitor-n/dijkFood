#!/usr/bin/env python3
"""
Geodata preparation pipeline for São Paulo's 96 districts.

Downloads GeoJSON geometry from public sources, merges with hardcoded
IBGE Census 2022 population data, zone classification, and commercial
indices, simplifies geometries, and outputs a compact JSON file.

Output: mock/bootstrap/src/data/distritos_sp.json
"""

import json
import os
import sys
import requests
from shapely.geometry import shape, mapping
from shapely import wkt

# ──────────────────────────────────────────────────────────────────────
# IBGE Census 2022 population data for all 96 districts of São Paulo
# Source: https://pt.wikipedia.org/wiki/Lista_dos_distritos_de_São_Paulo_por_população
# ──────────────────────────────────────────────────────────────────────

POPULATION_DATA = {
    "Grajaú": 384873,
    "Jardim Ângela": 311432,
    "Capão Redondo": 270767,
    "Sapopemba": 266715,
    "Sacomã": 261436,
    "Jardim São Luís": 259377,
    "Cidade Ademar": 249218,
    "Brasilândia": 243273,
    "Campo Limpo": 236162,
    "Jabaquara": 214982,
    "Jaraguá": 211617,
    "Itaquera": 210960,
    "Itaim Paulista": 205295,
    "Tremembé": 196563,
    "Cidade Tiradentes": 194177,
    "Cidade Dutra": 182459,
    "Pirituba": 179724,
    "Vila Andrade": 168669,
    "Lajeado": 164391,
    "Pedreira": 163586,
    "São Mateus": 155682,
    "Parelheiros": 153687,
    "Iguatemi": 149700,
    "São Rafael": 148145,
    "Cachoeirinha": 143366,
    "Cangaíba": 141172,
    "Vila Curuçá": 140673,
    "São Lucas": 138038,
    "Freguesia do Ó": 137240,
    "Cidade Líder": 136660,
    "Vila Jacuí": 134189,
    "Penha": 132452,
    "Rio Pequeno": 131631,
    "Jardim Helena": 129409,
    "Saúde": 128469,
    "José Bonifácio": 128243,
    "Vila Mariana": 127286,
    "Vila Sônia": 123748,
    "Raposo Tavares": 117738,
    "Ipiranga": 116271,
    "Campo Grande": 115925,
    "Santana": 115689,
    "Vila Medeiros": 114939,
    "Ermelino Matarazzo": 112333,
    "Guaianases": 109316,
    "Vila Maria": 108543,
    "Vila Prudente": 105690,
    "Mandaqui": 103665,
    "Vila Matilde": 103558,
    "Cursino": 103171,
    "Perdizes": 102391,
    "Itaim Bibi": 101452,
    "Tucuruvi": 99559,
    "Tatuapé": 98601,
    "Artur Alvim": 95575,
    "Vila Formosa": 92186,
    "Ponte Rasa": 89881,
    "Aricanduva": 89574,
    "São Domingos": 88884,
    "Perus": 87716,
    "Jaçanã": 87329,
    "Água Rasa": 85788,
    "Santo Amaro": 85349,
    "Carrão": 84397,
    "Limão": 82373,
    "Moema": 81899,
    "Jardim Paulista": 81859,
    "São Miguel": 81011,
    "Santa Cecília": 80972,
    "Mooca": 80880,
    "Casa Verde": 80536,
    "Lapa": 75533,
    "Anhanguera": 75360,
    "Parque do Carmo": 74677,
    "Campo Belo": 71034,
    "Liberdade": 66056,
    "Pinheiros": 65145,
    "República": 60825,
    "Bela Vista": 60024,
    "Belém": 55785,
    "Jaguaré": 55382,
    "Consolação": 53144,
    "Vila Guilherme": 52587,
    "Butantã": 51715,
    "Vila Leopoldina": 46875,
    "Cambuci": 45163,
    "Morumbi": 43690,
    "Brás": 38750,
    "Socorro": 38051,
    "Alto de Pinheiros": 37359,
    "Bom Retiro": 33520,
    "Barra Funda": 33436,
    "Jaguara": 24730,
    "Sé": 23832,
    "Pari": 17359,
    "Marsilac": 11451,
}

# ──────────────────────────────────────────────────────────────────────
# Zone classification for each district
# Norte, Sul, Leste, Oeste, Centro
# ──────────────────────────────────────────────────────────────────────

ZONE_DATA = {
    # Centro
    "Sé": "Centro",
    "República": "Centro",
    "Bela Vista": "Centro",
    "Liberdade": "Centro",
    "Santa Cecília": "Centro",
    "Consolação": "Centro",
    "Bom Retiro": "Centro",
    "Cambuci": "Centro",
    "Brás": "Centro",
    "Pari": "Centro",
    "Barra Funda": "Centro",
    # Norte
    "Brasilândia": "Norte",
    "Cachoeirinha": "Norte",
    "Casa Verde": "Norte",
    "Limão": "Norte",
    "Freguesia do Ó": "Norte",
    "Jaraguá": "Norte",
    "Pirituba": "Norte",
    "São Domingos": "Norte",
    "Perus": "Norte",
    "Anhanguera": "Norte",
    "Tremembé": "Norte",
    "Jaçanã": "Norte",
    "Mandaqui": "Norte",
    "Santana": "Norte",
    "Tucuruvi": "Norte",
    "Vila Guilherme": "Norte",
    "Vila Maria": "Norte",
    "Vila Medeiros": "Norte",
    # Sul
    "Campo Belo": "Sul",
    "Campo Grande": "Sul",
    "Campo Limpo": "Sul",
    "Capão Redondo": "Sul",
    "Cidade Ademar": "Sul",
    "Cidade Dutra": "Sul",
    "Grajaú": "Sul",
    "Jabaquara": "Sul",
    "Jardim Ângela": "Sul",
    "Jardim São Luís": "Sul",
    "Marsilac": "Sul",
    "Parelheiros": "Sul",
    "Pedreira": "Sul",
    "Santo Amaro": "Sul",
    "Socorro": "Sul",
    "Vila Andrade": "Sul",
    "Cursino": "Sul",
    "Ipiranga": "Sul",
    "Sacomã": "Sul",
    "Saúde": "Sul",
    "Moema": "Sul",
    "Vila Mariana": "Sul",
    "Jardim Paulista": "Sul",
    "Morumbi": "Sul",
    "Vila Sônia": "Sul",
    # Leste
    "Aricanduva": "Leste",
    "Artur Alvim": "Leste",
    "Cangaíba": "Leste",
    "Carrão": "Leste",
    "Cidade Líder": "Leste",
    "Cidade Tiradentes": "Leste",
    "Ermelino Matarazzo": "Leste",
    "Guaianases": "Leste",
    "Iguatemi": "Leste",
    "Itaim Paulista": "Leste",
    "Itaquera": "Leste",
    "Jardim Helena": "Leste",
    "José Bonifácio": "Leste",
    "Lajeado": "Leste",
    "Parque do Carmo": "Leste",
    "Penha": "Leste",
    "Ponte Rasa": "Leste",
    "São Lucas": "Leste",
    "São Mateus": "Leste",
    "São Miguel": "Leste",
    "São Rafael": "Leste",
    "Sapopemba": "Leste",
    "Tatuapé": "Leste",
    "Vila Curuçá": "Leste",
    "Vila Formosa": "Leste",
    "Vila Jacuí": "Leste",
    "Vila Matilde": "Leste",
    "Vila Prudente": "Leste",
    "Água Rasa": "Leste",
    "Belém": "Leste",
    "Mooca": "Leste",
    # Oeste
    "Alto de Pinheiros": "Oeste",
    "Butantã": "Oeste",
    "Itaim Bibi": "Oeste",
    "Jaguara": "Oeste",
    "Jaguaré": "Oeste",
    "Lapa": "Oeste",
    "Perdizes": "Oeste",
    "Pinheiros": "Oeste",
    "Raposo Tavares": "Oeste",
    "Rio Pequeno": "Oeste",
    "Vila Leopoldina": "Oeste",
}

# ──────────────────────────────────────────────────────────────────────
# Commercial index (0.0 to 1.0) — rough estimate for restaurant density weighting
# Higher values = more commercial activity / business districts
# Lower values = more residential / peripheral areas
# ──────────────────────────────────────────────────────────────────────

COMMERCIAL_INDEX = {
    # Centro — highest commercial density
    "Sé": 0.95,
    "República": 0.92,
    "Bela Vista": 0.80,
    "Liberdade": 0.82,
    "Santa Cecília": 0.75,
    "Consolação": 0.85,
    "Bom Retiro": 0.70,
    "Cambuci": 0.50,
    "Brás": 0.72,
    "Pari": 0.45,
    "Barra Funda": 0.68,
    # Oeste — high-end commercial/business
    "Itaim Bibi": 0.93,
    "Pinheiros": 0.90,
    "Jardim Paulista": 0.88,
    "Perdizes": 0.72,
    "Lapa": 0.65,
    "Alto de Pinheiros": 0.55,
    "Vila Leopoldina": 0.58,
    "Butantã": 0.50,
    "Jaguaré": 0.40,
    "Jaguara": 0.30,
    "Raposo Tavares": 0.30,
    "Rio Pequeno": 0.35,
    # Sul — mixed
    "Vila Mariana": 0.82,
    "Moema": 0.88,
    "Saúde": 0.60,
    "Cursino": 0.45,
    "Ipiranga": 0.50,
    "Sacomã": 0.38,
    "Jabaquara": 0.42,
    "Santo Amaro": 0.65,
    "Campo Belo": 0.62,
    "Vila Andrade": 0.45,
    "Morumbi": 0.55,
    "Vila Sônia": 0.40,
    "Campo Limpo": 0.32,
    "Capão Redondo": 0.22,
    "Jardim São Luís": 0.25,
    "Jardim Ângela": 0.15,
    "Cidade Ademar": 0.30,
    "Cidade Dutra": 0.28,
    "Pedreira": 0.25,
    "Campo Grande": 0.28,
    "Grajaú": 0.15,
    "Parelheiros": 0.10,
    "Marsilac": 0.05,
    "Socorro": 0.30,
    # Norte — mixed
    "Santana": 0.68,
    "Tucuruvi": 0.55,
    "Mandaqui": 0.42,
    "Tremembé": 0.28,
    "Jaçanã": 0.30,
    "Vila Guilherme": 0.45,
    "Vila Maria": 0.38,
    "Vila Medeiros": 0.32,
    "Casa Verde": 0.45,
    "Limão": 0.35,
    "Freguesia do Ó": 0.40,
    "Brasilândia": 0.20,
    "Cachoeirinha": 0.28,
    "Pirituba": 0.40,
    "São Domingos": 0.35,
    "Jaraguá": 0.22,
    "Perus": 0.20,
    "Anhanguera": 0.15,
    # Leste — mixed
    "Tatuapé": 0.72,
    "Mooca": 0.65,
    "Belém": 0.50,
    "Água Rasa": 0.45,
    "Vila Prudente": 0.42,
    "São Lucas": 0.35,
    "Sapopemba": 0.28,
    "Vila Formosa": 0.40,
    "Carrão": 0.45,
    "Aricanduva": 0.35,
    "Penha": 0.48,
    "Vila Matilde": 0.38,
    "Artur Alvim": 0.30,
    "Cangaíba": 0.28,
    "Ermelino Matarazzo": 0.30,
    "Ponte Rasa": 0.30,
    "Itaquera": 0.38,
    "Cidade Líder": 0.30,
    "José Bonifácio": 0.28,
    "Parque do Carmo": 0.25,
    "Guaianases": 0.25,
    "Lajeado": 0.20,
    "Cidade Tiradentes": 0.18,
    "Iguatemi": 0.20,
    "São Mateus": 0.32,
    "São Rafael": 0.22,
    "Itaim Paulista": 0.25,
    "Vila Curuçá": 0.25,
    "Vila Jacuí": 0.22,
    "Jardim Helena": 0.20,
    "São Miguel": 0.30,
}


# ──────────────────────────────────────────────────────────────────────
# GeoJSON download sources (in order of preference)
# ──────────────────────────────────────────────────────────────────────

GEOJSON_URLS = [
    "https://raw.githubusercontent.com/codigourbano/distritos-sp/master/distritos.geojson",
    "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-35-mun-3550308-distritos.json",
]

# Local file fallback paths (checked if remote download fails)
LOCAL_GEOJSON_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "distritos-sp.geojson"),
    os.path.expanduser("~/Downloads/distritos-sp.geojson"),
    os.path.expanduser("~/Downloads/distritos.geojson"),
]


def download_geojson():
    """Try multiple sources for the GeoJSON file: remote URLs first, then local files."""
    # Try remote URLs
    for url in GEOJSON_URLS:
        print(f"Trying to download GeoJSON from: {url}")
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✓ Downloaded successfully ({len(resp.content)} bytes)")
                return data
            else:
                print(f"  ✗ HTTP {resp.status_code}")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    # Try local file paths as fallback
    print("\nTrying local file paths...")
    for path in LOCAL_GEOJSON_PATHS:
        print(f"  Checking: {path}")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"  ✓ Loaded from local file ({os.path.getsize(path):,} bytes)")
                return data
            except Exception as e:
                print(f"  ✗ Error reading file: {e}")

    return None


def normalize_name(name):
    """Normalize district names for matching between GeoJSON and our data."""
    import unicodedata

    # Common name mappings from GeoJSON sources to our canonical names
    name_map = {
        "AGUA RASA": "Água Rasa",
        "ALTO DE PINHEIROS": "Alto de Pinheiros",
        "ANHANGUERA": "Anhanguera",
        "ARICANDUVA": "Aricanduva",
        "ARTUR ALVIM": "Artur Alvim",
        "BARRA FUNDA": "Barra Funda",
        "BELA VISTA": "Bela Vista",
        "BELEM": "Belém",
        "BOM RETIRO": "Bom Retiro",
        "BRASILANDIA": "Brasilândia",
        "BRAS": "Brás",
        "BUTANTA": "Butantã",
        "CACHOEIRINHA": "Cachoeirinha",
        "CAMBUCI": "Cambuci",
        "CAMPO BELO": "Campo Belo",
        "CAMPO GRANDE": "Campo Grande",
        "CAMPO LIMPO": "Campo Limpo",
        "CANGAIBA": "Cangaíba",
        "CAPAO REDONDO": "Capão Redondo",
        "CARRAO": "Carrão",
        "CASA VERDE": "Casa Verde",
        "CIDADE ADEMAR": "Cidade Ademar",
        "CIDADE DUTRA": "Cidade Dutra",
        "CIDADE LIDER": "Cidade Líder",
        "CIDADE TIRADENTES": "Cidade Tiradentes",
        "CONSOLACAO": "Consolação",
        "CURSINO": "Cursino",
        "ERMELINO MATARAZZO": "Ermelino Matarazzo",
        "FREGUESIA DO O": "Freguesia do Ó",
        "GRAJAU": "Grajaú",
        "GUAIANASES": "Guaianases",
        "IGUATEMI": "Iguatemi",
        "IPIRANGA": "Ipiranga",
        "ITAIM BIBI": "Itaim Bibi",
        "ITAIM PAULISTA": "Itaim Paulista",
        "ITAQUERA": "Itaquera",
        "JABAQUARA": "Jabaquara",
        "JACANA": "Jaçanã",
        "JAGUARA": "Jaguara",
        "JAGUARE": "Jaguaré",
        "JARAGUA": "Jaraguá",
        "JARDIM ANGELA": "Jardim Ângela",
        "JARDIM HELENA": "Jardim Helena",
        "JARDIM PAULISTA": "Jardim Paulista",
        "JARDIM SAO LUIS": "Jardim São Luís",
        "JOSE BONIFACIO": "José Bonifácio",
        "LAJEADO": "Lajeado",
        "LAPA": "Lapa",
        "LIBERDADE": "Liberdade",
        "LIMAO": "Limão",
        "MANDAQUI": "Mandaqui",
        "MARSILAC": "Marsilac",
        "MOEMA": "Moema",
        "MOOCA": "Mooca",
        "MORUMBI": "Morumbi",
        "PARELHEIROS": "Parelheiros",
        "PARI": "Pari",
        "PARQUE DO CARMO": "Parque do Carmo",
        "PEDREIRA": "Pedreira",
        "PENHA": "Penha",
        "PERDIZES": "Perdizes",
        "PERUS": "Perus",
        "PINHEIROS": "Pinheiros",
        "PIRITUBA": "Pirituba",
        "PONTE RASA": "Ponte Rasa",
        "RAPOSO TAVARES": "Raposo Tavares",
        "REPUBLICA": "República",
        "RIO PEQUENO": "Rio Pequeno",
        "SACOMÃ": "Sacomã",
        "SACOMA": "Sacomã",
        "SANTA CECILIA": "Santa Cecília",
        "SANTANA": "Santana",
        "SANTO AMARO": "Santo Amaro",
        "SAO DOMINGOS": "São Domingos",
        "SAO LUCAS": "São Lucas",
        "SAO MATEUS": "São Mateus",
        "SAO MIGUEL": "São Miguel",
        "SAO MIGUEL PAULISTA": "São Miguel",
        "SAO RAFAEL": "São Rafael",
        "SAPOPEMBA": "Sapopemba",
        "SAUDE": "Saúde",
        "SE": "Sé",
        "SOCORRO": "Socorro",
        "TATUAPE": "Tatuapé",
        "TREMEMBE": "Tremembé",
        "TUCURUVI": "Tucuruvi",
        "VILA ANDRADE": "Vila Andrade",
        "VILA CURUCA": "Vila Curuçá",
        "VILA FORMOSA": "Vila Formosa",
        "VILA GUILHERME": "Vila Guilherme",
        "VILA JACUI": "Vila Jacuí",
        "VILA LEOPOLDINA": "Vila Leopoldina",
        "VILA MARIA": "Vila Maria",
        "VILA MARIANA": "Vila Mariana",
        "VILA MATILDE": "Vila Matilde",
        "VILA MEDEIROS": "Vila Medeiros",
        "VILA PRUDENTE": "Vila Prudente",
        "VILA SONIA": "Vila Sônia",
    }

    # Strip and normalize
    name = name.strip()

    # Try direct lookup in our data
    if name in POPULATION_DATA:
        return name

    # Normalize: remove accents and uppercase for matching
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_upper = "".join(c for c in nfkd if not unicodedata.combining(c)).upper()

    if ascii_upper in name_map:
        return name_map[ascii_upper]

    # Try title case
    title = name.title()
    if title in POPULATION_DATA:
        return title

    return None


def extract_district_name(properties):
    """Extract the district name from GeoJSON feature properties."""
    # Try common property names for district name
    for key in ["NOME_DIST", "nome_dist", "nome", "NOME", "name", "NAME",
                 "NM_DISTRIT", "nm_distrit", "NM_DIST", "nm_dist",
                 "ds_nome", "DS_NOME", "NOME_DISTR", "nome_distr"]:
        if key in properties and properties[key]:
            return str(properties[key]).strip()
    # If none found, return all properties for debugging
    return None


def simplify_geometry(geom_dict, tolerance=0.001):
    """Simplify a GeoJSON geometry using Shapely."""
    try:
        geom = shape(geom_dict)
        simplified = geom.simplify(tolerance, preserve_topology=True)
        result = mapping(simplified)
        # Round coordinates to 5 decimal places for compactness
        return round_coordinates(result)
    except Exception as e:
        print(f"  Warning: Could not simplify geometry: {e}")
        return geom_dict


def round_coordinates(geom_dict, precision=5):
    """Round all coordinates in a GeoJSON geometry to specified precision."""
    def round_coords(coords):
        if isinstance(coords[0], (list, tuple)):
            return [round_coords(c) for c in coords]
        else:
            return [round(c, precision) for c in coords]

    result = dict(geom_dict)
    if "coordinates" in result:
        result["coordinates"] = round_coords(result["coordinates"])
    return result


def process_geojson(geojson_data):
    """Process the GeoJSON data: match districts, add metadata, simplify."""
    features = geojson_data.get("features", [])
    print(f"\nProcessing {len(features)} features from GeoJSON...")

    output_features = []
    matched = set()
    unmatched = []

    for feature in features:
        props = feature.get("properties", {})
        raw_name = extract_district_name(props)

        if raw_name is None:
            print(f"  Warning: Could not extract name from properties: {list(props.keys())}")
            continue

        canonical_name = normalize_name(raw_name)

        if canonical_name is None:
            unmatched.append(raw_name)
            continue

        if canonical_name in matched:
            print(f"  Warning: Duplicate district '{canonical_name}' (from '{raw_name}')")
            continue

        matched.add(canonical_name)

        # Simplify geometry
        simplified_geom = simplify_geometry(feature["geometry"])

        # Build output feature
        output_feature = {
            "type": "Feature",
            "properties": {
                "nome": canonical_name,
                "populacao": POPULATION_DATA.get(canonical_name, 0),
                "zona": ZONE_DATA.get(canonical_name, "Unknown"),
                "indice_comercial": COMMERCIAL_INDEX.get(canonical_name, 0.3),
            },
            "geometry": simplified_geom,
        }
        output_features.append(output_feature)

    # Report unmatched
    if unmatched:
        print(f"\n  ⚠ Could not match {len(unmatched)} features:")
        for name in unmatched:
            print(f"    - '{name}'")

    # Report missing districts
    missing = set(POPULATION_DATA.keys()) - matched
    if missing:
        print(f"\n  ⚠ {len(missing)} districts not found in GeoJSON:")
        for name in sorted(missing):
            print(f"    - '{name}'")

    return output_features, matched


def main():
    # Determine project root (script is at mock/bootstrap/scripts/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
    output_dir = os.path.join(project_root, "mock", "bootstrap", "src", "data")
    output_file = os.path.join(output_dir, "distritos_sp.json")

    print("=" * 60)
    print("São Paulo Districts Geodata Preparation Pipeline")
    print("=" * 60)
    print(f"Project root: {project_root}")
    print(f"Output file:  {output_file}")
    print(f"Districts in database: {len(POPULATION_DATA)}")
    print()

    # Step 1: Download GeoJSON
    print("Step 1: Downloading GeoJSON...")
    geojson_data = download_geojson()

    if geojson_data is None:
        print("\n✗ Could not download GeoJSON from any source.")
        print("  Please check your internet connection or provide a local file.")
        sys.exit(1)

    # Step 2: Process and merge data
    print("\nStep 2: Processing and merging data...")
    output_features, matched = process_geojson(geojson_data)

    # Step 3: Build output GeoJSON
    output_geojson = {
        "type": "FeatureCollection",
        "features": output_features,
    }

    # Step 4: Save output
    print(f"\nStep 3: Saving output...")
    os.makedirs(output_dir, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_geojson, f, ensure_ascii=False, separators=(",", ":"))

    file_size = os.path.getsize(output_file)
    print(f"  ✓ Saved to {output_file}")
    print(f"  ✓ File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    # Step 5: Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total districts in output: {len(output_features)}")

    total_pop = sum(f["properties"]["populacao"] for f in output_features)
    print(f"Total population:          {total_pop:,}")

    # Zone breakdown
    zone_counts = {}
    for f in output_features:
        z = f["properties"]["zona"]
        zone_counts[z] = zone_counts.get(z, 0) + 1
    print(f"\nDistricts by zone:")
    for zone in ["Centro", "Norte", "Sul", "Leste", "Oeste"]:
        print(f"  {zone}: {zone_counts.get(zone, 0)}")

    # Top 5 most populous
    sorted_districts = sorted(
        output_features, key=lambda f: f["properties"]["populacao"], reverse=True
    )
    print(f"\nTop 5 most populous districts:")
    for i, f in enumerate(sorted_districts[:5], 1):
        p = f["properties"]
        print(f"  {i}. {p['nome']}: {p['populacao']:,} ({p['zona']})")

    # Top 5 highest commercial index
    sorted_commercial = sorted(
        output_features,
        key=lambda f: f["properties"]["indice_comercial"],
        reverse=True,
    )
    print(f"\nTop 5 highest commercial index:")
    for i, f in enumerate(sorted_commercial[:5], 1):
        p = f["properties"]
        print(f"  {i}. {p['nome']}: {p['indice_comercial']:.2f} ({p['zona']})")

    print(f"\nFile size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")
    print("=" * 60)

    if len(output_features) != 96:
        print(f"\n⚠ WARNING: Expected 96 districts but got {len(output_features)}")
        return 1

    print("\n✓ All 96 districts processed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
