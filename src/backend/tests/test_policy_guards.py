import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.control.guard import Guard
from app.control.guards.policy import (
    BudgetGuard,
    ClearanceGuard,
    ModelGuard,
    ToolAccessGuard,
)
from app.core.schema.policy import Budget, Clearance, ToolAction

CATALOG = {
    ("clients", "client_id"): Clearance.PUBLIC,
    ("clients", "client_name"): Clearance.PUBLIC,
    ("clients", "risk_rating"): Clearance.CONFIDENTIAL,
    ("clients", "tax_id"): Clearance.RESTRICTED,
    ("accounts", "account_id"): Clearance.PUBLIC,
    ("accounts", "status"): Clearance.INTERNAL,
}
CLIENT = {"client_id": "CLT-1", "client_name": "Acme", "risk_rating": "HIGH"}


def prompt(text: str = "Who is client CLT-1?") -> Envelope:
    return Envelope(Direction.INBOUND, "a", "llm", "user_prompt", {"content": text})


def call(tool: str) -> Envelope:
    return Envelope(Direction.INBOUND, "a", "bank", tool, {"client_id": "CLT-1"})


def result(tool: str, data: dict[str, Any]) -> Envelope:
    payload = {"content": [json.dumps(data)], "structured_content": data}
    return Envelope(Direction.OUTBOUND, "a", "bank", tool, payload)


def inspect(guard: Guard, envelope: Envelope) -> Verdict:
    return asyncio.run(guard.inspect(envelope))


def clearance(
    level: Clearance = Clearance.INTERNAL,
    above: ToolAction = ToolAction.REDACT,
    tools: dict[str, ToolAction] | None = None,
) -> ClearanceGuard:
    return ClearanceGuard(CATALOG, level, above, tools or {}, ToolAction.ALLOW)


def test_allowed_model_passes() -> None:
    # given
    guard = ModelGuard("gpt-4.1-mini", ["gpt-4.1-mini", "gpt-4.1"])

    # when / then
    assert inspect(guard, prompt()).action is Action.ALLOW


def test_model_the_policy_does_not_allow_is_blocked() -> None:
    # given
    guard = ModelGuard("gpt-4.1", ["gpt-4.1-mini"])

    # when
    verdict = inspect(guard, prompt())

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "model not allowed: gpt-4.1"


@pytest.mark.parametrize(
    ("budget", "tokens", "usd", "action"),
    [
        (Budget(), 10**9, Decimal(10**6), Action.ALLOW),
        (Budget(monthly_tokens=1000), 999, Decimal(0), Action.ALLOW),
        (Budget(monthly_tokens=1000), 1000, Decimal(0), Action.BLOCK),
        (Budget(monthly_usd=Decimal(5)), 0, Decimal("4.99"), Action.ALLOW),
        (Budget(monthly_usd=Decimal(5)), 0, Decimal(5), Action.BLOCK),
        (Budget(monthly_tokens=0), 0, Decimal(0), Action.BLOCK),
    ],
)
def test_budget(budget: Budget, tokens: int, usd: Decimal, action: Action) -> None:
    # given
    guard = BudgetGuard(budget, tokens, usd)

    # when / then
    assert inspect(guard, prompt()).action is action


def test_budget_score_is_the_share_used() -> None:
    # given
    guard = BudgetGuard(Budget(monthly_tokens=1000), 250, Decimal(0))

    # when / then
    assert inspect(guard, prompt()).score == 0.25


@pytest.mark.parametrize(
    ("tools", "default", "action"),
    [
        ({}, ToolAction.ALLOW, Action.ALLOW),
        ({}, ToolAction.BLOCK, Action.BLOCK),
        ({"bank__get_client": ToolAction.ALLOW}, ToolAction.BLOCK, Action.ALLOW),
        ({"bank__get_client": ToolAction.REDACT}, ToolAction.BLOCK, Action.ALLOW),
        ({"bank__get_client": ToolAction.BLOCK}, ToolAction.ALLOW, Action.BLOCK),
    ],
)
def test_tool_access(
    tools: dict[str, ToolAction], default: ToolAction, action: Action
) -> None:
    # given
    guard = ToolAccessGuard(tools, default)

    # when / then
    assert inspect(guard, call("get_client")).action is action


def test_data_within_clearance_passes() -> None:
    # given
    data = {"clients": [{"client_id": "CLT-1", "client_name": "Acme"}]}

    # when
    verdict = inspect(clearance(), result("search_clients", data))

    # then
    assert verdict.action is Action.ALLOW


def test_data_above_clearance_redacted_in_text_and_structured_content() -> None:
    # given
    data = {"client": CLIENT, "accounts": [{"account_id": "ACC-1", "status": "OPEN"}]}

    # when
    verdict = inspect(clearance(), result("get_client", data))

    # then
    assert verdict.action is Action.MODIFY
    assert verdict.reason == "redacted 1 fields above INTERNAL"
    assert verdict.payload is not None
    client = verdict.payload["structured_content"]["client"]
    assert client["risk_rating"] == "[redacted: CONFIDENTIAL]"
    assert client["client_name"] == "Acme"
    assert verdict.payload["structured_content"]["accounts"][0]["status"] == "OPEN"
    assert "HIGH" not in verdict.payload["content"][0]


def test_higher_clearance_sees_the_field() -> None:
    # when
    verdict = inspect(
        clearance(Clearance.CONFIDENTIAL), result("get_client", {"client": CLIENT})
    )

    # then
    assert verdict.action is Action.ALLOW


def test_data_above_clearance_blocked_when_policy_says_block() -> None:
    # when
    verdict = inspect(
        clearance(above=ToolAction.BLOCK), result("get_client", {"client": CLIENT})
    )

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "data above INTERNAL: CONFIDENTIAL"


def test_redact_tool_leaves_only_public_data() -> None:
    # given
    guard = clearance(
        Clearance.RESTRICTED,
        ToolAction.BLOCK,
        {"bank__get_account": ToolAction.REDACT},
    )
    data = {"account": {"account_id": "ACC-1", "status": "OPEN"}}

    # when
    verdict = inspect(guard, result("get_account", data))

    # then
    assert verdict.action is Action.MODIFY
    assert verdict.payload is not None
    account = verdict.payload["structured_content"]["account"]
    assert account == {"account_id": "ACC-1", "status": "[redacted: INTERNAL]"}


def test_field_missing_from_catalog_counts_as_restricted() -> None:
    # given
    data = {"client": {"client_id": "CLT-1", "new_secret_field": "x"}}

    # when
    verdict = inspect(clearance(Clearance.CONFIDENTIAL), result("get_client", data))

    # then
    assert verdict.payload is not None
    client = verdict.payload["structured_content"]["client"]
    assert client["new_secret_field"] == "[redacted: RESTRICTED]"


def test_empty_field_is_not_redacted() -> None:
    # given
    data = {"client": {"client_id": "CLT-1", "tax_id": None}}

    # when / then
    assert inspect(clearance(), result("get_client", data)).action is Action.ALLOW


def test_plain_text_result_passes() -> None:
    # given
    envelope = Envelope(
        Direction.OUTBOUND, "a", "docs", "read", {"content": ["Just some text"]}
    )

    # when / then
    assert inspect(clearance(), envelope).action is Action.ALLOW
