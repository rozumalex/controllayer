"""Locks a user out once the layer has blocked too many of their attacks in a
short time, or flagged too many of their requests as suspicious: a run of
attacks is someone probing the guards, often with a stolen account, not an
employee at work.

A request is suspicious when an injection guard scored what the user sent at
SUSPICIOUS or more but let it through: not enough to block on its own, but a
run of them is someone feeling for the threshold.

Only an attack counts: a block by one of the ATTACKS guards on what the user
sent, their prompt or their agent's tool call, or on the answer they drew
out. A poisoned tool result is the tool's fault, not the user's, so it counts
against the tool (see spoiled_tool.py). A block by the budget, the rate
limit, a model the role can't use, a secret pasted by mistake, a runaway
loop or a call to a tool the role shows as blocked stops that request only."""

from typing import Any

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.control.guards.data_flow import DataFlowGuard
from app.control.guards.policy import ToolAccessGuard
from app.control.guards.prompt_injection import PromptInjectionGuard
from app.control.guards.prompt_leak import PromptLeakGuard
from app.control.guards.semantic_injection import SemanticInjectionGuard
from app.control.guards.signatures import SignatureGuard

# The guards that catch an injection, in a prompt or in a tool result.
INJECTIONS = frozenset(
    {SignatureGuard.name, PromptInjectionGuard.name, SemanticInjectionGuard.name}
)
# The guards whose block on a user's request is an attack.
ATTACKS = INJECTIONS | {DataFlowGuard.name, PromptLeakGuard.name, ToolAccessGuard.name}
# The injection score at or above which a request it let through is suspicious.
SUSPICIOUS = 0.4


def suspicious(verdict: dict[str, Any]) -> bool:
    """Whether the logged verdict flags what the user sent as suspicious."""
    return (
        verdict.get("guard") in INJECTIONS
        and verdict.get("action") == Action.ALLOW
        and verdict.get("direction") != Direction.OUTBOUND
        and (verdict.get("score") or 0) >= SUSPICIOUS
    )


class LockoutGuard:
    """Blocks every message once limit of the user's attacks were blocked, or
    flags of their requests were flagged, in the last window seconds. A limit
    of 0 turns its count off. The lock lifts by itself when the window has
    passed with no more of them. The score is the share of the nearer limit
    used."""

    name = "lockout"

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        blocked: int,
        flags: int = 0,
        flagged: int = 0,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.blocked = blocked
        self.flags = flags
        self.flagged = flagged

    async def inspect(self, envelope: Envelope) -> Verdict:
        shares = [
            count / limit
            for count, limit in ((self.blocked, self.limit), (self.flagged, self.flags))
            if limit
        ]
        if not shares:
            return Verdict(Action.ALLOW, self.name)
        used = max(shares)
        if used < 1:
            return Verdict(Action.ALLOW, self.name, score=used)
        if self.limit and self.blocked >= self.limit:
            what = f"{self.blocked} blocked attacks"
        else:
            what = f"{self.flagged} suspicious requests"
        reason = f"account locked: {what} in {self.window_seconds} seconds"
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
