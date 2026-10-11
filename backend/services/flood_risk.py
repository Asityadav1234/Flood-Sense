"""Explainable rule-based flood-risk model.

risk = rain_factor * (0.25 + 0.75 * terrain_factor)
  rain_factor    : 24h rainfall and peak hourly intensity (0..1)
  terrain_factor : how much lower the spot is than its surroundings (water collects)
                   and how flat it is (water drains slowly)

This is an ESTIMATE from public rainfall + elevation data. It does not use
drainage maps or verified flood history, and is not a flood forecast.
"""
import math
from .elevation import get_elevations


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def level(s: float) -> str:
    return "low" if s < 0.25 else "medium" if s < 0.5 else "high"


def score(rain: dict, depress_m: float, slope: float) -> dict:
    rain_f = clamp(0.6 * rain["rain_24h_mm"] / 100 + 0.4 * rain["peak_hourly_mm"] / 30)
    low = clamp(0.5 + depress_m / 10)      # 5 m below surroundings -> 1.0
    flat = clamp(1 - slope / 0.05)         # 5% slope or more -> 0.0
    terrain = clamp(0.7 * low + 0.3 * flat)
    s = round(rain_f * (0.25 + 0.75 * terrain), 3)
    return {"score": s, "level": level(s), "factors": {
        "rain": round(rain_f, 2), "low_lying": round(low, 2), "flatness": round(flat, 2)},
        "depression_m": round(depress_m, 1), "slope_pct": round(slope * 100, 1)}


def explain(r: dict, rain: dict) -> str:
    f, parts = r["factors"], []
    parts.append(f"{rain['rain_24h_mm']} mm expected in 24h (peak {rain['peak_hourly_mm']} mm/h)"
                 if rain["rain_24h_mm"] > 0 else "no significant rain forecast")
    if f["low_lying"] > 0.65:
        parts.append(f"ground sits about {abs(r['depression_m'])} m below its surroundings")
    elif f["low_lying"] < 0.35:
        parts.append("ground is higher than its surroundings, so water drains away")
    if f["flatness"] > 0.7:
        parts.append("terrain is very flat, so water drains slowly")
    return f"Estimated {r['level']} risk: " + "; ".join(parts) + "."


async def risk_grid(south, west, north, east, rain: dict, n: int = 10) -> dict:
    """Score an n x n grid of cells covering the bounding box (n*n <= 100 per elevation call)."""
    lats = [south + (north - south) * (i + .5) / n for i in range(n)]
    lons = [west + (east - west) * (j + .5) / n for j in range(n)]
    elev = await get_elevations([(la, lo) for la in lats for lo in lons])
    Z = [elev[i * n:(i + 1) * n] for i in range(n)]
    dy = (north - south) / n * 111320
    dx = (east - west) / n * 111320 * math.cos(math.radians((north + south) / 2))
    cells = []
    for i in range(n):
        row = []
        for j in range(n):
            nb = [(a, b) for a in range(max(0, i - 1), min(n, i + 2))
                  for b in range(max(0, j - 1), min(n, j + 2)) if (a, b) != (i, j)]
            depress = sum(Z[a][b] for a, b in nb) / len(nb) - Z[i][j]
            slope = sum(abs(Z[a][b] - Z[i][j]) / math.hypot((a - i) * dy, (b - j) * dx) for a, b in nb) / len(nb)
            c = score(rain, depress, slope)
            c.update(elevation_m=round(Z[i][j], 1), explanation=explain(c, rain))
            row.append(c)
        cells.append(row)
    return {"south": south, "west": west, "north": north, "east": east, "n": n, "cells": cells}


def lookup(grid: dict, lat: float, lon: float) -> float:
    n = grid["n"]
    i = int(clamp((lat - grid["south"]) / (grid["north"] - grid["south"])) * n)
    j = int(clamp((lon - grid["west"]) / (grid["east"] - grid["west"])) * n)
    return grid["cells"][min(i, n - 1)][min(j, n - 1)]["score"]


def to_geojson(grid: dict) -> dict:
    n, feats = grid["n"], []
    dlat, dlon = (grid["north"] - grid["south"]) / n, (grid["east"] - grid["west"]) / n
    for i in range(n):
        for j in range(n):
            s, w = grid["south"] + i * dlat, grid["west"] + j * dlon
            ring = [[w, s], [w + dlon, s], [w + dlon, s + dlat], [w, s + dlat], [w, s]]
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                          "properties": grid["cells"][i][j]})
    return {"type": "FeatureCollection", "features": feats}


async def assess_point(lat: float, lon: float, rain: dict, step_m: float = 250) -> dict:
    """Score one point using a 3x3 neighbourhood (~250 m spacing) centred on it."""
    dlat = step_m / 111320
    dlon = step_m / (111320 * math.cos(math.radians(lat)))
    g = await risk_grid(lat - 1.5 * dlat, lon - 1.5 * dlon, lat + 1.5 * dlat, lon + 1.5 * dlon, rain, n=3)
    return g["cells"][1][1]
