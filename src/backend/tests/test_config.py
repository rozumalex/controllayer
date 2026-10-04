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


def test_resend_api_key_sends_through_resend() -> None:
    # when
    settings = Settings(resend_api_key="re_test", smtp_host="mailpit")

    # then
    assert (settings.smtp_host, settings.smtp_port) == ("smtp.resend.com", 587)
    assert (settings.smtp_username, settings.smtp_password) == ("resend", "re_test")
    assert settings.smtp_tls == "starttls"
