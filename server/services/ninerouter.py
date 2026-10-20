"""9router Responses API adapter. Credentials and payloads stay on the backend."""
from collections.abc import Sequence
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .generation import KnowledgeDraftPayload, SuggestionPayload, knowledge_prompt
from .model_pool import GenerationModelPool, GenerationProviderError

Payload = TypeVar("Payload", bound=BaseModel)


class NineRouterService:
    def __init__(self, api_key: str, base_url: str, model: str, fallback_models: Sequence[str] = ()):
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip('/') + '/',
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(25, connect=5),
            follow_redirects=False,
        )
        self.pool = GenerationModelPool(model, fallback_models)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise TimeoutError("9router không phản hồi trong thời gian cho phép.") from None
        except httpx.RequestError:
            raise GenerationProviderError(503) from None
        if not response.is_success:
            # Do not propagate remote bodies: they may contain prompts or credentials.
            raise GenerationProviderError(response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise GenerationProviderError(502) from None
        if not isinstance(data, dict):
            raise GenerationProviderError(502)
        return data

    async def validate(self) -> None:
        # Check router authentication without generating billable customer content.
        await self._request("GET", "models")

    async def _generate(self, prompt: str, schema: type[Payload]) -> Payload:
        async def operation(model: str) -> Payload:
            data = await self._request("POST", "responses", json={
                "model": model,
                "input": prompt,
                "stream": False,
                "store": False,
                "max_output_tokens": 4096,
                "text": {"format": {
                    "type": "json_schema", "name": schema.__name__,
                    "schema": schema.model_json_schema(), "strict": False,
                }},
            })
            if data.get("error") or data.get("status") in ("failed", "incomplete", "cancelled"):
                raise GenerationProviderError(502)
            try:
                parts = [
                    part["text"] for output in data.get("output", [])
                    if output.get("type") == "message"
                    for part in output.get("content", [])
                    if part.get("type") == "output_text"
                ]
                return schema.model_validate_json("".join(parts))
            except (ValidationError, TypeError, KeyError, AttributeError):
                raise GenerationProviderError(502) from None
        return await self.pool.call(operation)

    async def generate_suggestion(self, prompt: str) -> SuggestionPayload:
        return await self._generate(prompt, SuggestionPayload)

    async def draft_knowledge(self, subject: str, answers: dict[str, str]) -> dict:
        draft = await self._generate(knowledge_prompt(subject, answers), KnowledgeDraftPayload)
        return draft.model_dump()

    async def aclose(self) -> None:
        await self.client.aclose()
