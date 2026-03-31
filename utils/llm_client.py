"""
llm_client.py
-------------
Centralised LLM client wrapper around the Groq API.

Design decisions:
  - Uses the FAST_MODEL (8b) for bulk extraction tasks → higher rate limits
  - Uses the SMART_MODEL (70b) for entailment and risk reasoning → higher quality
  - Exponential backoff: 1s, 2s, 4s between retries
  - temperature=0.1 for deterministic structured output
  - json_mode=True enforces JSON response format
  - All calls pass through a single function → one place to add caching/logging
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any

from groq import AsyncGroq, Groq, RateLimitError

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Client (singleton) ────────────────────────────────────────────────────────

_client: Groq | None = None
_async_client: AsyncGroq | None = None
_groq_semaphore = asyncio.Semaphore(5)


def get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com"
            )
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def get_async_client() -> AsyncGroq:
    global _async_client
    if _async_client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com"
            )
        _async_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _async_client


# ── Core call ─────────────────────────────────────────────────────────────────

def call_llm(
    prompt: str,
    system: str = "You are a precise legal and technical compliance analyst. "
                  "Always respond with valid JSON only — no markdown, no preamble.",
    model: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    retries: int | None = None,
) -> dict[str, Any] | str:
    """
    Call the Groq LLM with automatic retry and exponential backoff.

    Args:
        prompt:      The user message content.
        system:      System prompt (defaults to compliance analyst persona).
        model:       Groq model name. Defaults to settings.SMART_MODEL.
        json_mode:   If True, enforces JSON output and parses the response.
        max_tokens:  Maximum response tokens.
        temperature: Sampling temperature (0.1 = deterministic).
        retries:     Number of retry attempts. Defaults to settings.MAX_RETRIES.

    Returns:
        Parsed dict if json_mode=True, raw string otherwise.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    model = model or settings.SMART_MODEL
    retries = retries if retries is not None else settings.MAX_RETRIES
    client = get_client()

    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content.strip()

            if json_mode:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "JSON parse failed on attempt %d/%d: %s\nRaw: %s",
                        attempt + 1, retries, e, text[:200],
                    )
                    # Try to extract JSON from markdown fences if present
                    if "```" in text:
                        import re
                        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                        if match:
                            return json.loads(match.group(1))
                    raise

            return text

        except RateLimitError as e:
            wait = 2 ** attempt
            logger.warning(
                "Rate limit hit on attempt %d/%d. Sleeping %ds. Error: %s",
                attempt + 1, retries, wait, e,
            )
            time.sleep(wait)
            last_error = e

        except Exception as e:
            wait = 2 ** attempt
            logger.error(
                "LLM call failed on attempt %d/%d. Sleeping %ds. Error: %s",
                attempt + 1, retries, wait, e,
            )
            if attempt < retries - 1:
                time.sleep(wait)
            last_error = e

    raise RuntimeError(
        f"LLM call failed after {retries} attempts. Last error: {last_error}"
    )


async def acall_llm(
    prompt: str,
    system: str = "You are a precise legal and technical compliance analyst. "
                  "Always respond with valid JSON only — no markdown, no preamble.",
    model: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    retries: int | None = None,
) -> dict[str, Any] | str:
    """
    Async Groq call with retry, exponential backoff, and rate limiting.
    """
    model = model or settings.SMART_MODEL
    retries = retries if retries is not None else settings.MAX_RETRIES
    client = get_async_client()
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            async with _groq_semaphore:
                response = await client.chat.completions.create(**kwargs)
            text = (response.choices[0].message.content or "").strip()

            if json_mode:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Async JSON parse failed on attempt %d/%d: %s\nRaw: %s",
                        attempt + 1, retries, e, text[:200],
                    )
                    raise
            return text

        except RateLimitError as e:
            last_error = e
            if attempt >= retries - 1:
                break
            wait = (2 ** attempt) + random.uniform(0, 0.25)
            logger.warning(
                "Async rate limit hit on attempt %d/%d. Sleeping %.2fs. Error: %s",
                attempt + 1, retries, wait, e,
            )
            await asyncio.sleep(wait)

        except Exception as e:
            last_error = e
            if attempt >= retries - 1:
                break
            wait = (2 ** attempt) + random.uniform(0, 0.25)
            logger.error(
                "Async LLM call failed on attempt %d/%d. Sleeping %.2fs. Error: %s",
                attempt + 1, retries, wait, e,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(
        f"Async LLM call failed after {retries} attempts. Last error: {last_error}"
    )


# ── Convenience wrappers ──────────────────────────────────────────────────────

def call_smart(prompt: str, system: str | None = None, **kwargs) -> dict[str, Any]:
    """Use the 70B model — for entailment classification and risk reasoning."""
    kw = {"model": settings.SMART_MODEL, "json_mode": True, **kwargs}
    if system:
        kw["system"] = system
    return call_llm(prompt, **kw)  # type: ignore[return-value]


def call_fast(prompt: str, system: str | None = None, **kwargs) -> dict[str, Any]:
    """Use the 8B model — for bulk extraction tasks (higher rate limit)."""
    kw = {"model": settings.FAST_MODEL, "json_mode": True, **kwargs}
    if system:
        kw["system"] = system
    return call_llm(prompt, **kw)  # type: ignore[return-value]


async def acall_smart(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.0,
    **kwargs,
) -> dict[str, Any]:
    """
    Async smart call with model routing:
    - Start on SMART_MODEL (70B)
    - On repeated rate limits, fall back to FAST_MODEL (8B) for final attempt.
    """
    client = get_async_client()
    current_model = settings.SMART_MODEL
    base_system = (
        system
        or "You are a precise legal and technical compliance analyst. "
           "Always respond with valid JSON only — no markdown, no preamble."
    )

    last_error: Exception | None = None

    for attempt in range(3):
        try:
            kwargs_payload: dict[str, Any] = {
                "model": current_model,
                "messages": [
                    {"role": "system", "content": base_system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            async with _groq_semaphore:
                response = await client.chat.completions.create(**kwargs_payload)
            text = (response.choices[0].message.content or "").strip()
            return json.loads(text)

        except RateLimitError as e:
            last_error = e
            # On the second failure (attempt index 1), route to fallback model
            if attempt == 1:
                logger.warning(
                    "SMART_MODEL rate-limited twice. Routing to FAST_MODEL fallback..."
                )
                current_model = settings.FAST_MODEL
                await asyncio.sleep(1.0)
                continue

            # Standard smart sleep based on error hint if present
            import re

            match = re.search(r"Please try again in ([0-9.]+)s", str(e))
            wait_time = (float(match.group(1)) + 1.0) if match else (3 ** attempt)
            logger.warning(
                "Rate limit on model %s attempt %d/3. Sleeping %.2fs. Error: %s",
                current_model,
                attempt + 1,
                wait_time,
                e,
            )
            await asyncio.sleep(wait_time)

        except Exception as e:
            last_error = e
            if attempt == 2:
                break
            wait = 2 ** attempt
            logger.error(
                "acall_smart failed on model %s attempt %d/3. Sleeping %.2fs. Error: %s",
                current_model,
                attempt + 1,
                wait,
                e,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(f"acall_smart exhausted retries. Last error: {last_error}")


async def acall_fast(prompt: str, system: str | None = None, **kwargs) -> dict[str, Any]:
    """Async 8B model call for bulk extraction tasks."""
    kw = {"model": settings.FAST_MODEL, "json_mode": True, **kwargs}
    if system:
        kw["system"] = system
    return await acall_llm(prompt, **kw)  # type: ignore[return-value]


def call_fast_batch(
    prompts: list[str],
    system: str | None = None,
    sleep_between: float | None = None,
    **kwargs,
) -> list[dict[str, Any]]:
    """
    Process a list of prompts sequentially with rate-limit sleep between calls.
    Uses the fast model. Returns results in the same order as prompts.
    """
    sleep = sleep_between if sleep_between is not None else settings.RATE_LIMIT_SLEEP
    results = []
    for i, prompt in enumerate(prompts):
        result = call_fast(prompt, system=system, **kwargs)
        results.append(result)
        if i < len(prompts) - 1:
            time.sleep(sleep)
    return results


async def acall_fast_batch(
    prompts: list[str],
    system: str | None = None,
    sleep_between: float | None = None,
    **kwargs,
) -> list[dict[str, Any]]:
    """Async batch helper for fast model calls."""
    sleep = sleep_between if sleep_between is not None else settings.RATE_LIMIT_SLEEP
    results = []
    for i, prompt in enumerate(prompts):
        result = await acall_fast(prompt, system=system, **kwargs)
        results.append(result)
        if i < len(prompts) - 1:
            await asyncio.sleep(sleep)
    return results