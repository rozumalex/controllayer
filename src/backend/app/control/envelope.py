from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Direction(StrEnum):
    INBOUND = "inbound"  # agent -> tool: the tool call and its arguments
    OUTBOUND = "outbound"  # tool -> agent: the tool result
    RESPONSE = "response"  # model -> user: the model's answer
    DEFINITION = "definition"  # tool -> model: a tool's description and schema


class Action(StrEnum):
    ALLOW = "allow"
    MODIFY = "modify"
    BLOCK = "block"


@dataclass(frozen=True)
class Envelope:
    """One message crossing the layer. Guards see nothing else."""

    direction: Direction
    agent_id: str
    server: str
    tool: str
    payload: dict[str, Any]
    trace_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class Verdict:
    action: Action
    guard: str
    score: float | None = None
    reason: str = ""
    # The new payload, set only when action is MODIFY.
    payload: dict[str, Any] | None = None
    # What the guard keeps for the user's next requests, saved with the
    # verdict: labels and hashes only, never the message's text.
    memory: dict[str, list[str]] | None = None
