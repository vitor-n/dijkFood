#!/usr/bin/env python3
"""
pkl_to_osm.py — Converte um grafo OSMnx serializado (.pkl) para o formato .osm (XML)
que o osrm-extract consegue processar.

Uso:
    python pkl_to_osm.py <input.pkl> <output.osm>

O grafo deve ser um nx.MultiDiGraph com:
  - Atributos de nó: 'y' (lat), 'x' (lon)
  - Atributos de aresta: 'length', 'oneway' (opcional), 'highway' (opcional)
"""

import pickle
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom


def load_graph(pkl_path: str):
    print(f"Carregando grafo de {pkl_path}...")
    with open(pkl_path, "rb") as f:
        G = pickle.load(f)
    print(f"  Grafo carregado: {G.number_of_nodes()} nós, {G.number_of_edges()} arestas")
    return G


def build_osm(G) -> ET.Element:
    """Constrói a árvore XML do .osm a partir do grafo NetworkX."""
    print("Construindo XML OSM...")

    osm = ET.Element("osm", version="0.6", generator="pkl_to_osm.py")

    # ── Nós ──────────────────────────────────────────────────────────────────
    # O OSRM exige id, lat, lon como atributos de string no elemento <node>
    for node_id, data in G.nodes(data=True):
        lat = data.get("y")
        lon = data.get("x")
        if lat is None or lon is None:
            continue
        ET.SubElement(
            osm,
            "node",
            id=str(node_id),
            lat=f"{lat:.7f}",
            lon=f"{lon:.7f}",
            version="1",
        )

    # ── Arestas (ways) ────────────────────────────────────────────────────────
    # Cada aresta do MultiDiGraph vira um <way> com dois <nd> (origem e destino).
    # Arestas oneway=True ficam apenas no sentido original.
    # Arestas bidirecionais geram dois <way> distintos (sentidos opostos).
    way_id = 1
    for u, v, data in G.edges(data=True):
        oneway = data.get("oneway", True)
        highway = data.get("highway", "residential")
        # highway pode ser lista (OSMnx às vezes retorna assim)
        if isinstance(highway, list):
            highway = highway[0]

        # Way sentido u → v
        way = ET.SubElement(osm, "way", id=str(way_id), version="1")
        way_id += 1
        ET.SubElement(way, "nd", ref=str(u))
        ET.SubElement(way, "nd", ref=str(v))
        ET.SubElement(way, "tag", k="highway", v=str(highway))
        ET.SubElement(way, "tag", k="oneway", v="yes")

        # Se não for oneway, gera o sentido inverso também
        if not oneway:
            way_rev = ET.SubElement(osm, "way", id=str(way_id), version="1")
            way_id += 1
            ET.SubElement(way_rev, "nd", ref=str(v))
            ET.SubElement(way_rev, "nd", ref=str(u))
            ET.SubElement(way_rev, "tag", k="highway", v=str(highway))
            ET.SubElement(way_rev, "tag", k="oneway", v="yes")

    print(f"  {way_id - 1} ways gerados")
    return osm


def write_osm(osm_element: ET.Element, output_path: str) -> None:
    print(f"Escrevendo {output_path}...")
    # Serializa sem pretty-print primeiro (mais rápido para grafos grandes)
    tree = ET.ElementTree(osm_element)
    ET.indent(tree, space="  ")
    with open(output_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)
    import os
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  Arquivo salvo: {output_path} ({size_mb:.1f} MB)")


def main():
    if len(sys.argv) != 3:
        print(f"Uso: python {sys.argv[0]} <input.pkl> <output.osm>")
        sys.exit(1)

    pkl_path = sys.argv[1]
    osm_path = sys.argv[2]

    G = load_graph(pkl_path)
    osm = build_osm(G)
    write_osm(osm, osm_path)
    print("Conversão concluída com sucesso.")


if __name__ == "__main__":
    main()
