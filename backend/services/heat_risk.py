"""Explainable heatwave-risk model.

risk = hazard * (0.3 + 0.7 * exposure)
  hazard   : how hot it feels (heat index) and how many days in the next 7 reach 40 C+  (same for the whole city)
  exposure : how little green / water cover is near a spot (OpenStreetMap parks, forests, water bodies).
             Less cover -> heat builds up. This is a PROXY for the urban-heat-island effect, not measured land
             surface temperature. If OpenStreetMap is unreachable a neutral 0.5 is used and the response says so.
Estimate only. Not an official heatwave warning (follow IMD).
"""
import math
import time
import httpx
from .flood_risk import clamp, level, to_geojson, lookup  # noqa: F401  (re-exported for main.py)

OVERPASS = "https://overpass-api.de/api/interpreter"
from .cache import SharedCache
_green_cache = SharedCache("green")


def heat_index_c(t_c: float, rh: float) -> float:
    """'Feels like' temperature in C (NWS Rothfusz regression). Never below the air temperature."""
    t = t_c * 9 / 5 + 32
    if t < 80:
        return t_c
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - .22475541 * t * rh - .00683783 * t * t
          - .05481717 * rh * rh + .00122874 * t * t * rh + .00085282 * t * rh * rh - .00000199 * t * t * rh * rh)
    if rh < 13 and 80 <= t <= 112:
        hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
    elif rh > 85 and 80 <= t <= 87:
        hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return min(max(t_c, (hi - 32) * 5 / 9), t_c + 8)  # cap: the regression is unreliable far outside its range


def hazard(heat: dict) -> dict:
    intensity = clamp((heat["feels_like_c"] - 35) / 20)   # 35 C -> 0, 55 C -> 1
    duration = clamp(heat["hot_days"] / 5)                # 5+ days of 40 C+ -> 1
    return {"score": round(0.75 * intensity + 0.25 * duration, 3),
            "intensity": round(intensity, 2), "duration": round(duration, 2)}


def haversine(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


async def green_features(s, w, n, e) -> list | None:
    """Centres of parks / forests / water in the box from OpenStreetMap (Overpass). None if unavailable."""
    key = (round(s, 3), round(w, 3), round(n, 3), round(e, 3))
    hit = _green_cache.get(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    b = f"({s},{w},{n},{e})"
    q = ('[out:json][timeout:25];('
         f'way["leisure"~"^(park|garden|nature_reserve)$"]{b};'
         f'way["landuse"~"^(forest|grass|meadow|recreation_ground|village_green|orchard)$"]{b};'
         f'way["natural"~"^(wood|water|scrub|wetland)$"]{b};'
         f'relation["natural"="water"]{b};);out center 1500;')
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "FloodSense-hackathon/1.0"}) as c:
            r = await c.post(OVERPASS, data={"data": q})
            r.raise_for_status()
        pts = [(el["center"]["lat"], el["center"]["lon"]) for el in r.json().get("elements", []) if "center" in el]
    except Exception:
        return None
    _green_cache[key] = (time.time(), pts)
    return pts


def _cell(hz: dict, heat: dict, lat: float, lon: float, feats: list | None) -> dict:
    if feats is None:
        green, dist, src = 0.5, None, "neutral (OpenStreetMap unavailable)"
    else:
        dist = min((haversine((lat, lon), p) for p in feats), default=None)
        green = 0.0 if dist is None else clamp(1 - dist / 800)   # green/water within 800 m helps; on top of it = 1
        src = "OpenStreetMap green and water cover"
    exposure = 1 - green
    s = round(hz["score"] * (0.3 + 0.7 * exposure), 3)
    c = {"score": s, "level": level(s),
         "factors": {"heat": hz["score"], "exposure": round(exposure, 2), "green_cover": round(green, 2)},
         "green_dist_m": None if dist is None else round(dist), "exposure_source": src}
    c["explanation"] = explain(c, heat)
    return c


def explain(c: dict, heat: dict) -> str:
    parts = [f"feels like {heat['feels_like_c']} C (air {heat['tmax_c']} C, humidity {heat['humidity_pct']}%)"]
    if heat["hot_days"]:
        parts.append(f"{heat['hot_days']} day(s) of 40 C or more in the next 7")
    g = c["factors"]["green_cover"]
    if c["green_dist_m"] is None:
        parts.append("green cover unknown here")
    elif g > 0.65:
        parts.append(f"a park or water body about {c['green_dist_m']} m away helps cool this spot")
    elif g < 0.35:
        parts.append("little green or water cover nearby, so heat builds up")
    return f"Estimated {c['level']} heat risk: " + "; ".join(parts) + "."


async def heat_grid(south, west, north, east, heat: dict, n: int = 10) -> dict:
    hz = hazard(heat)
    pad = 0.01
    feats = await green_features(south - pad, west - pad, north + pad, east + pad)
    lats = [south + (north - south) * (i + .5) / n for i in range(n)]
    lons = [west + (east - west) * (j + .5) / n for j in range(n)]
    cells = [[_cell(hz, heat, la, lo, feats) for lo in lons] for la in lats]
    return {"south": south, "west": west, "north": north, "east": east, "n": n, "cells": cells}


async def assess_point(lat: float, lon: float, heat: dict) -> dict:
    feats = await green_features(lat - 0.012, lon - 0.012, lat + 0.012, lon + 0.012)
    return _cell(hazard(heat), heat, lat, lon, feats)
