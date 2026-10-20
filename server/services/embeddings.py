from .provider import call_provider
from typing import Protocol
from google import genai
from google.genai import types

VECTOR_DIMENSIONS = 768

class EmbeddingProvider(Protocol):
    async def validate(self) -> None: ...
    async def embed_document(self, text: str) -> list[float]: ...
    async def embed_query(self, text: str) -> list[float]: ...

class GeminiEmbeddingProvider:
    """Embedding adapter kept separate from Gemini text generation."""
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def validate(self):
        await self.embed_query("Kiểm tra cấu hình model embedding")

    async def _embed(self, text: str, task_type: str) -> list[float]:
        result = await call_provider(lambda: self.client.aio.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=VECTOR_DIMENSIONS, task_type=task_type),
        ))
        values = result.embeddings[0].values if result.embeddings else None
        if not values or len(values) != VECTOR_DIMENSIONS:
            raise RuntimeError("Gemini không trả về embedding đúng số chiều.")
        return list(values)

    async def embed_document(self, text: str) -> list[float]:
        return await self._embed(text, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed(text, "RETRIEVAL_QUERY")
