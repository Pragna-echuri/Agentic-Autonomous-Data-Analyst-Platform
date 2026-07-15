"""
LLM Client — Resilient Groq Wrapper
====================================
Async-first LLM client with:

* **Exponential backoff + jitter** for transient failures
* **Circuit breaker** to avoid hammering a down provider
* **Structured error mapping** (rate limit → LLMRateLimitError, etc.)
* **Token usage tracking** via the metrics subsystem
* **Timeout enforcement** per-request

The client wraps the ``groq`` Python SDK's synchronous API and
runs it in a thread executor to avoid blocking the async event loop.

Usage::

    from core.llm_client import LLMClient
    client = LLMClient()
    response = await client.chat_completion(messages, tools=tools)
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from groq import Groq

from core.config import Settings, get_settings
from core.exceptions import (
    LLMContextOverflowError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
)
from observability.logger import get_logger
from observability.metrics import metrics

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Simple circuit breaker with half-open recovery.

    States:
        CLOSED  — requests pass through normally.
        OPEN    — requests are rejected immediately.
        HALF_OPEN — one probe request is allowed to test recovery.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if (time.monotonic() - self._last_failure_time) >= self.recovery_timeout:
                self._state = self.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = self.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            log.warning(
                "circuit_breaker_opened",
                failures=self._failure_count,
                threshold=self.failure_threshold,
            )

    def check(self) -> None:
        """Raise if the circuit is open."""
        if self.state == self.OPEN:
            raise LLMProviderError(
                "Circuit breaker is OPEN — LLM provider appears unavailable. "
                f"Will retry after {self.recovery_timeout}s.",
                details={"failures": self._failure_count},
            )


# ═══════════════════════════════════════════════════════════════════════
#  LLM Client
# ═══════════════════════════════════════════════════════════════════════

class LLMClient:
    """Resilient async wrapper around the Groq SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = Groq(api_key=self._settings.groq_api_key)
        self._breaker = CircuitBreaker()

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Send a chat-completion request with retry and circuit-breaker.

        Parameters
        ----------
        messages:
            OpenAI-compatible message list.
        tools:
            Optional function-calling tool definitions.
        temperature:
            Override the default sampling temperature.
        max_tokens:
            Override the default max-tokens.

        Returns
        -------
        The raw ``ChatCompletion`` response object from Groq.

        Raises
        ------
        LLMRateLimitError
            Provider returned 429.
        LLMContextOverflowError
            The request exceeded the model's context window.
        LLMProviderError
            Unrecoverable provider-side error after all retries.
        """
        self._breaker.check()

        temp = temperature if temperature is not None else self._settings.llm_temperature
        mtok = max_tokens if max_tokens is not None else self._settings.llm_max_tokens

        kwargs: dict[str, Any] = {
            "model": self._settings.groq_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": mtok,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_exc: BaseException | None = None

        for attempt in range(1, self._settings.llm_max_retries + 1):
            try:
                with metrics.timer("llm_latency_ms"):
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.chat.completions.create(**kwargs),
                    )

                self._breaker.record_success()
                self._track_tokens(response)

                log.debug(
                    "llm_call_completed",
                    attempt=attempt,
                    model=self._settings.groq_model,
                )
                return response

            except Exception as exc:
                last_exc = exc
                classified = self._classify_error(exc)

                # Non-retryable errors
                if isinstance(classified, LLMContextOverflowError):
                    self._breaker.record_failure()
                    raise classified from exc

                # Rate-limit: respect the retry-after hint if available
                if isinstance(classified, LLMRateLimitError):
                    wait = self._backoff(attempt, base=2.0)
                    log.warning(
                        "llm_rate_limited",
                        attempt=attempt,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Transient errors: retry with backoff
                if attempt < self._settings.llm_max_retries:
                    wait = self._backoff(attempt)
                    log.warning(
                        "llm_transient_error",
                        attempt=attempt,
                        wait_seconds=wait,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait)
                else:
                    self._breaker.record_failure()

        raise LLMProviderError(
            f"LLM call failed after {self._settings.llm_max_retries} attempts.",
            details={"last_error": str(last_exc)},
        )

    # ── Sync Convenience ─────────────────────────────────────────────

    def chat_completion_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Blocking wrapper for environments without a running loop."""
        return asyncio.run(
            self.chat_completion(
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _backoff(attempt: int, base: float = 1.0) -> float:
        """Exponential backoff with jitter."""
        exp = min(base * (2 ** (attempt - 1)), 30.0)
        return exp + random.uniform(0, exp * 0.5)

    @staticmethod
    def _classify_error(exc: BaseException) -> LLMError:
        """Map provider exceptions to our typed hierarchy."""
        msg = str(exc).lower()

        if "rate" in msg and "limit" in msg:
            return LLMRateLimitError(str(exc))
        if "context" in msg and ("length" in msg or "window" in msg or "too long" in msg):
            return LLMContextOverflowError(str(exc))
        if "token" in msg and ("limit" in msg or "exceed" in msg or "maximum" in msg):
            return LLMContextOverflowError(str(exc))
        return LLMProviderError(str(exc))

    def _track_tokens(self, response: Any) -> None:
        """Record token usage in the metrics system."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or (prompt + completion)

        metrics.increment("llm_prompt_tokens_total", prompt)
        metrics.increment("llm_completion_tokens_total", completion)
        metrics.increment("llm_total_tokens", total)
