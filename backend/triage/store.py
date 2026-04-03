"""Triage result storage — thread-safe store for Tier 2 annotations and highlights.

Triage results are separate from Tier 1 anomalies. They're merged into API
responses at serve time, keeping the anomaly detection system immutable.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class TriageResult:
    """AI-generated annotation and highlight status for a single anomaly."""
    anomaly_id: str
    context: str              # One-line contextual annotation
    highlighted: bool         # Whether this is a "Palomar's pick"
    highlight_reason: str     # Why it's highlighted (empty string if not)
    model: str                # Which model produced this
    analyzed_at: float        # When triage ran (Unix timestamp)


class TriageStore:
    """Thread-safe store mapping anomaly_id → TriageResult.

    update() does a full replacement — after each triage cycle, only
    currently-analyzed anomalies have results. No stale entries accumulate.
    """

    def __init__(self) -> None:
        self._results: dict[str, TriageResult] = {}
        self._lock = threading.Lock()
        self._last_model: str | None = None
        self._last_run_at: float | None = None
        self._last_highlight_count: int = 0
        self._last_annotation_count: int = 0

    def update(self, results: list[TriageResult]) -> None:
        """Atomic full replacement of all triage results."""
        with self._lock:
            self._results = {r.anomaly_id: r for r in results}
            if results:
                self._last_model = results[0].model
                self._last_run_at = results[0].analyzed_at
                self._last_highlight_count = sum(1 for r in results if r.highlighted)
                self._last_annotation_count = len(results)

    def get(self, anomaly_id: str) -> TriageResult | None:
        """Get triage result for a specific anomaly."""
        with self._lock:
            return self._results.get(anomaly_id)

    def merge_into(self, anomalies: list[dict]) -> list[dict]:
        """Enrich anomaly dicts with triage fields.

        Sets ai_context, ai_highlighted, ai_highlight_reason, ai_model,
        ai_analyzed_at on every anomaly dict. Anomalies without triage
        results get null/false defaults.
        """
        with self._lock:
            for a in anomalies:
                result = self._results.get(a.get("anomaly_id", ""))
                if result:
                    a["ai_context"] = result.context
                    a["ai_highlighted"] = result.highlighted
                    a["ai_highlight_reason"] = result.highlight_reason if result.highlighted else None
                    a["ai_model"] = result.model
                    a["ai_analyzed_at"] = result.analyzed_at
                else:
                    a["ai_context"] = None
                    a["ai_highlighted"] = False
                    a["ai_highlight_reason"] = None
                    a["ai_model"] = None
                    a["ai_analyzed_at"] = None
        return anomalies

    def last_run_info(self) -> dict | None:
        """Return info about the last triage run for /api/health."""
        with self._lock:
            if self._last_run_at is None:
                return None
            return {
                "model": self._last_model,
                "last_run_at": self._last_run_at,
                "annotations": self._last_annotation_count,
                "highlights": self._last_highlight_count,
            }


# Module-level singleton
triage_store = TriageStore()
