"""The attack simulator: pick an employee's account an attacker has taken
over, and watch the corpus run through it, live. The chat acts as them through
the X-Simulate-* headers of /api/v1, see app/api/deps.py.
See app/core/simulator.py."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, OrgId, UserPolicy, event_sink, first_employee
from app.api.endpoints.traces import prompt
from app.control.audit import UserEventSink
from app.core.checklist import CHECKLIST, above
from app.core.schema.demo import (
    Account,
    AttackGoal,
    AttackRequest,
    AttackRun,
    Case,
    ChatCaseRequest,
    ChecklistItem,
    HistoryEntry,
    HistoryVerdict,
    Risk,
    Simulator,
    UnlockRequest,
)
from app.core.simulator import (
    ENDINGS,
    GOALS,
    RISKS,
    Simulation,
    goal_cases,
    outcome,
    risk,
    roles,
    stored,
)
from app.db.models import ControlEvent, User
from app.db.policy import recent_blocks, role_policy
from app.db.session import SessionLocal

router = APIRouter(prefix="/demo", tags=["demo"])

RUNS = 20


async def account(user: User, role: str) -> tuple[User, Account]:
    """The first employee with the role, or with none, the signed-in user
    under the role's policy."""
    employee = await first_employee(user.org_id, role) or user
    async with SessionLocal() as session:
        policy = await role_policy(session, user.org_id, role)
        blocked = await recent_blocks(session, employee.id, policy.lockout.seconds)
    limit = policy.lockout.blocks
    locked = bool(limit) and blocked >= limit
    checklist = [
        item.id
        for item in CHECKLIST
        if item.id != "above_clearance" or above(policy.clearance)
    ]
    return employee, Account(
        role=role,
        name=employee.name,
        policy=policy,
        locked=locked,
        checklist=checklist,
    )


async def simulation(user: User, role: str, **options: Any) -> Simulation:
    if role not in await roles(user.org_id):
        raise HTTPException(404, "Unknown role")
    employee, found = await account(user, role)
    return Simulation(employee, role, found.policy, **options)


@router.get("", response_model=Simulator, summary="Show the accounts and goals")
async def simulator(user: CurrentUser) -> Simulator:
    accounts = [(await account(user, role))[1] for role in await roles(user.org_id)]
    goals = [
        AttackGoal(
            id=g.id,
            title=g.title,
            description=g.description,
            cases=len(goal_cases(g.categories)),
        )
        for g in GOALS
    ]
    checklist = [ChecklistItem(**vars(item)) for item in CHECKLIST]
    risks = [Risk(id=r.id, title=r.title, guards=list(r.guards)) for r in RISKS]
    return Simulator(accounts=accounts, goals=goals, checklist=checklist, risks=risks)


@router.post(
    "/attack",
    summary="Run an attack through a taken-over account",
    description=(
        "Streams one JSON line per corpus case, as it runs through the agent, "
        "the control layer and the MCP gateway, then a line with the run's "
        "totals. Close the stream to stop the run."
    ),
)
async def attack(request: AttackRequest, user: CurrentUser) -> StreamingResponse:
    goals = [g for g in GOALS if g.id in request.goals]
    if len(goals) != len(set(request.goals)):
        raise HTTPException(404, "Unknown goal")
    run = await simulation(
        user,
        request.role,
        goals=goals,
        security=request.security,
    )

    async def lines() -> AsyncIterator[str]:
        async for event in run.run():
            yield json.dumps(event) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post(
    "/unlock",
    status_code=204,
    summary="Unlock an account the layer locked out",
    description=(
        "Wipes the slate of the role's employee: the lockout counts only the "
        "blocked attacks after this."
    ),
)
async def unlock(request: UnlockRequest, user: CurrentUser) -> Response:
    # With no employee, the signed-in user, as the simulator acts then.
    employee = await first_employee(user.org_id, request.role) or user
    sink = UserEventSink(event_sink(), employee.id, employee.org_id)
    await sink.write({"event": "unlock", "trace_id": uuid4().hex, "by": str(user.id)})
    return Response(status_code=204)


@router.post(
    "/chat-case",
    response_model=Case,
    summary="Log a chat answer as a case of its account",
    description=(
        "Tells what came of a chat request through a taken-over account, from "
        "its trace and the answer that got back, and keeps it in the account's "
        "logs, with PII and secrets masked."
    ),
)
async def chat_case(
    request: ChatCaseRequest, org_id: OrgId, policy: UserPolicy
) -> dict[str, Any]:
    async with SessionLocal() as session:
        events = list(
            await session.scalars(
                select(ControlEvent)
                .where(
                    ControlEvent.trace_id == request.trace_id,
                    ControlEvent.org_id == org_id,
                )
                .order_by(ControlEvent.id)
            )
        )
    if not events:
        raise HTTPException(404, "Unknown trace")
    case = {
        **await outcome(
            None,
            request.security,
            request.trace_id,
            [{**e.data, "event": e.event} for e in events],
            request.answer,
            policy.clearance,
        ),
        "id": "chat",
        "category": "chat",
        "source": "user_prompt",
        "mutation": "none",
        "prompt": prompt(next((e for e in events if e.event == "request"), None)) or "",
    }
    user_id = next((e.user_id for e in events if e.user_id), None)
    if user_id:
        await UserEventSink(event_sink(), user_id, org_id).write(stored(case))
    return case


@router.get(
    "/cases",
    response_model=list[Case],
    summary="List an account's cases, oldest first",
    description="The attack cases and chat answers of the role's employee.",
)
async def cases(
    user: CurrentUser,
    role: str,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
) -> list[dict[str, Any]]:
    employee = await first_employee(user.org_id, role) or user
    async with SessionLocal() as session:
        found = await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.user_id == employee.id, ControlEvent.event == "case")
            .order_by(ControlEvent.id.desc())
            .limit(limit)
        )
        # Again for each case, so cases logged before the risk was kept
        # count too.
        return [{**e.data, "risk": risk(e.data)} for e in reversed(list(found))]


def entry(events: list[ControlEvent]) -> HistoryEntry:
    """One request of the history, from its verdicts and decisions."""
    verdicts = [e for e in events if e.event == "verdict"]
    blocked = any(e.event == "decision" and e.action == "block" for e in events)
    # The guard that caught it comes first, ahead of the budget or lockout.
    stops = sorted(
        (v for v in verdicts if v.action == "block"),
        key=lambda v: v.data.get("guard") in ENDINGS,
    )
    changed = any(
        v.action == "modify" and v.data.get("guard") != "spotlight" for v in verdicts
    )
    status = (
        "blocked"
        if blocked
        else "passed"
        if stops
        else "contained"
        if changed
        else "allowed"
    )
    user = next((e.user.name for e in events if e.user), None)
    return HistoryEntry(
        trace_id=events[0].trace_id,
        created_at=events[0].created_at,
        user=user,
        status=status,
        guard=stops[0].data.get("guard") if stops else None,
        reason=stops[0].data.get("reason") if stops else None,
        verdicts=[
            HistoryVerdict.model_validate(v.data, extra="ignore") for v in verdicts
        ],
    )


@router.get(
    "/history",
    response_model=list[HistoryEntry],
    summary="List the organization's last requests with their verdicts",
)
async def history(
    org_id: OrgId, limit: Annotated[int, Query(ge=1, le=500)] = 200
) -> list[HistoryEntry]:
    async with SessionLocal() as session:
        first = func.min(ControlEvent.id)
        traces = (
            select(ControlEvent.trace_id)
            .where(ControlEvent.org_id == org_id, ControlEvent.event == "verdict")
            .group_by(ControlEvent.trace_id)
            .order_by(first.desc())
            .limit(limit)
        )
        events = await session.scalars(
            select(ControlEvent)
            .where(
                ControlEvent.trace_id.in_(traces),
                ControlEvent.event.in_(["verdict", "decision"]),
            )
            .order_by(ControlEvent.id)
        )
        by_trace: dict[str, list[ControlEvent]] = {}
        for event in events:
            by_trace.setdefault(event.trace_id, []).append(event)
    # Oldest first, as the page draws its timeline.
    return [entry(group) for group in by_trace.values()]


@router.get("/runs", response_model=list[AttackRun], summary="List the last runs")
async def runs(org_id: OrgId) -> list[AttackRun]:
    async with SessionLocal() as session:
        events = await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.org_id == org_id, ControlEvent.event == "attack")
            .order_by(ControlEvent.id.desc())
            .limit(RUNS)
        )
        return [
            AttackRun.model_validate(
                {**e.data, "trace_id": e.trace_id, "created_at": e.created_at}
            )
            for e in events
        ]
