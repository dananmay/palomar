"""Carrier repositioning detector — 1 rule for Tier 1 detection.

Rules:
1. carrier_repositioning — US Navy carrier estimated position changed significantly
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.rules import haversine_km

logger = logging.getLogger("anomaly.detectors.carriers")

# Module-level state: previous carrier positions (name -> (lat, lng))
_prev_carrier_positions: dict[str, tuple[float, float]] = {}


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all carrier anomaly rules against the current data snapshot."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_carrier_repositioning(snapshot))
    return anomalies


def _check_carrier_repositioning(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Carrier estimated position changed significantly.

    Tracks carrier positions between detection cycles and flags when a carrier
    has moved more than 93km (~50 nautical miles) since the previous cycle.
    """
    global _prev_carrier_positions
    results = []
    ships = snapshot.get("ships", [])
    if not ships:
        return results

    # Filter to carriers only
    carriers = [s for s in ships if s.get("type") == "carrier"]
    if not carriers:
        return results

    # Build current positions
    current_positions: dict[str, tuple[float, float, dict]] = {}
    for carrier in carriers:
        name = carrier.get("name")
        lat = carrier.get("lat")
        lng = carrier.get("lng")
        if not name or lat is None or lng is None:
            continue
        current_positions[name] = (lat, lng, carrier)

    # Compare to previous positions (only carriers present in both cycles)
    for name, (lat, lng, carrier) in current_positions.items():
        if name not in _prev_carrier_positions:
            continue
        prev_lat, prev_lng = _prev_carrier_positions[name]
        dist = haversine_km(prev_lat, prev_lng, lat, lng)
        if dist > 93:
            severity = Severity.CRITICAL if dist > 500 else Severity.HIGH
            results.append(Anomaly.create(
                domain="maritime",
                rule="carrier_repositioning",
                severity=severity,
                title=f"Carrier repositioning: {name} moved {dist:.0f}km",
                description=(
                    f"Carrier {name} estimated position changed by {dist:.0f}km "
                    f"(~{dist / 1.852:.0f}nm) since last cycle. "
                    f"Previous: ({prev_lat:.2f}, {prev_lng:.2f}), "
                    f"Current: ({lat:.2f}, {lng:.2f}). "
                    f"{carrier.get('description', '')}"
                ),
                entity_id=name,
                ttl=3600,
                lat=lat,
                lng=lng,
                metadata={
                    "carrier_name": name,
                    "distance_km": round(dist, 1),
                    "distance_nm": round(dist / 1.852, 1),
                    "prev_lat": prev_lat,
                    "prev_lng": prev_lng,
                    "description": carrier.get("description", ""),
                    "source": carrier.get("source", ""),
                },
            ))

    # Update previous positions at end of every cycle
    _prev_carrier_positions = {
        name: (lat, lng) for name, (lat, lng, _) in current_positions.items()
    }

    return results
