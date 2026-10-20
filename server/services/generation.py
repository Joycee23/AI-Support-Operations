"""Provider-neutral generation contracts and prompts."""
import json
from typing import Annotated, Literal, Protocol
from pydantic import BaseModel, Field, field_validator


class SuggestionPayload(BaseModel):
    topic: str = Field(min_length=1, max_length=100)
    priority: Literal["Khẩn cấp", "Cao", "Bình thường", "Thấp"]
    suggested_team_id: str | None = Field(max_length=100)
    reason: str = Field(max_length=2000)
    draft: str = Field(default="", max_length=8000)
    citations: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=10)
    grounded: bool = False
    handoff_reason: str | None = Field(default=None, max_length=2000)

    @field_validator('priority', mode='before')
    @classmethod
    def normalize_priority(cls, value):
        if isinstance(value, str):
            return {'urgent':'Khẩn cấp', 'critical':'Khẩn cấp', 'high':'Cao',
                    'normal':'Bình thường', 'medium':'Bình thường', 'low':'Thấp'}.get(value.strip().casefold(), value.strip())
        return value


class KnowledgeDraftPayload(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    category: str = Field(min_length=2, max_length=100)
    content: str = Field(min_length=20, max_length=30000)
    notes: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=10)


class GenerationProvider(Protocol):
    async def validate(self) -> None: ...
    async def generate_suggestion(self, prompt: str) -> SuggestionPayload: ...
    async def draft_knowledge(self, subject: str, answers: dict[str, str]) -> dict: ...


def knowledge_prompt(subject: str, answers: dict[str, str]) -> str:
    return (
        "Soạn bản nháp FAQ/chính sách tiếng Việt chỉ từ câu trả lời được cung cấp. "
        "Không thêm điều khoản hoặc cam kết chưa có căn cứ. Trả JSON gồm title, category, content, "
        "notes (mảng câu hỏi còn thiếu cần con người xác nhận). Nội dung chỉ là bản nháp chờ duyệt.\n"
        + json.dumps({"subject": subject, "answers": answers}, ensure_ascii=False)
    )
