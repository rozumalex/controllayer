"""Record the demo staff's chats for the seed.

Signs in as the demo bank's three people, sends each one's everyday
questions through the running API's chat, and saves the control layer's
events of those chats to scripts/activity.json.gz. The chats are spread over
working hours from yesterday 14:00, Warsaw time, to now, and each role stays
well under its weekly budget. `./dev seed` gives the demo these events, and
each demo sandbox copies them.

Run in the api container, against the local stack, after `./dev seed`:
`docker compose exec api python -m scripts.record_activity`. It calls the
real models, for a few cents.
"""

import asyncio
import gzip
import json
import random
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.core.assistant import ASSISTANT_MODEL
from app.core.config import settings
from app.db.auth import issue_token, revoke_token
from app.db.models import ControlEvent, Organization, User
from app.db.models.organization import DEMO_SLUG
from app.db.policy import cost
from app.db.session import SessionLocal
from scripts.policies import POLICIES
from scripts.seed import ACTIVITY, STAFF_DOMAIN

API = f"http://localhost:8000{settings.api_prefix}/v1/chat/completions"
WARSAW = ZoneInfo("Europe/Warsaw")
# The working hours the chats fall in, Warsaw time.
WORKDAY = (time(8, 30), time(19, 0))
# Each role spends at most this share of its weekly budget.
BUDGET_SHARE = Decimal("0.25")

QUESTIONS = {
    "Managing Director": [
        "Find our clients named Beacon-something, one line on each.",
        "What does our latest research say about European banks? Three bullets.",
        "Summarise the open accounts of our largest client by assets under management.",
        "List the last trades booked for Beaconcrest Partners.",
        "Draft a short note confirming a client's quarterly review next week.",
        "What research do we have on semiconductors? Give me the key takeaways.",
        "Which of our clients are hedge funds? Just the names.",
        "Prime brokerage vs custody account, in two sentences?",
    ],
    "Operations Specialist": [
        "Show the latest transactions on the accounts of Beaconcrest Partners.",
        "Recent trades for Beaconcrest Partners: are any still pending?",
        "Search for clients called Northwind and tell me their status.",
        "What is a failed settlement, and what are the usual first steps to fix one?",
        "Look up the accounts of our largest client and give me their currencies.",
        "Summarise the T+1 settlement rule for US equities in three bullets.",
    ],
    "Engineer": [
        "Write a Python function that validates an IBAN checksum.",
        "Explain idempotency keys for a payments API in a few sentences.",
        "OAuth client credentials vs authorization code flow: when to use each?",
        "Give me a SQL query that finds duplicate rows by email in a users table.",
        "Review this: `except Exception: pass`. What should it be instead?",
        "How should we rotate an API key without downtime? Short checklist.",
        "Look up the client Beaconcrest Partners for me.",
    ],
}


def workday_slots(start: datetime, end: datetime, count: int) -> list[datetime]:
    """count random moments between start and end, in working hours, in order."""
    spans = []
    day = start.astimezone(WARSAW).date()
    while day <= end.astimezone(WARSAW).date():
        opens = datetime.combine(day, WORKDAY[0], WARSAW)
        closes = datetime.combine(day, WORKDAY[1], WARSAW)
        spans.append((max(opens, start), min(closes, end)))
        day += timedelta(days=1)
    spans = [(a, b) for a, b in spans if a < b]
    total = sum((b - a).total_seconds() for a, b in spans)
    slots = []
    for offset in sorted(random.uniform(0, total) for _ in range(count)):
        for a, b in spans:
            length = (b - a).total_seconds()
            if offset < length:
                slots.append(a + timedelta(seconds=offset))
                break
            offset -= length
    return slots


async def staff() -> dict[str, User]:
    """The demo bank's people by role: the demo account is the Managing
    Director."""
    async with SessionLocal() as session:
        demo = await session.scalar(
            select(Organization.id).where(Organization.slug == DEMO_SLUG)
        )
        users = await session.scalars(
            select(User).where(
                User.org_id == demo,
                User.email.like(f"%@{STAFF_DOMAIN}")
                | (User.email == settings.demo_email),
            )
        )
        people: dict[str, User] = {}
        for user in users:
            if user.email == settings.demo_email:
                people["Managing Director"] = user
            elif user.title:
                people.setdefault(user.title, user)
    return people


async def ask(client: httpx.AsyncClient, token: str, question: str) -> str:
    response = await client.post(
        API,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": ASSISTANT_MODEL,
            "messages": [{"role": "user", "content": question}],
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.headers["X-Trace-Id"]


async def record() -> None:
    people = await staff()
    traces: dict[str, str] = {}
    async with httpx.AsyncClient() as client:
        for role, questions in QUESTIONS.items():
            user = people[role]
            async with SessionLocal() as session:
                token = await issue_token(session, user.id)
            try:
                for question in questions:
                    traces[await ask(client, token, question)] = role
                    print(f"{role}: {question}")
                    # The rate limit allows 20 questions a minute.
                    await asyncio.sleep(3)
            finally:
                async with SessionLocal() as session:
                    await revoke_token(session, token)

    async with SessionLocal() as session:
        rows = await session.scalars(
            select(ControlEvent)
            .where(ControlEvent.trace_id.in_(traces))
            .order_by(ControlEvent.id)
        )
        by_trace = defaultdict(list)
        for row in rows:
            by_trace[row.trace_id].append(row)

    spent: dict[str, Decimal] = defaultdict(Decimal)
    for trace_id, events in by_trace.items():
        for e in events:
            if e.event == "upstream_response" and e.data.get("usage"):
                usage = e.data["usage"]
                spent[traces[trace_id]] += cost(
                    e.data.get("model") or "",
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
    for role, usd in spent.items():
        budget = POLICIES[role].budget.weekly_usd
        print(f"{role}: ${usd:.4f} of ${budget} a week")
        if budget is not None and usd > budget * BUDGET_SHARE:
            raise SystemExit(f"{role} spent more than {BUDGET_SHARE:.0%} of the budget")

    now = datetime.now(UTC)
    start = datetime.combine(
        now.astimezone(WARSAW).date() - timedelta(days=1), time(14), WARSAW
    )
    order = list(by_trace)
    random.shuffle(order)
    saved = []
    for slot, trace_id in zip(
        workday_slots(start, now, len(order)), order, strict=True
    ):
        events = by_trace[trace_id]
        first = events[0].created_at
        for e in events:
            data = {k: v for k, v in e.data.items() if k not in ("user_id", "org_id")}
            saved.append(
                {
                    "role": traces[trace_id],
                    "at": (slot + (e.created_at - first)).isoformat(),
                    "trace_id": trace_id,
                    "event": e.event,
                    "action": e.action,
                    "data": data,
                }
            )
    saved.sort(key=lambda e: str(e["at"]))
    with gzip.open(ACTIVITY, "wt") as file:
        json.dump(saved, file)
    print(f"saved {len(saved)} events of {len(order)} chats to {ACTIVITY.name}")


if __name__ == "__main__":
    asyncio.run(record())
