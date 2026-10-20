"""Select a generation provider and optionally fall back from 9router to Gemini."""
import asyncio
import logging

from ..config import Settings
from .gemini import GeminiService
from .generation import GenerationProvider
from .model_pool import GenerationProviderError, ModelsUnavailable
from .ninerouter import NineRouterService

logger = logging.getLogger(__name__)


class FallbackGenerationService:
    def __init__(self, primary: NineRouterService, fallback: GenerationProvider | None):
        self.primary = primary
        self.fallback = fallback
        self._available_at = 0.0

    async def _call(self, method: str, *args):
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(90):
                if loop.time() >= self._available_at:
                    try:
                        return await getattr(self.primary, method)(*args)
                    except (GenerationProviderError, ModelsUnavailable, TimeoutError) as exc:
                        self._available_at = loop.time() + 60
                        logger.warning("9router unavailable status=%s; using configured fallback", getattr(exc, 'code', 'timeout'))
                        if self.fallback is None:
                            raise
                elif self.fallback is None:
                    raise ModelsUnavailable("9router đang tạm ngừng phục vụ. Vui lòng thử lại sau.")
                return await getattr(self.fallback, method)(*args)
        except TimeoutError:
            raise ModelsUnavailable("Đã hết thời gian chờ các model AI.") from None

    async def validate(self):
        await self._call("validate")

    async def generate_suggestion(self, prompt):
        return await self._call("generate_suggestion", prompt)

    async def draft_knowledge(self, subject, answers):
        return await self._call("draft_knowledge", subject, answers)

    async def aclose(self):
        await self.primary.aclose()


def create_generation_service(settings: Settings) -> GenerationProvider:
    gemini = GeminiService(settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_models)
    if settings.ai_provider == "gemini":
        return gemini
    router = NineRouterService(settings.ninerouter_api_key, settings.ninerouter_base_url,
                               settings.ninerouter_model, settings.ninerouter_fallback_models)
    return FallbackGenerationService(router, gemini if settings.ninerouter_gemini_fallback else None)
