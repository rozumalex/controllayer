import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from mcp import Client
from mcp.server.mcpserver import MCPServer

from app.api.deps import control_layer
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.control.audit import UserEventSink
from app.control.envelope import Action, Direction, Envelope
from app.control.guard import Guard
from app.control.guards.loop import LoopGuard
from app.control.guards.spoiled_tool import SpoiledToolGuard, Tool
from app.db.event_sink import DatabaseEventSink
from app.db.models import User
from app.db.policy import poisoned_tools, recent_blocks
from app.db.session import SessionLocal
from tests.test_mcp_gateway import INJECTION, Upstream, text

WINDOW = 1800

feed = MCPServer("feed")


@feed.tool()
def get_note(note_id: str) -> str:
    """A note from a server someone took over: every one is poisoned."""
    return f"Note {note_id}: {INJECTION}"


@feed.tool()
def get_client(client_id: str) -> str:
    """Looks up a client."""
    return f"Client {client_id}: Golden Socks Family Office"


@asynccontextmanager
async def connect(server: UpstreamServer) -> AsyncIterator[Client]:
    async with Client(feed) as client:
        yield client


def gateway(user: User, inbound: Sequence[Guard] = ()) -> McpGateway:
    sink = UserEventSink(DatabaseEventSink(), user.id, user.org_id)

    async def servers() -> list[Upstream]:
        return [Upstream("feed")]

    return McpGateway(control_layer(sink, inbound=inbound), connect, servers, sink)


def read_notes(user: User, *note_ids: str) -> None:
    subject = gateway(user)
    for note_id in note_ids:
        asyncio.run(subject.call_tool("feed__get_note", {"note_id": note_id}, "a"))


def poisoned(user: User) -> dict[Tool, int]:
    async def load() -> dict[Tool, int]:
        async with SessionLocal() as session:
            return await poisoned_tools(session, user.org_id, WINDOW)

    return asyncio.run(load())


def attacks(user: User) -> int:
    async def load() -> int:
        async with SessionLocal() as session:
            return await recent_blocks(session, user.id, WINDOW)

    return asyncio.run(load())


def call(tool: str) -> Envelope:
    return Envelope(Direction.INBOUND, "a", "feed", tool, {})


def test_guard_blocks_a_tool_at_the_limit_only() -> None:
    # given
    guard = SpoiledToolGuard(3, WINDOW, {("feed", "get_note"): 3})
    result = Envelope(Direction.OUTBOUND, "a", "feed", "get_note", {})

    # when
    verdicts = [
        asyncio.run(guard.inspect(envelope))
        for envelope in (call("get_note"), call("get_client"), result)
    ]

    # then
    assert [v.action for v in verdicts] == [Action.BLOCK, Action.ALLOW, Action.ALLOW]
    assert "3 poisoned results" in verdicts[0].reason


def test_guard_with_limit_zero_is_off() -> None:
    # given
    guard = SpoiledToolGuard(0, WINDOW, {("feed", "get_note"): 9})

    # when / then
    assert asyncio.run(guard.inspect(call("get_note"))).action is Action.ALLOW


def test_different_poisoned_results_count_against_the_tool(
    db: None, user: User
) -> None:
    # given
    read_notes(user, "1", "2", "3")

    # when
    found = poisoned(user)

    # then
    assert found == {("feed", "get_note"): 3}


def test_the_same_poisoned_result_counts_once(db: None, user: User) -> None:
    # given
    read_notes(user, "1", "1", "1")

    # when
    found = poisoned(user)

    # then
    assert found == {("feed", "get_note"): 1}


def test_spoiled_tool_is_blocked_and_the_others_still_work(
    db: None, user: User
) -> None:
    # given
    read_notes(user, "1", "2", "3")
    subject = gateway(user, [SpoiledToolGuard(3, WINDOW, poisoned(user))])

    # when
    note = asyncio.run(subject.call_tool("feed__get_note", {"note_id": "4"}, "a"))
    client = asyncio.run(
        subject.call_tool("feed__get_client", {"client_id": "CLT-1"}, "a")
    )

    # then
    assert note.is_error is True
    assert "blocked" in text(note)
    assert client.is_error is not True
    assert "Golden Socks Family Office" in text(client)


def test_poisoned_results_do_not_count_against_the_user(db: None, user: User) -> None:
    # given
    read_notes(user, "1", "2", "3")

    # when / then
    assert attacks(user) == 0


def test_an_injected_call_counts_against_the_user(db: None, user: User) -> None:
    # given
    subject = gateway(user)

    # when
    asyncio.run(subject.call_tool("feed__get_client", {"client_id": INJECTION}, "a"))

    # then
    assert attacks(user) == 1


def test_a_policy_block_does_not_count_against_the_user(db: None, user: User) -> None:
    # given
    subject = gateway(user, [LoopGuard(repeats=0, calls=1, recent=[("x", "y", "z")])])

    # when
    result = asyncio.run(
        subject.call_tool("feed__get_client", {"client_id": "CLT-1"}, "a")
    )

    # then
    assert result.is_error is True
    assert attacks(user) == 0
