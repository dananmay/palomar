"""Fire/thermal anomaly detector — 4 rules for Tier 1 detection.

Rules:
1. fire_near_nuclear_plant — FIRMS hotspot within 10km of a nuclear power plant
2. fire_near_military_base — FIRMS hotspot within 10km of a military base
3. fire_cluster_surge — Unusual concentration of fires in a region
4. fire_in_conflict_zone — High-FRP fire in a GDELT conflict hotspot
"""
from __future__ import annotations

import logging
from anomaly.models import Anomaly, Severity
from anomaly.baselines import RollingBaseline
from anomaly.rules import grid_key, haversine_km

logger = logging.getLogger("anomaly.detectors.fires")

# Baselines
_fire_baseline = RollingBaseline(window_seconds=43200)  # 12h

# Cached infrastructure lists (built once on first call)
_nuclear_plants: list[dict] | None = None
_PROXIMITY_KM = 10.0
_BOUNDS_DEG = 0.15  # ±0.15° pre-filter (~17km at equator, generous bounding box)
_MIN_FRP = 10  # Minimum fire radiative power (MW) to consider


def detect(snapshot: dict) -> list[Anomaly]:
    """Run all fire anomaly rules."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_check_fire_near_nuclear(snapshot))
    anomalies.extend(_check_fire_near_military_base(snapshot))
    anomalies.extend(_check_fire_cluster_surge(snapshot))
    anomalies.extend(_check_fire_in_conflict_zone(snapshot))
    return anomalies


def _get_nuclear_plants(snapshot: dict) -> list[dict]:
    """Cache nuclear plants from power_plants data (filter once).

    Only caches when plants are found. If power_plants data isn't loaded yet
    (first snapshot), returns empty and retries next cycle.
    """
    global _nuclear_plants
    if _nuclear_plants is None:
        all_plants = snapshot.get("power_plants", [])
        if not all_plants:
            return []  # Data not loaded yet — retry next cycle
        found = [
            p for p in all_plants
            if "nuclear" in (p.get("fuel_type", "") or "").lower()
            and p.get("lat") is not None
            and p.get("lng") is not None
        ]
        if found:
            _nuclear_plants = found
            logger.info(f"Cached {len(_nuclear_plants)} nuclear plants for fire proximity detection")
        else:
            return []  # No nuclear plants found — retry next cycle
    return _nuclear_plants


def _check_fire_near_nuclear(snapshot: dict) -> list[Anomaly]:
    """Rule 1: FIRMS hotspot within 10km of a nuclear power plant."""
    results = []
    nuclear = _get_nuclear_plants(snapshot)
    if not nuclear:
        return results

    fires = snapshot.get("firms_fires", [])
    for fire in fires:
        frp = fire.get("frp", 0) or 0
        if frp < _MIN_FRP:
            continue

        f_lat = fire.get("lat")
        f_lng = fire.get("lng")
        if f_lat is None or f_lng is None:
            continue

        for plant in nuclear:
            p_lat, p_lng = plant["lat"], plant["lng"]
            # Bounding box pre-filter (BOTH dimensions)
            if abs(f_lat - p_lat) > _BOUNDS_DEG or abs(f_lng - p_lng) > _BOUNDS_DEG:
                continue
            dist = haversine_km(f_lat, f_lng, p_lat, p_lng)
            if dist <= _PROXIMITY_KM:
                plant_name = plant.get("name", "Unknown")
                results.append(Anomaly.create(
                    domain="fires",
                    rule="fire_near_nuclear_plant",
                    severity=Severity.CRITICAL,
                    title=f"Fire detected near {plant_name}",
                    description=(
                        f"Thermal anomaly (FRP={frp:.0f}MW) detected {dist:.1f}km "
                        f"from nuclear plant {plant_name} "
                        f"({plant.get('country', '?')}, {plant.get('capacity_mw', '?')}MW). "
                        f"Confidence: {fire.get('confidence', 'N/A')}."
                    ),
                    entity_id=f"nuclear:{plant_name}:{f_lat:.2f}:{f_lng:.2f}",
                    ttl=3600,
                    lat=f_lat,
                    lng=f_lng,
                    metadata={
                        "plant_name": plant_name,
                        "plant_country": plant.get("country"),
                        "plant_capacity_mw": plant.get("capacity_mw"),
                        "distance_km": round(dist, 1),
                        "fire_frp": frp,
                        "fire_confidence": fire.get("confidence"),
                    },
                ))
                break  # One match per fire is enough

    return results


def _check_fire_near_military_base(snapshot: dict) -> list[Anomaly]:
    """Rule 2: FIRMS hotspot within 10km of a military base."""
    results = []
    bases = snapshot.get("military_bases", [])
    if not bases:
        return results

    fires = snapshot.get("firms_fires", [])
    for fire in fires:
        frp = fire.get("frp", 0) or 0
        if frp < _MIN_FRP:
            continue

        f_lat = fire.get("lat")
        f_lng = fire.get("lng")
        if f_lat is None or f_lng is None:
            continue

        for base in bases:
            b_lat = base.get("lat")
            b_lng = base.get("lng")
            if b_lat is None or b_lng is None:
                continue
            if abs(f_lat - b_lat) > _BOUNDS_DEG or abs(f_lng - b_lng) > _BOUNDS_DEG:
                continue
            dist = haversine_km(f_lat, f_lng, b_lat, b_lng)
            if dist <= _PROXIMITY_KM:
                base_name = base.get("name", "Unknown")
                results.append(Anomaly.create(
                    domain="fires",
                    rule="fire_near_military_base",
                    severity=Severity.HIGH,
                    title=f"Fire detected near {base_name}",
                    description=(
                        f"Thermal anomaly (FRP={frp:.0f}MW) detected {dist:.1f}km "
                        f"from military base {base_name} "
                        f"({base.get('country', '?')}, {base.get('branch', '?')})."
                    ),
                    entity_id=f"milbase:{base_name}:{f_lat:.2f}:{f_lng:.2f}",
                    ttl=1800,
                    lat=f_lat,
                    lng=f_lng,
                    metadata={
                        "base_name": base_name,
                        "base_country": base.get("country"),
                        "base_branch": base.get("branch"),
                        "distance_km": round(dist, 1),
                        "fire_frp": frp,
                        "fire_confidence": fire.get("confidence"),
                    },
                ))
                break

    return results


def _check_fire_cluster_surge(snapshot: dict) -> list[Anomaly]:
    """Rule 3: Unusual fire concentration per 2° grid cell."""
    results = []
    fires = snapshot.get("firms_fires", [])
    if not fires:
        return results

    # Count fires per grid cell
    grid_counts: dict[str, int] = {}
    grid_sample: dict[str, dict] = {}
    for fire in fires:
        lat, lng = fire.get("lat"), fire.get("lng")
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=2)
        grid_counts[gk] = grid_counts.get(gk, 0) + 1
        if gk not in grid_sample:
            grid_sample[gk] = fire

    for gk, count in grid_counts.items():
        _fire_baseline.record(gk, count)
        is_anom, z = _fire_baseline.is_anomalous(
            gk, count, sigma=2.0, min_samples=3, min_abs_deviation=20,
        )
        if is_anom:
            sample = grid_sample[gk]
            severity = Severity.HIGH if count >= 50 else Severity.MEDIUM
            results.append(Anomaly.create(
                domain="fires",
                rule="fire_cluster_surge",
                severity=severity,
                title=f"Fire cluster surge: {count} hotspots in {gk}",
                description=(
                    f"{count} thermal anomalies detected in grid cell {gk}, "
                    f"z-score {z:.1f} above 12h baseline."
                ),
                entity_id=gk,
                ttl=1800,
                lat=sample.get("lat"),
                lng=sample.get("lng"),
                metadata={"grid": gk, "count": count, "z_score": round(z, 2)},
            ))

    return results


def _check_fire_in_conflict_zone(snapshot: dict) -> list[Anomaly]:
    """Rule 4: High-FRP fire in a GDELT conflict hotspot.

    Cross-references FIRMS fires against GDELT conflict density. Flags fires
    with FRP > 30 that fall in a 4-degree grid cell with >= 10 GDELT events.
    """
    results = []
    fires = snapshot.get("firms_fires", [])
    if not fires:
        return results

    # Build GDELT conflict grid (count events per 4° cell)
    gdelt = snapshot.get("gdelt", [])
    if not gdelt:
        return results

    features = gdelt
    if isinstance(gdelt, dict):
        features = gdelt.get("features", [])

    conflict_grid: dict[str, int] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        # GeoJSON uses [lng, lat] order — swap
        lng, lat = coords[0], coords[1]
        if lat is None or lng is None:
            continue
        gk = grid_key(lat, lng, resolution=4)
        conflict_grid[gk] = conflict_grid.get(gk, 0) + 1

    if not conflict_grid:
        return results

    # Aggregate fires per conflict grid cell (track count + max FRP)
    cell_data: dict[str, dict] = {}  # gk → {count, max_frp, best_fire, gdelt_count}
    for fire in fires:
        frp = fire.get("frp", 0) or 0
        if frp <= 30:
            continue
        f_lat = fire.get("lat")
        f_lng = fire.get("lng")
        if f_lat is None or f_lng is None:
            continue

        gk = grid_key(f_lat, f_lng, resolution=4)
        gdelt_count = conflict_grid.get(gk, 0)
        if gdelt_count < 10:
            continue

        if gk not in cell_data or frp > cell_data[gk]["max_frp"]:
            cell_data[gk] = {
                "count": cell_data.get(gk, {}).get("count", 0) + 1,
                "max_frp": frp,
                "fire": fire,
                "gdelt_count": gdelt_count,
            }
        else:
            cell_data[gk]["count"] += 1

    for gk, data in cell_data.items():
        max_frp = data["max_frp"]
        count = data["count"]
        fire = data["fire"]
        gdelt_count = data["gdelt_count"]
        severity = Severity.CRITICAL if max_frp > 100 else Severity.HIGH
        results.append(Anomaly.create(
            domain="fires",
            rule="fire_in_conflict_zone",
            severity=severity,
            title=f"Fire in conflict zone {gk}: {count} hotspots (max FRP={max_frp:.0f}MW), {gdelt_count} GDELT events",
            description=(
                f"{count} thermal anomal{'y' if count == 1 else 'ies'} (max FRP={max_frp:.0f}MW) "
                f"detected in grid cell {gk} which has {gdelt_count} GDELT conflict events."
            ),
            entity_id=gk,
            ttl=1800,
            lat=fire.get("lat"),
            lng=fire.get("lng"),
            metadata={
                "grid": gk,
                "fire_count": count,
                "max_frp": max_frp,
                "gdelt_event_count": gdelt_count,
            },
        ))

    return results
