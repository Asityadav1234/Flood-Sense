"""Proactive alerts: Amazon SNS (email) + a watch list of areas in DynamoDB.

Flow: a person subscribes an email to an ~11 km area cell. SNS filter policies on the message attributes
`area` and `level` make sure each subscriber only gets alerts for their area at or above their chosen level.
An EventBridge schedule (see monitor.py) re-checks every watched area and publishes when risk rises.

Channels: email and SMS (SNS delivers one JSON message with an email body and a short SMS body). Each subscriber picks a
language; the monitor publishes one translated message per language with a `lang` message attribute, and the
subscription filter policy (area + level + lang) routes it. SMS caveats: new AWS accounts are in the SNS SMS sandbox
(destination numbers must be verified) and India needs DLT sender/template registration for real delivery.

Local dev: without ALERTS_TOPIC_ARN / WATCH_TABLE nothing leaves the machine; subscribers and the message that
WOULD have been sent are kept in memory so the whole flow can still be demoed.
"""
import json
import os
import re
import time

TOPIC_ARN = os.getenv("ALERTS_TOPIC_ARN", "")
WATCH_TABLE = os.getenv("WATCH_TABLE", "")
LEVELS = ["low", "medium", "high"]
MAX_WATCH = 25          # areas checked per scheduled run (keeps the Lambda inside its timeout)
RESEND_AFTER_S = 24 * 3600
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

_watch: dict = {}       # local-dev stand-in for the DynamoDB watch table
_subs: list = []
_outbox: list = []


def area_key(lat: float, lon: float) -> str:
    return f"{round(lat, 1):.1f},{round(lon, 1):.1f}"


def levels_from(min_level: str) -> list:
    return LEVELS[LEVELS.index(min_level):]


def _sns():
    import boto3
    return boto3.client("sns")


def _tbl():
    import boto3
    return boto3.resource("dynamodb").Table(WATCH_TABLE)


def subscribe(contact: str, lat: float, lon: float, place: str, min_level: str = "medium", lang: str = "English") -> dict:
    """contact = an email address or a phone number in international format (+91...)."""
    from .advisory import LANGS
    contact = contact.strip()
    kind = "sms" if PHONE_RE.match(contact.replace(" ", "")) else "email" if EMAIL_RE.match(contact) else None
    if not kind:
        raise ValueError("Enter a valid email address, or a phone number with country code like +919812345678.")
    if kind == "sms":
        contact = contact.replace(" ", "")
    if min_level not in LEVELS:
        raise ValueError("min_level must be low, medium or high.")
    if lang not in LANGS:
        raise ValueError("Unsupported language.")
    key = area_key(lat, lon)
    watch_add(key, lat, lon, place, lang)
    if not TOPIC_ARN:
        _subs.append({"contact": contact, "protocol": kind, "area": key, "min_level": min_level, "lang": lang})
        return {"area": key, "mode": "local", "channel": kind, "lang": lang,
                "message": f"Local mode: {kind} subscription kept in memory (nothing is sent)."}
    _sns().subscribe(TopicArn=TOPIC_ARN, Protocol=kind, Endpoint=contact, ReturnSubscriptionArn=True,
                     Attributes={"FilterPolicy": json.dumps({"area": [key], "level": levels_from(min_level), "lang": [lang]}),
                                 "FilterPolicyScope": "MessageAttributes"})
    msg = ("Check your inbox and confirm the Amazon SNS email to start receiving alerts."
           if kind == "email" else
           "SMS subscription created. New AWS accounts are in the SNS SMS sandbox, so the number must be verified in SNS first; "
           "in India, delivery also needs DLT registration.")
    return {"area": key, "mode": "sns", "channel": kind, "lang": lang, "message": msg}


def publish(key: str, level: str, subject: str, body: str, sms: str | None = None, lang: str = "English") -> dict:
    """One message for one language. With `sms`, SNS sends the long body to email and the short text to SMS."""
    if not TOPIC_ARN:
        n = sum(1 for s in _subs if s["area"] == key and s["lang"] == lang and LEVELS.index(level) >= LEVELS.index(s["min_level"]))
        _outbox.append({"area": key, "level": level, "lang": lang, "subject": subject, "body": body, "sms": sms, "recipients": n})
        return {"mode": "local", "lang": lang, "recipients": n, "subject": subject, "body": body, "sms": sms}
    kw = {"Message": body}
    if sms:
        kw = {"Message": json.dumps({"default": body, "email": body, "sms": sms}), "MessageStructure": "json"}
    r = _sns().publish(TopicArn=TOPIC_ARN, Subject=subject[:99],
                       MessageAttributes={"area": {"DataType": "String", "StringValue": key},
                                          "level": {"DataType": "String", "StringValue": level},
                                          "lang": {"DataType": "String", "StringValue": lang}}, **kw)
    return {"mode": "sns", "lang": lang, "message_id": r["MessageId"], "subject": subject}


# ---- watch list (which areas the scheduled monitor should check) ----
def watch_add(key: str, lat: float, lon: float, place: str, lang: str = "English") -> None:
    item = {"area": key, "lat": str(round(lat, 4)), "lon": str(round(lon, 4)), "place": (place or "this area")[:80]}
    if WATCH_TABLE:
        _tbl().update_item(Key={"area": key},
                           UpdateExpression="SET lat=:a, lon=:o, place=:p, #t=:t ADD langs :l",
                           ExpressionAttributeNames={"#t": "ttl"},
                           ExpressionAttributeValues={":a": item["lat"], ":o": item["lon"], ":p": item["place"],
                                                      ":t": int(time.time()) + 90 * 86400, ":l": {lang}})
    else:
        w = _watch.setdefault(key, {**item, "last_level": "low", "last_sent": 0, "langs": set()})
        w["langs"].add(lang)


def langs_for(key: str) -> list:
    """Languages people subscribed with for this area (English if unknown)."""
    if WATCH_TABLE:
        got = _tbl().get_item(Key={"area": key}).get("Item", {})
    else:
        got = _watch.get(key, {})
    return sorted(got.get("langs") or {"English"})


def watch_list() -> list:
    rows = _tbl().scan(Limit=MAX_WATCH).get("Items", []) if WATCH_TABLE else list(_watch.values())
    return [{**r, "lat": float(r["lat"]), "lon": float(r["lon"]), "last_level": r.get("last_level", "low"),
             "last_sent": int(r.get("last_sent", 0)),
             "langs": sorted(r.get("langs") or {"English"})} for r in rows][:MAX_WATCH]


def watch_mark(key: str, level: str) -> None:
    now = int(time.time())
    if WATCH_TABLE:
        _tbl().update_item(Key={"area": key}, UpdateExpression="SET last_level=:l, last_sent=:s",
                           ExpressionAttributeValues={":l": level, ":s": now})
    elif key in _watch:
        _watch[key].update(last_level=level, last_sent=now)


def should_send(level: str, last_level: str, last_sent: int) -> bool:
    """Alert on medium+ risk, but only when it got worse, or once a day if it stays elevated (no spam)."""
    if LEVELS.index(level) < 1:
        return False
    return LEVELS.index(level) > LEVELS.index(last_level) or time.time() - last_sent > RESEND_AFTER_S
