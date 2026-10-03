import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import mcp_gateway
from app.core.config import settings
from app.core.policy_assistant import Edit, policy_drafter
from app.db.models import ControlEvent, Policy, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import signed_in
from tests.test_mcp_gateway import gateway
from tests.test_policy import add_staff, roles

URL = "/api/policy/assistant"
RULE = "Analysts can't read notes and must see IBANs masked, ref 7f3a9c"


class FakeDrafter:
    """Stands in for the model: answers with the given edits."""

    def __init__(self, edits: list[Edit]) -> None:
        self.edits = edits
        self.instructions: list[str] = []

    async def draft(self, context: str, instruction: str) -> list[Edit]:
        self.instructions.append(instruction)
        return self.edits


@pytest.fixture
def staff(db: None, user: User) -> Iterator[TestClient]:
    asyncio.run(add_staff())
    app.dependency_overrides[mcp_gateway] = lambda: gateway("bank")
    with TestClient(app, headers=signed_in(user)) as client:
        yield client
    app.dependency_overrides.clear()


def model(*edits: Edit) -> FakeDrafter:
    drafter = FakeDrafter(list(edits))
    app.dependency_overrides[policy_drafter] = lambda: drafter
    return drafter


async def saved_policies() -> list[Policy]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(Policy)))


async def event_data() -> str:
    async with SessionLocal() as session:
        events = await session.scalars(select(ControlEvent))
        return json.dumps([e.data for e in events], default=str)


def propose(client: TestClient) -> dict[str, Any]:
    response = client.post(URL, json={"instruction": RULE})
    assert response.status_code == 200
    return response.json()


def test_proposal_shows_the_changes_and_saves_nothing(staff: TestClient) -> None:
    # given
    model(
        Edit("Analyst", "tool", "bank__get_note", "block"),
        Edit("Analyst", "pii", "iban", "redact"),
        Edit("Analyst", "injection_threshold", "", "0.5"),
    )

    # when
    proposal = propose(staff)

    # then
    assert proposal["dropped"] == []
    assert [r["role"] for r in proposal["roles"]] == ["Analyst"]
    assert proposal["roles"][0]["changes"] == [
        {
            "setting": "injection_threshold",
            "before": str(settings.control_injection_threshold),
            "after": "0.5",
        },
        {
            "setting": "tools.bank__get_note",
            "before": "default (allow)",
            "after": "block",
        },
        {"setting": "pii.iban", "before": "by clearance", "after": "redact"},
    ]
    assert asyncio.run(saved_policies()) == []


def test_unknown_names_are_dropped_and_reported(staff: TestClient) -> None:
    # given
    model(
        Edit("Intern", "clearance", "", "PUBLIC"),
        Edit("Analyst", "tool", "bank__wire_everything", "block"),
        Edit("Analyst", "pii", "dna", "block"),
        Edit("Analyst", "allow_model", "gpt-9", ""),
        Edit("Analyst", "clearance", "", "TOP_SECRET"),
        Edit("*", "default_tool_action", "", "redact"),
    )

    # when
    proposal = propose(staff)

    # then
    assert proposal["dropped"] == [
        "Unknown role Intern",
        "Unknown tool bank__wire_everything",
        "Unknown PII kind dna",
        "Unknown model gpt-9",
        "Invalid value for clearance of Analyst",
    ]
    assert [r["role"] for r in proposal["roles"]] == ["*"]


def test_applying_saves_the_proposal(staff: TestClient, user: User) -> None:
    # given
    model(Edit("Analyst", "tool", "bank__get_note", "block"))
    proposal = propose(staff)

    # when
    response = staff.post(f"{URL}/apply", json={"roles": proposal["roles"]})

    # then
    assert response.status_code == 204
    analyst = roles(staff.get("/api/policy").json())["Analyst"]
    assert analyst["customized"] is True
    assert analyst["settings"]["tools"] == {"bank__get_note": "block"}
    [saved] = asyncio.run(saved_policies())
    assert saved.updated_by_id == user.id


def test_a_stale_proposal_is_not_applied(staff: TestClient) -> None:
    # given
    model(Edit("Analyst", "tool", "bank__get_note", "block"))
    proposal = propose(staff)
    staff.put("/api/policy/roles/Analyst", json=proposal["roles"][0]["after"])

    # when
    response = staff.post(f"{URL}/apply", json={"roles": proposal["roles"]})

    # then
    assert response.status_code == 409


def test_only_admins_use_the_assistant(staff: TestClient) -> None:
    # given
    model()
    ann = asyncio.run(staff_member("ann@goldensocks.com"))

    # when
    response = staff.post(URL, json={"instruction": RULE}, headers=signed_in(ann))

    # then
    assert response.status_code == 403


async def staff_member(email: str) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


def test_without_a_model_the_assistant_is_unavailable(staff: TestClient) -> None:
    # when
    response = staff.post(URL, json={"instruction": RULE})

    # then
    assert response.status_code == 503
    assert "No model" in response.json()["detail"]


def test_the_rule_reaches_no_event_or_log(
    staff: TestClient, no_events: None, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    caplog.set_level(logging.DEBUG)
    drafter = model(Edit("Analyst", "pii", "iban", "redact"), Edit("x", "pii", "", ""))

    # when
    proposal = propose(staff)
    staff.post(f"{URL}/apply", json={"roles": proposal["roles"]})

    # then
    assert drafter.instructions == [RULE]
    assert "7f3a9c" not in caplog.text
    assert "7f3a9c" not in asyncio.run(event_data())
    assert "7f3a9c" not in json.dumps(proposal)
