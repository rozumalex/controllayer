import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.server.mcpserver import MCPServer

from app.api.deps import control_layer
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.control.adapters.openai_chat import ChatControl
from app.control.agent import Agent
from app.control.envelope import Direction
from app.control.guards.policy import ClearanceGuard, ToolAccessGuard
from app.control.guards.prompt_injection import PromptInjectionGuard
from app.core.schema.policy import Budget, Clearance, PolicySettings, ToolAction
from app.db.models import Policy, User
from app.db.policy import DEFAULT_ROLE, builtin_policy
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import signed_in
from tests.test_agent import QUESTION, ToolUsingUpstream
from tests.test_mcp_gateway import Upstream, text

URL = "/api/chat"

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
    async with SessionLocal() as session:
        session.add(Policy(role=role, settings=settings.model_dump(mode="json")))
        await session.commit()


async def add_analyst() -> User:
    async with SessionLocal() as session:
        user = User(email="ann@goldensocks.com", name="Ann Lee", title="Analyst")
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
        data = client.post(URL, json={"message": "What is 2 + 2?"}).json()

    # then
    assert data["blocked"] is True


def test_chat_blocked_once_monthly_tokens_are_used(db: None, user: User) -> None:
    # given
    asyncio.run(save(DEFAULT_ROLE, policy(budget=Budget(monthly_tokens=1))))
    request = {"message": "What is 2 + 2?"}

    # when
    with TestClient(app, headers=signed_in(user)) as client:
        first = client.post(URL, json=request).json()
        second = client.post(URL, json=request).json()

    # then
    assert first["blocked"] is False
    assert second["blocked"] is True


def test_role_policy_applies_over_the_default(analyst: TestClient) -> None:
    # given
    asyncio.run(save("Analyst", policy(allowed_models=[])))

    # when
    data = analyst.post(URL, json={"message": "What is 2 + 2?"}).json()

    # then
    assert data["blocked"] is True


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
    control = ChatControl(control_layer(), upstream, False, check_tools=False)
    tools = ToolAccessGuard(settings.tools, settings.default_tool_action)
    subject = Agent(control, gateway(settings), allows=tools.allows)

    # when
    asyncio.run(subject.complete(QUESTION, "trace"))

    # then
    names = {t["function"]["name"] for t in upstream.requests[0]["tools"]}
    assert names == {"crm__get_client"}
