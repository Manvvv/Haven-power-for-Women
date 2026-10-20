"""Rapid Response Network — incident-location resolution regression suite.

Proves the fix for the reported bug: the Authority Dashboard case card shows GPS
coordinates (rendered from the case `location` string) while POST /dispatch
returned 409 "No known incident location". Root cause was a representation
mismatch — several SOS creation paths persisted the fix only as a human-readable
"lat, lng" STRING (and, for voice SOS, numeric coords only on the sos_event, not
the case), while the dispatch resolver read only numeric top-level
latitude/longitude. The canonical resolver (services.incident_location) now
understands every stored shape, and the creation paths persist the canonical
numeric fields.

Covers the user's required scenarios A–G plus the MANDATORY proof test:
  A  valid stored GPS            -> resolver returns the point (dispatch proceeds)
  B  no GPS at all               -> resolver returns (None, None) (dispatch 409)
  C  malformed / out-of-range    -> rejected (None), never fabricated
  D  coords visible on the card  -> resolver recognizes the SAME coordinates  <-- PROOF
  E  fake request-body coords    -> ignored; only stored docs/live stream resolve
  F  existing /sos/location-update numeric write still resolves
  G  GeoJSON [lng, lat] ordering (and "lat, lng" string ordering) is correct

Runs under pytest OR standalone (`python test_incident_location.py`), using the
same dependency shims as the engine suite so it works in an offline sandbox.
"""
import sys

import _rrn_test_support  # noqa: F401  (installs dep shims only when missing)

from services import incident_location as il
import routers.dispatch_routes as dr

# The exact coordinates from the user's report (card string "28.6983808, 77.461374").
RPT_LAT, RPT_LNG = 28.6983808, 77.461374


class _FakeCollection:
    """Minimal find_one over a list of docs, honouring an exact-match query dict
    and a projection that drops _id — enough to mirror the resolver's two reads
    ({"event_id": id} on sos_events, {"case_id": id} on sos_cases)."""

    def __init__(self, docs):
        self._docs = list(docs)

    def find_one(self, query, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                out = dict(d)
                out.pop("_id", None)
                return out
        return None


class _FakeTracking:
    def __init__(self, latest=None):
        self.latest_locations = dict(latest or {})


def _patch_stores(events=None, cases=None, live=None):
    """Point the real dr._resolve_incident_location at fake stores + live cache.

    Returns a restore() callable. This exercises the PRODUCTION resolver end to
    end (its DB reads + the canonical resolver), never the request body."""
    saved_ev, saved_cs = dr.sos_events, dr.sos_cases
    dr.sos_events = lambda: _FakeCollection(events or [])
    dr.sos_cases = lambda: _FakeCollection(cases or [])
    fake_main = type(sys)("main")
    fake_main.tracking_manager = _FakeTracking(live or {})
    saved_main = sys.modules.get("main")
    sys.modules["main"] = fake_main

    def restore():
        dr.sos_events, dr.sos_cases = saved_ev, saved_cs
        if saved_main is not None:
            sys.modules["main"] = saved_main
        else:
            sys.modules.pop("main", None)

    return restore


# ── Documents EXACTLY as each creation path writes them (ground truth) ─────────
def voice_case_doc(case_id="VSOS-1", user="U-1"):
    """What routers/voice_routes.py writes to sos_cases AFTER the fix: the
    human-readable string the card shows PLUS the canonical numeric fields."""
    doc = {
        "case_id": case_id, "user_id": user, "trigger_type": "voice_sos",
        "location": f"{RPT_LAT}, {RPT_LNG}", "status": "RECEIVED",
    }
    doc.update(il.canonical_coord_fields(RPT_LAT, RPT_LNG))
    return doc


def voice_event_doc(case_id="VSOS-1", user="U-1"):
    """What routers/voice_routes.py writes to sos_events (numeric coords)."""
    return {"event_id": case_id, "user_id": user, "trigger_type": "voice_code",
            "latitude": RPT_LAT, "longitude": RPT_LNG, "status": "triggered"}


def panic_case_doc(case_id="HAVEN-1", user="U-2"):
    """What routers/sos_routes.py writes for a PanicButton submit AFTER the fix:
    the "lat,lng" string the client sent PLUS parsed canonical numeric fields.
    (PanicButton sends "lat,lng" with no space — covered deliberately.)"""
    doc = {
        "case_id": case_id, "user_id": user, "trigger_type": "steganography",
        "location": f"{RPT_LAT},{RPT_LNG}", "status": "CREATED",
    }
    doc.update(il.canonical_coord_fields(location_text=doc["location"]))
    return doc


# ═══════════════════════════ A — valid stored GPS ═════════════════════════════
def test_A_numeric_event_resolves():
    """A voice sos_event with numeric coords resolves (dispatch would proceed)."""
    r = _patch_stores(events=[voice_event_doc()])
    try:
        lng, lat, victim, _ = dr._resolve_incident_location("VSOS-1")
    finally:
        r()
    assert (lng, lat) == (RPT_LNG, RPT_LAT)
    assert victim == "U-1"


def test_A_pure_resolver_numeric():
    lng, lat, _, _ = il.resolve_incident_point(None, voice_event_doc(), None)
    assert (lng, lat) == (RPT_LNG, RPT_LAT)


# ═══════════════════════════ B — no GPS anywhere ══════════════════════════════
def test_B_no_fix_blocks_dispatch():
    """A case with no coords and no parseable location -> resolver returns None,
    so POST /dispatch stays blocked with 409 (security requirement preserved)."""
    nocoord = {"case_id": "C-NO", "user_id": "U-3", "location": "Unknown"}
    r = _patch_stores(cases=[nocoord])
    try:
        lng, lat, victim, _ = dr._resolve_incident_location("C-NO")
    finally:
        r()
    assert lng is None and lat is None
    assert victim == "U-3"  # owner still resolved so audit can attribute the block


def test_B_absent_case_returns_none():
    r = _patch_stores()
    try:
        lng, lat, _, _ = dr._resolve_incident_location("DOES-NOT-EXIST")
    finally:
        r()
    assert lng is None and lat is None


# ═══════════════════════ C — malformed / out of range ═════════════════════════
def test_C_out_of_range_rejected():
    bad = {"case_id": "C-BAD", "latitude": 999.0, "longitude": 77.0}
    assert il.point_from_document(bad) is None


def test_C_nan_and_nonnumeric_rejected():
    assert il.point_from_document({"latitude": float("nan"), "longitude": 1.0}) is None
    assert il.point_from_document({"latitude": "abc", "longitude": "def"}) is None
    assert il.parse_coordinate_text("not coordinates at all") is None
    assert il.parse_coordinate_text("28.69, 999.9") is None  # lng out of range


def test_C_place_name_not_geocoded():
    """A free-text place name must NOT be guessed into a point."""
    assert il.parse_coordinate_text("Near MG Road, Bengaluru") is None
    assert il.point_from_document({"location": "Connaught Place, New Delhi"}) is None


# ═══ D — MANDATORY PROOF: card shows coords AND /dispatch recognizes them ══════
def test_D_PROOF_voice_card_string_dispatch_parity():
    """The authority card renders the case `location` string. Prove the dispatch
    resolver recognizes the SAME coordinates for a VOICE case (string on the
    case, numeric on the event) — end to end through dr._resolve_incident_location."""
    case = voice_case_doc()
    card_text = case["location"]              # exactly what 📍 {c.location} shows
    assert card_text == f"{RPT_LAT}, {RPT_LNG}"
    r = _patch_stores(events=[voice_event_doc()], cases=[case])
    try:
        lng, lat, _, _ = dr._resolve_incident_location("VSOS-1")
    finally:
        r()
    # The point the resolver returns is the SAME one printed on the card.
    card_lng, card_lat = il.parse_coordinate_text(card_text)
    assert (lng, lat) == (card_lng, card_lat) == (RPT_LNG, RPT_LAT)


def test_D_PROOF_panic_card_string_only_dispatch_parity():
    """Hardest case: a PanicButton/steganography case whose ONLY stored location
    is the string the card shows (no event row, no live stream). Prove the
    resolver still recognizes those exact coordinates after the fix."""
    case = panic_case_doc()
    card_text = case["location"]
    r = _patch_stores(cases=[case])           # no events, no live fix
    try:
        lng, lat, victim, _ = dr._resolve_incident_location("HAVEN-1")
    finally:
        r()
    assert (lng, lat) == (RPT_LNG, RPT_LAT)
    assert victim == "U-2"
    # And parity with the literal card text.
    assert il.parse_coordinate_text(card_text) == (lng, lat)


def test_D_legacy_string_only_case_resolves():
    """Even a legacy case written BEFORE the fix (string only, no numeric fields)
    now resolves, because the resolver parses the stored `location` string."""
    legacy = {"case_id": "LEGACY-1", "user_id": "U-9",
              "location": f"{RPT_LAT}, {RPT_LNG}"}  # no latitude/longitude keys
    r = _patch_stores(cases=[legacy])
    try:
        lng, lat, _, _ = dr._resolve_incident_location("LEGACY-1")
    finally:
        r()
    assert (lng, lat) == (RPT_LNG, RPT_LAT)


# ═════════════════ E — request body coords are NEVER trusted ══════════════════
def test_E_resolver_ignores_body_only_reads_stored():
    """The resolver takes NO request-body coordinates — it reads only the live
    stream and stored docs. A case with no stored fix cannot be given one by a
    (hypothetical) body, so it stays unresolved. This is the structural guarantee
    that a dispatcher cannot redirect a unit to an arbitrary point."""
    import inspect
    # _resolve_incident_location's only input is the case_id (never coords).
    params = list(inspect.signature(dr._resolve_incident_location).parameters)
    assert params == ["case_id"]
    # resolve_incident_point's inputs are only the three stored sources.
    rp = list(inspect.signature(il.resolve_incident_point).parameters)
    assert rp == ["live_fix", "event_doc", "case_doc"]
    # With no stored fix, nothing resolves regardless of any body a caller holds.
    r = _patch_stores(cases=[{"case_id": "C-E", "user_id": "U-E", "location": "Unknown"}])
    try:
        lng, lat, _, _ = dr._resolve_incident_location("C-E")
    finally:
        r()
    assert lng is None and lat is None


def test_E_live_stream_overrides_stale_stored():
    """Priority: the authenticated live fix wins over a stored one (freshest truth)."""
    live = {"VSOS-1": {"latitude": 12.9716, "longitude": 77.5946}}
    r = _patch_stores(events=[voice_event_doc()], cases=[voice_case_doc()], live=live)
    try:
        lng, lat, _, _ = dr._resolve_incident_location("VSOS-1")
    finally:
        r()
    assert (lng, lat) == (77.5946, 12.9716)


# ═════════════ F — existing /sos/location-update numeric write resolves ═══════
def test_F_location_update_stored_shape_resolves():
    """POST /sos/location-update writes numeric latitude/longitude onto BOTH the
    event and the case. That exact `stored` shape must keep resolving — proving
    the existing live-location path is not broken by the fix."""
    stored_case = {
        "case_id": "VSOS-2", "user_id": "U-7",
        "latitude": RPT_LAT, "longitude": RPT_LNG,
        "location_timestamp": "2026-10-01T12:00:00", "location_accuracy": 5.0,
    }
    r = _patch_stores(cases=[stored_case])
    try:
        lng, lat, _, _ = dr._resolve_incident_location("VSOS-2")
    finally:
        r()
    assert (lng, lat) == (RPT_LNG, RPT_LAT)


def test_F_canonical_fields_from_numeric_inputs():
    """The write-time helper produces the canonical numeric fields SOS creation
    now persists (numeric path) — and refuses to fabricate when input is absent."""
    assert il.canonical_coord_fields(RPT_LAT, RPT_LNG) == {
        "latitude": RPT_LAT, "longitude": RPT_LNG}
    assert il.canonical_coord_fields(None, None) == {}         # voice w/o a fix
    assert il.canonical_coord_fields(0, 0) == {"latitude": 0.0, "longitude": 0.0}


def test_F_canonical_fields_parsed_from_string():
    """PanicButton sends `location` as a "lat,lng" string; the helper parses it
    into the same canonical numeric fields (no-space and spaced both work)."""
    assert il.canonical_coord_fields(location_text=f"{RPT_LAT},{RPT_LNG}") == {
        "latitude": RPT_LAT, "longitude": RPT_LNG}
    assert il.canonical_coord_fields(location_text=f"{RPT_LAT}, {RPT_LNG}") == {
        "latitude": RPT_LAT, "longitude": RPT_LNG}
    assert il.canonical_coord_fields(location_text="Somewhere in Delhi") == {}


# ═══════════════════ G — GeoJSON + string lng/lat ordering ════════════════════
def test_G_geojson_point_ordering():
    """GeoJSON coordinates are [lng, lat]; the extractor must read index 0 as lng
    and index 1 as lat (never swapped)."""
    doc = {"incident_location": {"type": "Point", "coordinates": [RPT_LNG, RPT_LAT]}}
    assert il.point_from_document(doc) == (RPT_LNG, RPT_LAT)
    # A swapped pair where lat>90 as lng must be rejected, proving no silent swap.
    swapped = {"location": {"type": "Point", "coordinates": [RPT_LAT, RPT_LNG]}}
    # [28.69, 77.46] -> lng=28.69 (valid), lat=77.46 (valid) so it DOES parse, but
    # as a DIFFERENT point — confirm we take it literally, not reinterpreted.
    assert il.point_from_document(swapped) == (RPT_LAT, RPT_LNG)


def test_G_string_is_lat_then_lng():
    """The stored string is "<lat>, <lng>"; canonical output is (lng, lat)."""
    assert il.parse_coordinate_text(f"{RPT_LAT}, {RPT_LNG}") == (RPT_LNG, RPT_LAT)
    # Longitude beyond ±90 proves the SECOND number is treated as longitude.
    assert il.parse_coordinate_text("10.0, 170.0") == (170.0, 10.0)


def test_G_numeric_priority_over_string():
    """When a doc has BOTH numeric fields and a (different) string, numeric wins."""
    doc = {"latitude": RPT_LAT, "longitude": RPT_LNG, "location": "1.0, 2.0"}
    assert il.point_from_document(doc) == (RPT_LNG, RPT_LAT)


# ── standalone runner (mirrors the engine suite; works without pytest) ─────────
def _run_standalone():
    import traceback
    tests = sorted((n, o) for n, o in globals().items()
                   if n.startswith("test_") and callable(o))
    passed = failed = 0
    failures = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            failures.append((name, traceback.format_exc()))
            print(f"  FAIL  {name}")
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    for name, tb in failures:
        print(f"\n===== {name} =====\n{tb}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_standalone())
