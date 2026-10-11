"""Terrain height (Copernicus DEM, 90 m) via Open-Meteo's elevation API."""
import httpx

URL = "https://api.open-meteo.com/v1/elevation"


async def get_elevations(points: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    async with httpx.AsyncClient(timeout=15) as c:
        for i in range(0, len(points), 100):  # API limit: 100 coordinates per call
            chunk = points[i:i + 100]
            r = await c.get(URL, params={"latitude": ",".join(f"{p[0]:.5f}" for p in chunk),
                                         "longitude": ",".join(f"{p[1]:.5f}" for p in chunk)})
            r.raise_for_status()
            out += r.json()["elevation"]
    return out
