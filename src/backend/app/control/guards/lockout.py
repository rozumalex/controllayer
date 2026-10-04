"""Locks a user out once the layer has blocked too many of their attacks in a
short time: a run of attacks is someone probing the guards, often with a
stolen account, not an employee at work.

Only an attack counts: a block by one of the ATTACKS guards on what the user
sent, their prompt or their agent's tool call, or on the answer they drew
out. A poisoned tool result is the tool's fault, not the user's, so it counts
against the tool (see spoiled_tool.py). A block by the budget, the rate
limit, a model the role can't use, a secret pasted by mistake or a runaway
loop stops that request only."""

from app.control.envelope import Action, Envelope, Verdict
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


class LockoutGuard:
    """Blocks every message once limit of the user's attacks were blocked in
    the last window seconds. The lock lifts by itself when the window has
    passed with no more attacks. The score is the share of the limit used."""

    name = "lockout"

    def __init__(self, limit: int, window_seconds: int, blocked: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.blocked = blocked

    async def inspect(self, envelope: Envelope) -> Verdict:
        if not self.limit:
            return Verdict(Action.ALLOW, self.name)
        used = self.blocked / self.limit
        if self.blocked < self.limit:
            return Verdict(Action.ALLOW, self.name, score=used)
        reason = (
            f"account locked: {self.blocked} blocked attacks in "
            f"{self.window_seconds} seconds"
        )
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
