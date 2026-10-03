import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
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


async def empty_tables() -> None:
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(create_database())


@pytest.fixture
def db() -> None:
    """Starts the test with empty tables."""
    asyncio.run(empty_tables())


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
