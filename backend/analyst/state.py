"""State snapshot builder for Tier 3 chat.

Builds the context that gets injected into the conversation prompt on every
message: active anomalies with triage annotations, regional news, and the
currently selected anomaly.

Does NOT import from services/fetchers/_store — news is passed in by the
endpoint to maintain separation between AI layer and data pipeline.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("analyst.state")

# Fail-safe imports from AI layer modules (not services/)
try:
    from anomaly.engine import engine as _engine
except Exception:
    _engine = None

try:
    from triage.store import triage_store as _triage_store
except Exception:
    _triage_store = None

try:
    from anomaly.rules import grid_key
except Exception:
    def grid_key(lat, lng, resolution=1):
        return f"{int(lat // resolution) * resolution}:{int(lng // resolution) * resolution}"


def _time_ago(ts: float) -> str:
    """Convert Unix timestamp to relative time string."""
    seconds = int(time.time() - ts)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def build_state_snapshot(
    selected_anomaly_id: Optional[str],
    news: list[dict],
) -> dict:
    """Build fresh state for the conversation prompt.

    Args:
        selected_anomaly_id: Currently selected anomaly on the map (or None)
        news: News snapshot passed from endpoint (NOT from _store)

    Returns:
        {anomalies_text, news_text, selected_anomaly_text}
    """
    # Get active anomalies with triage enrichment
    anomalies = []
    if _engine:
        anomalies = _engine.get_active_anomalies()
        if _triage_store:
            _triage_store.merge_into(anomalies)

    # Format anomalies
    anomalies_text = _format_anomalies(anomalies)

    # Match regional news to anomaly locations
    news_text = _match_news(anomalies, news)

    # Format selected anomaly
    selected_anomaly_text = _format_selected(anomalies, selected_anomaly_id)

    return {
        "anomalies_text": anomalies_text,
        "news_text": news_text,
        "selected_anomaly_text": selected_anomaly_text,
    }


def _format_anomalies(anomalies: list[dict]) -> str:
    """Format anomalies as rich multi-line blocks for the analyst model."""
    if not anomalies:
        return "No active anomalies."

    # Sort by severity (desc) then recency (desc)
    sorted_anomalies = sorted(
        anomalies,
        key=lambda a: (a.get("severity", 0), a.get("detected_at", 0)),
        reverse=True,
    )

    lines = []
    for a in sorted_anomalies:
        sev = a.get("severity_label", "?")
        title = a.get("title", "?")
        desc = a.get("description", "")
        lat = a.get("lat")
        lng = a.get("lng")
        detected = _time_ago(a.get("detected_at", time.time()))
        domain = a.get("domain", "?")
        rule = a.get("rule", "?")

        block = f"[{sev}] {title}\n"
        block += f"  Domain: {domain}/{rule}\n"
        if desc:
            block += f"  Description: {desc}\n"

        # Triage annotations
        ai_context = a.get("ai_context")
        if ai_context:
            block += f"  AI context: {ai_context}\n"
        if a.get("ai_highlighted"):
            reason = a.get("ai_highlight_reason", "")
            block += f"  Highlighted: Yes — {reason}\n"

        if lat is not None and lng is not None:
            block += f"  Location: {lat:.2f}, {lng:.2f}\n"
        block += f"  Detected: {detected}"
        if a.get("updated_at") and a["updated_at"] != a.get("detected_at"):
            block += f" · Updated: {_time_ago(a['updated_at'])}"

        lines.append(block)

    return "\n\n".join(lines)


def _match_news(anomalies: list[dict], news: list[dict]) -> str:
    """Match news articles to anomaly regions using 4° grid cells."""
    if not news:
        return "No recent news available."

    # Build set of grid cells near anomalies (3×3 neighborhood)
    anomaly_grids: set[str] = set()
    for a in anomalies:
        lat, lng = a.get("lat"), a.get("lng")
        if lat is not None and lng is not None:
            base_gk = grid_key(lat, lng, resolution=4)
            parts = base_gk.split(":")
            if len(parts) == 2:
                try:
                    base_lat, base_lng = int(parts[0]), int(parts[1])
                    for dlat in (-4, 0, 4):
                        for dlng in (-4, 0, 4):
                            anomaly_grids.add(f"{base_lat + dlat}:{base_lng + dlng}")
                except ValueError:
                    pass

    regional = []
    global_context = []

    for article in news:
        coords = article.get("coords")
        risk = article.get("risk_score", 0) or 0

        if coords and len(coords) >= 2 and coords[0] is not None and coords[1] is not None:
            news_gk = grid_key(coords[0], coords[1], resolution=4)
            if news_gk in anomaly_grids:
                regional.append(article)
                continue

        if risk >= 7:
            global_context.append(article)

    lines = []
    if regional:
        lines.append("Regional (near anomaly locations):")
        for a in regional[:15]:
            title = a.get("title", "")
            source = a.get("source", "")
            risk = a.get("risk_score", 0) or 0
            line = f'- "{title}" ({source}'
            if risk >= 5:
                line += f", risk {risk}/10"
            line += ")"
            lines.append(line)

    if global_context:
        if lines:
            lines.append("")
        lines.append("Global (not near any anomaly — only reference if a causal link is clear):")
        for a in global_context[:5]:
            title = a.get("title", "")
            source = a.get("source", "")
            risk = a.get("risk_score", 0) or 0
            lines.append(f'- "{title}" ({source}, risk {risk}/10)')

    return "\n".join(lines) if lines else "No relevant news found."


def _format_selected(anomalies: list[dict], selected_id: Optional[str]) -> str:
    """Format the selected anomaly for the prompt."""
    if not selected_id:
        return "No anomaly selected."

    for a in anomalies:
        if a.get("anomaly_id") == selected_id:
            parts = [
                f"[{a.get('severity_label', '?')}] {a.get('title', '?')}",
                f"Domain: {a.get('domain')}/{a.get('rule')}",
            ]
            if a.get("description"):
                parts.append(f"Description: {a['description']}")
            if a.get("ai_context"):
                parts.append(f"AI context: {a['ai_context']}")
            if a.get("ai_highlighted"):
                parts.append(f"Highlighted: {a.get('ai_highlight_reason', '')}")
            lat, lng = a.get("lat"), a.get("lng")
            if lat is not None and lng is not None:
                parts.append(f"Location: {lat:.4f}, {lng:.4f}")
            parts.append(f"Detected: {_time_ago(a.get('detected_at', time.time()))}")

            # Include metadata
            meta = a.get("metadata", {})
            if meta:
                meta_items = [
                    f"  {k}: {v}" for k, v in meta.items()
                    if not k.startswith("_") and not isinstance(v, (list, dict))
                ]
                if meta_items:
                    parts.append("Details:\n" + "\n".join(meta_items))

            return "\n".join(parts)

    return "Previously selected anomaly has expired."
