from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.control.pipeline import Mode


class Provider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class PoolModel(BaseModel):
    provider: Provider
    # US dollars per million prompt and completion tokens, for the budgets.
    price: tuple[Decimal, Decimal] = (Decimal(0), Decimal(0))


class Endpoint(NamedTuple):
    """A provider's OpenAI-compatible API: its base URL, its key, and the
    field it caps an answer's tokens with."""

    url: str
    key: str
    max_tokens_field: str


def pool_model(provider: Provider, prompt: str, completion: str) -> PoolModel:
    return PoolModel(provider=provider, price=(Decimal(prompt), Decimal(completion)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Every route lives under this prefix, so the frontend proxy and a load
    # balancer can send /api/* to the backend without rewriting the path.
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    # Celery sends the tasks through this Redis.
    redis_url: str = "redis://localhost:6379/0"
    # Sentry is off while the DSN is empty.
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 1.0
    # The control layer blocks in "enforce" mode and only logs in "monitor".
    control_mode: Mode = Mode.ENFORCE
    control_injection_threshold: float = 0.7
    # Log message contents at each stage of a chat completion. Prompts and
    # tool results may hold secrets, so turn it on only for a demo.
    control_log_payloads: bool = False
    # OpenAI serves the pool's OpenAI models. Without a key, they are off.
    openai_api_key: str = ""
    openai_url: str = "https://api.openai.com/v1"
    # An Ollama server, or any other OpenAI-compatible API, serves the pool's
    # local models. Empty turns them off.
    ollama_url: str = ""
    # The model pool: every LLM a policy may allow, by the name its provider
    # knows it by. A local model has an estimated price for the compute it
    # uses, so the budgets count it too.
    models: dict[str, PoolModel] = {
        "gpt-4.1-mini": pool_model(Provider.OPENAI, "0.40", "1.60"),
        "gpt-4.1": pool_model(Provider.OPENAI, "2.00", "8.00"),
        "gpt-4o-mini": pool_model(Provider.OPENAI, "0.15", "0.60"),
        "o4-mini": pool_model(Provider.OPENAI, "1.10", "4.40"),
        "qwen2.5:7b": pool_model(Provider.OLLAMA, "0.05", "0.05"),
    }
    # The chat uses the first of these models that the user's policy allows
    # and a provider serves, so without OpenAI it falls back to a local model.
    # With none served, a mock model echoes what it receives, so the demo runs
    # offline. The default policy allows these models.
    chat_models: list[str] = ["gpt-4.1-mini", "qwen2.5:7b"]
    # The most tokens the model may write in one answer, reasoning included,
    # so one prompt can't run up the bill.
    chat_max_tokens: int = 4096
    # Chat questions per user per minute; 0 turns the limit off.
    control_rate_limit_per_minute: int = 20
    # Runaway agent loops: in any window of this many seconds, a user's agent
    # may make the same tool call (same tool, same arguments) at most the
    # repeat limit times, and at most the call limit tool calls of any kind.
    # 0 turns a limit off.
    control_loop_window_seconds: int = 60
    control_loop_repeat_limit: int = 3
    control_loop_call_limit: int = 30
    # The semantic injection guard asks the first of these models that a
    # provider serves whether a message is an attack; with none served, it
    # is off. It needs a model that takes temperature and structured outputs,
    # so not a reasoning model.
    control_semantic_models: list[str] = ["gpt-4.1-mini", "qwen2.5:7b"]
    control_semantic_timeout: float = 10.0
    # Block when the semantic check fails, for example when OpenAI is down.
    # Turn it off to fall back to the heuristic guard alone.
    control_semantic_fail_closed: bool = True
    # The attack signatures: a JSON file path or an http(s) URL. Empty means
    # the feed that comes with the app, app/control/signatures.json. A file
    # is read again when it changes, a URL every refresh seconds.
    control_signature_feed: str = ""
    control_signature_refresh: float = 30.0
    # A signature at or above this severity blocks; a lower one is logged.
    control_signature_threshold: float = 0.7
    # The data flow guard remembers what a user's tool results carried for
    # this many minutes, across requests. It keeps keyed hashes, not values;
    # set the key so every API process makes the same ones.
    control_flow_window_minutes: int = 30
    control_flow_hash_key: str = ""
    # The bearer token of the example bank MCP server at /api/bank/mcp. While
    # it is empty, the server refuses every request.
    bank_mcp_token: str = ""

    @field_validator("database_url")
    @classmethod
    def use_asyncpg(cls, value: str) -> str:
        """Turn a plain postgresql:// URL, as hosts such as DigitalOcean give
        it, into one for the asyncpg driver."""
        url = make_url(value)
        if url.drivername in ("postgres", "postgresql"):
            url = url.set(drivername="postgresql+asyncpg")
        # asyncpg takes ssl=require instead of libpq's sslmode=require.
        query = dict(url.query)
        if "sslmode" in query:
            query["ssl"] = query.pop("sslmode")
            url = url.set(query=query)
        return url.render_as_string(hide_password=False)

    @field_validator("redis_url")
    @classmethod
    def require_tls_certificate(cls, value: str) -> str:
        """Celery refuses a rediss:// URL without ssl_cert_reqs, and hosts
        such as DigitalOcean give it without one."""
        if value.startswith("rediss://") and "ssl_cert_reqs=" not in value:
            separator = "&" if "?" in value else "?"
            value = f"{value}{separator}ssl_cert_reqs=required"
        return value

    def endpoint(self, model: str) -> Endpoint | None:
        """Where the provider that serves the model takes requests, or None
        when the model isn't in the pool or its provider is off."""
        entry = self.models.get(model)
        if entry is None:
            return None
        if entry.provider is Provider.OPENAI:
            if not self.openai_api_key:
                return None
            # Reasoning models refuse max_tokens.
            return Endpoint(
                self.openai_url, self.openai_api_key, "max_completion_tokens"
            )
        if not self.ollama_url:
            return None
        # Ollama takes any key, and ignores max_completion_tokens.
        return Endpoint(self.ollama_url, "ollama", "max_tokens")


settings = Settings()
