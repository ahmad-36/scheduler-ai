import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def fetch_hourly(lat: float, lon: float, timezone: str, start_date: str, end_date: str) -> dict:
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,precipitation",
        "timezone": timezone,
        "start_date": start_date,
        "end_date": end_date,
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()
