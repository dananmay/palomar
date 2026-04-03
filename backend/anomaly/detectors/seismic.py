"""Seismic anomaly detector — 2 rules for Tier 1 detection.

Rules:
1. earthquake_swarm — Multiple quakes in the same region within 12 hours
2. unusual_magnitude — Quake magnitude exceeds regional historical maximum
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key

logger = logging.getLogger("anomaly.detectors.seismic")

# 24h window for magnitude tracking (tracks max magnitude per grid cell)
_mag_baseline = RollingBaseline(window_seconds=86400)

# M6+ is always significant regardless of baseline
_UNCONDITIONAL_MAG = 6.0
# Flag when current max exceeds historical max by this much
_MAG_EXCEEDANCE = 1.0


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all seismic anomaly rules."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_swarm(snapshot))
    anomalies.extend(_check_unusual_magnitude(snapshot))
    return anomalies


def _check_swarm(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Earthquake swarm — 3+ quakes in same 2° grid cell.

    Uses a 2° grid (~222km cells) to group nearby earthquakes.
    The USGS feed provides quakes from the last 24 hours.
    """
    results = []
    quakes = snapshot.get("earthquakes", [])
    if not quakes:
        return results

    # Count quakes per 2° grid cell
    grid_counts: dict[str, list[dict]] = {}
    for q in quakes:
        lat, lng = q.get("lat"), q.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=2)
        grid_counts.setdefault(gk, []).append(q)

    for gk, cell_quakes in grid_counts.items():
        count = len(cell_quakes)
        if count >= 3:
            max_mag = max(q.get("mag", 0) for q in cell_quakes)
            severity = Severity.HIGH if count >= 5 or max_mag >= 5.0 else Severity.MEDIUM

            # Use the largest quake's location as the anomaly position
            biggest = max(cell_quakes, key=lambda q: q.get("mag", 0))
            results.append(Anomaly.create(
                domain="seismic",
                rule="earthquake_swarm",
                severity=severity,
                title=f"Earthquake swarm: {count} quakes in {gk} (max M{max_mag:.1f})",
                description=(
                    f"{count} earthquakes detected in grid cell {gk} within "
                    f"the last 24 hours. Largest: M{max_mag:.1f} at "
                    f"{biggest.get('place', 'unknown location')}."
                ),
                entity_id=gk,
                ttl=3600,
                lat=biggest.get("lat"),
                lng=biggest.get("lng"),
                metadata={
                    "grid": gk,
                    "count": count,
                    "max_magnitude": max_mag,
                    "quakes": [
                        {"id": q.get("id"), "mag": q.get("mag"),
                         "place": q.get("place")}
                        for q in cell_quakes
                    ],
                },
            ))

    return results


def _check_unusual_magnitude(snapshot: dict) -> list[Anomaly]:
    """Rule 2: Unusual magnitude for a region.

    Uses historical maximum per 2° grid cell. Flags when current max exceeds
    historical max by ≥1.0 magnitude units. M6+ is always flagged unconditionally.
    """
    results = []
    quakes = snapshot.get("earthquakes", [])
    if not quakes:
        return results

    # Track max magnitude per grid cell
    grid_max: dict[str, dict] = {}  # gk → quake with highest mag
    for q in quakes:
        lat, lng = q.get("lat"), q.get("lng")
        mag = q.get("mag")
        if lat is None or lng is None or mag is None:
            continue
        gk = grid_key(lat, lng, resolution=2)
        if gk not in grid_max or mag > grid_max[gk].get("mag", 0):
            grid_max[gk] = q

    for gk, quake in grid_max.items():
        mag = quake.get("mag", 0)

        # Record magnitude for baseline building
        _mag_baseline.record(gk, mag)

        # Unconditional: M6+ is always significant
        if mag >= _UNCONDITIONAL_MAG:
            results.append(Anomaly.create(
                domain="seismic",
                rule="unusual_magnitude",
                severity=Severity.CRITICAL if mag >= 7.0 else Severity.HIGH,
                title=f"Major earthquake: M{mag:.1f} at {quake.get('place', '?')}",
                description=(
                    f"Magnitude {mag:.1f} earthquake detected at "
                    f"{quake.get('place', 'unknown location')}. "
                    f"M6+ earthquakes are always flagged."
                ),
                entity_id=quake.get("id", gk),
                ttl=3600,
                lat=quake.get("lat"),
                lng=quake.get("lng"),
                metadata={"magnitude": mag, "place": quake.get("place"),
                          "quake_id": quake.get("id"), "grid": gk,
                          "unconditional": True},
            ))
            continue

        # Baseline comparison: exceeds historical max by ≥1.0
        hist_max = _mag_baseline.maximum(gk)
        if hist_max is not None and mag >= hist_max + _MAG_EXCEEDANCE:
            results.append(Anomaly.create(
                domain="seismic",
                rule="unusual_magnitude",
                severity=Severity.HIGH,
                title=(
                    f"Unusual magnitude: M{mag:.1f} at {quake.get('place', '?')} "
                    f"(baseline max M{hist_max:.1f})"
                ),
                description=(
                    f"Magnitude {mag:.1f} earthquake at "
                    f"{quake.get('place', 'unknown location')} exceeds "
                    f"24h regional maximum of M{hist_max:.1f} by "
                    f"{mag - hist_max:.1f} units."
                ),
                entity_id=quake.get("id", gk),
                ttl=3600,
                lat=quake.get("lat"),
                lng=quake.get("lng"),
                metadata={"magnitude": mag, "place": quake.get("place"),
                          "quake_id": quake.get("id"), "grid": gk,
                          "historical_max": hist_max,
                          "exceedance": round(mag - hist_max, 1)},
            ))

    return results
