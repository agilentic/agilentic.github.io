"""
utils/llm.py – Async Claude API wrapper (anthropic SDK).

Model: claude-sonnet-4-20250514

Features
--------
* Simple ``chat()`` and ``chat_json()`` async helpers.
* Exponential back-off with jitter on rate-limit (429) and server (>=500) errors.
* ``chat_json()`` validates that all expected schema keys are present and retries
  once if the model returns malformed JSON or missing keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-20250514"

_MAX_RETRIES = 5
_BASE_DELAY_S = 1.0       # initial back-off delay (seconds)
_MAX_DELAY_S = 120.0      # cap for exponential back-off
_JITTER_RANGE = 0.3       # ± fraction of current delay added as jitter

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS: set[int] = {429, 500, 502, 503, 504}


# ──────────────────────────────────────────────────────────────
# Client singleton (created lazily)
# ──────────────────────────────────────────────────────────────

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it or add it to your .env file."
            )
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


# ──────────────────────────────────────────────────────────────
# Back-off helper
# ──────────────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """Return True when *exc* is an API error that should be retried."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False


async def _call_with_backoff(
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    """
    Call the Claude Messages API with exponential back-off + jitter.

    Returns the text content of the first content block.
    Raises the last exception after *_MAX_RETRIES* exhausted.
    """
    client = _get_client()
    delay = _BASE_DELAY_S

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            # Extract text from the first content block
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        except Exception as exc:
            if not _is_retryable(exc) or attempt == _MAX_RETRIES:
                logger.error(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                raise

            jitter = delay * _JITTER_RANGE * (2 * random.random() - 1)
            wait = min(delay + jitter, _MAX_DELAY_S)
            logger.warning(
                "LLM call retryable error (attempt %d/%d), waiting %.1fs: %s",
                attempt,
                _MAX_RETRIES,
                wait,
                exc,
            )
            await asyncio.sleep(wait)
            delay = min(delay * 2, _MAX_DELAY_S)

    # Should be unreachable, but satisfies type checkers
    raise RuntimeError("_call_with_backoff: exceeded retries without raising")


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

async def chat(
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> str:
    """
    Send a single-turn chat request and return the assistant's reply as a string.

    Parameters
    ----------
    system:
        System-prompt text.
    user:
        User message text.
    max_tokens:
        Maximum tokens in the completion (default 1 024).

    Returns
    -------
    str
        The assistant's text response (may be empty string if no text block).
    """
    return await _call_with_backoff(system=system, user=user, max_tokens=max_tokens)


async def chat_json(
    system: str,
    user: str,
    schema_keys: list[str],
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """
    Like ``chat()``, but parses the response as JSON and validates that all
    *schema_keys* are present in the top-level object.

    Retries **once** if the first attempt produces invalid JSON or is missing
    required keys (a second LLM call is made with an error hint prepended).

    Parameters
    ----------
    system:
        System-prompt text.
    user:
        User message text.
    schema_keys:
        List of keys that must exist in the parsed response dict.
    max_tokens:
        Maximum tokens in the completion.

    Returns
    -------
    dict
        Parsed and validated JSON object.

    Raises
    ------
    ValueError
        If both attempts fail to produce a valid, complete JSON object.
    """
    for attempt in range(1, 3):  # at most 2 attempts
        prompt = user if attempt == 1 else (
            f"Your previous response was not valid JSON or was missing required keys "
            f"({schema_keys}). Please respond with ONLY a valid JSON object containing "
            f"exactly these top-level keys: {schema_keys}.\n\n{user}"
        )

        raw = await _call_with_backoff(
            system=system + "\nAlways respond with ONLY valid JSON — no markdown fences.",
            user=prompt,
            max_tokens=max_tokens,
        )

        # Strip markdown fences if the model added them anyway
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first and last fence lines
            text = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "chat_json attempt %d: JSON parse error: %s | raw=%r",
                attempt,
                exc,
                raw[:200],
            )
            if attempt == 2:
                raise ValueError(
                    f"LLM returned invalid JSON after 2 attempts. Last raw: {raw[:500]}"
                ) from exc
            continue

        if not isinstance(data, dict):
            logger.warning(
                "chat_json attempt %d: expected dict, got %s",
                attempt,
                type(data).__name__,
            )
            if attempt == 2:
                raise ValueError(
                    f"LLM returned a non-object JSON value: {type(data).__name__}"
                )
            continue

        missing = [k for k in schema_keys if k not in data]
        if missing:
            logger.warning(
                "chat_json attempt %d: missing keys %s in response",
                attempt,
                missing,
            )
            if attempt == 2:
                raise ValueError(
                    f"LLM response missing required keys {missing} after 2 attempts."
                )
            continue

        return data

    # Unreachable, but keeps type checkers happy
    raise ValueError("chat_json: exhausted attempts")
