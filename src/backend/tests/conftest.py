import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import PRIVILEGED
from app.core.config import settings
from app.db.base import Base
from app.db.models import ControlEvent, User
from app.db.session import SessionLocal
from app.main import app

# The tests get their own database, so they leave the dev data alone.
DEV_URL = make_url(settings.database_url)
TEST_URL = DEV_URL.set(database=f"{DEV_URL.database}_test")
# NullPool: a pooled connection belongs to the event loop that opened it, and
# TestClient and asyncio.run each start a new one.
test_engine = create_async_engine(TEST_URL, poolclass=NullPool)
SessionLocal.configure(bind=test_engine)


async def create_database() -> None:
    dev = create_async_engine(DEV_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with dev.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_URL.database},
        )
        if not exists:
            await connection.execute(text(f'CREATE DATABASE "{TEST_URL.database}"'))
    await dev.dispose()
    await empty_tables()


async def empty_tables() -> None:
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(create_database())


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs every test on the mock model, without the semantic guard, even
    when the environment has an OpenAI key, so tests never call OpenAI."""
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns the rate limit off, so the tests can ask as often as they need.
    The rate limit tests turn it back on."""
    monkeypatch.setattr(settings, "control_rate_limit_per_minute", 0)


@pytest.fixture(autouse=True)
def no_loop_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns the loop limits off, so the tests can call a tool as often as
    they need. The loop guard tests turn them back on."""
    monkeypatch.setattr(settings, "control_loop_repeat_limit", 0)
    monkeypatch.setattr(settings, "control_loop_call_limit", 0)


@pytest.fixture
def db() -> None:
    """Starts the test with empty tables."""
    asyncio.run(empty_tables())


async def delete_events() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(ControlEvent))
        await session.commit()


@pytest.fixture
def no_events() -> None:
    """Starts the test with no control layer events in the database."""
    asyncio.run(delete_events())


TESTER_EMAIL = "tester@example.com"


async def tester() -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == TESTER_EMAIL))
        if user is None:
            user = User(
                email=TESTER_EMAIL, name="Test User", clearance_level=PRIVILEGED
            )
            session.add(user)
            await session.commit()
        return user


@pytest.fixture
def user() -> User:
    """The user the test signs in as, privileged so it can open the admin
    pages. Ask for it after db, which empties the users table."""
    return asyncio.run(tester())


def signed_in(user: User) -> dict[str, str]:
    return {"User-Id": str(user.id)}


@pytest.fixture
def client(user: User) -> Iterator[TestClient]:
    """A client signed in as the test user."""
    with TestClient(app, headers=signed_in(user)) as client:
        yield client
