import asyncio
import hashlib
import os
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
try:
    from mangum import Mangum  # only needed on AWS Lambda
except ImportError:  # Render / local: not required
    Mangum = None
from pydantic import BaseModel, Field

from services import weather, flood_risk, advisory, heat_risk, drought, leaks, alerts, monitor, photos, safe_places, ask, cache

app = FastAPI(title="FloodSense AI", description="Estimated flood, heatwave, drought and water-leak intelligence for any city (prototype)")
# ALLOWED_ORIGIN = your website URL(s), comma separated (e.g. https://floodsense-web.onrender.com). Unset = allow all (local dev)
_origins = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGIN", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins + ["http://localhost:5173"] if _origins else ["*"],
                   allow_methods=["*"], allow_headers=["*"])


def client_ip(request: Request) -> str:
    """Real visitor IP. Behind Render's proxy request.client is the proxy, so read X-Forwarded-For first."""
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def guard(name: str, limit: int, window_s: int):
    """Per-IP rate limit (DynamoDB counters, shared across Lambda instances) for endpoints that cost money or send messages."""
    async def dep(request: Request):
        ip = client_ip(request)
        if not await asyncio.to_thread(cache.hit, f"{name}#{ip}", limit, window_s):
            raise HTTPException(429, "Too many requests from your network. Please wait a few minutes and try again.")
    return Depends(dep)


def parse_bbox(bbox: str, max_lat: float = 0.5, max_lon: float = 0.8):
    """south,west,north,east, validated and size-capped so one request cannot trigger huge map or database queries."""
    try:
        s, w, n, e = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be 'south,west,north,east'")
    if not (-90 <= s < n <= 90 and -180 <= w < e <= 180) or n - s > max_lat or e - w > max_lon:
        raise HTTPException(422, "bbox is invalid or too large")
    return s, w, n, e

DISCLAIMER = "Estimated risk from rainfall and terrain only. Not a verified flood forecast."
DISCLAIMERS = {
    "flood": DISCLAIMER,
    "heat": "Estimated from forecast temperature, humidity and nearby green/water cover. Not an official IMD heatwave warning.",
    "drought": "Estimated from rainfall vs the 10-year normal and evaporation. Not an official drought declaration or a reservoir/groundwater reading.",
}


class RouteRequest(BaseModel):
    start: list[float]  # [lat, lon]
    end: list[float]
    rain_mm: float = 0


class SubscribeIn(BaseModel):
    contact: str = Field(max_length=320, description="email address, or phone number like +919812345678")
    lang: str = "English"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    place: str = Field("", max_length=80)
    min_level: Literal["low", "medium", "high"] = "medium"


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=400)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    place: str = Field("", max_length=80)
    lang: str = "English"
    rain_mm: float = 0
    temp_c: float = 0
    rain_pct: float = 0
    history: list[Turn] = Field(default_factory=list, max_length=6)


class LeakIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    kind: Literal["drip", "steady", "overflow", "burst"]
    note: str = Field("", max_length=200)
    photo_key: str = Field("", max_length=80)   # from POST /leaks/photo-upload, after the browser uploaded to S3


def lang_ok(lang: str) -> str:
    return lang if lang in advisory.LANGS else "English"


def upstream(e: Exception):
    raise HTTPException(503, f"Data source unavailable: {e}")


@app.get("/")
def root():
    return {"name": "FloodSense AI API", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/weather")
async def get_weather(lat: float, lon: float, rain_mm: float = 0):
    try:
        return await weather.get_forecast(lat, lon, rain_mm)
    except httpx.HTTPError as e:
        upstream(e)


@app.get("/flood-risk")
async def get_flood_risk(lat: float, lon: float, rain_mm: float = 0):
    try:
        rain = await weather.get_forecast(lat, lon, rain_mm)
        return {**await flood_risk.assess_point(lat, lon, rain), "rain": rain, "disclaimer": DISCLAIMER}
    except httpx.HTTPError as e:
        upstream(e)


@app.get("/advisory")
async def get_advisory(lat: float, lon: float, hazard: str = "flood", rain_mm: float = 0,
                       temp_c: float = 0, rain_pct: float = 0, place: str = "", lang: str = "English"):
    """Plain-language advice for one spot (Amazon Bedrock, with a rule-based fallback)."""
    try:
        if hazard == "heat":
            ctx = await weather.get_heat(lat, lon, temp_c)
            risk = await heat_risk.assess_point(lat, lon, ctx)
        elif hazard == "drought":
            ctx = await drought.get_inputs(lat, lon, rain_pct)
            risk = drought.assess(ctx)
        elif hazard == "flood":
            ctx = await weather.get_forecast(lat, lon, rain_mm)
            risk = await flood_risk.assess_point(lat, lon, ctx)
        else:
            raise HTTPException(422, "hazard must be flood, heat or drought")
        return {**await advisory.advise(risk, ctx, hazard, advisory.clean_place(place), lang_ok(lang)), "level": risk["level"], "disclaimer": DISCLAIMERS[hazard]}
    except httpx.HTTPError as e:
        upstream(e)


@app.post("/ask", dependencies=[guard("ask", 30, 600)])
async def post_ask(req: AskIn):
    """Ask FloodSense: answers a resident's question from the live data for this place (Amazon Bedrock, grounded)."""
    return await ask.answer(req.question.strip(), req.lat, req.lon, advisory.clean_place(req.place), lang_ok(req.lang),
                            (req.rain_mm, req.temp_c, req.rain_pct), [t.model_dump() for t in req.history])


@app.get("/briefing")
async def get_briefing(lat: float, lon: float, place: str = "", lang: str = "English",
                       rain_mm: float = 0, temp_c: float = 0, rain_pct: float = 0):
    """One AI briefing across flood, heat and drought for a spot. A failing data source only drops that hazard."""
    async def flood():
        ctx = await weather.get_forecast(lat, lon, rain_mm)
        return await flood_risk.assess_point(lat, lon, ctx), ctx

    async def heat():
        ctx = await weather.get_heat(lat, lon, temp_c)
        return await heat_risk.assess_point(lat, lon, ctx), ctx

    async def dry():
        ctx = await drought.get_inputs(lat, lon, rain_pct)
        return drought.assess(ctx), ctx

    res = await asyncio.gather(flood(), heat(), dry(), return_exceptions=True)
    parts = {h: (None if isinstance(r, Exception) else r) for h, r in zip(("flood", "heat", "drought"), res)}
    out = await advisory.brief(parts, advisory.clean_place(place), lang_ok(lang))
    return {**out, "disclaimer": "Estimates from public weather, terrain and map data. Not official forecasts or warnings."}


@app.post("/alerts/subscribe", dependencies=[guard("subscribe", 5, 3600)])
async def alerts_subscribe(req: SubscribeIn):
    """Email or SMS alerts for this ~11 km area via Amazon SNS, in the subscriber's language."""
    # at most 3 sign-ups per contact per day, so nobody can use us to spam someone's inbox or phone (hashed, not stored)
    who = hashlib.sha256(req.contact.strip().lower().encode()).hexdigest()[:20]
    if not await asyncio.to_thread(cache.hit, f"contact#{who}", 3, 86400):
        raise HTTPException(429, "Too many sign-ups for this contact today.")
    try:
        return await asyncio.to_thread(alerts.subscribe, req.contact, req.lat, req.lon,
                                       advisory.clean_place(req.place), req.min_level, req.lang)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/alerts/send-now", dependencies=[guard("sendnow", 4, 600)])
async def alerts_send_now(lat: float, lon: float, place: str = "", rain_mm: float = 0, temp_c: float = 0, rain_pct: float = 0):
    """Demo button: build the alert for this spot right now and publish it to the area's subscribers.
    Scenario values are allowed, and then the subject is marked [SIMULATED]."""
    if not await asyncio.to_thread(cache.hit, f"sendarea#{alerts.area_key(lat, lon)}", 1, 120):
        raise HTTPException(429, "An alert was just sent for this area. Please wait two minutes.")
    parts = await monitor.assess_all(lat, lon, rain_mm, temp_c, rain_pct)
    place = advisory.clean_place(place)
    from services import resilience
    res = resilience.score(parts)
    if res["overall"] == "unknown":
        raise HTTPException(503, "Data sources unavailable, try again.")
    safe = await monitor.safe_for(lat, lon, parts, res["overall"])
    subject, body = monitor.alert_text(place, parts, simulated=bool(rain_mm or temp_c or rain_pct), safe=safe)
    sms = monitor.sms_text(place, parts, simulated=bool(rain_mm or temp_c or rain_pct), safe=safe)
    key = alerts.area_key(lat, lon)
    langs = await asyncio.to_thread(alerts.langs_for, key)
    deliveries = await monitor.deliver(key, res["overall"], subject, body, sms, langs)
    return {"deliveries": deliveries, "overall": res["overall"], "resilience": res}


@app.get("/safe-places")
async def get_safe_places(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    """Nearest hospitals, shelters and higher ground (OpenStreetMap + terrain)."""
    try:
        return await safe_places.find(lat, lon)
    except httpx.HTTPError as e:
        upstream(e)


@app.get("/leaks")
async def get_leaks(bbox: str = Query(..., description="south,west,north,east")):
    s, w, n, e = parse_bbox(bbox, 0.2, 0.3)
    items, fixed = await asyncio.to_thread(leaks.split, s, w, n, e)
    items = photos.attach_urls(items)
    return {"leaks": items, "summary": leaks.summary(items), "impact": leaks.impact(fixed)}


@app.post("/leaks", dependencies=[guard("leakpost", 20, 3600)])
async def post_leak(req: LeakIn):
    ds = None
    try:  # drought stress raises the repair priority; skip quietly if the data source is slow
        ds = drought.assess(await asyncio.wait_for(drought.get_inputs(req.lat, req.lon), timeout=8))["score"]
    except Exception:
        pass
    check = None
    if req.photo_key:
        try:
            check = await asyncio.to_thread(photos.check, req.photo_key)
        except ValueError as e:  # photos.Rejected
            raise HTTPException(422, str(e))
    item = await asyncio.to_thread(leaks.create, req.lat, req.lon, req.kind, req.note, ds, False,
                                   req.photo_key if check else "", check)
    return photos.attach_urls([item])[0]


@app.post("/leaks/photo-upload", dependencies=[guard("photo", 20, 3600)])
async def leak_photo_upload():
    """Presigned S3 POST so the browser can upload one leak photo directly to S3."""
    try:
        return await asyncio.to_thread(photos.upload_form)
    except photos.Rejected as e:
        raise HTTPException(501, str(e))


@app.post("/leaks/{leak_id}/fix")
async def fix_leak(leak_id: str):
    if not await asyncio.to_thread(leaks.fix, leak_id):
        raise HTTPException(404, "Leak not found")
    return {"ok": True}


@app.post("/leaks-demo", dependencies=[guard("leakdemo", 10, 3600)])
async def seed_leaks(lat: float, lon: float):
    """Add clearly-labelled sample reports around a point (for demos in any city)."""
    return {"leaks": await asyncio.to_thread(leaks.seed_demo, lat, lon)}


@app.get("/heat-risk")
async def get_heat_risk(lat: float, lon: float, temp_c: float = 0):
    """Heatwave risk at one spot. temp_c > 0 simulates a heatwave (afternoon air temperature)."""
    try:
        heat = await weather.get_heat(lat, lon, temp_c)
        return {**await heat_risk.assess_point(lat, lon, heat), "heat": heat, "disclaimer": DISCLAIMERS["heat"]}
    except httpx.HTTPError as e:
        upstream(e)


@app.get("/heat-zones")
async def get_heat_zones(bbox: str = Query(..., description="south,west,north,east"), temp_c: float = 0, n: int = 10):
    try:
        s, w, nn, e = parse_bbox(bbox)
        heat = await weather.get_heat((s + nn) / 2, (w + e) / 2, temp_c)
        geo = heat_risk.to_geojson(await heat_risk.heat_grid(s, w, nn, e, heat, min(n, 20)))
        return {**geo, "heat": heat, "disclaimer": DISCLAIMERS["heat"]}
    except ValueError:
        raise HTTPException(422, "bbox must be 'south,west,north,east'")
    except httpx.HTTPError as err:
        upstream(err)


@app.get("/drought")
async def get_drought(lat: float, lon: float, rain_pct: float = 0):
    """City-level drought index. rain_pct > 0 simulates 'rain_pct % of normal rainfall' for demos."""
    try:
        d = await drought.get_inputs(lat, lon, rain_pct)
        return {**drought.assess(d), "data": d, "disclaimer": DISCLAIMERS["drought"]}
    except httpx.HTTPError as e:
        upstream(e)


@app.get("/risk-zones")
async def get_risk_zones(bbox: str = Query(..., description="south,west,north,east"), rain_mm: float = 0, n: int = 10):
    try:
        s, w, nn, e = parse_bbox(bbox)
        rain = await weather.get_forecast((s + nn) / 2, (w + e) / 2, rain_mm)
        geo = flood_risk.to_geojson(await flood_risk.risk_grid(s, w, nn, e, rain, min(n, 10)))
        return {**geo, "rain": rain, "disclaimer": DISCLAIMER}
    except ValueError:
        raise HTTPException(422, "bbox must be 'south,west,north,east'")
    except httpx.HTTPError as err:
        upstream(err)


@app.post("/safe-route", dependencies=[guard("route", 30, 600)])
async def post_safe_route(req: RouteRequest):
    from services import routing  # heavy import (osmnx) only when needed
    try:
        rain = await weather.get_forecast(req.start[0], req.start[1], req.rain_mm)
        return {**await routing.safe_route(req.start, req.end, rain), "disclaimer": DISCLAIMER + " Not an evacuation guarantee."}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(503, f"Routing failed: {e}")


_api = Mangum(app) if Mangum else None


def handler(event, context):
    """AWS Lambda entry point: EventBridge schedule -> early-warning monitor, anything else -> the web API."""
    if isinstance(event, dict) and event.get("source") == "aws.events":
        return asyncio.run(monitor.run())
    return _api(event, context)
