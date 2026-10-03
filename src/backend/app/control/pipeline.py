import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from app.control.audit import AuditSink
from app.control.envelope import Action, Envelope, Verdict
from app.control.guard import Guard


class Mode(StrEnum):
    ENFORCE = "enforce"  # a BLOCK verdict stops the message
    MONITOR = "monitor"  # every verdict is logged, nothing is blocked


@dataclass(frozen=True)
class Decision:
    action: Action
    envelope: Envelope
    verdicts: list[Verdict]


class Pipeline:
    """Runs guards in order and records every verdict.

    A Pipeline is a Guard too, so one layer can hold other layers. The guards
    named in monitored only log their BLOCK verdicts, whatever the mode."""

    def __init__(
        self,
        name: str,
        guards: Sequence[Guard],
        audit: AuditSink,
        mode: Mode,
        monitored: Collection[str] = (),
    ) -> None:
        self.name = name
        self.guards = guards
        self.audit = audit
        self.mode = mode
        self.monitored = monitored

    async def run(self, envelope: Envelope) -> Decision:
        verdicts: list[Verdict] = []
        modified = False
        for guard in self.guards:
            start = time.perf_counter()
            verdict = await guard.inspect(envelope)
            latency_ms = (time.perf_counter() - start) * 1000
            verdicts.append(verdict)
            await self.audit.record(envelope, verdict, latency_ms)
            if verdict.action is Action.BLOCK and self.enforces(guard):
                return Decision(Action.BLOCK, envelope, verdicts)
            if verdict.action is Action.MODIFY and verdict.payload is not None:
                envelope = replace(envelope, payload=verdict.payload)
                modified = True
        action = Action.MODIFY if modified else Action.ALLOW
        return Decision(action, envelope, verdicts)

    def enforces(self, guard: Guard) -> bool:
        return self.mode is Mode.ENFORCE and guard.name not in self.monitored

    async def inspect(self, envelope: Envelope) -> Verdict:
        decision = await self.run(envelope)
        reasons = [v.reason for v in decision.verdicts if v.action is not Action.ALLOW]
        scores = [v.score for v in decision.verdicts if v.score is not None]
        return Verdict(
            action=decision.action,
            guard=self.name,
            score=max(scores, default=None),
            reason="; ".join(reasons),
            payload=decision.envelope.payload
            if decision.action is Action.MODIFY
            else None,
        )
