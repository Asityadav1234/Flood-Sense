"""Rainfall forecast from Open-Meteo (free, no API key)."""
import time
import httpx

URL = "https://api.open-meteo.com/v1/forecast"
from .cache import SharedCache
_cache = SharedCache("weather")


def scenario(mm: float) -> dict:
    """Simulated storm for demos: mm of rain over 24h, peak hour = 25% of total."""
    return {"source": "scenario (simulated)", "rain_24h_mm": round(mm, 1), "peak_hourly_mm": round(mm / 4, 1)}


async def get_forecast(lat: float, lon: float, scenario_mm: float = 0) -> dict:
    if scenario_mm > 0:
        return scenario(scenario_mm)
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(URL, params={"latitude": lat, "longitude": lon, "hourly": "precipitation",
                                     "forecast_hours": 24, "timezone": "auto"})
        r.raise_for_status()
    hourly = [v or 0 for v in r.json()["hourly"]["precipitation"]]
    data = {"source": "Open-Meteo forecast", "rain_24h_mm": round(sum(hourly), 1),
            "peak_hourly_mm": round(max(hourly, default=0), 1)}
    _cache[key] = (time.time(), data)
    return data


async def heat_scenario(t: float, lat: float, lon: float) -> dict:
    """Simulated heatwave for demos: afternoon air temperature t (C). Humidity is taken from the live forecast
    for this location (so coastal and desert cities behave differently); 30% if that is unavailable."""
    from .heat_risk import heat_index_c
    rh = 30
    try:
        rh = max(10, min(90, (await get_heat(lat, lon, 0))["humidity_pct"]))
    except Exception:
        pass
    hot = 0 if t < 40 else max(1, min(7, round((t - 37) / 1.5)))
    return {"source": "scenario (simulated)", "tmax_c": round(t, 1), "humidity_pct": rh,
            "feels_like_c": round(heat_index_c(t, rh), 1), "hot_days": hot}


async def get_heat(lat: float, lon: float, scenario_c: float = 0) -> dict:
    """Peak temperature, humidity and heat index over the next 72 h, plus days >= 40 C in the next 7."""
    if scenario_c > 0:
        return await heat_scenario(scenario_c, lat, lon)
    from .heat_risk import heat_index_c
    key = ("heat", round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(URL, params={"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
                                     "hourly": "temperature_2m,relative_humidity_2m", "daily": "temperature_2m_max"})
        r.raise_for_status()
    j = r.json()
    temps = [v if v is not None else 0 for v in j["hourly"]["temperature_2m"][:72]]
    rhs = [v if v is not None else 50 for v in j["hourly"]["relative_humidity_2m"][:72]]
    his = [heat_index_c(t, h) for t, h in zip(temps, rhs)]
    i = max(range(len(his)), key=his.__getitem__)
    daily = [v for v in j["daily"]["temperature_2m_max"] if v is not None]
    data = {"source": "Open-Meteo forecast", "tmax_c": round(max(temps), 1), "humidity_pct": round(rhs[i]),
            "feels_like_c": round(his[i], 1), "hot_days": sum(1 for v in daily if v >= 40)}
    _cache[key] = (time.time(), data)
    return data
