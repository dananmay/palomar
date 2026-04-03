"""Tier 2: Cheap model triage — contextual annotations and highlights.

One LLM call per batch annotates every active anomaly with a one-line
explanation and identifies which ones genuinely warrant analyst attention.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("triage")


def run_triage_cycle(anomalies: list[dict], news: list[dict]) -> None:
    """Main entry point called by scheduler.

    Chains batcher → runner → store. If runner returns None (no model
    configured, LLM error), previous triage results are preserved.
    """
    from triage.batcher import prepare_batch
    from triage.runner import run_triage
    from triage.store import TriageResult, triage_store

    if not anomalies:
        logger.debug("Triage: no active anomalies, skipping")
        return

    # Prepare prompt content
    anomalies_text, news_text, id_mapping = prepare_batch(anomalies, news)
    if not anomalies_text:
        return

    # Call LLM
    result = run_triage(anomalies_text, news_text)
    if result is None:
        # LLM call failed or no model configured — keep previous results
        return

    annotations, highlights, model = result
    now = time.time()

    # Map short IDs back to real anomaly_ids
    for ann in annotations:
        short_id = ann.get("anomaly_id", "")
        ann["anomaly_id"] = id_mapping.get(short_id, short_id)

    highlighted_ids = set()
    highlight_reasons: dict[str, str] = {}
    for h in highlights:
        short_id = h.get("anomaly_id", "")
        real_id = id_mapping.get(short_id, short_id)
        h["anomaly_id"] = real_id
        highlighted_ids.add(real_id)
        highlight_reasons[real_id] = h.get("reason", "")

    # Build TriageResults
    triage_results: list[TriageResult] = []
    for ann in annotations:
        aid = ann["anomaly_id"]
        triage_results.append(TriageResult(
            anomaly_id=aid,
            context=ann.get("context", ""),
            highlighted=aid in highlighted_ids,
            highlight_reason=highlight_reasons.get(aid, ""),
            model=model,
            analyzed_at=now,
        ))

    # Update store (full replacement)
    triage_store.update(triage_results)
    logger.info(
        f"Triage cycle complete: {len(triage_results)} annotated, "
        f"{len(highlighted_ids)} highlighted"
    )
