from app.core.config import Settings


def test_database_url_plain_postgresql() -> None:
    # given
    url = "postgresql://user:secret@db.example.com:25060/app?sslmode=require"

    # when
    settings = Settings(database_url=url)

    # then
    assert (
        settings.database_url
        == "postgresql+asyncpg://user:secret@db.example.com:25060/app?ssl=require"
    )


def test_database_url_asyncpg_unchanged() -> None:
    # given
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"

    # when / then
    assert Settings(database_url=url).database_url == url


def test_redis_url_tls_requires_certificate() -> None:
    # given
    url = "rediss://default:secret@cache.example.com:25061"

    # when
    settings = Settings(redis_url=url)

    # then
    assert settings.redis_url == f"{url}?ssl_cert_reqs=required"


def test_redis_url_plain_unchanged() -> None:
    # given
    url = "redis://localhost:6379/0"

    # when / then
    assert Settings(redis_url=url).redis_url == url


def test_agent_tokens_map_to_identities() -> None:
    # given
    tokens = "low-secret:judge-low, priv-secret:judge-privileged,,broken"

    # when
    settings = Settings(mcp_agent_tokens=tokens)

    # then
    assert settings.agent_identities == {
        "low-secret": "judge-low",
        "priv-secret": "judge-privileged",
    }
