"""Anomaly detection engine — orchestrates detectors and manages anomaly lifecycle.

The engine is a module-level singleton. Detectors register themselves by tier
(fast/slow). On each detection cycle, the engine:
1. Receives a snapshot of latest_data (passed by data_fetcher.py)
2. Runs all detectors for the tier, each in a try/except
3. Rate-limits output per detector (max 25 anomalies)
4. Upserts results (dedup by anomaly_id, severity escalation, TTL refresh)
5. Appends genuinely new anomalies to a ring buffer for Tier 2 consumption
6. Prunes expired anomalies on read

Thread-safe: internal lock protects _anomalies and _recent from concurrent
API reads vs scheduler writes.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from anomaly.models import Anomaly, Severity

logger = logging.getLogger("anomaly.engine")

MAX_PER_DETECTOR = 25  # Rate limit: max anomalies per detector per cycle
RECENT_BUFFER_SIZE = 200  # Ring buffer for Tier 2 consumption


class AnomalyEngine:
    """Central anomaly detection orchestrator."""

    def __init__(self) -> None:
        self._anomalies: dict[str, Anomaly] = {}  # anomaly_id → Anomaly
        self._recent: deque[dict] = deque(maxlen=RECENT_BUFFER_SIZE)
        self._detectors: dict[str, list[Callable]] = {"fast": [], "slow": []}
        self._lock = threading.Lock()

    def register(self, tier: str, detector: Callable) -> None:
        """Register a detector function for a tier.

        Detector signature: def detect(snapshot: dict) -> list[Anomaly]
        """
        if tier not in self._detectors:
            self._detectors[tier] = []
        self._detectors[tier].append(detector)
        logger.info(f"Registered detector {detector.__name__} on {tier} tier")

    def run_detection(self, tier: str, snapshot: dict) -> None:
        """Run all detectors for the given tier against a data snapshot.

        Args:
            tier: "fast" or "slow"
            snapshot: Shallow copy of latest_data dict
        """
        t0 = time.time()
        new_count = 0
        escalated_count = 0

        for detector in self._detectors.get(tier, []):
            try:
                anomalies = detector(snapshot)
                if not anomalies:
                    continue

                # Rate limit: keep top N by severity
                if len(anomalies) > MAX_PER_DETECTOR:
                    anomalies.sort(key=lambda a: a.severity, reverse=True)
                    anomalies = anomalies[:MAX_PER_DETECTOR]

                for anomaly in anomalies:
                    was_new, was_escalated = self._upsert(anomaly)
                    if was_new:
                        new_count += 1
                    if was_escalated:
                        escalated_count += 1

            except Exception as e:
                logger.error(
                    f"Detector {detector.__name__} failed: {e}",
                    exc_info=True,
                )

        elapsed_ms = (time.time() - t0) * 1000
        active = self.active_count()
        if new_count or active:
            logger.info(
                f"Anomaly detection ({tier}): "
                f"{new_count} new, {escalated_count} escalated, "
                f"{active} active, {elapsed_ms:.0f}ms"
            )

    def _upsert(self, anomaly: Anomaly) -> tuple[bool, bool]:
        """Insert or update an anomaly. Returns (is_new, was_escalated).

        On upsert of existing anomaly:
        - Severity takes the HIGHER of old and new (escalation, never downgrade)
        - expires_at resets (TTL refresh)
        - updated_at refreshes
        - title/description/metadata update to latest
        """
        aid = anomaly.anomaly_id
        is_new = False
        was_escalated = False

        with self._lock:
            existing = self._anomalies.get(aid)

            if existing is None:
                # New anomaly
                self._anomalies[aid] = anomaly
                self._recent.append(anomaly.to_dict())
                is_new = True
            else:
                # Update existing: escalate severity, refresh TTL
                old_severity = existing.severity
                existing.severity = max(existing.severity, anomaly.severity)
                existing.updated_at = time.time()
                existing.expires_at = anomaly.expires_at
                existing.title = anomaly.title
                existing.description = anomaly.description
                existing.metadata = anomaly.metadata
                if existing.lat is None and anomaly.lat is not None:
                    existing.lat = anomaly.lat
                    existing.lng = anomaly.lng

                was_escalated = existing.severity > old_severity
                if was_escalated:
                    self._recent.append(existing.to_dict())

        return is_new, was_escalated

    def get_active_anomalies(self) -> list[dict]:
        """Return all non-expired anomalies as JSON-serializable dicts."""
        now = time.time()
        with self._lock:
            # Prune expired
            expired = [
                aid for aid, a in self._anomalies.items()
                if a.expires_at <= now
            ]
            for aid in expired:
                del self._anomalies[aid]

            return [a.to_dict() for a in self._anomalies.values()]

    def get_recent_anomalies(self, since: float = 0) -> list[dict]:
        """Return recent anomalies from the ring buffer, optionally filtered.

        Args:
            since: Unix timestamp. Only return anomalies detected after this time.
                Default 0 returns all buffered anomalies.
        """
        with self._lock:
            if since <= 0:
                return list(self._recent)
            return [
                a for a in self._recent
                if a.get("detected_at", 0) >= since
            ]

    def active_count(self) -> int:
        """Number of currently active (non-expired) anomalies."""
        now = time.time()
        with self._lock:
            return sum(1 for a in self._anomalies.values() if a.expires_at > now)


# ---------------------------------------------------------------------------
# Module-level singleton and detector registration
# ---------------------------------------------------------------------------

engine = AnomalyEngine()

# Import and register detectors — each module exposes a detect(snapshot) function
try:
    from anomaly.detectors.aircraft import detect as detect_aircraft
    engine.register("fast", detect_aircraft)
except ImportError as e:
    logger.warning(f"Aircraft detector not available: {e}")

try:
    from anomaly.detectors.maritime import detect as detect_maritime
    engine.register("fast", detect_maritime)
except ImportError as e:
    logger.warning(f"Maritime detector not available: {e}")

try:
    from anomaly.detectors.seismic import detect as detect_seismic
    engine.register("slow", detect_seismic)
except ImportError as e:
    logger.warning(f"Seismic detector not available: {e}")

try:
    from anomaly.detectors.gdelt import detect as detect_gdelt
    engine.register("slow", detect_gdelt)
except ImportError as e:
    logger.warning(f"GDELT detector not available: {e}")

try:
    from anomaly.detectors.fires import detect as detect_fires
    engine.register("slow", detect_fires)
except ImportError as e:
    logger.warning(f"Fires detector not available: {e}")

try:
    from anomaly.detectors.infrastructure import detect as detect_infrastructure
    engine.register("slow", detect_infrastructure)
except ImportError as e:
    logger.warning(f"Infrastructure detector not available: {e}")

try:
    from anomaly.detectors.cross_domain import detect as detect_cross_domain
    engine.register("fast", detect_cross_domain)
except ImportError as e:
    logger.warning(f"Cross-domain detector not available: {e}")

try:
    from anomaly.detectors.carriers import detect as detect_carriers
    engine.register("slow", detect_carriers)
except ImportError as e:
    logger.warning(f"Carriers detector not available: {e}")

try:
    from anomaly.detectors.conflict import detect as detect_conflict
    engine.register("slow", detect_conflict)
except ImportError as e:
    logger.warning(f"Conflict detector not available: {e}")


def run_detection(tier: str, snapshot: dict) -> None:
    """Module-level entry point called by data_fetcher.py."""
    engine.run_detection(tier, snapshot)
