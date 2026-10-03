from decimal import Decimal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.control.pipeline import Mode


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
    # The OpenAI model behind /api/chat. With no key, a mock model echoes what
    # it receives, so the demo runs offline.
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
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
    # The semantic injection guard asks this model whether a message is an
    # attack. It runs only with an OpenAI key, and needs a model that takes
    # temperature and structured outputs, so not a reasoning model.
    control_semantic_model: str = "gpt-4.1-mini"
    # The models a policy may allow. A role allows the default model unless
    # its policy says otherwise.
    available_models: list[str] = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "o4-mini"]
    # US dollars per million prompt and completion tokens, for the budgets.
    model_prices: dict[str, tuple[Decimal, Decimal]] = {
        "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
        "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
        "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
        "o4-mini": (Decimal("1.10"), Decimal("4.40")),
    }
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


settings = Settings()
