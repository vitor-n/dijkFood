import h3

def generate_cell_index(lat: float, lon: float, res: int = 8) -> int:
    return h3.latlng_to_cell(lat, lon, res)