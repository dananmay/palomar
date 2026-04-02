"""Maritime anomaly detector — 3 rules for Tier 1 detection.

Rules:
1. speed_anomaly — Vessel exceeding speed limits for its type
2. vessel_concentration — Unusual number of vessels in a grid cell
3. ais_gap — Significant vessel goes dark (AIS transponder stops reporting)
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key

logger = logging.getLogger("anomaly.detectors.maritime")

# Module-level state
_conc_baseline = RollingBaseline(window_seconds=21600)  # 6h
_vessel_streak: dict[int, int] = {}  # mmsi → consecutive-cycle count
_prev_vessel_mmsis: set[int] = set()

# Speed limits by vessel type (knots over ground)
_SPEED_LIMITS = {
    "cargo": 25,
    "tanker": 22,
    "passenger": 30,
    "military_vessel": 35,
}

# Vessel types significant enough to track for AIS gaps
_SIGNIFICANT_TYPES = {"cargo", "tanker", "military_vessel"}


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all maritime anomaly rules."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_speed(snapshot))
    anomalies.extend(_check_concentration(snapshot))
    anomalies.extend(_check_ais_gap(snapshot))
    return anomalies


def _check_speed(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Vessel speed exceeds type-specific limits."""
    results = []
    for ship in snapshot.get("ships", []):
        vessel_type = ship.get("type", "unknown")
        limit = _SPEED_LIMITS.get(vessel_type)
        if limit is None:
            continue

        sog = ship.get("sog", 0)
        if sog is None or sog <= limit:
            continue

        mmsi = ship.get("mmsi", 0)
        name = ship.get("name", "Unknown")
        results.append(Anomaly.create(
            domain="maritime",
            rule="speed_anomaly",
            severity=Severity.MEDIUM,
            title=f"Speed anomaly: {name} ({vessel_type}) at {sog:.1f}kts",
            description=(
                f"Vessel {name} (MMSI {mmsi}, type={vessel_type}) "
                f"reporting {sog:.1f}kts speed over ground, exceeding "
                f"{limit}kts threshold for {vessel_type}."
            ),
            entity_id=str(mmsi),
            ttl=120,
            lat=ship.get("lat"),
            lng=ship.get("lng"),
            metadata={"mmsi": mmsi, "name": name, "vessel_type": vessel_type,
                      "sog": sog, "threshold": limit,
                      "destination": ship.get("destination"),
                      "country": ship.get("country")},
        ))

    return results


def _check_concentration(snapshot: dict) -> list[Anomaly]:
    """Rule 2: Unusual vessel count per 1° grid cell."""
    results = []
    ships = snapshot.get("ships", [])

    # Count vessels per grid cell
    grid_counts: dict[str, int] = {}
    grid_samples: dict[str, dict] = {}  # first vessel per cell for coords
    for ship in ships:
        lat, lng = ship.get("lat"), ship.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        if gk not in grid_samples:
            grid_samples[gk] = ship

    for gk, count in grid_counts.items():
        _conc_baseline.record(gk, count)
        is_anom, z = _conc_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=10, min_abs_deviation=8,
        )
        if is_anom:
            sample = grid_samples[gk]
            results.append(Anomaly.create(
                domain="maritime",
                rule="vessel_concentration",
                severity=Severity.MEDIUM,
                title=f"Vessel concentration: {count} ships in {gk}",
                description=(
                    f"{count} vessels detected in grid cell {gk}, "
                    f"z-score {z:.1f} above baseline."
                ),
                entity_id=gk,
                ttl=300,
                lat=sample.get("lat"),
                lng=sample.get("lng"),
                metadata={"grid": gk, "count": count, "z_score": round(z, 2)},
            ))

    return results


def _check_ais_gap(snapshot: dict) -> list[Anomaly]:
    """Rule 3: Significant vessel stops transmitting AIS.

    Only tracks cargo, tanker, and military vessels. Requires 5+ consecutive
    cycles of presence before flagging disappearance.
    """
    global _prev_vessel_mmsis
    results = []
    ships = snapshot.get("ships", [])

    # Build current set of significant vessels
    cur_significant: dict[int, dict] = {}
    for ship in ships:
        mmsi = ship.get("mmsi")
        vtype = ship.get("type", "unknown")
        if mmsi and vtype in _SIGNIFICANT_TYPES:
            cur_significant[mmsi] = ship

    cur_mmsis = set(cur_significant.keys())

    # Update streaks for present vessels
    for mmsi in cur_mmsis:
        _vessel_streak[mmsi] = _vessel_streak.get(mmsi, 0) + 1

    # Check absent significant vessels
    disappeared = _prev_vessel_mmsis - cur_mmsis
    for mmsi in disappeared:
        streak = _vessel_streak.get(mmsi, 0)
        if streak >= 5:  # Was present for 5+ cycles (~5 min)
            # Escalation: longer streaks = higher concern
            if streak >= 15:  # 15+ min of consistent tracking
                severity = Severity.HIGH
            elif streak >= 10:
                severity = Severity.MEDIUM
            else:
                severity = Severity.LOW

            results.append(Anomaly.create(
                domain="maritime",
                rule="ais_gap",
                severity=severity,
                title=f"AIS gap: vessel MMSI {mmsi} went dark",
                description=(
                    f"Vessel MMSI {mmsi} was consistently transmitting AIS "
                    f"for {streak} cycles (~{streak} min) and has stopped. "
                    f"Possible transponder off, signal loss, or intentional dark transit."
                ),
                entity_id=str(mmsi),
                ttl=600,
                metadata={"mmsi": mmsi, "streak_before_loss": streak},
            ))

        # Remove from streak tracking
        if mmsi in _vessel_streak:
            del _vessel_streak[mmsi]

    _prev_vessel_mmsis = cur_mmsis
    return results
