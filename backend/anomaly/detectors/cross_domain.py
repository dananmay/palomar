"""Cross-domain anomaly detector — 2 rules for Tier 1 detection.

Detects spatial co-occurrence across multiple data domains.
Pure Python grid overlap checks — no LLM, no external calls.

Rules:
1. military_near_conflict — Military aircraft in a region with elevated GDELT conflict events
2. internet_outage_in_conflict_zone — Internet outage co-located with conflict events

Note: GDELT data uses GeoJSON coordinate order [lng, lat], not [lat, lng].
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.rules import grid_key

logger = logging.getLogger("anomaly.detectors.cross_domain")

# GDELT event thresholds — set high because GDELT "conflict" events include
# domestic military activities and protests in the US/UK. Top cells globally
# are in the eastern US (40:-76 = 26 events). Only ≥15 filters to genuine hotspots.
_GDELT_THRESHOLD_MILITARY = 15
_GDELT_THRESHOLD_INTERNET = 10

# Grid cells containing known military bases — military aircraft near their
# own bases is normal, not anomalous. Built on first call from snapshot data.
_base_cells: set[str] | None = None


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all cross-domain anomaly rules."""
    # Pre-compute GDELT grid (shared by both rules)
    gdelt_grid = _build_gdelt_grid(snapshot)

    anomalies: list[Anomaly] = []
    anomalies.extend(_check_military_near_conflict(snapshot, gdelt_grid))
    anomalies.extend(_check_internet_outage_conflict(snapshot, gdelt_grid))
    return anomalies


def _build_gdelt_grid(snapshot: dict) -> dict[str, int]:
    """Build a grid of GDELT conflict event counts per 4° cell.

    IMPORTANT: GDELT data is GeoJSON — coordinates are [lng, lat], not [lat, lng].
    """
    gdelt = snapshot.get("gdelt", [])
    if isinstance(gdelt, dict):
        gdelt = gdelt.get("features", [])

    grid: dict[str, int] = {}
    for feature in gdelt:
        if not isinstance(feature, dict):
            continue
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        # GeoJSON: [lng, lat] — swap for grid_key(lat, lng)
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        grid[gk] = grid.get(gk, 0) + 1

    return grid


def _check_military_near_conflict(
    snapshot: dict, gdelt_grid: dict[str, int]
) -> list[Anomaly]:
    """Rule 1: Military aircraft in a region with elevated GDELT conflict events.

    Requires:
    - ≥3 military aircraft in a 2° grid cell
    - ≥15 GDELT events in the overlapping 4° grid cell
    - Grid alignment: 2° military cells map to the containing 4° GDELT cell
    """
    global _base_cells
    results = []
    mil_flights = snapshot.get("military_flights", [])
    if not mil_flights or not gdelt_grid:
        return results

    # Build set of grid cells containing known military bases (once)
    if _base_cells is None:
        _base_cells = set()
        for base in snapshot.get("military_bases", []):
            b_lat, b_lng = base.get("lat"), base.get("lng")
            if b_lat is not None and b_lng is not None:
                _base_cells.add(grid_key(b_lat, b_lng, resolution=2))
        if _base_cells:
            logger.info(f"Cached {len(_base_cells)} grid cells with military bases (excluded from military-conflict rule)")

    # Count military aircraft per 2° cell
    mil_cells: dict[str, list[dict]] = {}
    for f in mil_flights:
        lat, lng = f.get("lat"), f.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=2)
        mil_cells.setdefault(gk, []).append(f)

    for gk, flights in mil_cells.items():
        if len(flights) < 3:
            continue

        # Skip cells with known military bases — aircraft near their own base is normal
        if _base_cells and gk in _base_cells:
            continue

        # Map 2° military cell to containing 4° GDELT cell
        # Parse grid key "LAT:LNG" and snap to 4° resolution
        parts = gk.split(":")
        if len(parts) != 2:
            continue
        try:
            cell_lat, cell_lng = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        gdelt_gk = grid_key(cell_lat + 1, cell_lng + 1, resolution=4)  # Center of 2° cell

        gdelt_count = gdelt_grid.get(gdelt_gk, 0)
        if gdelt_count < _GDELT_THRESHOLD_MILITARY:
            continue

        sample = flights[0]
        mil_count = len(flights)
        callsigns = [f.get("callsign", "?") for f in flights[:5]]

        results.append(Anomaly.create(
            domain="cross_domain",
            rule="military_near_conflict",
            severity=Severity.HIGH,
            title=f"Military aircraft in conflict zone: {mil_count} in {gk}",
            description=(
                f"{mil_count} military aircraft detected in grid cell {gk}, "
                f"which has {gdelt_count} GDELT conflict events. "
                f"Aircraft: {', '.join(callsigns)}."
            ),
            entity_id=f"mil_conflict:{gk}",
            ttl=300,
            lat=sample.get("lat"),
            lng=sample.get("lng"),
            metadata={
                "grid": gk,
                "military_count": mil_count,
                "gdelt_count": gdelt_count,
                "gdelt_grid": gdelt_gk,
                "callsigns": callsigns,
            },
        ))

    return results


def _check_internet_outage_conflict(
    snapshot: dict, gdelt_grid: dict[str, int]
) -> list[Anomaly]:
    """Rule 2: Internet outage co-located with GDELT conflict events.

    Communications disruption during conflict is a major OSINT signal.
    """
    results = []
    outages = snapshot.get("internet_outages", [])
    if not outages or not gdelt_grid:
        return results

    for outage in outages:
        severity_val = outage.get("severity", 0) or 0
        if severity_val <= 50:  # Aligned with infrastructure.py threshold
            continue

        lat = outage.get("lat")
        lng = outage.get("lng")
        if lat is None or lng is None:
            continue

        # Check if outage location falls in a conflict-heavy GDELT cell
        gdelt_gk = grid_key(lat, lng, resolution=4)
        gdelt_count = gdelt_grid.get(gdelt_gk, 0)
        if gdelt_count < _GDELT_THRESHOLD_INTERNET:
            continue

        region = outage.get("region_name", "Unknown")
        country = outage.get("country_name", "Unknown")

        results.append(Anomaly.create(
            domain="cross_domain",
            rule="internet_outage_in_conflict_zone",
            severity=Severity.HIGH,
            title=f"Internet outage in conflict zone: {region}, {country}",
            description=(
                f"Internet outage in {region}, {country} "
                f"(severity {severity_val:.0f}%) co-located with "
                f"{gdelt_count} GDELT conflict events in grid cell {gdelt_gk}. "
                f"Potential communications disruption during active conflict."
            ),
            entity_id=f"outage_conflict:{outage.get('region_code', region)}",
            ttl=600,
            lat=lat,
            lng=lng,
            metadata={
                "region": region,
                "country": country,
                "outage_severity": severity_val,
                "gdelt_count": gdelt_count,
                "gdelt_grid": gdelt_gk,
            },
        ))

    return results
