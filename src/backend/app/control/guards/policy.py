"""Guards that apply the signed-in user's policy: which models they may use,
how much they may spend, which tools they may call and which data they see.

They are built for each request from the policy of the user's role, so a
policy saved in the admin pages applies to the next request."""

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.core.schema.policy import Budget, Clearance, ToolAction

# The gateway names tools as <server>__<tool>, and so do policies.
SEPARATOR = "__"
LEVELS = list(Clearance)
# The catalog names tables in the plural; a result may hold one row.
TABLES = {"client": "clients", "account": "accounts", "trade": "trades"}
TABLES |= {"transaction": "transactions", "user": "users"}

Catalog = Mapping[tuple[str, str], Clearance]


def tool_action(
    tools: Mapping[str, ToolAction], default: ToolAction, name: str
) -> ToolAction:
    return tools.get(name, default)


class ModelGuard:
    """Blocks a prompt to a model the role's policy doesn't allow."""

    name = "policy_model"

    def __init__(self, model: str, allowed: list[str]) -> None:
        self.model = model
        self.allowed = allowed

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.tool != "user_prompt" or self.model in self.allowed:
            return Verdict(Action.ALLOW, self.name)
        reason = f"model not allowed: {self.model}"
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)


class BudgetGuard:
    """Blocks a prompt once the user has spent their weekly budget. The score
    is the share of it spent."""

    name = "policy_budget"

    def __init__(self, budget: Budget, weekly: Decimal) -> None:
        self.budget = budget
        self.weekly = weekly

    @property
    def used(self) -> float:
        if self.budget.weekly_usd is None:
            return 0.0
        return share(self.weekly, self.budget.weekly_usd)

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.tool != "user_prompt":
            return Verdict(Action.ALLOW, self.name)
        used = self.used
        if used < 1:
            return Verdict(Action.ALLOW, self.name, score=used)
        return Verdict(
            Action.BLOCK, self.name, score=used, reason="weekly budget spent"
        )


def result_clearance(
    tools: Mapping[str, ToolAction],
    default: ToolAction,
    name: str,
    clearance: Clearance,
    above_clearance: ToolAction,
) -> tuple[Clearance, ToolAction]:
    """The clearance a tool's result is shown at, and what happens to data
    above it. A tool the policy marks redact shows public data only."""
    if tool_action(tools, default, name) is ToolAction.REDACT:
        return Clearance.PUBLIC, ToolAction.REDACT
    return clearance, above_clearance


def above(level: Clearance, clearance: Clearance) -> bool:
    return LEVELS.index(level) > LEVELS.index(clearance)


def share(used: int | Decimal, limit: int | Decimal) -> float:
    return float(used / limit) if limit else 1.0


class ToolAccessGuard:
    """Blocks a call to a tool the role's policy blocks."""

    name = "policy_tools"

    def __init__(self, tools: Mapping[str, ToolAction], default: ToolAction) -> None:
        self.tools = tools
        self.default = default

    def allows(self, name: str) -> bool:
        return tool_action(self.tools, self.default, name) is not ToolAction.BLOCK

    async def inspect(self, envelope: Envelope) -> Verdict:
        name = f"{envelope.server}{SEPARATOR}{envelope.tool}"
        if envelope.direction is Direction.OUTBOUND or self.allows(name):
            return Verdict(Action.ALLOW, self.name)
        reason = f"tool blocked by policy: {name}"
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)


class ClearanceGuard:
    """Hides the fields of a tool result that are above the role's clearance,
    by the sensitivity the bank's data catalog gives them. A field the catalog
    doesn't know, in a table it does, counts as restricted.

    The policy says whether such a result is redacted or withheld. A tool the
    policy marks redact always has its result redacted, down to public data.
    """

    name = "policy_clearance"

    def __init__(
        self,
        catalog: Catalog,
        clearance: Clearance,
        above_clearance: ToolAction,
        tools: Mapping[str, ToolAction],
        default: ToolAction,
    ) -> None:
        self.catalog = catalog
        self.tables = {table for table, _ in catalog}
        self.clearance = clearance
        self.above_clearance = above_clearance
        self.tools = tools
        self.default = default

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.direction is Direction.INBOUND:
            return Verdict(Action.ALLOW, self.name)
        name = f"{envelope.server}{SEPARATOR}{envelope.tool}"
        clearance, action = result_clearance(
            self.tools, self.default, name, self.clearance, self.above_clearance
        )
        # The fields hidden, by table and name: the text blocks repeat the
        # structured content, so a field may be hidden twice.
        hidden: dict[tuple[str, str], Clearance] = {}
        payload = {
            key: self.redact(value, None, clearance, hidden, parse=key == "content")
            for key, value in envelope.payload.items()
        }
        if not hidden:
            return Verdict(Action.ALLOW, self.name, score=0.0)
        highest = max(hidden.values(), key=LEVELS.index)
        if action is ToolAction.BLOCK:
            reason = f"data above {clearance}: {highest}"
            return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
        reason = f"redacted {len(hidden)} fields above {clearance}"
        return Verdict(
            Action.MODIFY, self.name, score=1.0, reason=reason, payload=payload
        )

    def redact(
        self,
        value: Any,
        table: str | None,
        clearance: Clearance,
        hidden: dict[tuple[str, str], Clearance],
        parse: bool = False,
    ) -> Any:
        if isinstance(value, list):
            return [self.redact(v, table, clearance, hidden, parse) for v in value]
        if isinstance(value, str) and parse:
            # Text blocks carry the same rows as the structured content, as
            # JSON.
            try:
                data = json.loads(value)
            except ValueError:
                return value
            if not isinstance(data, dict | list):
                return value
            return json.dumps(self.redact(data, None, clearance, hidden))
        if not isinstance(value, dict):
            return value
        redacted = {}
        for key, field in value.items():
            level = self.level(table, key) if table else None
            if table and level and field is not None and above(level, clearance):
                hidden[table, key] = level
                redacted[key] = f"[redacted: {level}]"
                continue
            nested = TABLES.get(key, key)
            child = nested if nested in self.tables else table
            redacted[key] = self.redact(field, child, clearance, hidden)
        return redacted

    def level(self, table: str, field: str) -> Clearance:
        return self.catalog.get((table, field), Clearance.RESTRICTED)
