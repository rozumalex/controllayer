from datetime import datetime
from typing import Any, Literal
from uuid import UUID

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


class TraceUser(BaseModel):
    id: UUID
    name: str


class TraceSummary(BaseModel):
    trace_id: str
    started_at: datetime
    agent_id: str | None
    user: TraceUser | None = Field(
        description="The signed-in user the request came from, if any."
    )
    prompt: str | None = Field(
        description=(
            "The user's message, or the tool an MCP call went to. The message "
            "and the call's arguments are empty unless CONTROL_LOG_PAYLOADS is on."
        )
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


Range = Literal["1h", "24h", "7d"]


class Bucket(BaseModel):
    """The traces that started in one time bucket."""

    start: datetime
    allowed: int = 0
    flagged: int = 0
    blocked: int = 0
    error: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    p50_ms: float | None = Field(None, description="Median request duration.")
    p95_ms: float | None = Field(None, description="95th percentile duration.")


class FindingCount(BaseModel):
    guard: str
    reason: str
    count: int


class Analytics(BaseModel):
    range: Range
    bucket_seconds: int
    timeline: list[Bucket] = Field(description="Every bucket, oldest first.")
    findings: list[FindingCount] = Field(description="The most common first.")
