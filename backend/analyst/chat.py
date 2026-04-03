"""Tier 3 chat orchestrator.

Handles a single chat message: builds state snapshot, manages history,
loads the conversation prompt, calls the strong model via LiteLLM.

This is a sync function — FastAPI runs it in a thread pool automatically,
keeping the event loop free for other requests.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from analyst.state import build_state_snapshot
from analyst.history import manage_history

logger = logging.getLogger("analyst.chat")

# Lazy litellm import
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
            logger.warning("litellm not installed — chat requires: pip install litellm")
    return _litellm


def _load_prompt() -> str | None:
    """Load conversation prompt template from prompts/conversation.md."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "prompts", "conversation.md"
    )
    prompt_path = os.path.normpath(prompt_path)
    try:
        with open(prompt_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Conversation prompt not found: {prompt_path}")
        return None


def handle_chat(
    message: str,
    history: list[dict],
    selected_anomaly_id: Optional[str] = None,
    news: Optional[list[dict]] = None,
) -> dict:
    """Handle a single chat message. Sync — runs in FastAPI's thread pool.

    Args:
        message: The user's message text
        history: Full conversation history [{role, content}, ...]
        selected_anomaly_id: Currently selected anomaly on map (or None)
        news: News snapshot from the data pipeline

    Returns:
        {response: str, model: str, latency_ms: int}

    Raises:
        ValueError: If model is not configured or litellm is missing
    """
    # Check configuration
    model = os.environ.get("PALOMAR_ANALYST_MODEL", "").strip()
    if not model:
        raise ValueError(
            "Configure PALOMAR_ANALYST_MODEL in .env to enable the analyst "
            "(e.g., claude-sonnet-4-6, openai/gpt-4o, ollama/llama3.2)"
        )

    litellm = _get_litellm()
    if litellm is None:
        raise ValueError("litellm is required: pip install litellm")

    # Build state snapshot (anomalies + triage + news + selected)
    state = build_state_snapshot(selected_anomaly_id, news or [])

    # Manage conversation history (summarize old turns if needed)
    trimmed_history, conversation_summary = manage_history(history)

    # Load and populate the prompt template
    template = _load_prompt()
    if template is None:
        raise ValueError("Conversation prompt template not found")

    prompt = template.replace("{anomalies}", state["anomalies_text"])
    prompt = prompt.replace("{news_context}", state["news_text"])
    prompt = prompt.replace("{selected_anomaly}", state["selected_anomaly_text"])
    prompt = prompt.replace("{conversation_summary}", conversation_summary or "No prior conversation.")

    # Build messages array
    messages = [{"role": "system", "content": prompt}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": message})

    # Call LLM
    kwargs = {
        "model": model,
        "messages": messages,
        "timeout": 120,
        "num_retries": 2,
        "temperature": 0.5,
        "max_tokens": 8192,
    }

    ollama_base = os.environ.get("PALOMAR_OLLAMA_BASE_URL", "").strip()
    if model.startswith("ollama/") and ollama_base:
        kwargs["api_base"] = ollama_base

    t0 = time.time()
    try:
        response = litellm.completion(**kwargs)
    except Exception as e:
        logger.error(f"Chat LLM call failed ({model}): {e}")
        raise ValueError(f"Model error: {e}")

    elapsed_ms = int((time.time() - t0) * 1000)

    # Extract response
    try:
        text = response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        raise ValueError("No content in model response")

    logger.info(
        f"Chat: {len(messages)} messages → {model} → "
        f"{len(text)} chars, {elapsed_ms}ms"
    )

    return {
        "response": text,
        "model": model,
        "latency_ms": elapsed_ms,
    }


def get_chat_status() -> dict:
    """Check if chat is available. For GET /api/chat/status."""
    model = os.environ.get("PALOMAR_ANALYST_MODEL", "").strip()
    litellm = _get_litellm()

    if not model:
        return {"available": False, "model": None, "error": "PALOMAR_ANALYST_MODEL not configured"}
    if litellm is None:
        return {"available": False, "model": None, "error": "litellm not installed"}

    return {"available": True, "model": model, "error": None}
