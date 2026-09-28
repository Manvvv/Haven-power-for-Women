"""
Deterministic, advisory abuse / anomaly signal — SEPARATE from emergency_risk.

WHY THIS EXISTS (spec: "abuse_risk / suspicious_activity_score must be SEPARATE
from emergency_risk; authority review is final; no auto-punishment; never
auto-classify a user as 'fake'"):
    HAVEN needs a way to flag telemetry that looks physically impossible or
    automated (possible GPS spoofing, a script hammering the location endpoint)
    so a HUMAN investigator can glance at data quality. It must NEVER be allowed
    to weaken the emergency response.

HARD RULES enforced by design (do not change without the spec changing):
  * This signal is ADVISORY ONLY. It never rejects a location fix, never changes
    SOS severity/status/dispatch, and never suspends or labels a user.
  * It is fully DECOUPLED from emergency_risk. A high implied speed can be
    entirely real (a woman in a moving car / train / being driven away by an
    abductor), so a movement flag is a *data-quality* note, not a reason to doubt
    the victim. `affects_emergency_response` is a constant False.
  * It is DETERMINISTIC and explainable — pure `math`/`datetime`, no model, no
    LLM. Every factor reports the OBSERVABLE evidence (distance, dt, implied
    speed), never hidden reasoning.
  * A human is always the final decision-maker; the strongest output this module
    produces is `flagged_for_review = True`.

Pure standard library so it runs on a fresh checkout and is unit-testable
without FastAPI/pymongo.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

MODULE_VERSION = "anomaly-signal-v1"

EARTH_RADIUS_M = 6_371_000.0

# WGS84 bounds (mirror services.geo_validation so we reject identical bad input).
_LAT_MIN, _LAT_MAX = -90.0, 90.0
_LNG_MIN, _LNG_MAX = -180.0, 180.0

# ── Physical-plausibility thresholds for movement between two consecutive fixes ─
# These flag DATA-QUALITY / possible-spoofing concerns only. A high implied speed
# can be perfectly legitimate, so a flag is advisory and NEVER downgrades the
# emergency or rejects the fix.
IMPROBABLE_SPEED_MPS = 150.0     # ~540 km/h — above any ground vehicle; plausibly a plane
IMPOSSIBLE_SPEED_MPS = 1200.0    # ~4320 km/h — beyond commercial aviation; implies bad data/spoof
MIN_DT_SECONDS = 0.5             # ignore sub-second dt (clock jitter → meaningless speed)

# Update-flooding: many fixes in a short window suggests an automated sender.
BURST_WINDOW_S = 10.0
BURST_MAX_UPDATES = 25           # > this many fixes within the window = flooding

# Advisory levels — deliberately NOT the emergency severity vocabulary
# (LOW/MODERATE/HIGH/CRITICAL) so the two can never be confused or conflated.
NONE = "none"
NOTICE = "notice"
REVIEW = "review"

# Per-factor advisory weights (sum, capped at 100). Tuned so a single "impossible"
# reading crosses the REVIEW line on its own, while a merely "improbable" one does not.
_WEIGHTS = {
    "impossible_travel_speed": 70,
    "improbable_travel_speed": 30,
    "non_monotonic_timestamp": 20,
    "update_flooding": 30,
}
_REVIEW_AT = 60
_NOTICE_AT = 25


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _coords(fix) -> "tuple | None":
    """Return (lat, lon) if the fix carries a valid finite in-range coordinate."""
    if not isinstance(fix, dict):
        return None
    try:
        lat = float(fix.get("latitude"))
        lon = float(fix.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (_LAT_MIN <= lat <= _LAT_MAX and _LNG_MIN <= lon <= _LNG_MAX):
        return None
    return (lat, lon)


def _to_epoch(ts) -> "float | None":
    """Parse an ISO-8601 string or numeric epoch into epoch seconds (UTC).

    Naive timestamps are treated as UTC (the backend emits tz-less UTC via
    datetime.utcnow().isoformat()). Returns None for missing/unparseable input —
    the caller then simply omits the speed computation (never fabricates one).
    """
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        f = float(ts)
        return f if math.isfinite(f) else None
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def movement(prev_fix, curr_fix) -> "dict | None":
    """Observable movement between two fixes, or None if it can't be computed.

    Each fix is a dict with latitude/longitude and a timestamp
    (`timestamp` or `location_timestamp`). Returns
    {distance_m, dt_seconds, speed_mps} where dt_seconds/speed_mps are None when
    the timestamps are missing/unusable — NEVER fabricated.
    """
    p, c = _coords(prev_fix), _coords(curr_fix)
    if p is None or c is None:
        return None
    dist = haversine_m(p[0], p[1], c[0], c[1])
    t0 = _to_epoch(prev_fix.get("timestamp") or prev_fix.get("location_timestamp"))
    t1 = _to_epoch(curr_fix.get("timestamp") or curr_fix.get("location_timestamp"))
    dt = (t1 - t0) if (t0 is not None and t1 is not None) else None
    speed = dist / dt if (dt is not None and dt >= MIN_DT_SECONDS) else None
    return {"distance_m": round(dist, 2), "dt_seconds": dt, "speed_mps": speed}


def _empty_signal() -> dict:
    """A clean 'nothing anomalous' advisory result."""
    return {
        "abuse_risk_score": 0,
        "level": NONE,
        "factors": [],
        "advisory_only": True,            # constant — this signal NEVER auto-acts
        "affects_emergency_response": False,  # constant — decoupled from SOS severity/dispatch
        "flagged_for_review": False,
        "module_version": MODULE_VERSION,
    }


def assess(prev_fix, curr_fix, recent_update_epochs=None) -> dict:
    """Produce the advisory abuse/anomaly signal for a new location fix.

    Inputs:
      prev_fix / curr_fix   — location dicts (see `movement`). prev_fix may be
                              None/absent (first fix of an event → no movement
                              factor, which is correct, not suspicious).
      recent_update_epochs  — optional list of epoch-second timestamps of recent
                              fixes for this event, used ONLY to detect automated
                              flooding. Omitted → no flooding factor.

    Returns an advisory dict (see `_empty_signal`). Guarantees:
      * `advisory_only` and `affects_emergency_response` are constants (True /
        False) — this output must never gate or downgrade the emergency.
      * `factors[*].observed` carries the raw evidence (distance/dt/speed/count),
        so the flag is fully explainable and contains no hidden reasoning.
    """
    sig = _empty_signal()
    factors = []

    mv = movement(prev_fix, curr_fix)
    if mv is not None:
        dt = mv["dt_seconds"]
        speed = mv["speed_mps"]
        # Timestamp went backwards (out-of-order / rewound clock) — data-quality flag.
        if dt is not None and dt < 0:
            factors.append({
                "code": "non_monotonic_timestamp",
                "detail": "New fix timestamp is earlier than the previous fix.",
                "observed": {"dt_seconds": round(dt, 3)},
            })
        if speed is not None:
            kmh = round(speed * 3.6, 1)
            if speed >= IMPOSSIBLE_SPEED_MPS:
                factors.append({
                    "code": "impossible_travel_speed",
                    "detail": (f"Implied speed {kmh} km/h between consecutive fixes "
                               "exceeds any real-world travel; likely spoofed or bad data."),
                    "observed": {"distance_m": mv["distance_m"], "dt_seconds": round(dt, 3),
                                 "speed_kmh": kmh},
                })
            elif speed >= IMPROBABLE_SPEED_MPS:
                factors.append({
                    "code": "improbable_travel_speed",
                    "detail": (f"Implied speed {kmh} km/h is unusually high (possible aircraft "
                               "or telemetry error). Advisory only — may be legitimate."),
                    "observed": {"distance_m": mv["distance_m"], "dt_seconds": round(dt, 3),
                                 "speed_kmh": kmh},
                })

    # Update flooding — automated sender hammering the endpoint (advisory only).
    if recent_update_epochs:
        try:
            epochs = sorted(float(e) for e in recent_update_epochs if e is not None)
        except (TypeError, ValueError):
            epochs = []
        if epochs:
            newest = epochs[-1]
            in_window = sum(1 for e in epochs if newest - e <= BURST_WINDOW_S)
            if in_window > BURST_MAX_UPDATES:
                factors.append({
                    "code": "update_flooding",
                    "detail": (f"{in_window} location updates within {int(BURST_WINDOW_S)}s "
                               "suggests an automated sender."),
                    "observed": {"updates_in_window": in_window,
                                 "window_seconds": BURST_WINDOW_S},
                })

    if not factors:
        return sig

    score = min(100, sum(_WEIGHTS.get(f["code"], 0) for f in factors))
    level = REVIEW if score >= _REVIEW_AT else (NOTICE if score >= _NOTICE_AT else NONE)
    sig["abuse_risk_score"] = score
    sig["level"] = level
    sig["factors"] = factors
    sig["flagged_for_review"] = level == REVIEW
    return sig
