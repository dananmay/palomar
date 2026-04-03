"""Conversation history manager for Tier 3 chat.

Handles rolling summarization: keeps the last N turn pairs in full,
summarizes older turns into a paragraph using the cheap Tier 2 model.
Failure is never fatal — if summarization fails, silently truncates.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("analyst.history")

# Lazy litellm import (same pattern as triage/runner.py)
_litellm = None
_litellm_import_attempted = False


def _get_litellm():
    global _litellm, _litellm_import_attempted
    if not _litellm_import_attempted:
        _litellm_import_attempted = True
        try:
            import litellm
            litellm.suppress_debug_info = True
            _litellm = litellm
        except ImportError:
            pass
    return _litellm


def manage_history(
    history: list[dict], max_turns: int = 8
) -> tuple[list[dict], str]:
    """Trim conversation history and summarize old turns.

    Args:
        history: Full conversation history [{role, content}, ...]
        max_turns: Max turn pairs to keep in full (1 turn = user + assistant)

    Returns:
        (trimmed_history, conversation_summary)
        If summarization fails, returns truncated history with empty summary.
    """
    max_messages = max_turns * 2  # Each turn is a user + assistant pair

    if len(history) <= max_messages:
        return history, ""

    # Split: old messages to summarize, recent messages to keep
    cutoff = len(history) - max_messages
    old_messages = history[:cutoff]
    recent_messages = history[cutoff:]

    # Try to summarize the old messages
    summary = _summarize(old_messages)

    return recent_messages, summary


def _summarize(messages: list[dict]) -> str:
    """Summarize old conversation messages using the cheap model.

    Returns summary string, or empty string on any failure.
    """
    litellm = _get_litellm()
    if litellm is None:
        return ""

    model = os.environ.get("PALOMAR_TRIAGE_MODEL", "").strip()
    if not model:
        return ""

    # Format messages for summarization
    conversation_text = ""
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        conversation_text += f"{role}: {content}\n\n"

    prompt = (
        "Summarize this conversation between a user and an OSINT analyst in "
        "2-3 sentences. Focus on what was discussed, any key findings, and "
        "conclusions reached. Be concise.\n\n"
        f"Conversation:\n{conversation_text}"
    )

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 30,
        "num_retries": 1,
        "temperature": 0.1,
        "max_tokens": 256,
    }

    ollama_base = os.environ.get("PALOMAR_OLLAMA_BASE_URL", "").strip()
    if model.startswith("ollama/") and ollama_base:
        kwargs["api_base"] = ollama_base

    try:
        response = litellm.completion(**kwargs)
        text = response.choices[0].message.content or ""
        logger.info(f"History summarized: {len(messages)} messages → {len(text)} chars")
        return text.strip()
    except Exception as e:
        logger.warning(f"History summarization failed: {e}")
        return ""
