import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.control.adapters.openai_chat import text_of
from app.core.schema.traces import (
    Analytics,
    Bucket,
    Finding,
    FindingCount,
    Outcome,
    Range,
    Stats,
    TraceDetail,
    TraceEvent,
    TraceList,
    TraceSummary,
    Usage,
)
from app.db.models import ControlEvent
from app.db.session import get_session

router = APIRouter(prefix="/traces", tags=["traces"])

Session = Annotated[AsyncSession, Depends(get_session)]

# The window of each range, and the size of its buckets.
RANGES: dict[str, tuple[timedelta, timedelta]] = {
    "1h": (timedelta(hours=1), timedelta(minutes=1)),
    "24h": (timedelta(hours=24), timedelta(hours=1)),
    "7d": (timedelta(days=7), timedelta(hours=6)),
}
TOP_FINDINGS = 8


def outcome(events: Sequence[ControlEvent]) -> Outcome:
    kinds = {(e.event, e.action) for e in events}
    if ("decision", "block") in kinds:
        return "blocked"
    if any(event == "upstream_error" for event, _ in kinds):
        return "error"
    if ("verdict", "block") in kinds:
        return "flagged"
    return "allowed"


def prompt(request: ControlEvent | None) -> str | None:
    messages = request.data.get("messages") if request else None
    users = [m for m in messages or [] if m.get("role") == "user"]
    return text_of(users[-1].get("content")) if users else None


def usage(events: Sequence[ControlEvent]) -> Usage:
    total = Usage()
    for event in events:
        if event.event == "upstream_response" and event.data.get("usage"):
            used = Usage.model_validate(event.data["usage"], extra="ignore")
            total.prompt_tokens += used.prompt_tokens
            total.completion_tokens += used.completion_tokens
            total.total_tokens += used.total_tokens
    return total


def summary(events: Sequence[ControlEvent]) -> TraceSummary:
    request = next((e for e in events if e.event == "request"), None)
    started, ended = events[0].created_at, events[-1].created_at
    return TraceSummary(
        trace_id=events[0].trace_id,
        started_at=started,
        agent_id=request.data.get("agent_id") if request else None,
        prompt=prompt(request),
        outcome=outcome(events),
        findings=[
            Finding.model_validate(e.data, extra="ignore")
            for e in events
            if e.event == "verdict" and e.action != "allow"
        ],
        usage=usage(events),
        duration_ms=round((ended - started).total_seconds() * 1000, 3),
    )


async def stats(session: AsyncSession) -> Stats:
    def traces(*where: Any) -> Any:
        query = select(func.count(func.distinct(ControlEvent.trace_id)))
        return query.where(*where).scalar_subquery()

    blocked_ids = select(ControlEvent.trace_id).where(
        ControlEvent.event == "decision", ControlEvent.action == "block"
    )

    def tokens(name: str) -> Any:
        value = ControlEvent.data["usage"][name].astext.cast(Integer)
        query = select(func.coalesce(func.sum(value), 0))
        return query.where(ControlEvent.event == "upstream_response").scalar_subquery()

    row = (
        await session.execute(
            select(
                traces(ControlEvent.event == "request"),
                traces(ControlEvent.trace_id.in_(blocked_ids)),
                traces(
                    ControlEvent.event == "verdict",
                    ControlEvent.action == "block",
                    ControlEvent.trace_id.not_in(blocked_ids),
                ),
                traces(ControlEvent.event == "upstream_error"),
                tokens("prompt_tokens"),
                tokens("completion_tokens"),
                tokens("total_tokens"),
            )
        )
    ).one()
    return Stats(
        requests=row[0],
        blocked=row[1],
        flagged=row[2],
        errors=row[3],
        usage=Usage(
            prompt_tokens=row[4], completion_tokens=row[5], total_tokens=row[6]
        ),
    )


@router.get(
    "",
    response_model=TraceList,
    summary="List the newest traces of the control layer",
)
async def list_traces(
    session: Session, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> TraceList:
    started = func.min(ControlEvent.created_at).label("started")
    newest = (
        select(ControlEvent.trace_id, started)
        .group_by(ControlEvent.trace_id)
        .order_by(started.desc())
        .limit(limit)
    )
    trace_ids = [row.trace_id for row in await session.execute(newest)]
    rows = await session.scalars(
        select(ControlEvent)
        .where(ControlEvent.trace_id.in_(trace_ids))
        .order_by(ControlEvent.id)
    )
    events: dict[str, list[ControlEvent]] = defaultdict(list)
    for row in rows:
        events[row.trace_id].append(row)
    return TraceList(
        stats=await stats(session),
        traces=[summary(events[trace_id]) for trace_id in trace_ids],
    )


def percentile(values: list[float], fraction: float) -> float | None:
    """The nearest-rank percentile, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


async def events_since(
    session: AsyncSession, start: datetime
) -> dict[str, list[ControlEvent]]:
    """The events of every trace that started at or after start."""
    started = select(ControlEvent.trace_id).where(
        ControlEvent.event == "request", ControlEvent.created_at >= start
    )
    rows = await session.scalars(
        select(ControlEvent)
        .where(ControlEvent.trace_id.in_(started))
        .order_by(ControlEvent.id)
    )
    events: dict[str, list[ControlEvent]] = defaultdict(list)
    for row in rows:
        events[row.trace_id].append(row)
    return events


@router.get(
    "/analytics",
    response_model=Analytics,
    summary="Count the traces of a time range, bucket by bucket",
    description=(
        "Outcomes, tokens and request durations per bucket, and the most "
        "common findings. 1h has one-minute buckets, 24h one-hour buckets and "
        "7d six-hour buckets."
    ),
)
async def analytics(
    session: Session, period: Annotated[Range, Query(alias="range")] = "1h"
) -> Analytics:
    window, step = RANGES[period]
    # Buckets end on whole steps, so a refresh doesn't shift them.
    seconds = step.total_seconds()
    now = datetime.now(UTC).timestamp()
    end = datetime.fromtimestamp((now // seconds + 1) * seconds, UTC)
    start = end - window

    buckets = [Bucket(start=start + i * step) for i in range(window // step)]
    durations: list[list[float]] = [[] for _ in buckets]
    findings: Counter[tuple[str, str]] = Counter()
    for events in (await events_since(session, start)).values():
        trace = summary(events)
        index = int((trace.started_at - start) / step)
        if not 0 <= index < len(buckets):
            continue
        bucket = buckets[index]
        setattr(bucket, trace.outcome, getattr(bucket, trace.outcome) + 1)
        bucket.prompt_tokens += trace.usage.prompt_tokens
        bucket.completion_tokens += trace.usage.completion_tokens
        durations[index].append(trace.duration_ms)
        findings.update((f.guard, f.reason) for f in trace.findings)
    for bucket, values in zip(buckets, durations, strict=True):
        bucket.p50_ms = percentile(values, 0.5)
        bucket.p95_ms = percentile(values, 0.95)

    return Analytics(
        range=period,
        bucket_seconds=int(seconds),
        timeline=buckets,
        findings=[
            FindingCount(guard=guard, reason=reason, count=count)
            for (guard, reason), count in findings.most_common(TOP_FINDINGS)
        ],
    )


@router.get(
    "/{trace_id}",
    response_model=TraceDetail,
    summary="Get every event of one trace",
    responses={404: {"description": "No trace has this id."}},
)
async def get_trace(trace_id: str, session: Session) -> TraceDetail:
    rows = list(
        await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.trace_id == trace_id)
            .order_by(ControlEvent.id)
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return TraceDetail(
        summary=summary(rows),
        events=[TraceEvent.model_validate(row, from_attributes=True) for row in rows],
    )
