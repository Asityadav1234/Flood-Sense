"""Scheduled early-warning monitor (Amazon EventBridge -> same Lambda).

For every watched area: compute flood + heat + drought, and publish an SNS alert when the overall level is
medium/high and has risen (or a day has passed). A failing data source only drops that hazard, like /briefing.
"""
import asyncio

from . import advisory, alerts, drought, flood_risk, heat_risk, resilience, safe_places, weather


async def assess_all(lat: float, lon: float, rain_mm: float = 0, temp_c: float = 0, rain_pct: float = 0) -> dict:
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
    return {h: (None if isinstance(r, Exception) else r) for h, r in zip(("flood", "heat", "drought"), res)}


async def safe_for(lat: float, lon: float, parts: dict, overall: str) -> dict | None:
    """Nearby hospitals / shelters / higher ground for medium+ alerts. Never raises: alerts must go out regardless."""
    if overall not in ("medium", "high"):
        return None
    try:
        return await asyncio.wait_for(safe_places.find(lat, lon), timeout=25)
    except Exception:
        return None


SHORT = {
    "flood": {"medium": "Avoid underpasses and low roads.", "high": "Avoid low roads, move vehicles and people to higher ground."},
    "heat": {"medium": "Avoid sun from noon to 4 pm, drink water.", "high": "Stay indoors, drink water and ORS, check on the elderly."},
    "drought": {"medium": "Fix leaks, store some drinking water.", "high": "Cut non-essential water use, store drinking water."},
}


def sms_text(place: str, parts: dict, simulated: bool = False, safe: dict | None = None) -> str:
    """One short SMS (about 250 characters): level, top hazard, one action, nearest hospital."""
    res = resilience.score(parts)
    top, lvl = res["top_hazard"], res["overall"]
    msg = (f"{'[SIMULATED] ' if simulated else ''}FloodSense {lvl.upper()} risk, {place[:30]}: {top} {lvl}. "
           f"{SHORT[top][lvl]}")
    hosp = next((p for p in (safe or {}).get("places", []) if p["kind"] == "hospital"), None)
    if hosp:
        msg += f" Hospital: {hosp['name'][:30]}, {safe_places.km(hosp['distance_m'])}."
    return msg + " Estimate, not an official warning."


async def localize(subject: str, body: str, sms: str, lang: str) -> tuple[str, str, str]:
    """Translate subject, email body and SMS into `lang` (Amazon Bedrock). The email also keeps the English original
    below the translation so a wrong translation can never hide the facts."""
    if lang == "English":
        return subject, body, sms
    s, b, m = await asyncio.gather(advisory.translate(subject, lang, 100), advisory.translate(body, lang, 900),
                                   advisory.translate(sms, lang, 250))
    return s, (b if b == body else f"{b}\n\n--- English original ---\n{body}"), m


async def deliver(area: str, level: str, subject: str, body: str, sms: str, langs: list) -> list:
    """Publish one translated message per subscriber language through Amazon SNS."""
    msgs = await asyncio.gather(*(localize(subject, body, sms, l) for l in langs))
    return [await asyncio.to_thread(alerts.publish, area, level, s, b, m, l) for l, (s, b, m) in zip(langs, msgs)]


def alert_text(place: str, parts: dict, simulated: bool = False, safe: dict | None = None) -> tuple[str, str]:
    res = resilience.score(parts)
    top = res["top_hazard"]
    tag = "[SIMULATED] " if simulated else ""
    subject = f"{tag}FloodSense: {res['overall']} risk for {place} ({top})"
    lines = [f"{tag}FloodSense AI early warning for {place}", "",
             f"Resilience score: {res['score']}/100 ({res['label']})"]
    lines += [f"- {d['hazard'].title()}: {d['level']}" for d in res["drivers"]]
    flood_up = bool(parts.get("flood")) and parts["flood"][0]["level"] in ("medium", "high")
    lines += safe_places.alert_lines(safe, flood_up)
    lines += ["", advisory.TIPS[top][res["overall"]], "",
              "This is an automated estimate from public weather, terrain and map data. It is not an official "
              "forecast or warning. Follow your national weather service and local authority advisories."]
    return subject, "\n".join(lines)


async def run() -> dict:
    sent, checked = 0, 0
    for w in alerts.watch_list():
        checked += 1
        try:
            parts = await asyncio.wait_for(assess_all(w["lat"], w["lon"]), timeout=45)
            res = resilience.score(parts)
            if res["overall"] == "unknown":
                continue
            if alerts.should_send(res["overall"], w["last_level"], w["last_sent"]):
                safe = await safe_for(w["lat"], w["lon"], parts, res["overall"])
                subject, body = alert_text(w["place"], parts, safe=safe)
                await deliver(w["area"], res["overall"], subject, body, sms_text(w["place"], parts, safe=safe), w["langs"])
                alerts.watch_mark(w["area"], res["overall"])
                sent += 1
        except Exception as e:  # one bad area must not stop the others
            print(f"monitor: {w.get('area')} failed: {type(e).__name__}: {e}")
    return {"checked": checked, "alerts_sent": sent}
