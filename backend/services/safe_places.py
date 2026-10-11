"""Safe places near a spot: hospitals, shelters and higher ground.

Data: OpenStreetMap via Overpass (hospitals, shelters, assembly points, community centres, schools) and the same
Copernicus 90 m elevation service the flood model uses. Elevation is read for the spot, for every place found and for
a ring of sample points around the spot (600 m and 1.2 km, 8 directions) to suggest the nearest higher ground.

Honest limits: OpenStreetMap coverage varies by city; only places tagged as shelters/assembly points are called
shelters, community centres and schools are shown as POSSIBLE shelters (not confirmed); the higher-ground hint comes
from 90 m terrain and may be private land or water. This is not an evacuation plan.
"""
import math
import time

import httpx

from .elevation import get_elevations
from .heat_risk import haversine

OVERPASS = "https://overpass-api.de/api/interpreter"
from .cache import SharedCache
_cache = SharedCache("osm-safe")
LABELS = {"hospital": "Hospital", "shelter": "Shelter / assembly point", "possible": "Possible shelter (unconfirmed)"}
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
LIMITS = {"hospital": 3, "shelter": 3, "possible": 2}


def _query(lat: float, lon: float) -> str:
    a = lambda r: f"(around:{r},{lat},{lon})"
    return ("[out:json][timeout:25];("
            f'nwr["amenity"="hospital"]{a(6000)};nwr["healthcare"="hospital"]{a(6000)};'
            f'nwr["emergency"="assembly_point"]{a(6000)};nwr["amenity"="shelter"]{a(6000)};'
            f'nwr["emergency"="shelter"]{a(6000)};'
            f'nwr["amenity"="community_centre"]{a(3500)};nwr["amenity"="school"]{a(3000)};'
            ");out center 600;")


def _kind(t: dict) -> str | None:
    if t.get("amenity") == "hospital" or t.get("healthcare") == "hospital":
        return "hospital"
    if t.get("emergency") in ("assembly_point", "shelter"):
        return "shelter"
    if t.get("amenity") == "shelter":
        return None if t.get("shelter_type") in ("public_transport", "picnic_shelter", "weather_shelter") else "shelter"
    if t.get("amenity") in ("community_centre", "school"):
        return "possible"
    return None


async def _fetch(lat: float, lon: float) -> list | None:
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "FloodSense-hackathon/1.0"}) as c:
            r = await c.post(OVERPASS, data={"data": _query(lat, lon)})
            r.raise_for_status()
        els = r.json().get("elements", [])
    except Exception:
        return None
    out = []
    for el in els:
        t = el.get("tags", {})
        k = _kind(t)
        c = el if "lat" in el else el.get("center")
        if k and c:
            out.append({"kind": k, "name": t.get("name:en") or t.get("name") or LABELS[k], "lat": c["lat"], "lon": c["lon"],
                        "emergency": t.get("emergency") == "yes" or t.get("healthcare:speciality") == "emergency"})
    _cache[key] = (time.time(), out)
    return out


def _ring(lat: float, lon: float) -> list:
    dl = 1 / max(0.2, math.cos(math.radians(lat)))
    pts = []
    for r_m in (600, 1200):
        d = r_m / 111_320
        for i in range(8):
            b = math.radians(i * 45)
            pts.append({"bearing": COMPASS[i], "distance_m": r_m,
                        "lat": lat + d * math.cos(b), "lon": lon + d * math.sin(b) * dl})
    return pts


def directions(a: tuple, b: tuple) -> str:
    return f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={a[0]:.5f}%2C{a[1]:.5f}%3B{b[0]:.5f}%2C{b[1]:.5f}"


async def find(lat: float, lon: float) -> dict:
    found = await _fetch(lat, lon)
    here = (lat, lon)
    chosen, counts = [], {k: 0 for k in LIMITS}
    for p in sorted(found or [], key=lambda p: haversine(here, (p["lat"], p["lon"]))):
        if counts[p["kind"]] < LIMITS[p["kind"]]:
            counts[p["kind"]] += 1
            chosen.append(p)
    ring = _ring(lat, lon)
    elev = await get_elevations([here] + [(p["lat"], p["lon"]) for p in chosen] + [(r["lat"], r["lon"]) for r in ring])
    e0 = elev[0]
    places = []
    for p, e in zip(chosen, elev[1:1 + len(chosen)]):
        rise = round(e - e0, 1)
        places.append({**p, "label": LABELS[p["kind"]], "distance_m": round(haversine(here, (p["lat"], p["lon"]))),
                       "elevation_m": round(e, 1), "rise_m": rise, "lower": rise < -1.0,
                       "directions_url": directions(here, (p["lat"], p["lon"]))})
    higher = None
    cands = [{**r, "rise_m": round(e - e0, 1)} for r, e in zip(ring, elev[1 + len(chosen):]) if e - e0 >= 3]
    if cands:
        near = min(r["distance_m"] for r in cands)
        best = max((r for r in cands if r["distance_m"] == near), key=lambda r: r["rise_m"])
        higher = {**best, "directions_url": directions(here, (best["lat"], best["lon"]))}
    return {"origin": {"lat": lat, "lon": lon, "elevation_m": round(e0, 1)}, "places": places, "higher_ground": higher,
            "osm_available": found is not None,
            "source": "OpenStreetMap (Overpass) and Copernicus 90 m terrain",
            "disclaimer": "Check with local authorities which shelters are open. Community centres and schools are only "
                          "possible shelters. OpenStreetMap may be incomplete and the higher-ground hint comes from 90 m "
                          "terrain data. Not an evacuation plan."}


def km(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{round(m, -1):.0f} m"


def alert_lines(sp: dict | None, flood: bool) -> list:
    """Plain-text lines for alert emails. Hospitals always; shelters and higher ground only for flood alerts."""
    if not sp:
        return []
    lines, by = [], {}
    for p in sp["places"]:
        by.setdefault(p["kind"], p)
    if "hospital" in by:
        h = by["hospital"]
        lines.append(f"Nearest hospital: {h['name']}, {km(h['distance_m'])} away")
    if flood:
        s = by.get("shelter") or by.get("possible")
        if s:
            note = "" if s["kind"] == "shelter" else " (possible shelter, not confirmed)"
            lines.append(f"Nearest shelter: {s['name']}, {km(s['distance_m'])} away{note}")
        g = sp.get("higher_ground")
        if g:
            lines.append(f"Higher ground: about {km(g['distance_m'])} {g['bearing']}, roughly {g['rise_m']:.0f} m higher")
    return (["", "Nearby safe places (from OpenStreetMap, confirm locally):"] + [f"- {x}" for x in lines]) if lines else []
