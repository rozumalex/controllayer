from decimal import Decimal

import pytest

from app.api.deps import chat_model, chat_upstream, semantic_guard
from app.control.guards.semantic_injection import OpenAIInjectionClassifier
from app.control.upstream import MockUpstream, OpenAIUpstream
from app.core.config import Endpoint, settings
from app.core.schema.policy import PolicySettings
from app.db.policy import builtin_policy, price

OLLAMA = "http://ollama:11434/v1"


def policy(*models: str) -> PolicySettings:
    return builtin_policy().model_copy(update={"allowed_models": list(models)})


@pytest.fixture
def openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ollama_url", OLLAMA)


def test_openai_model_is_off_without_a_key() -> None:
    # when / then
    assert settings.endpoint("gpt-4.1-mini") is None


@pytest.mark.usefixtures("openai")
def test_openai_model_is_served_with_a_key() -> None:
    # when / then
    assert settings.endpoint("gpt-4.1-mini") == Endpoint(
        settings.openai_url, "sk-test", "max_completion_tokens"
    )


@pytest.mark.usefixtures("ollama")
def test_local_model_is_served_with_an_ollama_url() -> None:
    # when / then
    assert settings.endpoint("qwen2.5:7b") == Endpoint(OLLAMA, "ollama", "max_tokens")


@pytest.mark.usefixtures("openai", "ollama")
def test_model_outside_the_pool_is_never_served() -> None:
    # when / then
    assert settings.endpoint("llama-unknown") is None


@pytest.mark.usefixtures("openai", "ollama")
def test_chat_prefers_the_first_chat_model() -> None:
    # when / then
    assert chat_model(policy("qwen2.5:7b", "gpt-4.1-mini")) == "gpt-4.1-mini"


@pytest.mark.usefixtures("ollama")
def test_chat_falls_back_to_a_local_model_without_openai() -> None:
    # when / then
    assert chat_model(policy("qwen2.5:7b", "gpt-4.1-mini")) == "qwen2.5:7b"


@pytest.mark.usefixtures("ollama")
def test_chat_keeps_to_the_models_the_policy_allows() -> None:
    # when / then
    assert chat_model(policy("gpt-4.1")) == "gpt-4.1"


@pytest.mark.usefixtures("ollama")
def test_chat_reaches_ollama_for_a_local_model() -> None:
    # when
    upstream = chat_upstream("qwen2.5:7b")

    # then
    assert isinstance(upstream, OpenAIUpstream)
    assert upstream.url == f"{OLLAMA}/chat/completions"
    # Ollama ignores max_completion_tokens, so the cap goes in max_tokens.
    request = upstream.limit({"messages": []})
    assert request["max_tokens"] == settings.chat_max_tokens
    assert "max_completion_tokens" not in request


def test_chat_uses_the_mock_model_when_no_provider_serves_it() -> None:
    # when / then
    assert isinstance(chat_upstream("gpt-4.1-mini"), MockUpstream)


def test_semantic_guard_is_off_when_no_model_is_served() -> None:
    # when / then
    assert semantic_guard(0.7) is None


@pytest.mark.usefixtures("ollama")
def test_semantic_guard_runs_on_a_local_model_without_openai() -> None:
    # when
    guard = semantic_guard(0.7)

    # then
    assert guard is not None
    assert guard.model == "qwen2.5:7b"
    assert isinstance(guard.classifier, OpenAIInjectionClassifier)
    assert guard.classifier.url == f"{OLLAMA}/chat/completions"


def test_local_model_counts_toward_the_budget() -> None:
    # when / then
    assert price("qwen2.5:7b") == (Decimal("0.05"), Decimal("0.05"))


def test_dated_openai_name_takes_the_price_of_its_model() -> None:
    # when / then
    assert price("gpt-4.1-mini-2025-04-14") == (Decimal("0.40"), Decimal("1.60"))
