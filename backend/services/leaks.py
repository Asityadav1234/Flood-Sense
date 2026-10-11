"""Water-leak reports (4th layer): citizen reports -> estimated water loss -> priority for repair crews.

Storage: DynamoDB when LEAKS_TABLE is set (AWS), otherwise an in-memory dict (local dev).
Loss per leak type is a ROUGH PLANNING ASSUMPTION, not a measurement. Priority rises when the area
is also under drought stress, because every litre wasted matters more then.
"""
import math
import os
import random
import time
import uuid
from decimal import Decimal

from .flood_risk import clamp, level

TABLE = os.getenv("LEAKS_TABLE", "")
TTL_DAYS = 30
PER_PERSON_L = 135  # litres per person per day, common urban water-supply planning norm in India (CPHEEO)

KINDS = {
    "drip": {"label": "Dripping tap or joint", "lpd": 20},
    "steady": {"label": "Steady stream from pipe or tap", "lpd": 2000},
    "overflow": {"label": "Overflowing tank", "lpd": 1000},
    "burst": {"label": "Burst or gushing pipe", "lpd": 50000},
}
CELL = 0.05  # grid cell size in degrees (about 5.5 km): the key of the CellIndex secondary index
_mem: dict = {}


def cell_of(lat: float, lon: float) -> str:
    return f"{math.floor(lat / CELL)}:{math.floor(lon / CELL)}"


def _in_box(s: float, w: float, n: float, e: float) -> list:
    """Reports inside a box. DynamoDB: query the CellIndex for each grid cell the box touches (no table scan)."""
    inside = lambda i: s <= i["lat"] <= n and w <= i["lon"] <= e
    if not TABLE:
        return [i for i in _mem.values() if inside(i)]
    from concurrent.futures import ThreadPoolExecutor
    from boto3.dynamodb.conditions import Key
    cells = [f"{i}:{j}" for i in range(math.floor(s / CELL), math.floor(n / CELL) + 1)
             for j in range(math.floor(w / CELL), math.floor(e / CELL) + 1)][:60]

    def one(c):
        out, kw = [], {}
        for _ in range(3):
            r = _tbl().query(IndexName="CellIndex", KeyConditionExpression=Key("cell").eq(c), **kw)
            out += _clean(r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}
        return out
    with ThreadPoolExecutor(8) as ex:
        return [i for chunk in ex.map(one, cells) for i in chunk if inside(i)]


def priority(kind: str, drought_score: float | None) -> dict:
    lpd = KINDS[kind]["lpd"]
    loss = clamp(math.log10(lpd) / 5)                     # 20 L -> 0.26, 2,000 L -> 0.66, 50,000 L -> 0.94
    d = 0.3 if drought_score is None else drought_score   # unknown drought stress -> mild
    s = round(loss * (0.6 + 0.4 * d), 3)
    return {"score": s, "level": level(s), "lpd": lpd}


def _clean(o):
    if isinstance(o, Decimal):
        return float(o) if o % 1 else int(o)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _tbl():
    import boto3
    return boto3.resource("dynamodb").Table(TABLE)


def create(lat: float, lon: float, kind: str, note: str = "", drought_score: float | None = None,
           demo: bool = False, photo_key: str = "", photo_check: dict | None = None) -> dict:
    p = priority(kind, drought_score)
    item = {"id": uuid.uuid4().hex[:12], "lat": round(lat, 6), "lon": round(lon, 6), "kind": kind,
            "label": KINDS[kind]["label"], "note": note.strip()[:200], "lpd": p["lpd"], "score": p["score"],
            "level": p["level"], "status": "open", "demo": demo, "created": int(time.time()), "cell": cell_of(lat, lon)}
    if photo_key:
        item.update(photo_key=photo_key, photo_check=photo_check or {"status": "unchecked", "labels": []})
    if TABLE:
        import json
        _tbl().put_item(Item=json.loads(json.dumps({**item, "ttl": item["created"] + TTL_DAYS * 86400}),
                                        parse_float=Decimal))
    else:
        _mem[item["id"]] = item
    return item


def _all() -> list:
    if not TABLE:
        return list(_mem.values())
    t, out, kw = _tbl(), [], {}
    for _ in range(5):  # hackathon scale: scan a few pages. Use a geohash key / GSI for production
        r = t.scan(**kw)
        out += _clean(r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            break
        kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}
    return out


def in_bbox(s: float, w: float, n: float, e: float) -> list:
    items = [i for i in _in_box(s, w, n, e) if i.get("status") != "fixed"]
    return sorted(items, key=lambda i: -i["score"])[:300]


def split(s: float, w: float, n: float, e: float) -> tuple[list, list]:
    """(open leaks, fixed leaks) inside a bounding box, from ONE table read."""
    inside = _in_box(s, w, n, e)
    open_ = sorted((i for i in inside if i.get("status") != "fixed"), key=lambda i: -i["score"])[:300]
    return open_, [i for i in inside if i.get("status") == "fixed"]


TANKER_L = 10_000  # a common municipal water-tanker size in India; used only to make litres easier to picture


def impact(fixed: list) -> dict:
    """Water saved by fixed reports. 'Stopped per day' is the loss rate that no longer happens;
    'saved so far' adds it up from the moment each leak was marked fixed (planning assumption, not metered)."""
    now = time.time()
    stopped = sum(i["lpd"] for i in fixed)
    saved = sum(i["lpd"] * max(0.0, now - i.get("fixed_at", now)) / 86400 for i in fixed)
    return {"fixed": len(fixed), "lpd_stopped": stopped, "litres_saved": round(saved),
            "tanker_trips": round(saved / TANKER_L, 1), "people_days": round(saved / PER_PERSON_L)}


def fix(leak_id: str) -> bool:
    if not TABLE:
        if leak_id in _mem:
            _mem[leak_id].update(status="fixed", fixed_at=int(time.time()))
            return True
        return False
    from botocore.exceptions import ClientError
    try:
        _tbl().update_item(Key={"id": leak_id}, UpdateExpression="SET #s = :f, fixed_at = :t",
                           ConditionExpression="attribute_exists(id)",
                           ExpressionAttributeNames={"#s": "status"},
                           ExpressionAttributeValues={":f": "fixed", ":t": int(time.time())})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def summary(items: list) -> dict:
    total = sum(i["lpd"] for i in items)
    by = {k: 0 for k in KINDS}
    for i in items:
        by[i["kind"]] = by.get(i["kind"], 0) + 1
    return {"open": len(items), "lpd_total": total, "people_equivalent": round(total / PER_PERSON_L),
            "by_kind": by, "assumption": f"Loss per leak is a rough planning assumption. {PER_PERSON_L} L/person/day norm."}


def seed_demo(lat: float, lon: float, n: int = 9) -> list:
    """Clearly-labelled sample reports around a point so the layer can be demoed anywhere."""
    rnd = random.Random(int(lat * 1000) * 31 + int(lon * 1000))
    kinds = ["drip", "drip", "steady", "steady", "overflow", "burst", "drip", "steady", "overflow"]
    dlon = 1 / max(0.2, math.cos(math.radians(lat)))
    return [create(lat + rnd.uniform(-0.025, 0.025), lon + rnd.uniform(-0.025, 0.025) * dlon, kinds[i % len(kinds)],
                   "Demo report", None, demo=True) for i in range(n)]
