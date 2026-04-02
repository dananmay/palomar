"""Anomaly data structures for Tier 1 statistical detection."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Optional


class Severity(IntEnum):
    """Anomaly severity levels."""
    LOW = 1       # Mildly unusual
    MEDIUM = 2    # Notable, worth monitoring
    HIGH = 3      # Significant, warrants deeper analysis
    CRITICAL = 4  # Immediate attention needed


@dataclass
class Anomaly:
    """A single detected anomaly from Tier 1 statistical detection.

    Anomalies are identified by anomaly_id (hash of domain:rule:entity_id)
    for deduplication. Re-detection of the same anomaly upserts rather than
    duplicates — severity escalates (never downgrades), expiry resets,
    and updated_at refreshes.
    """
    domain: str                          # "aircraft", "maritime", "seismic", "gdelt"
    rule: str                            # e.g. "emergency_squawk", "speed_anomaly"
    severity: Severity
    title: str                           # Human-readable one-liner
    description: str                     # Detail paragraph
    lat: Optional[float]                 # Location (WGS84) or None
    lng: Optional[float]
    entity_id: str                       # icao24, mmsi, earthquake id, grid key, etc.
    metadata: dict = field(default_factory=dict)   # Rule-specific extra data
    detected_at: float = field(default_factory=time.time)   # First detection
    updated_at: float = field(default_factory=time.time)    # Last re-detection
    expires_at: float = 0.0              # Auto-expiry timestamp

    @property
    def anomaly_id(self) -> str:
        """Stable identifier for deduplication. Same domain+rule+entity = same anomaly."""
        raw = f"{self.domain}:{self.rule}:{self.entity_id}"
        return hashlib.md5(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        """JSON-serializable dict for API responses."""
        d = asdict(self)
        d["anomaly_id"] = self.anomaly_id
        d["severity_label"] = self.severity.name
        d["severity"] = int(self.severity)
        return d

    @classmethod
    def create(
        cls,
        domain: str,
        rule: str,
        severity: Severity,
        title: str,
        description: str,
        entity_id: str,
        ttl: float,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> Anomaly:
        """Convenience constructor that sets timestamps and expiry from TTL."""
        now = time.time()
        return cls(
            domain=domain,
            rule=rule,
            severity=severity,
            title=title,
            description=description,
            lat=lat,
            lng=lng,
            entity_id=entity_id,
            metadata=metadata or {},
            detected_at=now,
            updated_at=now,
            expires_at=now + ttl,
        )
