import asyncio
from collections.abc import Sequence
from .model_pool import GenerationModelPool
from google.genai.errors import APIError
import json
from .generation import SuggestionPayload, KnowledgeDraftPayload, knowledge_prompt
from google import genai
from google.genai import types

class GeminiService:
    def __init__(self, api_key: str, model: str, fallback_models: Sequence[str] = ()):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.pool = GenerationModelPool(model, fallback_models)

    async def validate(self):
        for index, model in enumerate(self.pool.models):
            try:
                await asyncio.wait_for(self.client.aio.models.get(model=model), timeout=15)
                return
            except (APIError, TimeoutError) as exc:
                if getattr(exc, "code", None) == 401 or index == len(self.pool.models) - 1:
                    raise

    async def generate_suggestion(self, prompt: str) -> SuggestionPayload:
        response = await self.pool.call(lambda model: self.client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SuggestionPayload,
                temperature=0.1,
                max_output_tokens=4096,
            ),
        ))
        if not response.text:
            raise RuntimeError("Gemini trả về kết quả trống.")
        return SuggestionPayload.model_validate(json.loads(response.text))

    async def draft_knowledge(self, subject: str, answers: dict[str, str]) -> dict:
        prompt = knowledge_prompt(subject, answers)
        response = await self.pool.call(lambda model: self.client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=KnowledgeDraftPayload, temperature=0.1, max_output_tokens=4096),
        ))
        return KnowledgeDraftPayload.model_validate_json(response.text or "{}").model_dump()
