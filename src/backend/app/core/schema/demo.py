from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.schema.policy import PolicySettings


class Account(BaseModel):
    role: str = Field(description="The job title whose policy the account has.")
    name: str = Field(description="The employee whose account it is.")
    policy: PolicySettings
    locked: bool = Field(
        description="Whether the layer locked the account out for too many "
        "blocked attacks in a short time."
    )
    lock_reason: str | None = Field(
        default=None,
        description="Why the layer locked the account, such as 6 blocked "
        "attacks in 5 minutes; None when it isn't locked.",
    )
    out_of_budget: bool = Field(
        description="Whether the account spent its weekly budget."
    )


class AttackGoal(BaseModel):
    id: str
    title: str
    description: str
    cases: int = Field(description="The corpus cases the goal replays.")


class ChecklistItem(BaseModel):
    id: str
    title: str
    description: str


class Risk(BaseModel):
    id: str = Field(description="The risk's OWASP Top 10 for LLM id, as LLM01.")
    title: str
    guards: list[str] = Field(description="The guards whose stops count toward it.")


class Simulator(BaseModel):
    accounts: list[Account]
    goals: list[AttackGoal]
    checklist: list[ChecklistItem] = Field(description="The hacker's checklist.")
    risks: list[Risk] = Field(description="The OWASP Top 10 for LLM applications.")
    scenarios: int = Field(description="How many scenarios the attack runs.")
    turns: int = Field(description="The total turn count across those scenarios.")
    missing: list[str] = Field(
        description="Ids of scenarios still holding a <turn N> placeholder."
    )


class UnlockRequest(BaseModel):
    role: str = Field(description="The role of the account to unlock or reset.")


class ChatCaseRequest(BaseModel):
    trace_id: str = Field(max_length=64)
    answer: str = Field(max_length=100_000, description="What the chat got back.")
    security: bool = Field(description="Whether the guards were on.")


class Case(BaseModel):
    """A request through a taken-over account and what came of it: a case of
    an attack, or a chat answer."""

    type: Literal["case"] = "case"
    id: str = Field(description="The corpus case, or chat.")
    category: str
    source: str
    mutation: str
    trace_id: str
    security: bool
    status: str
    guard: str | None = Field(
        description="The guard that stopped it, or with security off, would have."
    )
    reason: str | None
    prompt: str = Field(description="PII and secrets in it are masked once stored.")
    answer: str = Field(description="PII and secrets in it are masked once stored.")
    stolen: int = Field(
        description="Client data, the canary password and system prompt leaks "
        "that got out."
    )
    achieved: list[str] = Field(description="The checklist goals it achieved.")
    risk: str | None = Field(
        description="The OWASP risk of the attack the layer stopped, or None when "
        "it stopped none."
    )
    tokens: int
    usd: str
    verdicts: list[dict[str, Any]]
    # Set on scenario turns; absent on chat cases and older logs.
    scenario: str | None = None
    title: str | None = None
    owasp: str | None = None
    turn: int | None = None
    turns: int | None = None
    # Set on a scenario's last turn, after the judge.
    verdict: str | None = None
    story: str | None = None


class AttackRequest(BaseModel):
    role: str = Field(description="The role of the account taken over.")
    goals: list[str] = Field(min_length=1)
    security: bool = Field(
        description="Whether the guards block and redact, or only log."
    )
    step: bool = Field(
        default=True,
        description="When true, the run waits for POST /attack/next after "
        "each scenario so logs stop with the chat's Next / Explain.",
    )


class AttackNextRequest(BaseModel):
    run_id: str = Field(description="The run_id from a streamed case event.")
    security: bool | None = Field(
        default=None,
        description="When set, the next scenario uses this protection setting.",
    )


class AttackRun(BaseModel):
    trace_id: str = Field(description="The trace of the run's last case.")
    created_at: datetime
    outcome: Literal["done", "out_of_budget", "over_budget", "locked_out", "stopped"]
    goal: str
    role: str
    security: bool
    cases: int
    blocked: int
    landed: int
    false_alarms: int
    stolen: int = Field(
        description="Client data, the canary password and system prompt leaks "
        "that got out."
    )
    tokens: int
    usd: Decimal
    guards: dict[str, int] = Field(description="Attacks each guard stopped.")


class HistoryVerdict(BaseModel):
    direction: str | None = None
    tool: str | None = None
    guard: str
    action: str
    reason: str = ""
    latency_ms: float = 0


class HistoryEntry(BaseModel):
    trace_id: str
    created_at: datetime
    user: str | None = Field(description="The name of the user it ran as.")
    status: Literal["blocked", "contained", "passed", "allowed"]
    guard: str | None = Field(description="The guard that blocked it, or would.")
    reason: str | None
    verdicts: list[HistoryVerdict]
