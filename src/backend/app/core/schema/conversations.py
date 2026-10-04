import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=100_000)
    blocked: bool = Field(
        default=False, description="Whether the control layer stopped it."
    )


class NewMessages(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessage] = Field(
        description="Oldest first. PII and secrets in them are masked."
    )
