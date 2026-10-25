"""知识沉淀：FAQ 推荐审核、已发布 FAQ 库、知识缺口。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FaqItem(BaseModel):
    id: int
    question: str
    answer: str
    category: str | None = None
    related_unit_id: int | None = None
    related_unit_title: str | None = None
    source_type: str
    status: str
    answer_edited: bool = False
    hit_count: int = 0
    review_note: str | None = None
    reviewer_id: int | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    cached: bool = False
    created_at: datetime
    updated_at: datetime


class FaqReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    edited_answer: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=500)


class FaqUpdateRequest(BaseModel):
    question: str | None = Field(default=None, min_length=2, max_length=500)
    answer: str | None = Field(default=None, min_length=2, max_length=5000)
    category: str | None = Field(default=None, max_length=64)


class FaqCreateRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    answer: str = Field(min_length=2, max_length=5000)
    category: str | None = Field(default=None, max_length=64)
    related_unit_id: int | None = None
    publish: bool = False


class MiningResult(BaseModel):
    faq: dict
    gap: dict
    ran_at: str


class GapItem(BaseModel):
    id: int
    question_pattern: str
    sample_questions: list[str] = []
    ask_count: int
    last_asked_at: datetime | None = None
    status: str
    resolved_unit_id: int | None = None
    created_at: datetime
    updated_at: datetime


class GapResolveRequest(BaseModel):
    """把缺口转成新知识单元（title/content 二选一必填 content）。"""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    category: str | None = None
