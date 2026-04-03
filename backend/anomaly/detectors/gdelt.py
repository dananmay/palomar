"""GDELT/News anomaly detector — 4 rules for Tier 1 detection.

Rules:
1. risk_escalation — Regional news risk score jumps significantly
2. news_surge — Sudden spike in news articles about a region
3. gdelt_density_change — GDELT conflict event count changes significantly
4. news_risk_acceleration — Cycle-over-cycle risk score jump in a region

Note: GDELT data uses GeoJSON coordinate order [lng, lat].
News data uses [lat, lng]. Handle both correctly.
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key

logger = logging.getLogger("anomaly.detectors.gdelt")

# Module-level baselines
_risk_baseline = RollingBaseline(window_seconds=21600)   # 6h for risk scores
_news_baseline = RollingBaseline(window_seconds=21600)   # 6h for article counts
_gdelt_baseline = RollingBaseline(window_seconds=43200)  # 12h for conflict density

# Risk score jump threshold (absolute points)
_RISK_JUMP_THRESHOLD = 3

# Module-level state for risk acceleration tracking (cycle-over-cycle)
_prev_risk: dict[str, int] = {}
_warmup_done: bool = False


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all GDELT/news anomaly rules."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_risk_escalation(snapshot))
    anomalies.extend(_check_news_surge(snapshot))
    anomalies.extend(_check_gdelt_density(snapshot))
    anomalies.extend(_check_news_risk_acceleration(snapshot))
    return anomalies


def _check_risk_escalation(snapshot: dict) -> list[Anomaly]:
    """Rule 1: Regional max risk score jumps significantly vs baseline.

    Groups geocoded news articles by 4° grid cell and tracks max risk score
    per cell. Flags when current max exceeds 6h baseline mean by >3 points.
    """
    results = []
    news = snapshot.get("news", [])
    if not news:
        return results

    # Group articles by region, track max risk score
    grid_risk: dict[str, tuple[int, dict]] = {}  # gk → (max_risk, article)
    for article in news:
        coords = article.get("coords")
        if not coords or len(coords) < 2:
            continue
        # News uses [lat, lng] order
        lat, lng = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        risk = article.get("risk_score", 0) or 0
        if gk not in grid_risk or risk > grid_risk[gk][0]:
            grid_risk[gk] = (risk, article)

    for gk, (risk, article) in grid_risk.items():
        _risk_baseline.record(gk, risk)

        # Check if current risk exceeds baseline mean by threshold
        baseline_mean = _risk_baseline.mean(gk)
        if baseline_mean is not None and risk > baseline_mean + _RISK_JUMP_THRESHOLD:
            # Need enough samples for meaningful comparison
            if _risk_baseline.count(gk) < 3:
                continue

            coords = article.get("coords", [None, None])
            results.append(Anomaly.create(
                domain="gdelt",
                rule="risk_escalation",
                severity=Severity.HIGH if risk >= 8 else Severity.MEDIUM,
                title=f"Risk escalation in {gk}: score {risk}/10",
                description=(
                    f"News risk score in region {gk} jumped to {risk}/10 "
                    f"(baseline mean: {baseline_mean:.1f}). "
                    f"Top article: {article.get('title', 'N/A')[:80]}"
                ),
                entity_id=gk,
                ttl=600,
                lat=coords[0] if coords else None,
                lng=coords[1] if len(coords) > 1 else None,
                metadata={
                    "grid": gk,
                    "risk_score": risk,
                    "baseline_mean": round(baseline_mean, 1),
                    "jump": round(risk - baseline_mean, 1),
                    "top_article_title": article.get("title", "")[:100],
                    "top_article_source": article.get("source", ""),
                },
            ))

    return results


def _check_news_surge(snapshot: dict) -> list[Anomaly]:
    """Rule 2: Sudden spike in news articles about a region.

    Counts geocoded articles per 4° grid cell and flags when count exceeds
    baseline + 2σ.
    """
    results = []
    news = snapshot.get("news", [])
    if not news:
        return results

    # Count articles per grid cell
    grid_counts: dict[str, int] = {}
    grid_sample: dict[str, dict] = {}  # first article per cell for metadata
    for article in news:
        coords = article.get("coords")
        if not coords or len(coords) < 2:
            continue
        lat, lng = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        if gk not in grid_sample:
            grid_sample[gk] = article

    for gk, count in grid_counts.items():
        _news_baseline.record(gk, count)
        is_anom, z = _news_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=5, min_abs_deviation=3,
        )
        if is_anom:
            sample = grid_sample[gk]
            coords = sample.get("coords", [None, None])
            results.append(Anomaly.create(
                domain="gdelt",
                rule="news_surge",
                severity=Severity.MEDIUM,
                title=f"News surge in {gk}: {count} articles (z={z:.1f})",
                description=(
                    f"{count} news articles detected in region {gk}, "
                    f"z-score {z:.1f} above baseline. "
                    f"Sample: {sample.get('title', 'N/A')[:80]}"
                ),
                entity_id=gk,
                ttl=600,
                lat=coords[0] if coords else None,
                lng=coords[1] if len(coords) > 1 else None,
                metadata={"grid": gk, "count": count, "z_score": round(z, 2),
                          "sample_title": sample.get("title", "")[:100]},
            ))

    return results


def _check_gdelt_density(snapshot: dict) -> list[Anomaly]:
    """Rule 3: GDELT conflict event density change.

    Counts conflict events per 4° grid cell (matching existing news clustering
    resolution) and flags when count exceeds baseline + 2σ.

    IMPORTANT: GDELT data is GeoJSON — coordinates are [lng, lat] order.
    """
    results = []
    gdelt = snapshot.get("gdelt", [])
    if not gdelt:
        return results

    # GDELT can be a list of GeoJSON features or a FeatureCollection
    features = gdelt
    if isinstance(gdelt, dict):
        features = gdelt.get("features", [])

    # Count features per grid cell
    grid_counts: dict[str, int] = {}
    grid_sample: dict[str, dict] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        # GeoJSON uses [lng, lat] order — swap for our grid_key
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        if gk not in grid_sample:
            grid_sample[gk] = feature

    for gk, count in grid_counts.items():
        _gdelt_baseline.record(gk, count)
        is_anom, z = _gdelt_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=3, min_abs_deviation=5,
        )
        if is_anom:
            sample = grid_sample[gk]
            props = sample.get("properties", {})
            geom = sample.get("geometry", {})
            coords = geom.get("coordinates", [None, None])
            results.append(Anomaly.create(
                domain="gdelt",
                rule="gdelt_density_change",
                severity=Severity.MEDIUM,
                title=f"GDELT conflict surge in {gk}: {count} events (z={z:.1f})",
                description=(
                    f"{count} GDELT conflict events in region {gk}, "
                    f"z-score {z:.1f} above 12h baseline."
                ),
                entity_id=gk,
                ttl=900,
                # GeoJSON [lng, lat] → we store as lat, lng
                lat=coords[1] if len(coords) > 1 else None,
                lng=coords[0] if coords else None,
                metadata={"grid": gk, "count": count, "z_score": round(z, 2)},
            ))

    return results


def _check_news_risk_acceleration(snapshot: dict) -> list[Anomaly]:
    """Rule 4: Cycle-over-cycle risk score jump in a region.

    Tracks max news risk_score per 4-degree grid cell between detection cycles.
    Flags cells where risk jumped by >= 3 points AND current max >= 5.
    First cycle is warmup only (records baseline, no alerts).
    """
    global _prev_risk, _warmup_done
    results = []
    news = snapshot.get("news", [])

    # Build current max risk per grid cell
    current_risk: dict[str, tuple[int, dict]] = {}  # gk -> (max_risk, article)
    for article in news:
        coords = article.get("coords")
        if not coords or len(coords) < 2:
            continue
        lat, lng = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        risk = article.get("risk_score", 0) or 0
        if gk not in current_risk or risk > current_risk[gk][0]:
            current_risk[gk] = (risk, article)

    if not _warmup_done:
        # First cycle: just record and mark warmup done
        _prev_risk = {gk: risk for gk, (risk, _) in current_risk.items()}
        _warmup_done = True
        return results

    # Compare current to previous cycle
    for gk, (cur_max, article) in current_risk.items():
        prev_max = _prev_risk.get(gk, 0)
        jump = cur_max - prev_max
        if jump >= 3 and cur_max >= 5:
            severity = Severity.HIGH if (jump >= 5 or cur_max >= 8) else Severity.MEDIUM
            coords = article.get("coords", [None, None])
            results.append(Anomaly.create(
                domain="gdelt",
                rule="news_risk_acceleration",
                severity=severity,
                title=f"Risk acceleration in {gk}: {prev_max} -> {cur_max} (+{jump})",
                description=(
                    f"News risk score in region {gk} jumped from {prev_max} to "
                    f"{cur_max} (+{jump} points) between detection cycles. "
                    f"Top article: {article.get('title', 'N/A')[:80]}"
                ),
                entity_id=gk,
                ttl=600,
                lat=coords[0] if coords else None,
                lng=coords[1] if len(coords) > 1 else None,
                metadata={
                    "grid": gk,
                    "current_risk": cur_max,
                    "previous_risk": prev_max,
                    "jump": jump,
                    "top_article_title": article.get("title", "")[:100],
                    "top_article_source": article.get("source", ""),
                },
            ))

    # Update previous risk for next cycle
    _prev_risk = {gk: risk for gk, (risk, _) in current_risk.items()}

    return results
