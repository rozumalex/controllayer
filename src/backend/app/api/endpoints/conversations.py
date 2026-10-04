"""The chat history: the conversations of the user the request acts as, so
in the attack simulator, of the employee whose account was taken over.
Messages are stored scrubbed of PII and secrets."""

import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import ActingUser
from app.control.guards.sensitive_data import scrub
from app.core.schema.conversations import (
    ChatMessage,
    ConversationDetail,
    ConversationSummary,
    NewMessages,
)
from app.db.models import Conversation, User
from app.db.session import SessionLocal

router = APIRouter(prefix="/conversations", tags=["conversations"])

LISTED = 50
TITLE = 80


def stored(messages: list[ChatMessage]) -> list[dict]:
    return [m.model_copy(update={"text": scrub(m.text)}).model_dump() for m in messages]


def title(messages: list[dict]) -> str:
    asked = next((m["text"] for m in messages if m["role"] == "user"), "")
    text = " ".join(asked.split()) or "New conversation"
    return text if len(text) <= TITLE else text[: TITLE - 1] + "…"


async def owned(session, user: User, conversation_id: uuid.UUID) -> Conversation:
    found = await session.get(Conversation, conversation_id)
    if not found or found.user_id != user.id:
        raise HTTPException(404, "Unknown conversation")
    return found


@router.get(
    "",
    response_model=list[ConversationSummary],
    summary="List the user's conversations",
    description=f"The {LISTED} last changed first.",
)
async def conversations(user: ActingUser) -> list[Conversation]:
    async with SessionLocal() as session:
        found = await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(LISTED)
        )
        return list(found)


@router.post(
    "",
    response_model=ConversationSummary,
    status_code=201,
    summary="Start a conversation with its first messages",
)
async def start(request: NewMessages, user: ActingUser) -> Conversation:
    messages = stored(request.messages)
    conversation = Conversation(
        user_id=user.id, title=title(messages), messages=messages
    )
    async with SessionLocal() as session:
        session.add(conversation)
        await session.commit()
        await session.refresh(conversation)
    return conversation


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Show a conversation with its messages",
)
async def conversation(conversation_id: uuid.UUID, user: ActingUser) -> Conversation:
    async with SessionLocal() as session:
        return await owned(session, user, conversation_id)


@router.post(
    "/{conversation_id}/messages",
    status_code=204,
    summary="Add messages to a conversation",
)
async def add_messages(
    conversation_id: uuid.UUID, request: NewMessages, user: ActingUser
) -> Response:
    async with SessionLocal() as session:
        found = await owned(session, user, conversation_id)
        found.messages = [*found.messages, *stored(request.messages)]
        await session.commit()
    return Response(status_code=204)
