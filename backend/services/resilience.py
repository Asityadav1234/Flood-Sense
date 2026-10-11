"""Resilience score (0-100, higher = safer) combining flood, heat and drought risk for one place.

risk = 0.6 * (worst hazard score) + 0.4 * (average of the known hazard scores); resilience = 100 * (1 - risk),
capped at 49 when any hazard is high and at 74 when any is medium, so the label never contradicts the hazard levels.
Emphasising the worst hazard means one severe hazard cannot be hidden by two calm ones. The score is only a
summary of the three explainable rule-based scores; it is not a validated index.
"""
ORDER = {"low": 0, "medium": 1, "high": 2}


def score(parts: dict) -> dict:
    """parts = {hazard: (risk, ctx) or None}"""
    known = {h: v[0] for h, v in parts.items() if v}
    if not known:
        return {"score": None, "label": "unknown", "overall": "unknown", "top_hazard": None, "drivers": []}
    scores = {h: r["score"] for h, r in known.items()}
    # levels decide the headline (same thresholds as each hazard model), scores decide the number
    top = max(known, key=lambda h: (ORDER[known[h]["level"]], scores[h]))
    risk = 0.6 * max(scores.values()) + 0.4 * (sum(scores.values()) / len(scores))
    s = max(0, min(100, round(100 * (1 - risk))))
    s = min(s, 49) if known[top]["level"] == "high" else min(s, 74) if known[top]["level"] == "medium" else s
    label = "Good" if s >= 75 else "Watch" if s >= 50 else "Critical"
    drivers = sorted(({"hazard": h, "level": r["level"], "score": r["score"]} for h, r in known.items()),
                     key=lambda d: -d["score"])
    return {"score": s, "label": label, "overall": known[top]["level"], "top_hazard": top, "drivers": drivers}
