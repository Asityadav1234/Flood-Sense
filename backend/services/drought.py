"""Explainable drought-risk index (city level, rainfall-based).

score = 0.5 * deficit + 0.25 * dry_spell + 0.25 * evaporative_demand
  deficit  : last 91 days of rain vs the average for the same 91 days over the previous 10 years
             (40% of normal or less -> 1.0)
  dry_spell: consecutive days with under 1 mm of rain up to today (30+ days -> 1.0)
  demand   : forecast reference evapotranspiration (ET0) next 7 days (3 mm/day -> 0, 8 mm/day -> 1)
deficit and dry_spell are scaled down when the normal rain for the window is tiny (dry season), because
"no rain" is then expected and not a drought. Drought is regional, so there is one index per city, not a map.
Estimate only. Not an official drought declaration and not a reservoir/groundwater measurement.
"""
import time
from datetime import date, timedelta
import httpx
from .flood_risk import clamp, level

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
WINDOW, YEARS = 91, 10
from .cache import SharedCache
_cache = SharedCache("drought")


def _shift(d: date, k: int) -> date:
    try:
        return d.replace(year=d.year - k)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - k, day=28)


def _weekly(vals):
    return [round(sum(vals[i:i + 7]), 1) for i in range(0, len(vals), 7)]


def scenario(pct: float, base: dict | None = None) -> dict:
    """Demo scenario: `pct` % of normal rain over the last 91 days. Uses this location's real 10-year normal
    when it is meaningful (100 mm+), otherwise a 400 mm placeholder so the slider still does something."""
    real = bool(base) and base["normal_mm"] >= 100
    normal = base["normal_mm"] if real else 400.0
    nw = base["weekly_normal_mm"] if real else [round(normal / 13, 1)] * 13
    f = pct / 100
    return {"source": "scenario (simulated, " + ("local 10-year normal)" if real else "placeholder normal)"),
            "actual_mm": round(normal * f, 1), "normal_mm": normal,
            "dry_days": round((100 - pct) * 0.4), "et0_mm_day": round(4 + (100 - pct) / 100 * 4, 1),
            "weekly_mm": [round(x * f, 1) for x in nw], "weekly_normal_mm": nw}


async def get_inputs(lat: float, lon: float, pct: float = 0) -> dict:
    if pct > 0:
        try:
            base = await _live(lat, lon)
        except Exception:
            base = None
        return scenario(pct, base)
    return await _live(lat, lon)


async def _live(lat: float, lon: float) -> dict:
    key = (round(lat, 2), round(lon, 2), date.today())
    if key in _cache and time.time() - _cache[key][0] < 6 * 3600:
        return _cache[key][1]
    today = date.today()
    async with httpx.AsyncClient(timeout=40) as c:
        f = await c.get(FORECAST, params={"latitude": lat, "longitude": lon, "timezone": "auto",
                                          "daily": "precipitation_sum,et0_fao_evapotranspiration",
                                          "past_days": WINDOW - 1, "forecast_days": 7})
        f.raise_for_status()
        a = await c.get(ARCHIVE, params={"latitude": lat, "longitude": lon, "daily": "precipitation_sum",
                                         "start_date": (_shift(today, YEARS) - timedelta(days=WINDOW)).isoformat(),
                                         "end_date": _shift(today, 1).isoformat()})
        a.raise_for_status()
    d = f.json()["daily"]
    past = [v or 0 for v in d["precipitation_sum"][:WINDOW]]
    et = [v for v in d["et0_fao_evapotranspiration"][WINDOW:] if v is not None] or \
         [v for v in d["et0_fao_evapotranspiration"][:WINDOW][-7:] if v is not None] or [0]
    hist = {t: (v or 0) for t, v in zip(a.json()["daily"]["time"], a.json()["daily"]["precipitation_sum"])}
    wins = []
    for k in range(1, YEARS + 1):
        end = _shift(today, k)
        wins.append([hist.get((end - timedelta(days=WINDOW - 1 - i)).isoformat(), 0) for i in range(WINDOW)])
    normal_days = [sum(w[i] for w in wins) / len(wins) for i in range(WINDOW)]
    dry = 0
    for v in reversed(past):
        if v >= 1:
            break
        dry += 1
    data = {"source": "Open-Meteo (ERA5 history + forecast)", "actual_mm": round(sum(past), 1),
            "normal_mm": round(sum(normal_days), 1), "dry_days": dry,
            "et0_mm_day": round(sum(et) / len(et), 1),
            "weekly_mm": _weekly(past), "weekly_normal_mm": _weekly(normal_days)}
    _cache[key] = (time.time(), data)
    return data




def assess(d: dict) -> dict:
    normal = d["normal_mm"]
    pct = d["actual_mm"] / normal if normal > 0 else 1
    w = clamp(normal / 80)  # dry season: little rain is normal, so rain-based factors count for less
    deficit = clamp((1 - pct) / 0.6) * w
    dry = clamp(d["dry_days"] / 30) * w
    demand = clamp((d["et0_mm_day"] - 3) / 5)
    s = round(0.5 * deficit + 0.25 * dry + 0.25 * demand, 3)
    r = {"score": s, "level": level(s), "pct_of_normal": round(pct * 100),
         "factors": {"deficit": round(deficit, 2), "dry_spell": round(dry, 2), "evaporative_demand": round(demand, 2)}}
    parts = []
    if normal >= 30:
        parts.append(f"{d['actual_mm']} mm of rain in the last 91 days, {r['pct_of_normal']}% of the usual {normal} mm")
    else:
        parts.append(f"{d['actual_mm']} mm in the last 91 days; little rain is normal in this season ({normal} mm)")
    if d["dry_days"] >= 7:
        parts.append(f"{d['dry_days']} days in a row without meaningful rain")
    parts.append(f"high evaporation ({d['et0_mm_day']} mm/day) is drying soil and storage faster"
                 if demand > 0.5 else f"evaporation is moderate ({d['et0_mm_day']} mm/day)")
    r["explanation"] = f"Estimated {r['level']} drought risk: " + "; ".join(parts) + "."
    return r
