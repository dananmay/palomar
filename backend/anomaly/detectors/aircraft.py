"""Aircraft anomaly detector — 9 rules for Tier 1 detection.

Rules:
1. emergency_squawk — Squawk 7500 (hijack), 7600 (radio failure), 7700 (emergency)
2. military_concentration — Unusual number of military aircraft in a grid cell
3. gps_jamming_escalation — Persistent high-severity GPS jamming zones
4. unusual_holding — Holding pattern far from any airport
5. aircraft_disappearance — Military recon/cargo/tanker aircraft vanishes between cycles
6. speed_altitude_anomaly — Impossible speed or altitude for aircraft type
7. unusual_military_type — New military aircraft type appears in a grid cell
8. military_tanker_surge — Surge in cargo/tanker military aircraft in a grid cell
9. tracked_convergence — Different-operator tracked aircraft converging away from airports
"""
from __future__ import annotations

import logging
import time
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key, haversine_km, is_near_airport

logger = logging.getLogger("anomaly.detectors.aircraft")

# Module-level state (persists between detection cycles)
_mil_baseline = RollingBaseline(window_seconds=21600)  # 6h
_tanker_baseline = RollingBaseline(window_seconds=21600)  # 6h
_prev_military_icaos: set[str] = set()
_prev_tracked_icaos: set[str] = set()
_aircraft_streak: dict[str, int] = {}  # icao24 -> consecutive-cycle count
_jamming_streak: dict[str, int] = {}  # zone_key -> consecutive-cycle count
_aircraft_type_cache: dict[str, str] = {}  # icao24 -> military_type
_type_last_seen: dict[str, float] = {}  # "{grid}:{type}" -> last seen timestamp
_system_start: float = time.time()

# Military types that are significant for disappearance tracking
_DISAPPEARANCE_TYPES = {"recon", "cargo", "tanker"}

# Squawk code meanings
_SQUAWK_MEANINGS = {
    "7500": ("Hijack", Severity.CRITICAL),
    "7600": ("Radio Failure", Severity.HIGH),
    "7700": ("General Emergency", Severity.CRITICAL),
}

# Speed/altitude limits by classification
# Speeds between _SPEED_LIMITS and _SPEED_CAPS are flagged as anomalies.
# Speeds above _SPEED_CAPS are ADS-B data corruption, not real anomalies.
_SPEED_LIMITS = {
    "commercial_flights": 700,   # kts groundspeed (jet stream can push to ~650)
    "private_flights": 700,      # same as commercial — many misclassified jets end up here
    "private_jets": 700,         # aligned — business jets cruise at similar speeds
    "tracked_flights": 700,
}
_SPEED_CAPS = {
    "commercial_flights": 900,   # Above 900kts = bad data for any airliner
    "private_flights": 900,      # aligned with commercial (misclassified jets)
    "private_jets": 900,         # aligned
    "tracked_flights": 900,
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
    global _prev_military_icaos, _prev_tracked_icaos

    anomalies: list[Anomaly] = []
    anomalies.extend(_check_emergency_squawk(snapshot))
    anomalies.extend(_check_military_concentration(snapshot))
    anomalies.extend(_check_gps_jamming(snapshot))
    anomalies.extend(_check_unusual_holding(snapshot))
    anomalies.extend(_check_disappearance(snapshot))
    anomalies.extend(_check_speed_altitude(snapshot))
    anomalies.extend(_check_unusual_military_type(snapshot))
    anomalies.extend(_check_military_tanker_surge(snapshot))
    anomalies.extend(_check_tracked_convergence(snapshot))
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
                ttl=600,  # 10 min — emergencies are rare and always significant
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
    """Rule 3: Persistent high-severity GPS jamming zones.

    Only flags zones with severity == "high" that persist for 2+ consecutive
    detection cycles. Transient or low/medium-severity zones are ignored.
    """
    global _jamming_streak
    results = []
    current = snapshot.get("gps_jamming", [])

    # Build set of current high-severity zone keys
    current_high_keys: set[str] = set()
    current_zone_map: dict[str, dict] = {}
    for zone in current:
        if zone.get("severity") != "high":
            continue
        key = f"{zone.get('lat')}:{zone.get('lng')}"
        current_high_keys.add(key)
        current_zone_map[key] = zone

    # Rebuild streaks: increment for zones still present, drop absent ones
    new_streak: dict[str, int] = {}
    for key in current_high_keys:
        new_streak[key] = _jamming_streak.get(key, 0) + 1
    _jamming_streak = new_streak

    # Only flag zones with streak >= 2 (present in 2+ consecutive cycles)
    for key, streak in _jamming_streak.items():
        if streak >= 2:
            zone = current_zone_map[key]
            results.append(Anomaly.create(
                domain="aircraft",
                rule="gps_jamming_escalation",
                severity=Severity.MEDIUM,
                title=f"Persistent GPS jamming: high severity at {key}",
                description=(
                    f"GPS jamming zone at ({zone.get('lat')}, {zone.get('lng')}): "
                    f"severity=high, persisted for {streak} consecutive cycles, "
                    f"{zone.get('degraded', '?')}/{zone.get('total', '?')} aircraft degraded."
                ),
                entity_id=key,
                ttl=300,
                lat=zone.get("lat"),
                lng=zone.get("lng"),
                metadata={**zone, "streak": streak},
            ))

    return results


def _check_unusual_holding(snapshot: dict) -> list[Anomaly]:
    """Rule 4: Holding patterns far from any airport.

    Only flags military and tracked aircraft. Excludes helicopters (they circle
    by nature) and commercial/private/GA aircraft (routine holding).
    Airport exclusion radius is 100km to cover approach corridors.
    """
    results = []
    airports = snapshot.get("airports", [])
    if not airports:
        return results

    # Only check military and tracked flights — commercial/private holding is routine
    interesting_categories = ("military_flights", "tracked_flights")
    for category in interesting_categories:
        for f in snapshot.get(category, []):
            if not f.get("holding"):
                continue
            # Exclude helicopters — they circle by nature
            if f.get("aircraft_category") == "heli" or f.get("military_type") == "heli":
                continue
            model = (f.get("model") or "").upper()
            if any(h in model for h in ("H60", "H53", "H47", "H64", "A139", "EC35", "R44", "R66", "B06", "B07", "S70", "NH90", "AW1")):
                continue
            lat, lng = f.get("lat"), f.get("lng")
            if lat is None or lng is None:
                continue
            if not is_near_airport(lat, lng, airports, max_distance_km=100.0):
                callsign = f.get("callsign", "Unknown")
                results.append(Anomaly.create(
                    domain="aircraft",
                    rule="unusual_holding",
                    severity=Severity.LOW,
                    title=f"Unusual holding pattern: {callsign}",
                    description=(
                        f"Aircraft {callsign} ({f.get('model', '?')}) is holding "
                        f"at ({lat:.2f}, {lng:.2f}), >100km from any major airport."
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
    """Rule 5: Military recon/cargo/tanker aircraft disappears between cycles.

    Only flags aircraft with military_type in ("recon", "cargo", "tanker").
    Types like "heli", "fighter", and "default" go in and out of ADS-B
    coverage constantly and are excluded. Requires 10 consecutive cycles
    of presence before flagging a disappearance.
    """
    global _prev_military_icaos, _prev_tracked_icaos
    results = []

    # Build current sets and a mapping of icao -> military_type for filtering
    cur_mil: set[str] = set()
    mil_type_map: dict[str, str] = {}
    for f in snapshot.get("military_flights", []):
        icao = f.get("icao24")
        if icao:
            icao_lower = icao.lower()
            cur_mil.add(icao_lower)
            mil_type_map[icao_lower] = f.get("military_type", "default")

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
        streak = _aircraft_streak.get(icao, 0)
        if streak >= 10:  # Present for at least 10 cycles (~10 min)
            was_military = icao in _prev_military_icaos
            was_tracked = icao in _prev_tracked_icaos

            if was_military or was_tracked:
                # For military, only flag recon/cargo/tanker types
                if was_military:
                    cached_type = _aircraft_type_cache.get(icao, "default")
                    if cached_type not in _DISAPPEARANCE_TYPES:
                        del _aircraft_streak[icao]
                        continue

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

    # Update type cache for current military aircraft
    for icao, mtype in mil_type_map.items():
        _aircraft_type_cache[icao] = mtype
    # Clean up type cache for aircraft no longer tracked
    for icao in list(_aircraft_type_cache.keys()):
        if icao not in all_current and icao not in _aircraft_streak:
            del _aircraft_type_cache[icao]

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

        cap = _SPEED_CAPS.get(category, 900)

        if speed is not None and speed > limit:
            if speed > cap:
                continue  # Above plausibility cap = ADS-B data corruption, not a real anomaly
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
                          "cap": cap, "category": category, "callsign": callsign},
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


def _check_unusual_military_type(snapshot: dict) -> list[Anomaly]:
    """Rule 7: New military aircraft type appears in a grid cell.

    Tracks which military_type values have been seen in each 2-degree grid
    cell. Flags when a type appears that hasn't been seen in that cell for
    >6 hours (or ever), provided there are at least 2 aircraft of that type.

    During the first 600 seconds after system start, only records data
    without generating alerts (warmup guard).
    """
    global _type_last_seen
    results = []
    now = time.time()
    in_warmup = (now - _system_start) < 600

    mil_flights = snapshot.get("military_flights", [])

    # Count (grid, type) -> list of aircraft
    cell_type_counts: dict[str, dict[str, list[dict]]] = {}
    for f in mil_flights:
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        mtype = f.get("military_type", "default")
        gk = grid_key(lat, lng, resolution=2)
        cell_type_counts.setdefault(gk, {}).setdefault(mtype, []).append(f)

    # Check each (grid, type) pair
    for gk, type_map in cell_type_counts.items():
        for mtype, flights in type_map.items():
            lookup_key = f"{gk}:{mtype}"
            last_seen = _type_last_seen.get(lookup_key)

            if not in_warmup and len(flights) >= 2:
                # Flag if never seen or not seen for > 6 hours
                if last_seen is None or (now - last_seen) > 21600:
                    severity = Severity.HIGH if mtype in ("tanker", "recon") else Severity.MEDIUM
                    sample = flights[0]
                    label = "never before seen" if last_seen is None else "not seen for >6h"
                    results.append(Anomaly.create(
                        domain="aircraft",
                        rule="unusual_military_type",
                        severity=severity,
                        title=f"Unusual military type in {gk}: {mtype} ({len(flights)} aircraft)",
                        description=(
                            f"{len(flights)} military aircraft of type '{mtype}' detected "
                            f"in grid cell {gk}, {label} in this cell."
                        ),
                        entity_id=f"{gk}:{mtype}",
                        ttl=300,
                        lat=sample.get("lat"),
                        lng=sample.get("lng"),
                        metadata={
                            "grid": gk, "military_type": mtype,
                            "count": len(flights),
                            "aircraft": [f.get("callsign", "?") for f in flights[:5]],
                        },
                    ))

            # Always update last-seen timestamp (including during warmup)
            _type_last_seen[lookup_key] = now

    return results


def _check_military_tanker_surge(snapshot: dict) -> list[Anomaly]:
    """Rule 8: Surge in cargo/tanker military aircraft in a grid cell.

    Filters military flights to type "cargo" or "tanker", counts per 2-degree
    grid cell, and flags cells where the count exceeds baseline + 2 sigma
    with at least 3 aircraft.
    """
    results = []
    mil_flights = snapshot.get("military_flights", [])

    # Filter to cargo and tanker types
    tanker_cargo = [
        f for f in mil_flights
        if f.get("military_type") in ("cargo", "tanker")
    ]

    # Count per 2-degree grid cell
    grid_counts: dict[str, int] = {}
    grid_samples: dict[str, list[dict]] = {}
    for f in tanker_cargo:
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=2)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        grid_samples.setdefault(gk, []).append(f)

    # Record and check each cell
    for gk, count in grid_counts.items():
        _tanker_baseline.record(gk, count)
        is_anom, z = _tanker_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=5, min_abs_deviation=3,
        )
        if is_anom and count >= 3:
            sample = grid_samples[gk][0]
            severity = Severity.HIGH if count >= 5 else Severity.MEDIUM
            results.append(Anomaly.create(
                domain="aircraft",
                rule="military_tanker_surge",
                severity=severity,
                title=f"Cargo/tanker surge: {count} aircraft in {gk}",
                description=(
                    f"{count} military cargo/tanker aircraft detected in grid cell {gk}, "
                    f"z-score {z:.1f} above baseline."
                ),
                entity_id=gk,
                ttl=300,
                lat=sample.get("lat"),
                lng=sample.get("lng"),
                metadata={
                    "grid": gk, "count": count, "z_score": round(z, 2),
                    "aircraft": [f.get("callsign", "?") for f in grid_samples[gk][:5]],
                },
            ))

    return results


def _check_tracked_convergence(snapshot: dict) -> list[Anomaly]:
    """Rule 9: Different-operator tracked aircraft converging away from airports.

    Flags pairs of tracked flights (excluding helicopters and aircraft without
    an alert_operator) that are within 30km of each other, operated by different
    entities, and both >100km from any major airport.
    """
    results = []
    airports = snapshot.get("airports", [])
    if not airports:
        return results

    tracked = snapshot.get("tracked_flights", [])
    # Filter: exclude helicopters and aircraft with empty/missing alert_operator
    candidates = []
    for f in tracked:
        if f.get("aircraft_category") == "heli":
            continue
        operator = (f.get("alert_operator") or "").strip()
        if not operator:
            continue
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        candidates.append(f)

    # Pairwise distance check
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            # Must be different operators
            op_a = (a.get("alert_operator") or "").strip()
            op_b = (b.get("alert_operator") or "").strip()
            if op_a == op_b:
                continue

            dist = haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
            if dist > 30:
                continue

            # Both must be >100km from any major airport
            if is_near_airport(a["lat"], a["lng"], airports, max_distance_km=100.0):
                continue
            if is_near_airport(b["lat"], b["lng"], airports, max_distance_km=100.0):
                continue

            icao_a = a.get("icao24", "???")
            icao_b = b.get("icao24", "???")
            entity_id = ":".join(sorted([icao_a, icao_b]))
            call_a = a.get("callsign", icao_a)
            call_b = b.get("callsign", icao_b)

            results.append(Anomaly.create(
                domain="aircraft",
                rule="tracked_convergence",
                severity=Severity.HIGH,
                title=f"Tracked aircraft convergence: {call_a} / {call_b} ({dist:.0f}km)",
                description=(
                    f"Tracked aircraft {call_a} ({op_a}) and {call_b} ({op_b}) "
                    f"are within {dist:.1f}km of each other, both >100km from "
                    f"any major airport. Different operators suggest unrelated "
                    f"missions in close proximity."
                ),
                entity_id=entity_id,
                ttl=300,
                lat=a["lat"],
                lng=a["lng"],
                metadata={
                    "aircraft_a": {"icao24": icao_a, "callsign": call_a, "operator": op_a},
                    "aircraft_b": {"icao24": icao_b, "callsign": call_b, "operator": op_b},
                    "distance_km": round(dist, 1),
                },
            ))

    return results
