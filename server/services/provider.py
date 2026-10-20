"""Bounded retries for embedding calls; the embedding model stays consistent."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
from google.genai.errors import APIError

T = TypeVar("T")
logger = logging.getLogger(__name__)

async def call_provider(operation: Callable[[], Awaitable[T]]) -> T:
    for attempt in range(3):
        try:
            return await asyncio.wait_for(operation(), timeout=40)
        except (APIError, TimeoutError) as exc:
            status = getattr(exc, "code", None)
            transient = isinstance(exc, TimeoutError) or status in (500, 502, 503, 504)
            if not transient or attempt == 2:
                raise
            logger.warning("Gemini transient failure status=%s attempt=%s", status or "timeout", attempt + 1)
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("Provider retry exhausted")
