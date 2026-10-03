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
    # The bearer token that manages the MCP servers at /api/mcp-servers. While
    # it is empty, that API refuses every request.
    mcp_admin_token: str = ""
    # The agents' bearer tokens for the gateway at /api/mcp, as
    # "token:identity,token:identity". The identity, such as judge-low, is the
    # caller the guards see. With no tokens, the gateway refuses every agent.
    mcp_agent_tokens: str = ""

    @property
    def agent_identities(self) -> dict[str, str]:
        """The agents' identities, by token."""
        pairs = (item.partition(":") for item in self.mcp_agent_tokens.split(","))
        return {
            token.strip(): identity.strip()
            for token, _, identity in pairs
            if token.strip() and identity.strip()
        }

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
