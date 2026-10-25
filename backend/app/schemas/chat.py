"""AI 问答：会话与消息。"""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: int | None = None


class SessionItem(BaseModel):
    id: int
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    status: str = "done"
    citations: list[dict] = []
    missing_unit_ids: list[int] = []
    faq_id: int | None = None
    created_at: datetime
