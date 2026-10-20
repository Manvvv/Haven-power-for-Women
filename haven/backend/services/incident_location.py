"""Canonical incident-location resolution for the Rapid Response Network.

ONE place that turns any location representation HAVEN genuinely stores into a
single validated numeric WGS84 point. The dispatch resolver and every SOS
creation path funnel through here so "what the authority sees on the case card"
and "what dispatch resolves server-side" can never diverge again.

SECURITY (unchanged by this module): resolution only ever reads a location that
was already persisted to the case/event by the VICTIM's own client at SOS time
(or pushed over the live GPS stream). It must NEVER be fed coordinates from a
dispatch REQUEST BODY — that trust rule lives in the caller
(routers/dispatch_routes resolves exclusively from stored docs + the live
cache). Dispatch remains authority-triggered and server-side; this module
changes only HOW a stored fix is parsed, not WHO may dispatch nor WHERE the
coordinates come from.

Supported stored shapes (the app genuinely uses all of these), each normalized
to one canonical (lng, lat) float pair inside [-180,180]x[-90,90]:
  1. Numeric top-level fields:  {"latitude": <num>, "longitude": <num>}
     — the voice sos_events row, any row updated via POST /sos/location-update,
       and the live /ws/track cache. This is the machine-written canonical form.
  2. GeoJSON Point:  {"<key>": {"type": "Point", "coordinates": [lng, lat]}}
     for key in location / incident_location / current_location / last_location.
  3. Coordinate STRING "lat, lng" (or "lat,lng"):  {"location": "28.69, 77.46"}
     — the voice sos_cases row and the panic/steganography case store the fix
       this way; it is exactly the string the authority card renders. A free-text
       place name (no numeric pair) yields NO point: we never geocode or guess.

Priority within one document is numeric > GeoJSON > string, because the numeric
fields are canonical and the string is only a human-readable mirror.
"""
import re
from typing import Any, Dict, Optional, Tuple

from services.geo_validation import (
    finite_or_none, finite_in_range, LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX,
)

Point = Tuple[float, float]  # canonical (lng, lat)

_GEOJSON_KEYS = ("location", "incident_location", "current_location", "last_location")

# A coordinate pair: two signed decimals separated by a comma (optional spaces).
# Anchored end-to-end so a place name like "Near MG Road, Bengaluru" does NOT
# match — only a bare numeric pair is treated as a fix.
_COORD_RE = re.compile(r"^\s*([+-]?\d{1,3}(?:\.\d+)?)\s*,\s*([+-]?\d{1,3}(?:\.\d+)?)\s*$")


def _valid_point(lng: Any, lat: Any) -> Optional[Point]:
    """Coerce (lng, lat) to finite floats in range, or None. Never fabricates."""
    lng_f = finite_or_none(lng)
    lat_f = finite_or_none(lat)
    if lng_f is None or lat_f is None:
        return None
    if not (finite_in_range(lng_f, LNG_MIN, LNG_MAX) and finite_in_range(lat_f, LAT_MIN, LAT_MAX)):
        return None
    return (lng_f, lat_f)


def parse_coordinate_text(text: Any) -> Optional[Point]:
    """Parse a stored "lat, lng" string into canonical (lng, lat), or None.

    HAVEN stores the human-readable mirror as "<lat>, <lng>" (voice SOS and the
    PanicButton), so the FIRST number is latitude and the SECOND is longitude.
    Returns None for empty text, place names, or an out-of-range pair.
    """
    if not isinstance(text, str):
        return None
    m = _COORD_RE.match(text)
    if not m:
        return None
    lat_s, lng_s = m.group(1), m.group(2)
    return _valid_point(lng_s, lat_s)


def point_from_document(doc: Optional[Dict[str, Any]]) -> Optional[Point]:
    """Extract one canonical (lng, lat) from a case/event-like document, or None."""
    if not isinstance(doc, dict):
        return None
    # 1. Numeric top-level latitude/longitude (canonical machine form).
    p = _valid_point(doc.get("longitude"), doc.get("latitude"))
    if p:
        return p
    # 2. GeoJSON Point under any known key: coordinates are [lng, lat].
    for key in _GEOJSON_KEYS:
        val = doc.get(key)
        if isinstance(val, dict):
            coords = val.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                p = _valid_point(coords[0], coords[1])
                if p:
                    return p
    # 3. Human-readable coordinate string mirror (the card's text).
    for key in ("location", "location_text", "current_location"):
        p = parse_coordinate_text(doc.get(key))
        if p:
            return p
    return None


def resolve_incident_point(
    live_fix: Optional[Dict[str, Any]],
    event_doc: Optional[Dict[str, Any]],
    case_doc: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Resolve the canonical incident point + case owner from stored sources.

    Priority of location truth: the live GPS stream, then the sos_events row,
    then the sos_cases row — the first that yields a VALID point wins. Owner
    (victim_user_id) and jurisdiction are taken from the event then the case
    regardless of which source carried the coordinates. Returns
    (lng, lat, victim_user_id, jurisdiction); lng/lat are both None when NO
    source carries a valid fix, so the caller can refuse to dispatch rather than
    invent a location.
    """
    victim_user_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    for d in (event_doc, case_doc):
        if isinstance(d, dict):
            if not victim_user_id and d.get("user_id"):
                victim_user_id = str(d.get("user_id"))
            if not jurisdiction and d.get("jurisdiction"):
                jurisdiction = d.get("jurisdiction") or None

    for source in (live_fix, event_doc, case_doc):
        p = point_from_document(source)
        if p:
            lng, lat = p
            return lng, lat, victim_user_id, jurisdiction
    return None, None, victim_user_id, jurisdiction


def canonical_coord_fields(
    latitude: Any = None, longitude: Any = None, location_text: Any = None,
) -> Dict[str, float]:
    """Canonical numeric fields to PERSIST on a case/event, or {} if no valid fix.

    SOS creation paths call this so every row they write carries the numeric
    `latitude`/`longitude` the resolver and the authority map expect — not only a
    human-readable string. The fix may come from explicit numeric inputs OR be
    parsed from a "lat, lng" string the client supplied. Never fabricates:
    unknown/invalid input yields {} and the row simply has no numeric fix.
    """
    p = _valid_point(longitude, latitude)
    if p is None:
        p = parse_coordinate_text(location_text)
    if p is None:
        return {}
    lng, lat = p
    return {"latitude": lat, "longitude": lng}
