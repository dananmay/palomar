"""Infrastructure anomaly detector — 2 rules for Tier 1 detection.

Rules:
1. geomagnetic_storm — Kp index indicates geomagnetic storm conditions
2. critical_internet_outage — Significant BGP/ping internet outage
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity

logger = logging.getLogger("anomaly.detectors.infrastructure")


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all infrastructure anomaly rules."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_geomagnetic_storm(snapshot))
    anomalies.extend(_check_internet_outage(snapshot))
    return anomalies


def _check_geomagnetic_storm(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Geomagnetic storm from space weather Kp index.

    Kp scale:
    - 0-3: Quiet
    - 4: Active (current level, no alert)
    - 5: Storm G1 (minor) → MEDIUM
    - 6: Storm G2 (moderate) → MEDIUM
    - 7: Storm G3 (strong) → HIGH
    - 8: Storm G4 (severe) → CRITICAL
    - 9: Storm G5 (extreme) → CRITICAL
    """
    results = []
    sw = snapshot.get("space_weather")
    if not sw or not isinstance(sw, dict):
        return results

    kp = sw.get("kp_index")
    if kp is None:
        return results

    try:
        kp = float(kp)
    except (ValueError, TypeError):
        return results

    if kp < 5:
        return results

    if kp >= 8:
        severity = Severity.CRITICAL
        level = f"G{min(int(kp) - 4, 5)}"
    elif kp >= 7:
        severity = Severity.HIGH
        level = "G3"
    else:
        severity = Severity.MEDIUM
        level = f"G{int(kp) - 4}"

    kp_text = sw.get("kp_text", "STORM")
    events = sw.get("events", [])
    event_summary = ""
    if events:
        event_types = [e.get("type", "?") for e in events if e.get("type")]
        if event_types:
            event_summary = f" Active solar events: {', '.join(event_types[:5])}."

    results.append(Anomaly.create(
        domain="infrastructure",
        rule="geomagnetic_storm",
        severity=severity,
        title=f"Geomagnetic storm {level}: Kp={kp:.1f}",
        description=(
            f"Geomagnetic storm conditions detected. Kp index: {kp:.1f} "
            f"({kp_text}), storm level {level}. "
            f"May affect GPS accuracy, HF radio communications, and power grids."
            f"{event_summary}"
        ),
        entity_id="geomagnetic",
        ttl=600,
        lat=None,
        lng=None,
        metadata={
            "kp_index": kp,
            "kp_text": kp_text,
            "storm_level": level,
            "event_count": len(events),
        },
    ))

    return results


def _check_internet_outage(snapshot: dict) -> list[Anomaly]:
    """Rule 2: Critical internet outages from IODA BGP/ping data."""
    results = []
    outages = snapshot.get("internet_outages", [])
    if not outages:
        return results

    for outage in outages:
        severity_val = outage.get("severity", 0)
        if severity_val is None:
            continue
        try:
            severity_val = float(severity_val)
        except (ValueError, TypeError):
            continue

        if severity_val <= 50:
            continue

        severity = Severity.HIGH if severity_val > 70 else Severity.MEDIUM
        region = outage.get("region_name", "Unknown")
        country = outage.get("country_name", "Unknown")
        datasource = outage.get("datasource", "unknown")
        level = outage.get("level", "")

        results.append(Anomaly.create(
            domain="infrastructure",
            rule="critical_internet_outage",
            severity=severity,
            title=f"Internet outage: {region}, {country} (severity {severity_val:.0f}%)",
            description=(
                f"Significant internet outage detected in {region}, {country}. "
                f"Severity: {severity_val:.0f}% ({level}), "
                f"data source: {datasource}. "
                f"Indicates potential infrastructure disruption, cable damage, "
                f"or state-level internet restrictions."
            ),
            entity_id=f"outage:{outage.get('region_code', region)}",
            ttl=600,
            lat=outage.get("lat"),
            lng=outage.get("lng"),
            metadata={
                "region": region,
                "country": country,
                "severity_pct": severity_val,
                "level": level,
                "datasource": datasource,
                "region_code": outage.get("region_code"),
            },
        ))

    return results
