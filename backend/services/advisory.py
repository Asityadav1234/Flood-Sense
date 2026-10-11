"""Plain-language advisories for flood, heat and drought.

Uses Amazon Bedrock (Converse API) to turn the numeric risk factors into 2-3 sentences of advice.
If Bedrock is off, unreachable or not permitted, it falls back to fixed rule-based tips, so the
endpoint never fails because of AWS. The rule-based score stays the source of truth.
"""
import asyncio
import os

from . import resilience

REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
USE_BEDROCK = os.getenv("USE_BEDROCK", "1") == "1"
GUARDRAIL_ID = os.getenv("GUARDRAIL_ID", "")  # optional Amazon Bedrock Guardrail, used for the open-ended /ask

TIPS = {
    "flood": {
        "low": "Low estimated risk. Normal travel is fine, but keep an eye on local weather updates.",
        "medium": "Medium estimated risk. Avoid underpasses and low roads if rain continues, "
                  "keep vehicles on higher ground and charge your phone.",
        "high": "High estimated risk. Avoid travelling through this area during heavy rain, move vehicles "
                "and valuables to higher ground, and follow official advisories.",
    },
    "heat": {
        "low": "Low estimated heat risk. Normal activity is fine; drink water regularly and avoid long sun exposure.",
        "medium": "Medium estimated heat risk. Avoid outdoor work between noon and 4 pm, drink water often, "
                  "wear light clothing and check on elderly neighbours.",
        "high": "High estimated heat risk. Stay indoors in the hottest hours, drink water and ORS regularly, "
                "never leave children or pets in parked vehicles, and seek medical help for dizziness, "
                "confusion or very hot dry skin.",
    },
    "drought": {
        "low": "Low estimated drought risk. Normal water use is fine; fixing leaking taps and pipes still saves water.",
        "medium": "Medium estimated drought risk. Fix leaks, avoid watering plants or washing vehicles in "
                  "the afternoon, and store some drinking water.",
        "high": "High estimated drought risk. Cut non-essential water use, fix every leak, reuse water where safe, "
                "store drinking water, and follow municipal water-supply notices.",
    },
}

_ROLE = {"flood": "flood-safety", "heat": "heatwave-safety", "drought": "water-saving and drought"}


def facts(hazard: str, risk: dict, ctx: dict) -> str:
    f = risk["factors"]
    if hazard == "heat":
        return (f"Feels-like {ctx['feels_like_c']} C (air {ctx['tmax_c']} C, humidity {ctx['humidity_pct']}%), "
                f"{ctx['hot_days']} day(s) of 40 C+ in the next 7. Green/water cover nearby 0-1: {f['green_cover']}. "
                f"Factors 0-1: heat {f['heat']}, exposure {f['exposure']}.")
    if hazard == "drought":
        return (f"Rain last 91 days: {ctx['actual_mm']} mm, {risk['pct_of_normal']}% of normal ({ctx['normal_mm']} mm). "
                f"{ctx['dry_days']} dry days in a row. Evaporation {ctx['et0_mm_day']} mm/day. "
                f"Factors 0-1: rain deficit {f['deficit']}, dry spell {f['dry_spell']}, evaporation {f['evaporative_demand']}.")
    return (f"Rain: {ctx['rain_24h_mm']} mm in 24h, peak {ctx['peak_hourly_mm']} mm/h ({ctx['source']}). "
            f"Ground elevation {risk.get('elevation_m')} m, about {risk['depression_m']} m below its surroundings, "
            f"slope {risk['slope_pct']}%. Factors 0-1: rain {f['rain']}, low-lying {f['low_lying']}, flatness {f['flatness']}.")


LANGS = {"English", "Hindi", "Tamil", "Bengali", "Marathi", "Telugu", "Gujarati", "Kannada", "Malayalam",
         "Punjabi", "Urdu", "Spanish", "French", "Portuguese", "Arabic", "Indonesian", "Swahili"}


def clean_place(p: str) -> str:
    return " ".join((p or "").split())[:80] or "this area"


def _lang_line(lang: str) -> str:
    return "" if lang == "English" else f"Write the answer in {lang}. "


def _prompt(hazard: str, risk: dict, ctx: dict, place: str = "this area", lang: str = "English") -> str:
    return (f"You write short {_ROLE[hazard]} advice for residents of {place}.\n"
            f"Estimated risk level: {risk['level']} (score {risk['score']}).\n{facts(hazard, risk, ctx)}\n"
            "Write 2 or 3 short sentences of practical advice. Use only the facts above. "
            "Say it is an estimate, not an official forecast or warning. Plain text, no markdown, no lists. "
            + _lang_line(lang))


def _invoke(prompt: str, max_tokens: int = 200, guard: bool = False) -> str:
    import boto3  # imported here so the app still starts if boto3 is missing
    from botocore.config import Config

    client = boto3.client("bedrock-runtime", region_name=REGION,
                          config=Config(read_timeout=10, connect_timeout=5, retries={"max_attempts": 1}))
    extra = {"guardrailConfig": {"guardrailIdentifier": GUARDRAIL_ID, "guardrailVersion": "DRAFT"}} if guard and GUARDRAIL_ID else {}
    r = client.converse(modelId=MODEL_ID, messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3}, **extra)
    return r["output"]["message"]["content"][0]["text"].strip()


async def advise(risk: dict, ctx: dict, hazard: str = "flood", place: str = "this area", lang: str = "English") -> dict:
    note = "Bedrock disabled (USE_BEDROCK=0)"
    if USE_BEDROCK:
        try:
            text = await asyncio.wait_for(asyncio.to_thread(_invoke, _prompt(hazard, risk, ctx, place, lang)), timeout=15)
            if text:
                return {"advisory": text, "source": "Amazon Bedrock", "model": MODEL_ID}
            note = "Bedrock returned an empty answer"
        except Exception as e:  # never let AWS problems break the app
            note = f"Bedrock unavailable ({type(e).__name__})"
    return {"advisory": TIPS[hazard][risk["level"]], "source": "rule-based fallback (English)", "note": note}


ORDER = {"low": 0, "medium": 1, "high": 2}


async def brief(parts: dict, place: str = "this area", lang: str = "English") -> dict:
    """One combined briefing across hazards. parts = {hazard: (risk, ctx) or None}. Never raises."""
    levels = {h: (v[0]["level"] if v else None) for h, v in parts.items()}
    known = {h: l for h, l in levels.items() if l}
    overall = max(known.values(), key=ORDER.get) if known else "unknown"
    top = max(known, key=lambda h: ORDER[known[h]]) if known else None
    res = {"levels": levels, "overall": overall, "resilience": resilience.score(parts)}
    note = "Bedrock disabled (USE_BEDROCK=0)"
    if USE_BEDROCK and known:
        lines = "\n".join(f"- {h.upper()} ({v[0]['level']}, score {v[0]['score']}): {facts(h, v[0], v[1])}"
                          for h, v in parts.items() if v)
        prompt = (f"You are a city resilience assistant writing a daily briefing for residents of {place}.\n{lines}\n"
                  "Write 3 or 4 short sentences: start with the most serious hazard, give the most useful action, and if "
                  "drought risk is medium or high also say that fixing and reporting water leaks helps. Use only the facts above. "
                  "Say these are estimates, not official forecasts or warnings. Plain text, no markdown, no lists. "
                  + _lang_line(lang))
        try:
            text = await asyncio.wait_for(asyncio.to_thread(_invoke, prompt, 300), timeout=18)
            if text:
                return {**res, "briefing": text, "source": "Amazon Bedrock", "model": MODEL_ID}
        except Exception as e:
            note = f"Bedrock unavailable ({type(e).__name__})"
    if top:
        text = f"Highest estimated risk right now: {top} ({known[top]}). " + TIPS[top][known[top]]
    else:
        text = "Not enough data to build a briefing right now. Please try again."
    return {**res, "briefing": text, "source": "rule-based fallback (English)", "note": note}


async def translate(text: str, lang: str, max_tokens: int = 700) -> str:
    """Translate an alert with Amazon Bedrock. Falls back to the English text if Bedrock is off or fails,
    so an alert is never lost because of translation."""
    if lang == "English" or not USE_BEDROCK or not text.strip():
        return text
    prompt = (f"Translate this public safety alert into {lang}. Keep every number, unit, place name and hospital name "
              "exactly as written, keep the line breaks and dashes, do not add, remove or soften any information, and keep "
              "the sentence that says it is an estimate and not an official warning. Output only the translation, "
              f"plain text.\n\n{text}")
    try:
        out = await asyncio.wait_for(asyncio.to_thread(_invoke, prompt, max_tokens), timeout=20)
        return out or text
    except Exception:
        return text
