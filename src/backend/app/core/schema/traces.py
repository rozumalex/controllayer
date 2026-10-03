from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Outcome = Literal["allowed", "flagged", "blocked", "error"]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Finding(BaseModel):
    """A guard's verdict other than allow."""

    guard: str
    action: str
    reason: str
    score: float | None
    direction: str
    tool: str


class TraceSummary(BaseModel):
    trace_id: str
    started_at: datetime
    agent_id: str | None
    prompt: str | None = Field(
        description="The user's message; empty unless CONTROL_LOG_PAYLOADS is on."
    )
    outcome: Outcome = Field(
        description=(
            "blocked: the layer stopped something. error: the model failed. "
            "flagged: a guard said block, but monitor mode let it through."
        )
    )
    findings: list[Finding]
    usage: Usage = Field(description="The model's tokens; zero if it wasn't called.")
    duration_ms: float


class Stats(BaseModel):
    requests: int
    blocked: int
    flagged: int
    errors: int
    usage: Usage


class TraceList(BaseModel):
    stats: Stats = Field(description="Over every trace, not only the listed ones.")
    traces: list[TraceSummary] = Field(description="The newest first.")


class TraceEvent(BaseModel):
    id: int
    event: str
    action: str | None
    created_at: datetime
    data: dict[str, Any]


class TraceDetail(BaseModel):
    summary: TraceSummary
    events: list[TraceEvent] = Field(description="In the order they happened.")
