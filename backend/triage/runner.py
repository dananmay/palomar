"""Triage runner — calls LLM via LiteLLM and parses the JSON response.

Loads the prompt template from prompts/triage.md on every call (allows live
editing). Handles malformed JSON from small models gracefully.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger("triage.runner")

# Lazy import — litellm may not be installed
_litellm = None
_litellm_import_attempted = False


def _get_litellm():
    """Lazy import litellm. Returns module or None."""
    global _litellm, _litellm_import_attempted
    if not _litellm_import_attempted:
        _litellm_import_attempted = True
        try:
            import litellm
            litellm.suppress_debug_info = True
            _litellm = litellm
        except ImportError:
            logger.warning(
                "litellm not installed — triage requires: pip install litellm"
            )
    return _litellm


def _load_prompt() -> str | None:
    """Load triage prompt template from prompts/triage.md."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "prompts", "triage.md"
    )
    prompt_path = os.path.normpath(prompt_path)
    try:
        with open(prompt_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Triage prompt not found: {prompt_path}")
        return None


def _parse_json_response(text: str) -> dict | None:
    """Parse JSON from LLM response, handling common failure modes.

    Small models often wrap JSON in markdown fences, add preamble text,
    or include trailing commas. This parser handles all of those.
    """
    if not text:
        return None

    cleaned = text.strip()

    # Strip markdown fences: ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    # Strip preamble text before first {
    brace_pos = cleaned.find("{")
    if brace_pos > 0:
        cleaned = cleaned[brace_pos:]

    # Strip text after last }
    last_brace = cleaned.rfind("}")
    if last_brace >= 0:
        cleaned = cleaned[: last_brace + 1]

    # Fix trailing commas before } or ] (common LLM mistake)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    logger.warning(f"Failed to parse triage JSON response ({len(text)} chars)")
    return None


def run_triage(
    anomalies_text: str, news_text: str
) -> tuple[list[dict], list[dict], str] | None:
    """Load prompt, call LLM via LiteLLM, parse response.

    Args:
        anomalies_text: Formatted anomaly text for {anomalies} substitution
        news_text: Formatted news text for {regional_news} substitution

    Returns:
        (annotations, highlights, model_name) or None on failure.
    """
    if not anomalies_text:
        return None

    # Check model configuration
    model = os.environ.get("PALOMAR_TRIAGE_MODEL", "").strip()
    if not model:
        return None

    # Check litellm availability
    litellm = _get_litellm()
    if litellm is None:
        return None

    # Load prompt template
    template = _load_prompt()
    if template is None:
        return None

    # Substitute template variables
    prompt = template.replace("{anomalies}", anomalies_text)
    prompt = prompt.replace("{regional_news}", news_text)

    # Build LiteLLM kwargs
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 120,
        "num_retries": 2,
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    # Ollama support
    ollama_base = os.environ.get("PALOMAR_OLLAMA_BASE_URL", "").strip()
    if model.startswith("ollama/") and ollama_base:
        kwargs["api_base"] = ollama_base

    # Call LLM
    t0 = time.time()
    try:
        response = litellm.completion(**kwargs)
    except Exception as e:
        logger.error(f"Triage LLM call failed ({model}): {e}")
        return None

    elapsed = time.time() - t0

    # Extract response text
    try:
        text = response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        logger.error("Triage: no content in LLM response")
        return None

    # Parse JSON
    result = _parse_json_response(text)
    if result is None:
        return None

    # Extract annotations and highlights
    annotations = result.get("annotations", [])
    highlights = result.get("highlights", [])

    # Validate structure
    if not isinstance(annotations, list):
        annotations = []
    if not isinstance(highlights, list):
        highlights = []

    # Filter to valid entries
    annotations = [
        a for a in annotations
        if isinstance(a, dict) and "anomaly_id" in a and "context" in a
    ]
    highlights = [
        h for h in highlights
        if isinstance(h, dict) and "anomaly_id" in h
    ]

    logger.info(
        f"Triage: {len(annotations)} annotations, "
        f"{len(highlights)} highlights "
        f"via {model} in {elapsed:.1f}s"
    )

    return annotations, highlights, model
