"""Conflict escalation detector — 1 rule for Tier 1 detection.

Rules:
1. liveuamap_surge — LiveUAMap incident count increased significantly between cycles
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity

logger = logging.getLogger("anomaly.detectors.conflict")

# Module-level state: previous incident counts per region
_prev_counts: dict[str, int] = {}


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all conflict anomaly rules against the current data snapshot."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_liveuamap_surge(snapshot))
    return anomalies


def _check_liveuamap_surge(snapshot: dict) -> list[Anomaly]:
    """Rule 1: LiveUAMap incident count increased significantly between cycles.

    Counts incidents per region and compares to previous cycle. Flags regions
    where the absolute increase is >= 8 AND relative increase is >= 25%.
    Skips regions that had 0 previous count (could be scraper failure).
    """
    global _prev_counts
    results = []
    incidents = snapshot.get("liveuamap", [])
    if not incidents:
        return results

    # Count incidents per region and keep a representative sample per region
    current_counts: dict[str, int] = {}
    region_sample: dict[str, dict] = {}
    for incident in incidents:
        region = incident.get("region")
        if not region:
            continue
        current_counts[region] = current_counts.get(region, 0) + 1
        if region not in region_sample:
            region_sample[region] = incident

    # Compare to previous counts
    for region, current in current_counts.items():
        prev = _prev_counts.get(region, 0)
        if prev <= 0:
            continue  # Skip if prev was 0 — could be scraper failure
        increase = current - prev
        if increase < 8:
            continue
        if current / prev < 1.25:
            continue

        # Determine severity
        doubled = current >= prev * 2
        severity = Severity.HIGH if (increase >= 15 or doubled) else Severity.MEDIUM

        sample = region_sample.get(region, {})
        lat = sample.get("lat")
        lng = sample.get("lng")

        results.append(Anomaly.create(
            domain="conflict",
            rule="liveuamap_surge",
            severity=severity,
            title=f"Conflict surge in {region}: {prev} -> {current} incidents (+{increase})",
            description=(
                f"LiveUAMap incident count in {region} increased from {prev} to "
                f"{current} (+{increase}, {current / prev * 100 - 100:.0f}%) "
                f"between detection cycles."
            ),
            entity_id=region,
            ttl=900,
            lat=lat,
            lng=lng,
            metadata={
                "region": region,
                "current_count": current,
                "previous_count": prev,
                "increase": increase,
                "increase_pct": round(current / prev * 100 - 100, 1),
            },
        ))

    # Update previous counts at end of every cycle
    _prev_counts = dict(current_counts)

    return results
