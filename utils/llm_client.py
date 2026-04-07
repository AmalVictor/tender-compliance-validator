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
import hashlib
import json
import logging
import time
from types import SimpleNamespace
from typing import Any

from groq import AsyncGroq, Groq, RateLimitError
from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal, LLMCache

logger = logging.getLogger(__name__)

# ── Client (singleton) ────────────────────────────────────────────────────────

_client: Groq | None = None
_async_client: AsyncGroq | None = None


def _is_groq_rate_limit_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return "429" in str(e) or "rate limit" in msg


def _rate_limit_fallback_json_str() -> str:
    return json.dumps(
        {
            "reply": "Data unavailable due to rate limits.",
            "status": "NONE",
            "confidence": 0.0,
        }
    )


class _GroqRateLimitFakeResponse:
    """Synthetic completion when Groq returns 429 after all retries."""

    _is_rl_fallback = True

    def __init__(self, content: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


def _map_generic_rl_fallback_to_entailment_shape(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep EntailmentResponse-compatible payload when using generic RL fallback JSON."""
    if raw.get("reply") == "Data unavailable due to rate limits.":
        return {
            "status": "NONE",
            "confidence": float(raw.get("confidence", 0.0)),
            "evidence_quote": None,
            "section_ref": None,
            "explanation": str(raw["reply"]),
        }
    return raw


async def _groq_chat_with_traffic_and_rl_backoff(
    client: AsyncGroq,
    *,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """
    Per-attempt: traffic slot (see services.audit_orchestrator) + 1.5s trickle, then create.
    On 429 / rate limit: exponential-style backoff (attempt+1)*3 seconds between attempts.
    After max_retries, return a synthetic response (never raises for exhausted RL).
    Other errors: re-raise immediately.
    """
    from services.audit_orchestrator import run_llm_with_traffic

    for attempt in range(max_retries):
        try:
            return await run_llm_with_traffic(client.chat.completions.create(**kwargs))
        except Exception as e:
            if not _is_groq_rate_limit_error(e):
                raise
            logger.warning(
                "Groq rate limited (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
            if attempt >= max_retries - 1:
                return _GroqRateLimitFakeResponse(_rate_limit_fallback_json_str())
            await asyncio.sleep((attempt + 1) * 3)
    return _GroqRateLimitFakeResponse(_rate_limit_fallback_json_str())


def _make_prompt_hash(system: str, prompt: str, model: str) -> str:
    payload = f"{system}\n---\n{prompt}\n---\n{model}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _get_cached_json(prompt_hash: str) -> dict[str, Any] | None:
    db = AsyncSessionLocal()
    try:
        result = await db.execute(
            select(LLMCache).where(LLMCache.prompt_hash == prompt_hash)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        logger.info("LLM Cache HIT")
        return json.loads(row.response_json)
    finally:
        await db.close()


async def _set_cached_json(prompt_hash: str, model_name: str, response_dict: dict[str, Any]) -> None:
    db = AsyncSessionLocal()
    try:
        cache_row = LLMCache(
            prompt_hash=prompt_hash,
            model_name=model_name,
            response_json=json.dumps(response_dict),
        )
        db.add(cache_row)
        await db.commit()
    except Exception:
        await db.rollback()
        # Best-effort cache write; avoid blocking normal LLM flow.
    finally:
        await db.close()


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

    max_rl_retries = 3
    response = None
    for attempt in range(max_rl_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except Exception as e:
            if not _is_groq_rate_limit_error(e):
                raise
            logger.warning(
                "Groq rate limited (sync attempt %d/%d): %s",
                attempt + 1,
                max_rl_retries,
                e,
            )
            if attempt >= max_rl_retries - 1:
                if json_mode:
                    return json.loads(_rate_limit_fallback_json_str())
                return _rate_limit_fallback_json_str()
            time.sleep((attempt + 1) * 3)

    assert response is not None
    text = (response.choices[0].message.content or "").strip()

    if json_mode:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed: %s\nRaw: %s", e, text[:200])
            if "```" in text:
                import re

                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            raise

    return text


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
    prompt_hash = _make_prompt_hash(system, prompt, model)

    if json_mode:
        cached = await _get_cached_json(prompt_hash)
        if cached is not None:
            return cached

        logger.info("LLM Cache MISS - Calling API")

    kwargs_llm: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs_llm["response_format"] = {"type": "json_object"}

    response = await _groq_chat_with_traffic_and_rl_backoff(
        client, max_retries=3, **kwargs_llm
    )
    text = (response.choices[0].message.content or "").strip()

    if json_mode:
        try:
            response_dict = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                "Async JSON parse failed: %s\nRaw: %s",
                e,
                text[:200],
            )
            raise
        if not getattr(response, "_is_rl_fallback", False):
            await _set_cached_json(prompt_hash, model, response_dict)
        return response_dict

    return text


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
            prompt_hash = _make_prompt_hash(base_system, prompt, current_model)
            cached = await _get_cached_json(prompt_hash)
            if cached is not None:
                return cached

            logger.info("LLM Cache MISS - Calling API")

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
            response = await _groq_chat_with_traffic_and_rl_backoff(
                client, max_retries=3, **kwargs_payload
            )
            text = (response.choices[0].message.content or "").strip()
            response_dict = json.loads(text)

            if getattr(response, "_is_rl_fallback", False):
                if current_model == settings.SMART_MODEL and attempt < 2:
                    logger.warning(
                        "Groq rate limit exhausted on %s; retrying with FAST_MODEL",
                        current_model,
                    )
                    current_model = settings.FAST_MODEL
                    await asyncio.sleep(1.0)
                    continue
                response_dict = _map_generic_rl_fallback_to_entailment_shape(response_dict)
                return response_dict

            await _set_cached_json(prompt_hash, current_model, response_dict)
            return response_dict

        except RateLimitError as e:
            last_error = e
            if attempt == 1:
                logger.warning(
                    "SMART_MODEL rate-limited twice. Routing to FAST_MODEL fallback..."
                )
                current_model = settings.FAST_MODEL
                await asyncio.sleep(1.0)
                continue

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


def _make_messages_hash(messages: list[dict[str, str]], model: str) -> str:
    """Stable hash for caching multi-turn chat completions."""
    payload = json.dumps(messages, ensure_ascii=False) + "\n---\n" + model
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def acall_smart_messages(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 800,
    temperature: float = 0.0,
    skip_cache: bool = False,
) -> dict[str, Any]:
    """
    Async JSON-mode chat with arbitrary message list (system + user/assistant turns).
    Same retry / rate-limit behaviour as acall_smart; cache keyed on full messages + model.
    """
    client = get_async_client()
    current_model = settings.SMART_MODEL
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            prompt_hash = _make_messages_hash(messages, current_model)
            
            if not skip_cache:
                cached = await _get_cached_json(prompt_hash)
                if cached is not None:
                    return cached


            logger.info("LLM Cache MISS - Calling API (messages mode)")

            kwargs_payload: dict[str, Any] = {
                "model": current_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            response = await _groq_chat_with_traffic_and_rl_backoff(
                client, max_retries=3, **kwargs_payload
            )
            text = (response.choices[0].message.content or "").strip()
            response_dict = json.loads(text)

            if getattr(response, "_is_rl_fallback", False):
                if current_model == settings.SMART_MODEL and attempt < 2:
                    logger.warning(
                        "Groq rate limit exhausted on %s (messages); retrying with FAST_MODEL",
                        current_model,
                    )
                    current_model = settings.FAST_MODEL
                    await asyncio.sleep(1.0)
                    continue
                return response_dict

            if not skip_cache:
                await _set_cached_json(prompt_hash, current_model, response_dict)
            return response_dict

        except RateLimitError as e:
            last_error = e
            if attempt == 1:
                logger.warning(
                    "SMART_MODEL rate-limited twice. Routing to FAST_MODEL fallback..."
                )
                current_model = settings.FAST_MODEL
                await asyncio.sleep(1.0)
                continue

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
                "acall_smart_messages failed on model %s attempt %d/3. Sleeping %.2fs. Error: %s",
                current_model,
                attempt + 1,
                wait,
                e,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(f"acall_smart_messages exhausted retries. Last error: {last_error}")


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

async def acall_smart_messages_stream(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 800,
    temperature: float = 0.0,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields raw text delta strings as the LLM produces them.
 
    The caller is responsible for accumulating the full reply.
    The model is still instructed to respond in JSON mode, so the deltas will
    spell out the JSON incrementally.  The frontend strips the wrapper.
 
    Usage:
        async for token in acall_smart_messages_stream(messages):
            yield token
    """
    client = get_async_client()
 
    try:
        stream = await client.chat.completions.create(
            model=settings.SMART_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            
            stream=True,
        )
 
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
 
    except Exception as e:
        logger.warning(
            "acall_smart_messages_stream failed (%s). "
            "The chat router will fall back to non-streaming.", e
        )
        raise NotImplementedError("Streaming not available, use fallback") from e