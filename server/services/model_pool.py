"""Generation failover with a bounded request budget and per-model cooldowns."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from typing import TypeVar

from google.genai.errors import APIError

T = TypeVar("T")
logger = logging.getLogger(__name__)
FAILOVER_CODES = {403, 404, 429, 500, 502, 503, 504}
attempt_budget: ContextVar[list[int] | None] = ContextVar('generation_attempt_budget', default=None)


class GenerationProviderError(RuntimeError):
    def __init__(self, code: int):
        self.code = code
        super().__init__(f"AI provider failed (status={code})")


class ModelsUnavailable(RuntimeError):
    code = 503


class GenerationModelPool:
    def __init__(self, primary: str, fallbacks: Sequence[str] = ()):
        self.models = tuple(dict.fromkeys(
            model.strip() for model in (primary, *fallbacks) if model.strip()
        ))
        if not self.models:
            raise ValueError("Cần cấu hình ít nhất một model sinh nội dung.")
        self._cooldowns: dict[str, float] = {}

    async def call(self, operation: Callable[[str], Awaitable[T]]) -> T:
        deadline = time.monotonic() + 90
        last_error: Exception | None = None
        for model in self.models:
            if self._cooldowns.get(model, 0) > time.monotonic():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            budget = attempt_budget.get()
            if budget is not None:
                if budget[0] <= 0:
                    break
                budget[0] -= 1
            try:
                result = await asyncio.wait_for(operation(model), timeout=min(25, remaining))
            except (APIError, GenerationProviderError, TimeoutError) as exc:
                status = getattr(exc, "code", None)
                if not isinstance(exc, TimeoutError) and status not in FAILOVER_CODES:
                    raise
                last_error = exc
                cooldown = 300 if status in (403, 404) else 120 if status == 429 else 60
                self._cooldowns[model] = time.monotonic() + cooldown
                logger.warning(
                    "AI model unavailable model=%s status=%s; trying next configured model",
                    model, status or "timeout",
                )
            else:
                self._cooldowns.pop(model, None)
                logger.info("AI generation succeeded model=%s", model)
                return result
        raise ModelsUnavailable(
            "Các model sinh nội dung đang quá tải hoặc tạm hết hạn mức."
        ) from last_error
