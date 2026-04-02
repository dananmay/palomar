"""Aircraft anomaly detector — 6 rules for Tier 1 detection.

Rules:
1. emergency_squawk — Squawk 7500 (hijack), 7600 (radio failure), 7700 (emergency)
2. military_concentration — Unusual number of military aircraft in a grid cell
3. gps_jamming_escalation — New or worsening GPS jamming zones
4. unusual_holding — Holding pattern far from any airport
5. aircraft_disappearance — Military/tracked aircraft vanishes between cycles
6. speed_altitude_anomaly — Impossible speed or altitude for aircraft type
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key, is_near_airport

logger = logging.getLogger("anomaly.detectors.aircraft")

# Module-level state (persists between detection cycles)
_mil_baseline = RollingBaseline(window_seconds=21600)  # 6h
_prev_military_icaos: set[str] = set()
_prev_tracked_icaos: set[str] = set()
_aircraft_streak: dict[str, int] = {}  # icao24 → consecutive-cycle count
_prev_jamming: list[dict] = []

# Squawk code meanings
_SQUAWK_MEANINGS = {
    "7500": ("Hijack", Severity.CRITICAL),
    "7600": ("Radio Failure", Severity.HIGH),
    "7700": ("General Emergency", Severity.CRITICAL),
}

# Speed/altitude limits by classification
_SPEED_LIMITS = {
    "commercial_flights": 700,   # kts groundspeed (jet stream can push to ~650)
    "private_flights": 600,
    "private_jets": 650,
    "tracked_flights": 700,
}
_MAX_CIVILIAN_ALT = 60000  # feet


def _all_flights(snapshot: dict) -> list[tuple[str, dict]]:
    """Yield (category, flight_dict) for all flight categories."""
    for category in ("commercial_flights", "private_flights", "private_jets",
                     "tracked_flights", "military_flights"):
        for f in snapshot.get(category, []):
            yield category, f


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all aircraft anomaly rules against the current data snapshot."""
    global _prev_military_icaos, _prev_tracked_icaos, _prev_jamming

    anomalies: list[Anomaly] = []
    anomalies.extend(_check_emergency_squawk(snapshot))
    anomalies.extend(_check_military_concentration(snapshot))
    anomalies.extend(_check_gps_jamming(snapshot))
    anomalies.extend(_check_unusual_holding(snapshot))
    anomalies.extend(_check_disappearance(snapshot))
    anomalies.extend(_check_speed_altitude(snapshot))
    return anomalies


def _check_emergency_squawk(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Emergency squawk codes."""
    results = []
    for category, f in _all_flights(snapshot):
        squawk = str(f.get("squawk", "")).strip()
        if squawk in _SQUAWK_MEANINGS:
            meaning, severity = _SQUAWK_MEANINGS[squawk]
            callsign = f.get("callsign", "Unknown")
            model = f.get("model", "Unknown")
            icao24 = f.get("icao24", squawk)
            results.append(Anomaly.create(
                domain="aircraft",
                rule="emergency_squawk",
                severity=severity,
                title=f"{meaning}: {callsign} (Squawk {squawk})",
                description=(
                    f"Aircraft {callsign} ({model}) is transmitting squawk code "
                    f"{squawk} ({meaning}) at {f.get('alt', 'N/A')}ft, "
                    f"{f.get('speed_knots', 'N/A')}kts."
                ),
                entity_id=icao24,
                ttl=120,
                lat=f.get("lat"),
                lng=f.get("lng"),
                metadata={"squawk": squawk, "meaning": meaning,
                          "callsign": callsign, "model": model,
                          "altitude": f.get("alt"), "speed": f.get("speed_knots")},
            ))
    return results


def _check_military_concentration(snapshot: dict) -> list[Anomaly]:
    """Rule 2: Unusual military aircraft concentration per grid cell."""
    results = []
    mil_flights = snapshot.get("military_flights", [])

    # Count military aircraft per grid cell
    grid_counts: dict[str, int] = {}
    grid_samples: dict[str, list[dict]] = {}
    for f in mil_flights:
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        grid_samples.setdefault(gk, []).append(f)

    # Record and check each cell
    for gk, count in grid_counts.items():
        _mil_baseline.record(gk, count)
        is_anom, z = _mil_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=10, min_abs_deviation=4,
        )
        if is_anom:
            # Use first aircraft in cell for lat/lng
            sample = grid_samples[gk][0]
            severity = Severity.HIGH if count >= 8 else Severity.MEDIUM
            results.append(Anomaly.create(
                domain="aircraft",
                rule="military_concentration",
                severity=severity,
                title=f"Unusual military concentration: {count} aircraft in {gk}",
                description=(
                    f"{count} military aircraft detected in grid cell {gk}, "
                    f"z-score {z:.1f} above baseline."
                ),
                entity_id=gk,
                ttl=300,
                lat=sample.get("lat"),
                lng=sample.get("lng"),
                metadata={"grid": gk, "count": count, "z_score": round(z, 2),
                          "aircraft": [f.get("callsign", "?") for f in grid_samples[gk][:5]]},
            ))

    # Record zero counts for cells that had aircraft last cycle but not now
    # (prevents baselines from only seeing non-zero values)
    # This is implicitly handled since we only record cells with aircraft.
    # Cells with 0 aircraft are not recorded, which is fine — the baseline
    # only tracks cells that have had activity.

    return results


def _check_gps_jamming(snapshot: dict) -> list[Anomaly]:
    """Rule 3: New or escalating GPS jamming zones."""
    global _prev_jamming
    results = []
    current = snapshot.get("gps_jamming", [])

    # Build lookup of previous jamming zones by grid position
    prev_map: dict[str, dict] = {}
    for z in _prev_jamming:
        key = f"{z.get('lat')}:{z.get('lng')}"
        prev_map[key] = z

    severity_rank = {"low": 1, "medium": 2, "high": 3}

    for zone in current:
        key = f"{zone.get('lat')}:{zone.get('lng')}"
        prev = prev_map.get(key)
        cur_sev = severity_rank.get(zone.get("severity", ""), 0)

        is_new = prev is None
        is_escalated = (
            prev is not None
            and cur_sev > severity_rank.get(prev.get("severity", ""), 0)
        )

        if is_new or is_escalated:
            label = "New" if is_new else "Escalating"
            results.append(Anomaly.create(
                domain="aircraft",
                rule="gps_jamming_escalation",
                severity=Severity.MEDIUM,
                title=f"{label} GPS jamming: {zone.get('severity', '?')} at {key}",
                description=(
                    f"GPS jamming zone at ({zone.get('lat')}, {zone.get('lng')}): "
                    f"severity={zone.get('severity')}, "
                    f"{zone.get('degraded', '?')}/{zone.get('total', '?')} aircraft degraded."
                ),
                entity_id=key,
                ttl=300,
                lat=zone.get("lat"),
                lng=zone.get("lng"),
                metadata=zone,
            ))

    _prev_jamming = list(current)
    return results


def _check_unusual_holding(snapshot: dict) -> list[Anomaly]:
    """Rule 4: Holding patterns far from any airport."""
    results = []
    airports = snapshot.get("airports", [])
    if not airports:
        # Airports not loaded yet (startup race) — skip this rule
        return results

    for category, f in _all_flights(snapshot):
        if not f.get("holding"):
            continue
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        if not is_near_airport(lat, lng, airports, max_distance_km=50.0):
            callsign = f.get("callsign", "Unknown")
            results.append(Anomaly.create(
                domain="aircraft",
                rule="unusual_holding",
                severity=Severity.LOW,
                title=f"Unusual holding pattern: {callsign}",
                description=(
                    f"Aircraft {callsign} ({f.get('model', '?')}) is holding "
                    f"at ({lat:.2f}, {lng:.2f}), >50km from any major airport."
                ),
                entity_id=f.get("icao24", callsign),
                ttl=120,
                lat=lat,
                lng=lng,
                metadata={"callsign": callsign, "model": f.get("model"),
                          "altitude": f.get("alt"), "category": category},
            ))

    return results


def _check_disappearance(snapshot: dict) -> list[Anomaly]:
    """Rule 5: Military/tracked aircraft disappears between cycles."""
    global _prev_military_icaos, _prev_tracked_icaos
    results = []

    # Build current sets
    cur_mil = {
        f.get("icao24", "").lower()
        for f in snapshot.get("military_flights", [])
        if f.get("icao24")
    }
    cur_tracked = {
        f.get("icao24", "").lower()
        for f in snapshot.get("tracked_flights", [])
        if f.get("icao24")
    }

    # Update streaks
    all_current = cur_mil | cur_tracked
    for icao in all_current:
        _aircraft_streak[icao] = _aircraft_streak.get(icao, 0) + 1
    # Decay absent aircraft
    absent = set(_aircraft_streak.keys()) - all_current
    for icao in list(absent):
        # Check if this aircraft was present long enough and just disappeared
        streak = _aircraft_streak.get(icao, 0)
        if streak >= 3:  # Present for at least 3 cycles (~3 min)
            was_military = icao in _prev_military_icaos
            was_tracked = icao in _prev_tracked_icaos
            if was_military or was_tracked:
                label = "Military" if was_military else "Tracked"
                results.append(Anomaly.create(
                    domain="aircraft",
                    rule="aircraft_disappearance",
                    severity=Severity.HIGH,
                    title=f"{label} aircraft disappeared: {icao}",
                    description=(
                        f"{label} aircraft {icao} was transmitting for "
                        f"{streak} cycles and has stopped. "
                        f"Possible signal loss, landing, or transponder off."
                    ),
                    entity_id=icao,
                    ttl=180,
                    metadata={"icao24": icao, "streak_before_loss": streak,
                              "was_military": was_military, "was_tracked": was_tracked},
                ))
        # Remove from streak tracking
        del _aircraft_streak[icao]

    _prev_military_icaos = cur_mil
    _prev_tracked_icaos = cur_tracked
    return results


def _check_speed_altitude(snapshot: dict) -> list[Anomaly]:
    """Rule 6: Impossible speed or altitude for aircraft type."""
    results = []
    for category, f in _all_flights(snapshot):
        if category == "military_flights":
            continue  # Military aircraft can go fast/high

        speed = f.get("speed_knots")
        alt = f.get("alt")
        limit = _SPEED_LIMITS.get(category, 700)

        if speed is not None and speed > limit:
            callsign = f.get("callsign", "Unknown")
            results.append(Anomaly.create(
                domain="aircraft",
                rule="speed_altitude_anomaly",
                severity=Severity.MEDIUM,
                title=f"Speed anomaly: {callsign} at {speed:.0f}kts",
                description=(
                    f"Aircraft {callsign} ({f.get('model', '?')}) "
                    f"reporting {speed:.0f}kts groundspeed, exceeding "
                    f"{limit}kts threshold for {category}."
                ),
                entity_id=f.get("icao24", callsign),
                ttl=120,
                lat=f.get("lat"),
                lng=f.get("lng"),
                metadata={"speed_knots": speed, "threshold": limit,
                          "category": category, "callsign": callsign},
            ))

        if alt is not None and alt > _MAX_CIVILIAN_ALT and category != "military_flights":
            callsign = f.get("callsign", "Unknown")
            results.append(Anomaly.create(
                domain="aircraft",
                rule="speed_altitude_anomaly",
                severity=Severity.MEDIUM,
                title=f"Altitude anomaly: {callsign} at {alt}ft",
                description=(
                    f"Aircraft {callsign} ({f.get('model', '?')}) "
                    f"reporting {alt}ft altitude, above {_MAX_CIVILIAN_ALT}ft "
                    f"civilian ceiling."
                ),
                entity_id=f.get("icao24", callsign),
                ttl=120,
                lat=f.get("lat"),
                lng=f.get("lng"),
                metadata={"altitude": alt, "threshold": _MAX_CIVILIAN_ALT,
                          "category": category, "callsign": callsign},
            ))

    return results
