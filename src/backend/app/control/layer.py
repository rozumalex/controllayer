from collections.abc import Mapping
from dataclasses import dataclass, field

from app.control.audit import AuditSink, EventAuditSink
from app.control.envelope import Direction, Envelope
from app.control.guard import Guard
from app.control.guards.prompt_injection import (
    DESCRIPTIONS,
    PATTERNS,
    PromptInjectionGuard,
)
from app.control.guards.spotlight import SpotlightGuard
from app.control.pipeline import Decision, Mode, Pipeline


@dataclass(frozen=True)
class GuardSettings:
    """What an operator can change about one guard."""

    enabled: bool = True
    # Monitor logs the guard's BLOCK verdicts but lets the message through.
    mode: Mode = Mode.ENFORCE
    directions: frozenset[Direction] = frozenset(Direction)
    # Only for guards that score; a score at or above it blocks.
    threshold: float | None = None
    disabled_rules: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Rule:
    name: str
    score: float
    description: str


@dataclass(frozen=True)
class GuardSpec:
    """A guard the layer can run, and the settings it takes."""

    name: str
    title: str
    description: str
    # The directions it can run in, in pipeline order.
    directions: tuple[Direction, ...]
    # False for guards that only rewrite messages, so mode means nothing.
    blocks: bool
    scored: bool = False
    rules: tuple[Rule, ...] = field(default=())


GUARDS: tuple[GuardSpec, ...] = (
    GuardSpec(
        name="prompt_injection",
        title="Prompt injection",
        description=(
            "Matches known injection patterns in user prompts, tool calls and "
            "tool results, and blocks what scores at or above the threshold."
        ),
        directions=(Direction.INBOUND, Direction.OUTBOUND),
        blocks=True,
        scored=True,
        rules=tuple(
            Rule(label, score, DESCRIPTIONS[label]) for label, score, _ in PATTERNS
        ),
    ),
    GuardSpec(
        name="spotlight",
        title="Spotlighting",
        description=(
            "Wraps every tool result in delimiters, so the model can tell "
            "data it fetched from instructions it was given."
        ),
        directions=(Direction.OUTBOUND,),
        blocks=False,
    ),
)


def default_settings(spec: GuardSpec, mode: Mode, threshold: float) -> GuardSettings:
    return GuardSettings(
        mode=mode,
        directions=frozenset(spec.directions),
        threshold=threshold if spec.scored else None,
    )


def build_guard(spec: GuardSpec, settings: GuardSettings) -> Guard:
    if spec.name == "prompt_injection":
        return PromptInjectionGuard(
            threshold=settings.threshold if settings.threshold is not None else 0.7,
            disabled_rules=settings.disabled_rules,
        )
    return SpotlightGuard()


class ControlLayer:
    """The one entry point for transports: one pipeline per direction."""

    def __init__(self, pipelines: dict[Direction, Pipeline]) -> None:
        self.pipelines = pipelines

    async def inspect(self, envelope: Envelope) -> Decision:
        return await self.pipelines[envelope.direction].run(envelope)


def build_layer(
    controls: Mapping[str, GuardSettings], audit: AuditSink | None = None
) -> ControlLayer:
    """One pipeline per direction, with every enabled guard that runs in it.
    Tool results are where indirect injection comes from, so whatever passes
    the outbound guards is still marked as untrusted data."""
    audit = audit or EventAuditSink()
    guards = {
        spec.name: build_guard(spec, controls[spec.name])
        for spec in GUARDS
        if controls[spec.name].enabled
    }
    monitored = {name for name in guards if controls[name].mode is Mode.MONITOR}
    return ControlLayer(
        {
            direction: Pipeline(
                direction.value,
                [
                    guard
                    for name, guard in guards.items()
                    if direction in controls[name].directions
                ],
                audit,
                Mode.ENFORCE,
                monitored,
            )
            for direction in Direction
        }
    )
