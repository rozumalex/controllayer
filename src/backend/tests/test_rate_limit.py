import asyncio

import pytest
from fastapi.testclient import TestClient

from app.control.envelope import Action, Direction, Envelope
from app.control.guards.rate_limit import RateLimitGuard
from app.core.config import settings
from tests.test_chat import URL


def prompt() -> Envelope:
    return Envelope(Direction.INBOUND, "a", "llm", "user_prompt", {"content": "Hi"})


@pytest.mark.parametrize(
    ("limit", "recent", "action"),
    [
        (5, 4, Action.ALLOW),
        (5, 5, Action.BLOCK),
        (0, 100, Action.ALLOW),
    ],
)
def test_rate_limit(limit: int, recent: int, action: Action) -> None:
    # given
    guard = RateLimitGuard(limit, recent)

    # when / then
    assert asyncio.run(guard.inspect(prompt())).action is action


def test_chat_blocked_past_the_rate_limit(
    no_events: None, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "control_rate_limit_per_minute", 2)
    request = {"message": "What is 2 + 2?"}

    # when
    replies = [client.post(URL, json=request).json() for _ in range(3)]

    # then
    assert [r["blocked"] for r in replies] == [False, False, True]
