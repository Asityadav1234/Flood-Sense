"""Shared cache + rate limiting on one small DynamoDB table (CACHE_TABLE).

SharedCache is a drop-in for the old per-instance dicts: each Lambda instance still keeps a fast in-memory copy, but
results are also stored in DynamoDB, so a cold start or a second instance reuses weather, drought and OpenStreetMap
answers instead of calling the upstream APIs again. Rate-limit counters live in the same table (atomic ADD, ttl).
Without CACHE_TABLE everything stays in memory (local dev). Any DynamoDB error is ignored: cache misses never break
the app, and the rate limiter fails open.
"""
import json
import os
import time

TABLE = os.getenv("CACHE_TABLE", "")
KEEP_S = 7 * 3600  # longest caller TTL is 6 h


def _tbl():
    import boto3
    return boto3.resource("dynamodb").Table(TABLE)


class SharedCache:
    def __init__(self, name: str):
        self.name, self._l1 = name, {}

    def _k(self, key) -> str:
        return f"{self.name}#{key}"

    def get(self, key):
        k = self._k(key)
        if k in self._l1:
            return self._l1[k]
        if TABLE:
            try:
                it = _tbl().get_item(Key={"k": k}).get("Item")
                if it and int(it["ttl"]) > time.time():
                    self._l1[k] = (float(it["ts"]), json.loads(it["v"]))
                    return self._l1[k]
            except Exception:
                pass
        return None

    def __contains__(self, key):
        return self.get(key) is not None

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key, val):
        k = self._k(key)
        self._l1[k] = val
        if TABLE:
            try:
                _tbl().put_item(Item={"k": k, "ts": str(val[0]), "v": json.dumps(val[1], default=list),
                                      "ttl": int(time.time()) + KEEP_S})
            except Exception:
                pass


_mem_hits: dict = {}


def hit(bucket: str, limit: int, window_s: int) -> bool:
    """Count one request in a fixed time window. True = allowed, False = over the limit."""
    win = int(time.time() // window_s)
    k = f"rl#{bucket}#{win}"
    if not TABLE:
        _mem_hits[k] = _mem_hits.get(k, 0) + 1
        return _mem_hits[k] <= limit
    try:
        r = _tbl().update_item(Key={"k": k}, UpdateExpression="ADD n :one SET #t = :t",
                               ExpressionAttributeNames={"#t": "ttl"},
                               ExpressionAttributeValues={":one": 1, ":t": (win + 2) * window_s},
                               ReturnValues="UPDATED_NEW")
        return int(r["Attributes"]["n"]) <= limit
    except Exception:
        return True
