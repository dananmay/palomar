"""Triage batcher — formats anomalies and regional news for the triage prompt.

Prepares the {anomalies} and {regional_news} template variables used in
prompts/triage.md. Assigns short sequential IDs (a1, a2, ...) to save tokens
and returns a mapping to convert response IDs back to real anomaly_ids.
"""
from __future__ import annotations

import time


def _time_ago(ts: float) -> str:
    """Convert Unix timestamp to relative time string."""
    seconds = int(time.time() - ts)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def _grid_key_4deg(lat: float, lng: float) -> str:
    """Snap coordinates to a 4° grid cell key."""
    return f"{int(lat // 4) * 4}:{int(lng // 4) * 4}"


def prepare_batch(
    anomalies: list[dict], news: list[dict]
) -> tuple[str, str, dict[str, str]]:
    """Format anomalies and regional news for the triage prompt.

    Args:
        anomalies: List of anomaly dicts from engine.get_active_anomalies()
        news: List of news article dicts from latest_data["news"]

    Returns:
        (anomalies_text, regional_news_text, id_mapping)
        id_mapping maps short prompt IDs ("a1", "a2") back to real anomaly_ids.
        Returns ("", "", {}) if no anomalies.
    """
    if not anomalies:
        return "", "", {}

    # Sort by severity (desc) then recency (desc), cap at 20
    sorted_anomalies = sorted(
        anomalies,
        key=lambda a: (a.get("severity", 0), a.get("detected_at", 0)),
        reverse=True,
    )[:20]

    # Build anomaly text with short IDs
    id_mapping: dict[str, str] = {}  # "a1" → real anomaly_id
    anomaly_lines = []
    anomaly_grids: set[str] = set()  # Track grids for news matching

    for i, a in enumerate(sorted_anomalies):
        short_id = f"a{i + 1}"
        real_id = a.get("anomaly_id", "")
        id_mapping[short_id] = real_id

        lat = a.get("lat")
        lng = a.get("lng")
        detected = _time_ago(a.get("detected_at", time.time()))

        parts = [
            f'id: "{short_id}"',
            f'domain: {a.get("domain", "?")}',
            f'rule: {a.get("rule", "?")}',
            f'severity: {a.get("severity", 0)}',
            f'title: "{a.get("title", "")}"',
            f'description: "{a.get("description", "")}"',
        ]
        if lat is not None and lng is not None:
            parts.append(f"lat: {lat:.1f}, lng: {lng:.1f}")
            anomaly_grids.add(_grid_key_4deg(lat, lng))
        parts.append(f"detected: {detected}")

        anomaly_lines.append("- " + ", ".join(parts))

    anomalies_text = "\n".join(anomaly_lines)

    # Build regional news context
    news_text = _match_regional_news(news, anomaly_grids)

    return anomalies_text, news_text, id_mapping


def _match_regional_news(news: list[dict], anomaly_grids: set[str]) -> str:
    """Select news articles relevant to anomaly regions.

    Matches news by 4° grid cell, including 3×3 neighborhood around each
    anomaly grid. Also includes high-risk unlocated news for general context.
    """
    if not news:
        return "No recent news available."

    # Expand anomaly grids to 3×3 neighborhoods
    expanded_grids: set[str] = set()
    for gk in anomaly_grids:
        parts = gk.split(":")
        if len(parts) != 2:
            continue
        try:
            base_lat, base_lng = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        for dlat in (-4, 0, 4):
            for dlng in (-4, 0, 4):
                expanded_grids.add(f"{base_lat + dlat}:{base_lng + dlng}")

    matched: list[dict] = []

    for article in news:
        coords = article.get("coords")
        if not coords or len(coords) < 2 or coords[0] is None or coords[1] is None:
            continue  # Skip unlocated news — prevents irrelevant global headlines from leaking in
        news_grid = _grid_key_4deg(coords[0], coords[1])
        if news_grid in expanded_grids:
            matched.append(article)

    # Only geographically matched news, cap at 20
    selected = matched[:20]

    if not selected:
        return "No relevant regional news found."

    lines = []
    for article in selected:
        title = article.get("title", "")
        source = article.get("source", "")
        risk = article.get("risk_score", 0) or 0
        line = f'- "{title}" ({source}'
        if risk >= 5:
            line += f", risk {risk}/10"
        line += ")"
        lines.append(line)

    return "\n".join(lines)
