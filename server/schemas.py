from typing import Literal
from pydantic import BaseModel, Field, field_validator

class TicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    topic: str | None = Field(default=None, max_length=100)
    team_id: str | None = None
    assignee_id: str | None = None
    note: str | None = Field(default=None, max_length=4000)
    reply: str | None = Field(default=None, max_length=8000)

    @field_validator('note', 'reply', 'topic', mode='before')
    @classmethod
    def strip_ticket_text(cls, value):
        return value.strip() if isinstance(value, str) else value

class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    category: str = Field(min_length=2, max_length=100)
    content: str = Field(min_length=20, max_length=30000)
    team_id: str | None = None

    @field_validator('title', 'category', 'content', mode='before')
    @classmethod
    def strip_knowledge_text(cls, value):
        return value.strip() if isinstance(value, str) else value

class KnowledgeUpdate(KnowledgeCreate):
    change_note: str = Field(default="Cập nhật nội dung", max_length=300)

class FeedbackCreate(BaseModel):
    save_reply: bool = False
    decision: str
    edited_draft: str | None = Field(default=None, max_length=8000)

class DraftFAQRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=240)
    answers: dict[str, str]

    @field_validator('answers')
    @classmethod
    def bound_answers(cls, value):
        if len(value) > 20 or any(len(k) > 200 or len(v) > 4000 for k, v in value.items()) or sum(len(k) + len(v) for k, v in value.items()) > 16000:
            raise ValueError('Tối đa 20 câu trả lời, 4000 ký tự mỗi câu và 16000 ký tự tổng cộng.')
        return value

class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    color: Literal["blue", "amber", "green", "red"] = "blue"

class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: str
    team_id: str

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)


class TicketCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: str = Field(min_length=5, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=3, max_length=8000)
    team_id: str
    channel: Literal['Email', 'Chat', 'Điện thoại', 'Khác'] = 'Email'
