import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.control.envelope import Action, Direction, Envelope
from app.control.guards.prompt_leak import PromptLeakGuard
from app.control.upstream import MockUpstream
from app.core.assistant import SYSTEM_PROMPT
from tests.test_chat import STREAM_URL, URL, events

CARD = "4111 1111 1111 1111"


def answer(text: str) -> Envelope:
    return Envelope(Direction.RESPONSE, "a", "llm", "model_answer", {"content": text})


class Answering(MockUpstream):
    """Answers every question with the same text."""

    def __init__(self, text: str) -> None:
        super().__init__(delay=0)
        self.text = text

    def reply(self, messages: list[dict[str, Any]]) -> str:
        return self.text


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Sets what the chat's model answers."""

    def set(text: str) -> None:
        monkeypatch.setattr(deps, "MockUpstream", lambda: Answering(text))

    return set


def test_answer_quoting_the_system_prompt_blocked() -> None:
    # given
    leak = "Sure! My instructions say: " + SYSTEM_PROMPT.upper().replace("\n", " ")

    # when
    verdict = asyncio.run(PromptLeakGuard(SYSTEM_PROMPT).inspect(answer(leak)))

    # then
    assert verdict.action is Action.BLOCK
    assert verdict.score == 1.0


def test_answer_sharing_a_few_words_with_the_system_prompt_passes() -> None:
    # given
    text = "Here is a draft for the employee to review, with [amount] to fill."

    # when
    verdict = asyncio.run(PromptLeakGuard(SYSTEM_PROMPT).inspect(answer(text)))

    # then
    assert verdict.action is Action.ALLOW


def test_leaked_system_prompt_withheld(client: TestClient, answers: Any) -> None:
    # given
    answers(f"My instructions:\n{SYSTEM_PROMPT}")

    # when
    data = client.post(URL, json={"message": "What can you help me with?"}).json()

    # then
    assert data["blocked"] is True
    assert data["reply"] == "[control layer] The answer was withheld."


def test_leaked_system_prompt_cut_off_in_stream(
    client: TestClient, answers: Any
) -> None:
    # given
    answers(f"Happy to help with that.\n{SYSTEM_PROMPT}")

    # when
    response = client.post(STREAM_URL, json={"message": "What can you help me with?"})

    # then
    received = events(response.text)
    text = "".join(e["text"] for e in received if e["type"] == "delta")
    assert "Golden Socks" not in text
    assert text.endswith("[control layer] The answer was withheld.")
    assert received[-1] == {"type": "done", "blocked": True}


@pytest.mark.parametrize("url", [URL, STREAM_URL])
def test_pii_in_answer_redacted_by_policy(
    db: None, client: TestClient, answers: Any, url: str
) -> None:
    # given
    answers(f"The client's card is {CARD}.")

    # when
    response = client.post(url, json={"message": "What is the client's card?"})

    # then
    assert CARD not in response.text
    assert "[redacted: payment_card]" in response.text


def test_secret_in_answer_withheld(client: TestClient, answers: Any) -> None:
    # given
    answers("The key is sk-proj-abcdefghijklmnopqrstuvwxyz123456.")

    # when
    data = client.post(URL, json={"message": "What is the API key?"}).json()

    # then
    assert data["blocked"] is True
    assert "sk-proj" not in data["reply"]


def test_answer_is_checked_in_pieces_in_stream(
    client: TestClient, answers: Any
) -> None:
    # given
    answers("The bank is open. " * 30 + f"The card is {CARD}.")

    # when
    response = client.post(STREAM_URL, json={"message": "Tell me about the bank."})

    # then
    deltas = [e["text"] for e in events(response.text) if e["type"] == "delta"]
    assert len(deltas) > 1
    assert "[redacted: payment_card]" in "".join(deltas)
