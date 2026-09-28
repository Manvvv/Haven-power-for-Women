"""
Stdlib validator for the advisory abuse/anomaly signal (services.anomaly_signal).

Runs with plain `python3 validate_anomaly_signal.py` — no pytest, no network, no
DB — so the deterministic guarantees can be verified on a fresh checkout.

It asserts the SAFETY INVARIANTS that make this signal safe to ship:
  * It is always advisory (advisory_only=True) and never affects the emergency
    response (affects_emergency_response=False).
  * A first fix, normal walking, and normal driving are NEVER flagged.
  * Physically impossible travel is flagged for human review; merely improbable
    travel is a softer 'notice', not a review flag.
  * Timestamps/coordinates are parsed honestly; missing data yields no fabricated
    speed and no false flag.
"""
import services.anomaly_signal as A

_checks = 0
_failures = []


def check(cond, label):
    global _checks
    _checks += 1
    if not cond:
        _failures.append(label)


DELHI = (28.6139, 77.2090)
MUMBAI = (19.0760, 72.8777)


def fix(lat, lon, ts=None):
    d = {"latitude": lat, "longitude": lon}
    if ts is not None:
        d["timestamp"] = ts
    return d


# ── Haversine accuracy (Delhi↔Mumbai ≈ 1148 km) ──
d_km = A.haversine_m(*DELHI, *MUMBAI) / 1000.0
check(1100 <= d_km <= 1200, f"haversine Delhi-Mumbai out of range: {d_km:.0f} km")
check(A.haversine_m(28.61, 77.20, 28.61, 77.20) == 0.0, "haversine same-point must be 0")

# ── Invariants that must hold for EVERY output ──
walk_prev = fix(*DELHI, "2026-09-28T10:00:00")
walk_curr = fix(28.6143, 77.2093, "2026-09-28T10:00:30")
teleport = fix(*MUMBAI, "2026-09-28T10:00:30")           # Delhi→Mumbai in 30s
improbable = fix(*MUMBAI, "2026-09-28T12:00:00")         # Delhi→Mumbai in 2h (~575 km/h)

samples = [
    A.assess(None, walk_curr),
    A.assess(walk_prev, walk_curr),
    A.assess(walk_prev, teleport),
    A.assess(walk_prev, improbable),
]
for i, s in enumerate(samples):
    check(s["advisory_only"] is True, f"sample {i}: advisory_only must be True")
    check(s["affects_emergency_response"] is False, f"sample {i}: must not affect emergency")
    check(s["level"] in (A.NONE, A.NOTICE, A.REVIEW), f"sample {i}: bad level")
    check(0 <= s["abuse_risk_score"] <= 100, f"sample {i}: score out of range")
    check(s["module_version"] == A.MODULE_VERSION, f"sample {i}: version mismatch")

# ── First fix / normal movement must NOT be flagged ──
check(A.assess(None, walk_curr)["level"] == A.NONE, "first fix must be clean")
check(A.assess(walk_prev, walk_curr)["level"] == A.NONE, "walking must be clean")
# City driving: ~22 km in 15 min (~88 km/h) — clean.
drive = fix(28.70, 77.40, "2026-09-28T10:15:00")
check(A.assess(walk_prev, drive)["level"] == A.NONE, "normal driving must be clean")

# ── Impossible vs improbable travel ──
tele_sig = A.assess(walk_prev, teleport)
check(tele_sig["flagged_for_review"] is True, "teleport must be flagged for review")
check(any(f["code"] == "impossible_travel_speed" for f in tele_sig["factors"]),
      "teleport must add impossible_travel_speed factor")
imp_sig = A.assess(walk_prev, improbable)
check(imp_sig["level"] == A.NOTICE and imp_sig["flagged_for_review"] is False,
      "improbable travel must be a NOTICE, not a review flag")

# ── Non-monotonic timestamp (clock went backwards) ──
back = A.assess(walk_prev, fix(28.6143, 77.2093, "2026-09-28T09:59:00"))
check(any(f["code"] == "non_monotonic_timestamp" for f in back["factors"]),
      "backwards timestamp must be flagged as non_monotonic_timestamp")

# ── Missing timestamps → no fabricated speed, no false flag ──
no_ts = A.assess(fix(*DELHI), fix(*MUMBAI))
check(no_ts["level"] == A.NONE, "missing timestamps must not fabricate a speed flag")
mv = A.movement(fix(*DELHI), fix(*MUMBAI))
check(mv is not None and mv["speed_mps"] is None, "no timestamps → speed_mps must be None")

# ── Sub-second dt is ignored (jitter must not create absurd speeds) ──
jitter = A.movement(fix(*DELHI, "2026-09-28T10:00:00.000"),
                    fix(28.6140, 77.2091, "2026-09-28T10:00:00.100"))
check(jitter is not None and jitter["speed_mps"] is None, "sub-second dt → speed_mps None")

# ── Invalid coordinates rejected (NaN / out of range) ──
check(A.movement(fix(float("nan"), 77.2), fix(*MUMBAI)) is None, "NaN lat must yield None")
check(A.movement(fix(200.0, 77.2), fix(*MUMBAI)) is None, "out-of-range lat must yield None")

# ── Update flooding (advisory) ──
base = A._to_epoch("2026-09-28T10:00:00")
flood = [base + i * 0.1 for i in range(40)]          # 40 fixes in ~4s
calm = [base + i * 15 for i in range(5)]             # 5 fixes over 60s
flood_sig = A.assess(walk_prev, walk_curr, recent_update_epochs=flood)
check(any(f["code"] == "update_flooding" for f in flood_sig["factors"]),
      "40 fixes in 4s must flag update_flooding")
calm_sig = A.assess(walk_prev, walk_curr, recent_update_epochs=calm)
check(not any(f["code"] == "update_flooding" for f in calm_sig["factors"]),
      "normal cadence must NOT flag flooding")

# ── Timezone handling: Z-suffix + explicit offset both parse ──
tz = A.assess(fix(*DELHI, "2026-09-28T10:00:00Z"),
              fix(28.6143, 77.2093, "2026-09-28T10:00:30+00:00"))
check(tz["level"] == A.NONE, "tz-aware fixes must parse and stay clean")

if _failures:
    print(f"FAILED {len(_failures)}/{_checks} checks:")
    for f in _failures:
        print("  -", f)
    raise SystemExit(1)
print(f"PASSED {_checks} checks")
print("ALL ANOMALY-SIGNAL CHECKS PASSED")
