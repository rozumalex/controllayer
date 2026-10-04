from typing import Any

from fastapi.testclient import TestClient

URL = "/api/conversations"


def turn(question: str, answer: str, blocked: bool = False) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "user", "text": question},
            {"role": "assistant", "text": answer, "blocked": blocked},
        ]
    }


def test_conversation_kept_with_its_messages(db: None, client: TestClient) -> None:
    # given
    started = client.post(URL, json=turn("What is 2 + 2?", "4")).json()
    more = turn("And 3 + 3?", "Blocked.", blocked=True)
    client.post(f"{URL}/{started['id']}/messages", json=more)

    # when
    found = client.get(f"{URL}/{started['id']}").json()

    # then
    assert found["title"] == "What is 2 + 2?"
    assert [m["text"] for m in found["messages"]] == [
        "What is 2 + 2?",
        "4",
        "And 3 + 3?",
        "Blocked.",
    ]
    assert found["messages"][-1]["blocked"] is True


def test_conversations_listed_last_changed_first(db: None, client: TestClient) -> None:
    # given
    first = client.post(URL, json=turn("First", "a")).json()
    second = client.post(URL, json=turn("Second", "b")).json()
    client.post(f"{URL}/{first['id']}/messages", json=turn("Again", "c"))

    # when
    listed = client.get(URL).json()

    # then
    assert [c["id"] for c in listed] == [first["id"], second["id"]]


def test_messages_stored_without_secrets(db: None, client: TestClient) -> None:
    # given
    secret = "AKIAIOSFODNN7EXAMPLE"
    started = client.post(URL, json=turn(f"My key is {secret}", "Blocked.")).json()

    # when
    found = client.get(f"{URL}/{started['id']}").json()

    # then
    assert secret not in str(found)


def test_unknown_conversation_not_found(db: None, client: TestClient) -> None:
    # given
    url = f"{URL}/00000000-0000-0000-0000-000000000000"

    # when / then
    assert client.get(url).status_code == 404
