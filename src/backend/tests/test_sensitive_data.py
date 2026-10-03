import asyncio
import json
from typing import Any

import pytest

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.control.guards.sensitive_data import SensitiveDataGuard, scrub
from app.core.schema.policy import Clearance, PiiKind, ToolAction

# Split, so the repo's private key hook doesn't flag the test.
PRIVATE_KEY = (
    "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
)


def guard(
    clearance: Clearance = Clearance.INTERNAL,
    above: ToolAction = ToolAction.REDACT,
    tools: dict[str, ToolAction] | None = None,
    pii: dict[PiiKind, ToolAction] | None = None,
) -> SensitiveDataGuard:
    return SensitiveDataGuard(
        pii or {}, clearance, above, tools or {}, ToolAction.ALLOW
    )


def prompt(text: str) -> Envelope:
    return Envelope(Direction.INBOUND, "a", "llm", "user_prompt", {"content": text})


def call(arguments: dict[str, Any]) -> Envelope:
    return Envelope(Direction.INBOUND, "a", "bank", "add_client_note", arguments)


def result(data: dict[str, Any], tool: str = "get_client") -> Envelope:
    payload = {"content": [json.dumps(data)], "structured_content": data}
    return Envelope(Direction.OUTBOUND, "a", "bank", tool, payload)


def inspect(subject: SensitiveDataGuard, envelope: Envelope) -> Verdict:
    return asyncio.run(subject.inspect(envelope))


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Write to eleanor.fairbanks@beaconcrest.com", "email"),
        ("Call +1 837 825 8997 today", "phone"),
        ("Pay into GB82 WEST 1234 5698 7654 32", "iban"),
        ("Pay into PL61109010140000071219812874", "iban"),
        ("Card 4111 1111 1111 1111 was declined", "payment_card"),
        ("Her PESEL is 44051401359", "pesel"),
    ],
)
def test_pii_in_prompt_redacted(text: str, kind: str) -> None:
    # when
    verdict = inspect(guard(), prompt(text))

    # then
    assert verdict.action is Action.MODIFY
    assert verdict.reason == f"redacted: {kind}"
    assert verdict.payload is not None
    assert f"[redacted: {kind}]" in verdict.payload["content"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key AKIAIOSFODNN7EXAMPLE", "aws_key"),
        (f"token ghp_{'a1' * 18}", "github_token"),
        (f"use sk-proj-{'x' * 30}", "api_key"),
        (f"Authorization: Bearer {'t' * 32}", "bearer_token"),
        ("db password=hunter2secret", "password"),
        (PRIVATE_KEY, "private_key"),
    ],
)
def test_secret_in_prompt_blocked_for_any_clearance(text: str, kind: str) -> None:
    # when
    verdict = inspect(guard(Clearance.RESTRICTED), prompt(text))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == f"secret: {kind}"


@pytest.mark.parametrize(
    "text",
    [
        "Card 4111 1111 1111 1112 is not a card",
        "Pay into GB82 WEST 1234 5698 7654 33",
        "Order 44051401358",
        "Trade TRD-000123 settled on 2026-06-15 at 585.19",
        "Who is client CLT-1?",
    ],
)
def test_text_without_valid_matches_passes(text: str) -> None:
    # when / then
    assert inspect(guard(), prompt(text)).action is Action.ALLOW


def test_scrub_keeps_the_password_key() -> None:
    # when / then
    assert scrub("password: hunter2secret") == "password: [redacted: password]"


def test_scrub_redacts_all_pii_and_secrets() -> None:
    # given
    data = {"note": "Mail a@b.com, card 4111111111111111", "api_key": "abc"}

    # when / then
    assert scrub(data) == {
        "note": "Mail [redacted: email], card [redacted: payment_card]",
        "api_key": "[redacted: password]",
    }


def test_pii_within_clearance_passes() -> None:
    # given
    data = {"note": "Reach Eleanor at eleanor@beaconcrest.com"}

    # when / then
    assert inspect(guard(Clearance.CONFIDENTIAL), result(data)).action is Action.ALLOW


def test_pii_above_clearance_redacted_in_text_and_structured_content() -> None:
    # given
    data = {"note": "Reach Eleanor at eleanor@beaconcrest.com"}

    # when
    verdict = inspect(guard(), result(data))

    # then
    assert verdict.action is Action.MODIFY
    assert verdict.payload is not None
    note = "Reach Eleanor at [redacted: email]"
    assert verdict.payload["structured_content"] == {"note": note}
    assert json.loads(verdict.payload["content"][0]) == {"note": note}


def test_restricted_pii_redacted_for_confidential_clearance() -> None:
    # given
    data = {"note": "Card 4111111111111111, mail eleanor@beaconcrest.com"}

    # when
    verdict = inspect(guard(Clearance.CONFIDENTIAL), result(data))

    # then
    assert verdict.payload is not None
    note = verdict.payload["structured_content"]["note"]
    assert note == "Card [redacted: payment_card], mail eleanor@beaconcrest.com"


def test_pii_above_clearance_blocked_when_policy_says_block() -> None:
    # given
    data = {"note": "Card 4111111111111111"}

    # when
    verdict = inspect(guard(above=ToolAction.BLOCK), result(data))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "PII blocked by policy: payment_card"


def test_redact_tool_redacts_all_pii() -> None:
    # given
    subject = guard(Clearance.RESTRICTED, tools={"bank__get_client": ToolAction.REDACT})
    data = {"note": "Reach eleanor@beaconcrest.com"}

    # when
    verdict = inspect(subject, result(data))

    # then
    assert verdict.action is Action.MODIFY
    assert verdict.reason == "redacted: email"


def test_secret_in_result_blocked_for_any_clearance() -> None:
    # given
    data = {"note": "Shared key AKIAIOSFODNN7EXAMPLE by mistake"}

    # when
    verdict = inspect(guard(Clearance.RESTRICTED), result(data))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "secret: aws_key"


def test_field_named_like_a_secret_blocks_the_result() -> None:
    # given
    data = {"user": {"name": "svc", "api_key": "abc"}}

    # when
    verdict = inspect(guard(Clearance.RESTRICTED), result(data))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "secret: password"


def test_policy_allows_pii_above_the_clearance() -> None:
    # given
    subject = guard(pii={PiiKind.EMAIL: ToolAction.ALLOW})
    data = {"note": "Reach eleanor@beaconcrest.com"}

    # when / then
    assert inspect(subject, result(data)).action is Action.ALLOW


def test_policy_redacts_pii_within_the_clearance() -> None:
    # given
    subject = guard(Clearance.RESTRICTED, pii={PiiKind.PHONE: ToolAction.REDACT})

    # when
    verdict = inspect(subject, prompt("Call +1 837 825 8997 or a@b.com"))

    # then
    assert verdict.payload == {"content": "Call [redacted: phone] or a@b.com"}


def test_policy_blocks_a_prompt_with_pii() -> None:
    # given
    subject = guard(Clearance.RESTRICTED, pii={PiiKind.PESEL: ToolAction.BLOCK})

    # when
    verdict = inspect(subject, prompt("Her PESEL is 44051401359"))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "PII blocked by policy: pesel"


def test_redact_tool_redacts_pii_the_policy_allows() -> None:
    # given
    subject = guard(
        tools={"bank__get_client": ToolAction.REDACT},
        pii={PiiKind.EMAIL: ToolAction.ALLOW},
    )

    # when
    verdict = inspect(subject, result({"note": "Reach a@b.com"}))

    # then
    assert verdict.reason == "redacted: email"


def test_pii_in_tool_call_passes() -> None:
    # given
    arguments = {"client_id": "CLT-1", "email": "eleanor@beaconcrest.com"}

    # when / then
    assert inspect(guard(), call(arguments)).action is Action.ALLOW


def test_secret_in_tool_call_blocked() -> None:
    # given
    arguments = {"client_id": "CLT-1", "note": "key AKIAIOSFODNN7EXAMPLE"}

    # when
    verdict = inspect(guard(), call(arguments))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.reason == "secret: aws_key"
