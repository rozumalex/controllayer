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
    # The semantic injection guard asks this model whether a message is an
    # attack. It runs only with an OpenAI key, and needs a model that takes
    # temperature and structured outputs, so not a reasoning model.
    control_semantic_model: str = "gpt-4.1-mini"
    control_semantic_timeout: float = 10.0
    # Block when the semantic check fails, for example when OpenAI is down.
    # Turn it off to fall back to the heuristic guard alone.
    control_semantic_fail_closed: bool = True
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
