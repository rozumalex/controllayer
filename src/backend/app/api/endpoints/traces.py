import csv
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgId
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
    TraceExport,
    TraceList,
    TraceSummary,
    TraceUser,
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
    if request and request.data.get("tool"):
        # A tool call through the MCP gateway: the tool, and the arguments
        # when they were stored.
        call = f"{request.data.get('server')}__{request.data['tool']}"
        arguments = request.data.get("arguments")
        return f"{call} {json.dumps(arguments)}" if arguments is not None else call
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


def user(events: Sequence[ControlEvent]) -> TraceUser | None:
    found = next((e.user for e in events if e.user), None)
    return TraceUser(id=found.id, name=found.name) if found else None


def summary(events: Sequence[ControlEvent]) -> TraceSummary:
    request = next((e for e in events if e.event == "request"), None)
    started, ended = events[0].created_at, events[-1].created_at
    return TraceSummary(
        trace_id=events[0].trace_id,
        started_at=started,
        agent_id=request.data.get("agent_id") if request else None,
        user=user(events),
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


async def stats(session: AsyncSession, org_id: UUID) -> Stats:
    mine = ControlEvent.org_id == org_id

    def traces(*where: Any) -> Any:
        query = select(func.count(func.distinct(ControlEvent.trace_id)))
        return query.where(mine, *where).scalar_subquery()

    blocked_ids = select(ControlEvent.trace_id).where(
        mine, ControlEvent.event == "decision", ControlEvent.action == "block"
    )

    def tokens(name: str) -> Any:
        value = ControlEvent.data["usage"][name].astext.cast(Integer)
        query = select(func.coalesce(func.sum(value), 0))
        query = query.where(mine, ControlEvent.event == "upstream_response")
        return query.scalar_subquery()

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
    session: Session,
    org_id: OrgId,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> TraceList:
    started = func.min(ControlEvent.created_at).label("started")
    newest = (
        select(ControlEvent.trace_id, started)
        .where(ControlEvent.org_id == org_id)
        .group_by(ControlEvent.trace_id)
        .order_by(started.desc())
        .limit(limit)
    )
    trace_ids = [row.trace_id for row in await session.execute(newest)]
    rows = await session.scalars(
        select(ControlEvent)
        .where(ControlEvent.org_id == org_id, ControlEvent.trace_id.in_(trace_ids))
        .order_by(ControlEvent.id)
    )
    events: dict[str, list[ControlEvent]] = defaultdict(list)
    for row in rows:
        events[row.trace_id].append(row)
    return TraceList(
        stats=await stats(session, org_id),
        traces=[summary(events[trace_id]) for trace_id in trace_ids],
    )


def percentile(values: list[float], fraction: float) -> float | None:
    """The nearest-rank percentile, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


async def events_since(
    session: AsyncSession,
    org_id: UUID,
    start: datetime | None,
    end: datetime | None = None,
) -> dict[str, list[ControlEvent]]:
    """The events of every trace of the organization that started at or after
    start, and before end. No start or no end leaves that side open."""
    mine = ControlEvent.org_id == org_id
    started = select(ControlEvent.trace_id).where(mine, ControlEvent.event == "request")
    if start:
        started = started.where(ControlEvent.created_at >= start)
    if end:
        started = started.where(ControlEvent.created_at < end)
    rows = await session.scalars(
        select(ControlEvent)
        .where(mine, ControlEvent.trace_id.in_(started))
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
    session: Session,
    org_id: OrgId,
    period: Annotated[Range, Query(alias="range")] = "1h",
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
    for events in (await events_since(session, org_id, start)).values():
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


EXPORT_LIMIT = 10_000
CSV_COLUMNS = [
    "trace_id",
    "started_at",
    "user_id",
    "user_name",
    "agent_id",
    "outcome",
    "findings",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "duration_ms",
    "prompt",
]


def cell(value: object) -> object:
    """A CSV cell that a spreadsheet won't run as a formula."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def csv_of(traces: list[TraceSummary]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for trace in traces:
        row = [
            trace.trace_id,
            trace.started_at.isoformat(),
            trace.user.id if trace.user else "",
            trace.user.name if trace.user else "",
            trace.agent_id or "",
            trace.outcome,
            "; ".join(f"{f.guard}:{f.action}:{f.reason}" for f in trace.findings),
            trace.usage.prompt_tokens,
            trace.usage.completion_tokens,
            trace.usage.total_tokens,
            trace.duration_ms,
            trace.prompt or "",
        ]
        writer.writerow([cell(value) for value in row])
    return out.getvalue()


@router.get(
    "/export",
    summary="Download the audit log as CSV or JSON",
    description=(
        "One row per trace, the newest first, filtered by when it started, its "
        f"outcome, its user and the guards that found something. At most "
        f"{EXPORT_LIMIT} traces. The prompt column is empty unless "
        "CONTROL_LOG_PAYLOADS is on."
    ),
    responses={
        200: {
            "content": {"text/csv": {}, "application/json": {}},
            "description": "The traces, as a file to save.",
        }
    },
)
async def export_traces(
    session: Session,
    org_id: OrgId,
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
    start: Annotated[
        datetime | None, Query(description="Traces that started at or after it.")
    ] = None,
    end: Annotated[
        datetime | None, Query(description="Traces that started before it.")
    ] = None,
    outcomes: Annotated[list[Outcome] | None, Query(alias="outcome")] = None,
    user_id: UUID | None = None,
    guards: Annotated[
        list[str] | None,
        Query(alias="guard", description="Traces with a finding of one of them."),
    ] = None,
) -> Response:
    traces = [
        summary(events)
        for events in (await events_since(session, org_id, start, end)).values()
    ]
    traces = [
        trace
        for trace in traces
        if (not outcomes or trace.outcome in outcomes)
        and (not user_id or (trace.user and trace.user.id == user_id))
        and (not guards or any(f.guard in guards for f in trace.findings))
    ]
    traces.sort(key=lambda trace: trace.started_at, reverse=True)
    traces = traces[:EXPORT_LIMIT]

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    headers = {"Content-Disposition": f'attachment; filename="audit-log-{stamp}.{fmt}"'}
    if fmt == "json":
        body = TraceExport(traces=traces).model_dump_json(indent=2)
        return Response(body, media_type="application/json", headers=headers)
    return Response(csv_of(traces), media_type="text/csv", headers=headers)


@router.get(
    "/{trace_id}",
    response_model=TraceDetail,
    summary="Get every event of one trace",
    responses={404: {"description": "No trace has this id."}},
)
async def get_trace(trace_id: str, session: Session, org_id: OrgId) -> TraceDetail:
    rows = list(
        await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.org_id == org_id, ControlEvent.trace_id == trace_id)
            .order_by(ControlEvent.id)
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return TraceDetail(
        summary=summary(rows),
        events=[TraceEvent.model_validate(row, from_attributes=True) for row in rows],
    )
