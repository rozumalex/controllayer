"""The attack simulator's scenarios: short multi-turn stories an attacker
plays through a taken-over account.

Each scenario goes after one item of the hacker's checklist and names the
OWASP risk it showcases. Turns are plain prompts; a turn still written as
``<turn N>`` means the scenario isn't ready for a live run yet.
"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.checklist import CHECKLIST

SCENARIOS = Path(__file__).resolve().parents[1].parent / "scripts" / "scenarios.json"
OWASP = re.compile(r"^LLM(0[1-9]|10)$")
GOALS = {item.id for item in CHECKLIST}
PLACEHOLDER = re.compile(r"^<turn \d+>$")


class Scenario(BaseModel):
    id: str
    title: str
    owasp: str
    goal: str
    turns: list[str] = Field(min_length=1, max_length=3)

    @field_validator("owasp")
    @classmethod
    def owasp_id(cls, value: str) -> str:
        if not OWASP.match(value):
            raise ValueError(f"owasp must be LLM01–LLM10, got {value!r}")
        return value

    @field_validator("goal")
    @classmethod
    def checklist_goal(cls, value: str) -> str:
        if value not in GOALS:
            raise ValueError(f"goal must be a checklist id, got {value!r}")
        return value


class Pack(BaseModel):
    research_feed_note: str = ""
    scenarios: list[Scenario]


def load(path: Path = SCENARIOS) -> Pack:
    """The scenarios file, read on every call so edits apply without a
    restart."""
    return Pack.model_validate_json(path.read_bytes())


def ready(scenario: Scenario) -> bool:
    """False while any turn is still a ``<turn N>`` placeholder."""
    return not any(PLACEHOLDER.match(turn.strip()) for turn in scenario.turns)


Verdict = Literal["succeeded", "stopped", "failed"]
STOPPED = frozenset({"blocked", "false_alarm", "out_of_budget", "locked_out"})


def verdict(turns: list[dict]) -> Verdict:
    """What came of a scenario, from its turns' outcomes. Decided in code,
    never by the model."""
    if any(turn.get("achieved") for turn in turns):
        return "succeeded"
    if any(turn.get("status") in STOPPED for turn in turns):
        return "stopped"
    return "failed"
