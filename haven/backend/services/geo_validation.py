"""Pure, dependency-free geo/telemetry validation helpers.

Extracted so the SAME validation runs on both the REST location-update path
(routers/sos_routes.py) and the WebSocket live-stream path (main.py), and so the
logic can be unit-tested without importing FastAPI/pymongo. Imports only `math`.

Design rule (spec: "Do not fabricate missing accuracy/speed/heading"):
  * finite_in_range → strict validation gate (reject NaN/±inf/out-of-range).
  * finite_or_none  → coerce a client value to a finite float, else None, so the
    caller can include a field ONLY when the device genuinely supplied it.
"""
import math

# Canonical bounds shared by REST + WS so both reject identical bad telemetry.
LAT_MIN, LAT_MAX = -90.0, 90.0
LNG_MIN, LNG_MAX = -180.0, 180.0
ACCURACY_MAX = 100_000.0     # metres — generous ceiling, rejects absurd values
SPEED_MAX = 12_000.0         # m/s — above any real ground/air speed
HEADING_MAX = 360.0          # degrees


def finite_in_range(value, lo, hi) -> bool:
    """True only if value is a real, finite number within [lo, hi]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(f):
        return False
    return lo <= f <= hi


def finite_or_none(value):
    """Return value as a finite float, or None if missing/NaN/±inf/non-numeric."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# Mean Earth radius (metres) — WGS84 mean, matches MongoDB 2dsphere's sphere model
# closely enough for a straight-line (great-circle) distance estimate.
_EARTH_RADIUS_M = 6_371_008.8


def haversine_meters(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two WGS84 points, or None.

    STRAIGHT-LINE only — this is NOT a routed/road distance and must never be
    presented as an ETA or drive time (the Rapid Response Network reports
    distance_type="straight_line" and eta_minutes=null). Returns None if any
    coordinate is missing/NaN/±inf/out-of-range so callers never fabricate a
    distance from bad input.
    """
    a_lat = finite_or_none(lat1)
    a_lng = finite_or_none(lng1)
    b_lat = finite_or_none(lat2)
    b_lng = finite_or_none(lng2)
    if a_lat is None or a_lng is None or b_lat is None or b_lng is None:
        return None
    if not (LAT_MIN <= a_lat <= LAT_MAX and LAT_MIN <= b_lat <= LAT_MAX):
        return None
    if not (LNG_MIN <= a_lng <= LNG_MAX and LNG_MIN <= b_lng <= LNG_MAX):
        return None
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlmb = math.radians(b_lng - a_lng)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))
