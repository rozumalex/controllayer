from typing import Self

from pydantic import BaseModel, Field

from app.control.envelope import Direction
from app.control.layer import GuardSettings, GuardSpec
from app.control.pipeline import Mode


class GuardSettingsModel(BaseModel):
    enabled: bool = Field(description="Whether the guard runs at all.")
    mode: Mode = Field(
        description="enforce blocks; monitor logs the block and lets it through."
    )
    directions: list[Direction] = Field(
        description="Where it runs: inbound is prompts and tool calls, "
        "outbound is tool results."
    )
    threshold: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="For scoring guards: a score at or above it blocks.",
    )
    disabled_rules: list[str] = Field(
        default=[], description="The guard's rules that are switched off."
    )

    @classmethod
    def of(cls, settings: GuardSettings) -> Self:
        return cls(
            enabled=settings.enabled,
            mode=settings.mode,
            directions=sorted(settings.directions),
            threshold=settings.threshold,
            disabled_rules=sorted(settings.disabled_rules),
        )

    def settings(self) -> GuardSettings:
        return GuardSettings(
            enabled=self.enabled,
            mode=self.mode,
            directions=frozenset(self.directions),
            threshold=self.threshold,
            disabled_rules=frozenset(self.disabled_rules),
        )


class RuleModel(BaseModel):
    name: str
    score: float = Field(description="The score a match gives.")
    description: str


class GuardControl(BaseModel):
    """A guard, what it can be set to, and its current settings."""

    name: str
    title: str
    description: str
    directions: list[Direction] = Field(description="The directions it can run in.")
    blocks: bool = Field(description="False if it only rewrites messages.")
    scored: bool = Field(description="Whether it takes a threshold.")
    rules: list[RuleModel]
    customized: bool = Field(description="False while it runs with the defaults.")
    settings: GuardSettingsModel

    @classmethod
    def of(cls, spec: GuardSpec, settings: GuardSettings, customized: bool) -> Self:
        return cls(
            name=spec.name,
            title=spec.title,
            description=spec.description,
            directions=list(spec.directions),
            blocks=spec.blocks,
            scored=spec.scored,
            rules=[
                RuleModel(name=r.name, score=r.score, description=r.description)
                for r in spec.rules
            ],
            customized=customized,
            settings=GuardSettingsModel.of(settings),
        )
