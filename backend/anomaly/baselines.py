"""Rolling statistical baselines for Tier 1 anomaly detection.

Maintains sliding windows of (timestamp, value) pairs per key and provides
simple statistical tests (mean, std, z-score) to determine if a new value
is anomalous. Thread-safe via internal lock.

No external dependencies — pure Python math.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional


class RollingBaseline:
    """Thread-safe rolling window of observations for statistical anomaly detection.

    Each key (e.g., a grid cell identifier) maintains its own deque of
    (timestamp, value) pairs. Old entries are pruned based on window_seconds.
    """

    def __init__(self, window_seconds: float = 21600):  # 6 hours default
        self._data: dict[str, deque[tuple[float, float]]] = {}
        self._window = window_seconds
        self._lock = threading.Lock()
        self._op_count = 0

    def record(self, key: str, value: float) -> None:
        """Record a new observation for the given key."""
        now = time.time()
        with self._lock:
            if key not in self._data:
                self._data[key] = deque()
            self._data[key].append((now, value))
            self._prune_key(key, now)
            # Lazy cleanup of stale empty keys every 500 operations
            self._op_count += 1
            if self._op_count % 500 == 0:
                self._cleanup_empty_keys()

    def _prune_key(self, key: str, now: float) -> None:
        """Remove entries older than the window. Must be called under lock."""
        cutoff = now - self._window
        dq = self._data.get(key)
        if dq:
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def _cleanup_empty_keys(self) -> None:
        """Remove keys with empty deques. Must be called under lock."""
        empty = [k for k, v in self._data.items() if not v]
        for k in empty:
            del self._data[k]

    def count(self, key: str) -> int:
        """Number of observations in the rolling window for a key."""
        with self._lock:
            self._prune_key(key, time.time())
            dq = self._data.get(key)
            return len(dq) if dq else 0

    def mean(self, key: str) -> Optional[float]:
        """Mean of values in the rolling window, or None if no data."""
        with self._lock:
            self._prune_key(key, time.time())
            dq = self._data.get(key)
            if not dq:
                return None
            return sum(v for _, v in dq) / len(dq)

    def std(self, key: str) -> Optional[float]:
        """Population standard deviation of values, or None if no data."""
        with self._lock:
            self._prune_key(key, time.time())
            dq = self._data.get(key)
            if not dq or len(dq) < 2:
                return None
            values = [v for _, v in dq]
            n = len(values)
            avg = sum(values) / n
            variance = sum((v - avg) ** 2 for v in values) / n
            return math.sqrt(variance)

    def maximum(self, key: str) -> Optional[float]:
        """Maximum value in the rolling window, or None if no data."""
        with self._lock:
            self._prune_key(key, time.time())
            dq = self._data.get(key)
            if not dq:
                return None
            return max(v for _, v in dq)

    def is_anomalous(
        self,
        key: str,
        value: float,
        sigma: float = 2.0,
        min_samples: int = 5,
        min_abs_deviation: float = 0,
    ) -> tuple[bool, float]:
        """Test if a value is anomalous relative to the rolling baseline.

        Args:
            key: Baseline key (e.g., grid cell identifier)
            value: Current observation to test
            sigma: Number of standard deviations for anomaly threshold
            min_samples: Minimum observations needed before flagging
            min_abs_deviation: Minimum absolute difference from mean required
                (prevents flagging when 1 unit differs from 0 baseline)

        Returns:
            (is_anomalous: bool, z_score: float)
            z_score is float('inf') when std=0 and value differs from mean.
        """
        with self._lock:
            now = time.time()
            self._prune_key(key, now)
            dq = self._data.get(key)

            if not dq or len(dq) < min_samples:
                return False, 0.0

            values = [v for _, v in dq]
            n = len(values)
            avg = sum(values) / n
            abs_dev = abs(value - avg)

            # Absolute deviation guard
            if abs_dev < min_abs_deviation:
                return False, 0.0

            variance = sum((v - avg) ** 2 for v in values) / n
            sd = math.sqrt(variance)

            if sd == 0:
                # All historical values identical. Flag only if deviation
                # exceeds the minimum absolute threshold.
                if value != avg and abs_dev >= min_abs_deviation:
                    return True, float('inf')
                return False, 0.0

            z = abs_dev / sd
            return z > sigma, z
