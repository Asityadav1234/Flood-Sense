"""Flood-risk-aware routing: shortest path vs. a path penalised by estimated risk."""
import asyncio
import math
import networkx as nx
import numpy as np
import osmnx as ox
from . import flood_risk

ox.settings.cache_folder = "/tmp/osmnx_cache"  # Lambda: only /tmp is writable
RISK_PENALTY = 8  # a fully "high risk" road feels 9x longer to the safer router
_graphs: dict = {}


def haversine(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def _load_graph(lat, lon, dist):
    key = (round(lat, 3), round(lon, 3), int(dist // 250))
    if key not in _graphs:
        _graphs[key] = ox.graph_from_point((lat, lon), dist=dist, network_type="drive")
    return _graphs[key]


def _edge(G, u, v, weight):
    return min(G[u][v].values(), key=lambda d: d[weight])


def _describe(G, path, weight):
    coords, dist, risk_len, mx, high_m = [], 0.0, 0.0, 0.0, 0.0
    for u, v in zip(path[:-1], path[1:]):
        d = _edge(G, u, v, weight)
        pts = [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])]
        if "geometry" in d:
            pts = [(y, x) for x, y in d["geometry"].coords]
            if haversine(pts[0], (G.nodes[u]["y"], G.nodes[u]["x"])) > haversine(pts[-1], (G.nodes[u]["y"], G.nodes[u]["x"])):
                pts.reverse()
        coords += pts
        dist += d["length"]
        risk_len += d["risk"] * d["length"]
        mx = max(mx, d["risk"])
        if d["risk"] >= 0.5:
            high_m += d["length"]
    return {"coords": coords, "distance_m": round(dist), "avg_risk": round(risk_len / max(dist, 1), 3),
            "max_risk": round(mx, 3), "high_risk_m": round(high_m)}


async def safe_route(start, end, rain: dict) -> dict:
    d = haversine(start, end)
    if d > 15000:
        raise ValueError("Route too long for this prototype (max 15 km).")
    G = await asyncio.to_thread(_load_graph, (start[0] + end[0]) / 2, (start[1] + end[1]) / 2, d / 2 + 1000)
    ids = list(G.nodes)
    arr = np.array([[G.nodes[i]["y"], G.nodes[i]["x"]] for i in ids])
    k = math.cos(math.radians(start[0]))

    def nearest(p):
        return ids[int(np.argmin((arr[:, 0] - p[0]) ** 2 + ((arr[:, 1] - p[1]) * k) ** 2))]

    o, t = nearest(start), nearest(end)
    pad = 0.002
    grid = await flood_risk.risk_grid(arr[:, 0].min() - pad, arr[:, 1].min() - pad,
                                      arr[:, 0].max() + pad, arr[:, 1].max() + pad, rain, n=10)
    for u, v, _, data in G.edges(keys=True, data=True):
        r = flood_risk.lookup(grid, (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2, (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2)
        data["risk"] = r
        data["safe_w"] = data["length"] * (1 + RISK_PENALTY * r)
    try:
        fast = nx.shortest_path(G, o, t, weight="length")
        safe = nx.shortest_path(G, o, t, weight="safe_w")
    except nx.NetworkXNoPath:
        raise ValueError("No drivable route found between these points.")
    a, b = _describe(G, fast, "length"), _describe(G, safe, "safe_w")
    return {"shortest": a, "safer": b, "same_route": fast == safe,
            "extra_distance_pct": round(100 * (b["distance_m"] - a["distance_m"]) / max(a["distance_m"], 1), 1),
            "rain": rain}
