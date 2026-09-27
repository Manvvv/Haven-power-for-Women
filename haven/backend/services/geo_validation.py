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
