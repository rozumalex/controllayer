import asyncio

from app.api.deps import control_layer
from app.control.adapters.mcp_gateway import McpGateway
from app.control.adapters.openai_chat import ChatControl
from app.control.agent import Agent
from app.control.audit import EventSink, UserEventSink
from app.control.envelope import Action, Direction, Envelope
from app.control.guards.loop import LoopGuard, call_of
from app.db.event_sink import DatabaseEventSink
from app.db.models import User
from app.db.policy import recent_tool_calls
from app.db.session import SessionLocal
from tests.test_agent import QUESTION, ToolUsingUpstream
from tests.test_mcp_gateway import Upstream, calls, connect, text


def call(client_id: str = "CLT-1") -> Envelope:
    return Envelope(
        Direction.INBOUND, "a", "bank", "get_client", {"client_id": client_id}
    )


def check(guard: LoopGuard, envelopes: list[Envelope]) -> list[Action]:
    async def run() -> list[Action]:
        return [(await guard.inspect(e)).action for e in envelopes]

    return asyncio.run(run())


def gateway(guard: LoopGuard, sink: EventSink | None = None) -> McpGateway:
    async def servers() -> list[Upstream]:
        return [Upstream("bank")]

    return McpGateway(control_layer(sink, inbound=[guard]), connect, servers)


def test_same_call_blocked_past_the_repeat_limit() -> None:
    # given
    guard = LoopGuard(repeats=2, calls=0)

    # when
    actions = check(guard, [call(), call(), call()])

    # then
    assert actions == [Action.ALLOW, Action.ALLOW, Action.BLOCK]


def test_different_arguments_are_different_calls() -> None:
    # given
    guard = LoopGuard(repeats=1, calls=0)

    # when
    actions = check(guard, [call("CLT-1"), call("CLT-2"), call("CLT-3")])

    # then
    assert actions == [Action.ALLOW] * 3


def test_too_many_calls_blocked_even_when_they_differ() -> None:
    # given
    guard = LoopGuard(repeats=0, calls=3)

    # when
    actions = check(guard, [call(f"CLT-{i}") for i in range(4)])

    # then
    assert actions == [Action.ALLOW] * 3 + [Action.BLOCK]


def test_calls_from_earlier_requests_count() -> None:
    # given
    guard = LoopGuard(repeats=2, calls=0, recent=[call_of(call())] * 2)

    # when / then
    assert check(guard, [call()]) == [Action.BLOCK]


def test_zero_turns_the_limits_off() -> None:
    # given
    guard = LoopGuard(repeats=0, calls=0)

    # when
    actions = check(guard, [call()] * 50)

    # then
    assert set(actions) == {Action.ALLOW}


def test_reason_holds_no_arguments() -> None:
    # given
    guard = LoopGuard(repeats=1, calls=0)
    check(guard, [call("CLT-SECRET")])

    # when
    verdict = asyncio.run(guard.inspect(call("CLT-SECRET")))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.guard == "loop"
    assert "CLT-SECRET" not in verdict.reason


def test_gateway_blocks_the_repeated_call_before_the_server() -> None:
    # given
    subject = gateway(LoopGuard(repeats=2, calls=10))
    calls.clear()

    async def run() -> list[bool]:
        results = [
            await subject.call_tool("bank__get_client", {"client_id": c}, "a")
            for c in ["CLT-1", "CLT-2", "CLT-1", "CLT-1"]
        ]
        return [bool(r.is_error) and "blocked" in text(r) for r in results]

    # when
    blocked = asyncio.run(run())

    # then
    assert blocked == [False, False, False, True]
    assert calls == [{"client_id": c} for c in ["CLT-1", "CLT-2", "CLT-1"]]
    assert subject.looping


def test_loop_spans_requests_through_the_database(no_events: None, user: User) -> None:
    # given
    sink = UserEventSink(DatabaseEventSink(), user.id)
    first = gateway(LoopGuard(repeats=2, calls=0), sink)
    for _ in range(2):
        asyncio.run(first.call_tool("bank__get_client", {"client_id": "C1"}, "a"))

    async def recent() -> list[tuple[str, str, str]]:
        async with SessionLocal() as session:
            return await recent_tool_calls(session, user.id, 60)

    # when
    second = gateway(LoopGuard(repeats=2, calls=0, recent=asyncio.run(recent())))
    result = asyncio.run(second.call_tool("bank__get_client", {"client_id": "C1"}, "a"))

    # then
    assert result.is_error is True
    assert "blocked" in text(result)


def test_agent_stops_asking_for_tools_after_a_loop() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "C1"}, always=True)
    subject = gateway(LoopGuard(repeats=1, calls=0))
    control = ChatControl(control_layer(), upstream, False, check_tools=False)
    agent = Agent(control, subject)

    # when
    asyncio.run(agent.complete(QUESTION, "trace"))

    # then
    assert "tool_choice" not in upstream.requests[1]
    assert upstream.requests[2]["tool_choice"] == "none"
