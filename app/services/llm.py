"""Hugging Face Inference API client with failover and retries.

Two production concerns drive the shape of this module:

1. **Model churn.** Hosted model ids get retired. v1 hardcoded one id, and when
   ``Meta-Llama-3-8B-Instruct`` left the Inference Providers catalogue every
   request started failing with ``model_not_supported``. A ranked list plus
   sticky failover means that outage degrades to a slower model instead.
2. **Transient upstream errors.** Rate limits and 5xx are normal at this layer,
   so they are retried with exponential backoff rather than surfaced.

Uses ``AsyncInferenceClient``; v1 called the sync client inside ``async def``,
which blocked the event loop for the whole generation.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator

from huggingface_hub import AsyncInferenceClient

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when every candidate model failed."""


def _is_permanent(exc: Exception) -> bool:
    """True when retrying the same model cannot possibly help.

    A retired, gated, or misspelled model id is permanent for this process;
    a timeout or a 503 is not.
    """
    text = str(exc).lower()
    markers = (
        "model_not_supported",
        "not supported by any provider",
        "not found",
        "does not exist",
        "gated",
        "authorization",
        "unauthorized",
        "403",
        "404",
    )
    return any(marker in text for marker in markers)


class LLMClient:
    def __init__(self, settings) -> None:
        self._settings = settings
        self._models: list[str] = [settings.model_id, *settings.fallback_models]
        self._clients: dict[str, AsyncInferenceClient] = {}
        # Index of the model currently believed good. Once we fail over we stay
        # there, so every later request skips the known-dead model.
        self._active = 0

    @property
    def active_model(self) -> str:
        return self._models[self._active]

    def _client(self, model: str) -> AsyncInferenceClient:
        if model not in self._clients:
            self._clients[model] = AsyncInferenceClient(
                model=model,
                token=self._settings.hf_token,
                timeout=self._settings.request_timeout,
            )
        return self._clients[model]

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield response text incrementally, failing over between models.

        Failover only happens before the first token reaches the caller. Once
        output has been emitted a mid-stream error is surfaced, because
        restarting on another model would duplicate half a sentence.
        """
        last_error: Exception | None = None

        for offset in range(len(self._models)):
            index = (self._active + offset) % len(self._models)
            model = self._models[index]

            try:
                emitted = False
                started = time.perf_counter()
                first_token_at: float | None = None
                chars = 0

                async for delta in self._attempt(model, messages):
                    if not emitted:
                        emitted = True
                        first_token_at = time.perf_counter() - started
                        if index != self._active:
                            logger.warning(
                                "Failing over to %s (previous: %s)",
                                model,
                                self._models[self._active],
                            )
                            self._active = index
                    chars += len(delta)
                    yield delta

                logger.info(
                    "generation ok model=%s ttft=%.2fs total=%.2fs chars=%d",
                    model,
                    first_token_at or 0.0,
                    time.perf_counter() - started,
                    chars,
                )
                return

            except _StreamAlreadyStarted as exc:
                logger.error("Stream failed after output began on %s", model)
                raise LLMError(str(exc.__cause__ or exc)) from exc.__cause__
            except Exception as exc:
                last_error = exc
                logger.warning("Model %s unavailable: %s", model, exc)

        logger.error("All %d models failed", len(self._models))
        raise LLMError(str(last_error) if last_error else "No model available")

    async def _attempt(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """One model, with retries for transient failures.

        Tracks emission locally: once a token has left this generator, neither
        a retry nor a failover can happen without duplicating output, so the
        error is escalated instead.
        """
        attempts = self._settings.max_retries + 1
        emitted = False

        for attempt in range(attempts):
            try:
                stream = await self._client(model).chat_completion(
                    messages=messages,
                    max_tokens=self._settings.max_tokens,
                    temperature=self._settings.temperature,
                    stream=True,
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    # The terminating chunk carries a null delta; v1 crashed on it.
                    delta = chunk.choices[0].delta.content
                    if delta:
                        emitted = True
                        yield delta
                return

            except Exception as exc:
                if emitted:
                    raise _StreamAlreadyStarted from exc
                if _is_permanent(exc) or attempt == attempts - 1:
                    raise
                # Exponential backoff with jitter, so retries from concurrent
                # requests do not stampede the upstream in lockstep.
                delay = self._settings.retry_backoff * (2**attempt)
                delay += random.uniform(0, delay / 2)  # noqa: S311 - not crypto
                logger.info(
                    "Retrying %s in %.2fs (attempt %d/%d): %s",
                    model,
                    delay,
                    attempt + 1,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return "".join([chunk async for chunk in self.stream(messages)])

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.close()


class _StreamAlreadyStarted(Exception):
    """Internal marker: the stream broke after tokens had been delivered."""
