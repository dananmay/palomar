"""Multi-domain hotspot detector — 1 rule for Tier 1 detection.

Rules:
1. multi_domain_hotspot — Geographic region with active anomalies from 3+ different domains
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.rules import grid_key

logger = logging.getLogger("anomaly.detectors.hotspot")

# Derived domains that should not count toward multi-domain hotspots
_EXCLUDED_DOMAINS = {"cross_domain", "hotspot"}


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all hotspot anomaly rules against the current data snapshot."""
    return _check_multi_domain_hotspot(snapshot)


def _check_multi_domain_hotspot(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Geographic region with active anomalies from 3+ different domains.

    Groups active anomalies by 4-degree grid cell. Flags cells where 3 or more
    unique domains have active anomalies. Skips derived domains (cross_domain,
    hotspot) to prevent double-counting.
    """
    results = []
    active = snapshot.get("active_anomalies", [])

    # Group by grid cell, tracking domains and anomaly details
    cell_domains: dict[str, set[str]] = {}
    cell_anomalies: dict[str, list[dict]] = {}
    cell_position: dict[str, tuple[float, float]] = {}

    for a in active:
        domain = a.get("domain", "")
        if domain in _EXCLUDED_DOMAINS:
            continue
        lat, lng = a.get("lat"), a.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        cell_domains.setdefault(gk, set()).add(domain)
        cell_anomalies.setdefault(gk, []).append(a)
        # Use first anomaly's position for this cell
        if gk not in cell_position:
            cell_position[gk] = (lat, lng)

    for gk, domains in cell_domains.items():
        domain_count = len(domains)
        if domain_count < 3:
            continue

        severity = Severity.CRITICAL if domain_count >= 4 else Severity.HIGH
        anomaly_list = cell_anomalies[gk]
        anomaly_count = len(anomaly_list)
        lat, lng = cell_position[gk]

        results.append(Anomaly.create(
            domain="hotspot",
            rule="multi_domain_hotspot",
            severity=severity,
            title=f"Multi-domain hotspot: {domain_count} domains in {gk}",
            description=(
                f"{domain_count} different anomaly domains active in grid cell {gk}: "
                f"{', '.join(sorted(domains))}. "
                f"{anomaly_count} total anomalies in this region."
            ),
            entity_id=gk,
            ttl=900,
            lat=lat,
            lng=lng,
            metadata={
                "domains": sorted(domains),
                "domain_count": domain_count,
                "anomaly_count": anomaly_count,
                "anomaly_titles": [a.get("title", "?") for a in anomaly_list[:10]],
            },
        ))

    return results
