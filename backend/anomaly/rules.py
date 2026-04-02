"""Shared rules and utilities for Tier 1 anomaly detection.

Contains geospatial helpers (haversine, grid keys) used by multiple detectors.
No imports from services/ — this module is self-contained.
"""
from __future__ import annotations

import math
from typing import Optional


def grid_key(lat: float, lng: float, resolution: int = 1) -> str:
    """Snap coordinates to a grid cell key.

    Args:
        lat: Latitude (-90 to 90)
        lng: Longitude (-180 to 180)
        resolution: Grid cell size in degrees (1° ≈ 111km at equator)

    Returns:
        String key like "40:25" for the grid cell.
    """
    return f"{int(lat // resolution) * resolution}:{int(lng // resolution) * resolution}"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in kilometers.

    Uses the haversine formula. Duplicated from geo.py to maintain
    separation between the anomaly module and the services layer.
    """
    R = 6371.0  # Earth radius in km
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_near_airport(
    lat: float,
    lng: float,
    airports: list[dict],
    max_distance_km: float = 50.0,
) -> bool:
    """Check if a position is within max_distance_km of any airport.

    Args:
        lat, lng: Position to check
        airports: List of airport dicts with 'lat' and 'lng' keys.
            Expected to be large airports only (~500 entries from
            latest_data["airports"]).
        max_distance_km: Threshold distance

    Returns:
        True if within range of at least one airport.
    """
    for apt in airports:
        apt_lat = apt.get("lat")
        apt_lng = apt.get("lng")
        if apt_lat is None or apt_lng is None:
            continue
        if haversine_km(lat, lng, apt_lat, apt_lng) <= max_distance_km:
            return True
    return False
