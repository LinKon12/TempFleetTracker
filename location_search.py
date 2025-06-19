import requests

def geocode_place(place_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": place_name,
        "format": "json",
        "limit": 1
    }
    resp = requests.get(url, params=params, headers={"User-Agent": "fleet-tracker"})
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Place not found: {place_name}")
    lat = float(results[0]["lat"])
    lon = float(results[0]["lon"])
    return lat, lon
