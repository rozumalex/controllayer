"""The attack simulator: pick an employee's account an attacker has taken
over, and watch the scenarios run through it, live. The chat acts as them through
the X-Simulate-* headers of /api/v1, see app/api/deps.py.
See app/core/simulator.py."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, OrgId, event_sink, first_employee
from app.api.endpoints.traces import prompt
from app.control.audit import UserEventSink
from app.core.checklist import CHECKLIST
from app.core.scenarios import load as load_scenarios
from app.core.scenarios import ready
from app.core.schema.demo import (
    Account,
    AttackGoal,
    AttackNextRequest,
    AttackRequest,
    Case,
    ChatCaseRequest,
    ChecklistItem,
    Risk,
    Simulator,
    UnlockRequest,
)
from app.core.simulator import (
    GOALS,
    RISKS,
    Simulation,
    advance,
    outcome,
    risk,
    roles,
    stored,
)
from app.db.models import ControlEvent, User
from app.db.policy import recent_blocks, recent_flags, role_policy, spent_this_week
from app.db.session import SessionLocal

router = APIRouter(prefix="/demo", tags=["demo"])


async def account(user: User, role: str) -> tuple[User, Account]:
    """The first employee with the role, or with none, the signed-in user
    under the role's policy."""
    employee = await first_employee(user.org_id, role) or user
    async with SessionLocal() as session:
        policy = await role_policy(session, user.org_id, role)
        blocked = await recent_blocks(session, employee.id, policy.lockout.seconds)
        flagged = await recent_flags(session, employee.id, policy.lockout.seconds)
        spent = await spent_this_week(session, employee.id)
    limits = policy.lockout
    if limits.blocks and blocked >= limits.blocks:
        lock = f"{blocked} blocked attacks in {limits.minutes} minutes"
    elif limits.flags and flagged >= limits.flags:
        lock = f"{flagged} suspicious requests in {limits.minutes} minutes"
    else:
        lock = None
    weekly = policy.budget.weekly_usd
    return employee, Account(
        role=role,
        name=employee.name,
        policy=policy,
        locked=lock is not None,
        lock_reason=lock,
        out_of_budget=weekly is not None and spent >= weekly,
    )


async def simulation(user: User, role: str, **options: Any) -> Simulation:
    if role not in await roles(user.org_id):
        raise HTTPException(404, "Unknown role")
    employee, found = await account(user, role)
    return Simulation(employee, role, found.policy, **options)


@router.get("", response_model=Simulator, summary="Show the accounts and goals")
async def simulator(user: CurrentUser) -> Simulator:
    accounts = [(await account(user, role))[1] for role in await roles(user.org_id)]
    pack = load_scenarios()
    by_goal = {g.id: 0 for g in GOALS}
    for scenario in pack.scenarios:
        by_goal[scenario.goal] = by_goal.get(scenario.goal, 0) + len(scenario.turns)
    goals = [
        AttackGoal(
            id=g.id,
            title=g.title,
            description=g.description,
            cases=by_goal.get(g.id, 0),
        )
        for g in GOALS
    ]
    checklist = [ChecklistItem(**vars(item)) for item in CHECKLIST]
    risks = [Risk(id=r.id, title=r.title, guards=list(r.guards)) for r in RISKS]
    return Simulator(
        accounts=accounts,
        goals=goals,
        checklist=checklist,
        risks=risks,
        scenarios=len(pack.scenarios),
        turns=sum(len(s.turns) for s in pack.scenarios),
        missing=[s.id for s in pack.scenarios if not ready(s)],
    )


@router.post(
    "/attack",
    summary="Run an attack through a taken-over account",
    description=(
        "Streams one JSON line per scenario turn, as it runs through the agent, "
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
        step=request.step,
    )

    async def lines() -> AsyncIterator[str]:
        async for event in run.run():
            yield json.dumps(event) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post(
    "/attack/next",
    status_code=204,
    summary="Continue a stepped attack after Next / Explain",
    description=(
        "Releases the run named by run_id so it starts the next scenario. "
        "Each case event carries the run_id. Optional security flips "
        "protection for the next scenario and after."
    ),
)
async def attack_next(request: AttackNextRequest, user: CurrentUser) -> None:
    del user  # Auth only: run_ids are unguessable.
    if not advance(request.run_id, request.security):
        raise HTTPException(404, "Unknown run")


@router.post(
    "/unlock",
    response_model=Case,
    summary="Unlock an account the layer locked out",
    description=(
        "Wipes the slate of the role's employee: the lockout counts only the "
        "blocked attacks after this. The unlock lands in the account's logs "
        "and on the dashboard."
    ),
)
async def unlock(request: UnlockRequest, user: CurrentUser) -> dict[str, Any]:
    # With no employee, the signed-in user, as the simulator acts then.
    employee = await first_employee(user.org_id, request.role) or user
    sink = UserEventSink(event_sink(), employee.id, employee.org_id)
    trace_id = uuid4().hex
    reason = f"Unlocked by {user.name}"
    await sink.write(
        {"event": "unlock", "trace_id": trace_id, "by": str(user.id), "reason": reason}
    )
    case = {
        "type": "case",
        "id": "unlock",
        "category": "unlock",
        "source": "admin",
        "mutation": "none",
        "trace_id": trace_id,
        "security": True,
        "status": "unlocked",
        "guard": None,
        "reason": reason,
        "prompt": "",
        "answer": "",
        "stolen": 0,
        "achieved": [],
        "tokens": 0,
        "usd": "0",
        "verdicts": [],
    }
    await sink.write({**case, "event": "case"})
    return {**case, "risk": None}


@router.post(
    "/reset",
    status_code=204,
    summary="Start an account's hacker's checklist over",
    description=(
        "The role's employee's earlier cases tick nothing on the checklist "
        "any more. Nothing is deleted: the charts and logs keep every case."
    ),
)
async def reset(request: UnlockRequest, user: CurrentUser) -> None:
    employee = await first_employee(user.org_id, request.role) or user
    sink = UserEventSink(event_sink(), employee.id, employee.org_id)
    await sink.write({"event": "reset", "trace_id": uuid4().hex, "by": str(user.id)})


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
async def chat_case(request: ChatCaseRequest, org_id: OrgId) -> dict[str, Any]:
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
    description=(
        "The attack cases and chat answers of the role's employee. Cases from "
        "before the last reset tick nothing on the checklist."
    ),
)
async def cases(
    user: CurrentUser,
    role: str,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
) -> list[dict[str, Any]]:
    employee = await first_employee(user.org_id, role) or user
    async with SessionLocal() as session:
        reset = await session.scalar(
            select(func.max(ControlEvent.id)).where(
                ControlEvent.user_id == employee.id, ControlEvent.event == "reset"
            )
        )
        found = await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.user_id == employee.id, ControlEvent.event == "case")
            .order_by(ControlEvent.id.desc())
            .limit(limit)
        )
        # The risk again for each case, so cases logged before it was kept
        # count too.
        return [
            {
                **e.data,
                "risk": risk(e.data),
                **({"achieved": []} if e.id <= (reset or 0) else {}),
            }
            for e in reversed(list(found))
        ]
