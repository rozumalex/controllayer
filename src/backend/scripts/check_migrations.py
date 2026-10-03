"""Check that the migrations apply to an empty database and cover every model change.

Creates a throwaway database on the Postgres server in DATABASE_URL, applies
every migration to it, runs `alembic check`, then drops it. The database in
DATABASE_URL is never touched.

Run from src/backend: `uv run python -m scripts.check_migrations`.
"""

import asyncio
import sys
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy.engine import URL, make_url

from app.core.config import settings

CHECK_DATABASE = "migration_check"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def execute(url: URL, sql: str) -> None:
    connection = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database=url.database,
    )
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def main() -> int:
    url = make_url(settings.database_url)
    drop = f'DROP DATABASE IF EXISTS "{CHECK_DATABASE}" WITH (FORCE)'
    try:
        asyncio.run(execute(url, drop))
        asyncio.run(execute(url, f'CREATE DATABASE "{CHECK_DATABASE}"'))
    except OSError as error:
        print(
            f"Can't reach Postgres at {url.host}:{url.port}: {error}\n"
            "Start it with `./dev up db`, or point DATABASE_URL at your Postgres.",
            file=sys.stderr,
        )
        return 1
    except asyncpg.PostgresError as error:
        print(
            f"Can't connect to Postgres at {url.host}:{url.port}: {error}\n"
            "Check the user, password and database in DATABASE_URL.",
            file=sys.stderr,
        )
        return 1

    # migrations/env.py reads the URL from settings, so point it at the
    # throwaway database.
    settings.database_url = url.set(database=CHECK_DATABASE).render_as_string(
        hide_password=False
    )
    config = Config(ALEMBIC_INI)
    try:
        command.upgrade(config, "head")
        command.check(config)
    except CommandError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        asyncio.run(execute(url, drop))
    return 0


if __name__ == "__main__":
    sys.exit(main())
