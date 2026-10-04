import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.server.mcpserver import MCPServer

from app.api.deps import control_layer, sensitive_data
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.control.adapters.openai_chat import ChatControl
from app.control.agent import Agent
from app.control.envelope import Direction
from app.control.guards.policy import ClearanceGuard, ToolAccessGuard
from app.control.guards.prompt_injection import PromptInjectionGuard
from app.control.upstream import MockUpstream
from app.core.schema.policy import Budget, Clearance, PolicySettings, ToolAction
from app.db.models import Policy, User
from app.db.policy import DEFAULT_ROLE, builtin_policy
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id, signed_in
from tests.test_agent import QUESTION, ListSink, ToolUsingUpstream
from tests.test_chat import ask, blocked
from tests.test_mcp_gateway import Upstream, text

URL = "/api/v1/chat/completions"

crm = MCPServer("crm")
calls: list[str] = []


@crm.tool()
def get_client(client_id: str) -> dict[str, Any]:
    """A client row, with a confidential field."""
    calls.append(client_id)
    return {"client": {"client_id": client_id, "risk_rating": "HIGH"}}


@crm.tool()
def delete_client(client_id: str) -> str:
    """A tool the policy blocks."""
    calls.append(client_id)
    return "deleted"


@asynccontextmanager
async def connect(server: UpstreamServer) -> AsyncIterator[Client]:
    async with Client(crm) as client:
        yield client


def policy(**changes: Any) -> PolicySettings:
    return builtin_policy().model_copy(update=changes)


async def save(role: str, settings: PolicySettings) -> None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        values = settings.model_dump(mode="json")
        session.add(Policy(org_id=org_id, role=role, settings=values))
        await session.commit()


async def add_analyst() -> User:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        user = User(
            email="ann@goldensocks.com", name="Ann Lee", title="Analyst", org_id=org_id
        )
        session.add(user)
        await session.commit()
        return user


@pytest.fixture
def analyst(db: None) -> Iterator[TestClient]:
    user = asyncio.run(add_analyst())
    with TestClient(app, headers=signed_in(user)) as client:
        yield client


def gateway(settings: PolicySettings) -> McpGateway:
    catalog = {
        ("clients", "client_id"): Clearance.PUBLIC,
        ("clients", "risk_rating"): Clearance.CONFIDENTIAL,
    }
    tools = ToolAccessGuard(settings.tools, settings.default_tool_action)
    clearance = ClearanceGuard(
        catalog,
        settings.clearance,
        settings.above_clearance,
        settings.tools,
        settings.default_tool_action,
    )
    layer = control_layer(policy=settings, inbound=[tools], outbound=[clearance])

    async def servers() -> list[Upstream]:
        return [Upstream("crm")]

    return McpGateway(layer, connect, servers)


def test_chat_blocked_when_policy_allows_no_model(db: None, user: User) -> None:
    # given
    asyncio.run(save(DEFAULT_ROLE, policy(allowed_models=[])))

    # when
    with TestClient(app, headers=signed_in(user)) as client:
        data = client.post(URL, json=ask("What is 2 + 2?")).json()

    # then
    assert blocked(data) is True


def test_chat_blocked_once_the_weekly_budget_is_spent(db: None, user: User) -> None:
    # given
    budget = Budget(weekly_usd=Decimal(0))
    asyncio.run(save(DEFAULT_ROLE, policy(budget=budget)))
    request = ask("What is 2 + 2?")

    # when
    with TestClient(app, headers=signed_in(user)) as client:
        data = client.post(URL, json=request).json()

    # then
    assert blocked(data) is True


def test_role_policy_applies_over_the_default(analyst: TestClient) -> None:
    # given
    asyncio.run(save("Analyst", policy(allowed_models=[])))

    # when
    data = analyst.post(URL, json=ask("What is 2 + 2?")).json()

    # then
    assert blocked(data) is True


def test_policy_sets_the_injection_threshold() -> None:
    # given
    settings = policy(injection_threshold=0.35)

    # when
    layer = control_layer(policy=settings)

    # then
    [guard] = [
        g
        for g in layer.pipelines[Direction.INBOUND].guards
        if isinstance(g, PromptInjectionGuard)
    ]
    assert guard.threshold == 0.35


def test_gateway_redacts_data_above_clearance() -> None:
    # given
    subject = gateway(policy(clearance=Clearance.INTERNAL))

    # when
    result = asyncio.run(subject.call_tool("crm__get_client", {"client_id": "C1"}, "a"))

    # then
    assert "HIGH" not in text(result)
    assert "[redacted: CONFIDENTIAL]" in text(result)
    assert result.structured_content is not None
    client = result.structured_content["client"]
    assert "HIGH" not in client["risk_rating"]
    assert "C1" in client["client_id"]


def test_gateway_blocks_a_tool_the_policy_blocks() -> None:
    # given
    tools = {"crm__delete_client": ToolAction.BLOCK}
    subject = gateway(policy(tools=tools))
    calls.clear()

    # when
    result = asyncio.run(
        subject.call_tool("crm__delete_client", {"client_id": "C1"}, "a")
    )

    # then
    assert calls == []
    assert result.is_error is True
    assert "blocked" in text(result)


def test_model_never_sees_a_blocked_tool() -> None:
    # given
    settings = policy(tools={"crm__delete_client": ToolAction.BLOCK})
    upstream = ToolUsingUpstream("crm__get_client", {"client_id": "C1"})
    control = ChatControl(control_layer(), upstream, check_tools=False)
    tools = ToolAccessGuard(settings.tools, settings.default_tool_action)
    subject = Agent(control, gateway(settings), allows=tools.allows)

    # when
    asyncio.run(subject.complete(QUESTION, "trace"))

    # then
    names = {t["function"]["name"] for t in upstream.requests[0]["tools"]}
    assert names == {"crm__get_client"}


def test_model_never_sees_pii_from_the_prompt_on_any_step() -> None:
    # given
    settings = policy(clearance=Clearance.INTERNAL)
    upstream = ToolUsingUpstream("crm__get_client", {"client_id": "C1"})
    layer = control_layer(policy=settings, inbound=[sensitive_data(settings)])
    control = ChatControl(layer, upstream, check_tools=False)
    subject = Agent(control, gateway(settings))
    question = [{"role": "user", "content": "Card 4111 1111 1111 1111 for C1?"}]

    # when
    asyncio.run(subject.complete(question, "trace"))

    # then
    prompts = [r["messages"][0]["content"] for r in upstream.requests]
    assert len(prompts) == 2
    assert prompts == ["Card [redacted: payment_card] for C1?"] * 2


@pytest.mark.parametrize(
    "message", ["Mail eleanor@beaconcrest.com", "My key is AKIAIOSFODNN7EXAMPLE"]
)
def test_pii_and_secrets_never_logged(message: str) -> None:
    # given
    settings = policy(clearance=Clearance.INTERNAL)
    sink = ListSink()
    layer = control_layer(sink, settings, inbound=[sensitive_data(settings)])
    control = ChatControl(layer, MockUpstream(delay=0), sink)
    request = {"messages": [{"role": "user", "content": message}]}

    # when
    asyncio.run(control.complete(request, "trace"))

    # then
    logged = json.dumps(sink.events)
    assert "eleanor@" not in logged
    assert "AKIA" not in logged


def test_secret_never_reaches_the_model() -> None:
    # given
    settings = policy(clearance=Clearance.RESTRICTED)
    upstream = ToolUsingUpstream("crm__get_client", {"client_id": "C1"})
    layer = control_layer(policy=settings, inbound=[sensitive_data(settings)])
    control = ChatControl(layer, upstream, check_tools=False)
    question = [{"role": "user", "content": "Use key AKIAIOSFODNN7EXAMPLE"}]

    # when
    response = asyncio.run(Agent(control, gateway(settings)).complete(question, "t"))

    # then
    assert upstream.requests == []
    assert response["choices"][0]["finish_reason"] == "content_filter"
