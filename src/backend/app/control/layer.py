from app.control.audit import AuditSink, EventAuditSink
from app.control.envelope import Direction, Envelope
from app.control.guard import Guard
from app.control.guards.prompt_injection import PromptInjectionGuard
from app.control.guards.spotlight import SpotlightGuard
from app.control.pipeline import Decision, Mode, Pipeline


class ControlLayer:
    """The one entry point for transports: one pipeline per direction."""

    def __init__(self, pipelines: dict[Direction, Pipeline]) -> None:
        self.pipelines = pipelines

    async def inspect(self, envelope: Envelope) -> Decision:
        return await self.pipelines[envelope.direction].run(envelope)


def build_layer(
    mode: Mode,
    injection_threshold: float,
    audit: AuditSink | None = None,
    semantic: Guard | None = None,
) -> ControlLayer:
    """semantic is the AI-based injection guard. It runs after the heuristic
    one, so an obvious attack is blocked without a model call."""
    audit = audit or EventAuditSink()
    injection: list[Guard] = [PromptInjectionGuard(threshold=injection_threshold)]
    if semantic:
        injection.append(semantic)
    return ControlLayer(
        {
            Direction.INBOUND: Pipeline("inbound", injection, audit, mode),
            # Tool results are where indirect injection comes from. Whatever
            # passes is still marked as untrusted data.
            Direction.OUTBOUND: Pipeline(
                "outbound", [*injection, SpotlightGuard()], audit, mode
            ),
        }
    )
