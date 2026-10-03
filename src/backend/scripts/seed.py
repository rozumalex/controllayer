"""Load the Golden Socks bank data into a database.

Empties the bank_ tables and removes the bank's staff from users, then copies
every row from scripts/bank_data into them, all in one transaction. Other
users and tables are left alone, so it is safe to run again. Apply the
migrations first.

Run from src/backend: `uv run python -m scripts.seed`, or `./dev seed` from
the repo root. Pass `--url <postgres url>` to seed another database, such as
production.
"""

import argparse
import asyncio
import csv
import gzip
import sys
import uuid
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.db import models  # noqa: F401  registers the models in Base.metadata
from app.db.base import Base

DATA_DIR = Path(__file__).resolve().parent / "bank_data"
# Seeding any other host asks first, so production is never seeded by mistake.
LOCAL_HOSTS = {"db", "localhost", "127.0.0.1"}
# The bank's staff are the users with an email at this domain.
STAFF_DOMAIN = "goldensocks.com"

PARSERS: dict[type, Callable[[str], Any]] = {
    str: str,
    int: int,
    Decimal: Decimal,
    bool: {"true": True, "false": False}.__getitem__,
    date: date.fromisoformat,
    datetime: datetime.fromisoformat,
    uuid.UUID: uuid.UUID,
}


def seeded_tables() -> list[Table]:
    """users and the bank tables, each one after the tables it refers to."""
    return [
        t
        for t in Base.metadata.sorted_tables
        if t.name == "users" or t.name.startswith("bank_")
    ]


def load(table: Table) -> tuple[list[str], list[tuple[Any, ...]]]:
    """The columns and rows of a table's data file. An empty value is NULL."""
    path = DATA_DIR / f"{table.name.removeprefix('bank_')}.csv.gz"
    with gzip.open(path, "rt", newline="") as file:
        reader = csv.reader(file)
        columns = next(reader)
        if set(columns) != set(table.columns.keys()):
            raise ValueError(f"{path.name} doesn't have the columns of {table.name}")
        parsers = [PARSERS[table.columns[c].type.python_type] for c in columns]
        rows = [
            tuple(
                parse(v) if v else None for parse, v in zip(parsers, row, strict=True)
            )
            for row in reader
        ]
    return columns, rows


async def seed(url: str) -> None:
    tables = seeded_tables()
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            missing = await connection.run_sync(
                lambda sync: [
                    t.name for t in tables if not inspect(sync).has_table(t.name)
                ]
            )
            if missing:
                raise SystemExit(
                    f"The database has no {', '.join(missing)}. "
                    "Apply the migrations first."
                )
            names = ", ".join(t.name for t in tables if t.name != "users")
            await connection.execute(text(f"TRUNCATE {names}"))
            await connection.execute(
                text("DELETE FROM users WHERE email LIKE :staff"),
                {"staff": f"%@{STAFF_DOMAIN}"},
            )
            # COPY, through asyncpg, loads the rows far faster than INSERT.
            raw = (await connection.get_raw_connection()).driver_connection
            assert raw is not None
            for table in tables:
                columns, rows = load(table)
                await raw.copy_records_to_table(
                    table.name, records=rows, columns=columns
                )
                print(f"{table.name}: {len(rows)} rows")
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the Golden Socks bank data.")
    parser.add_argument("--url", help="the database to seed, DATABASE_URL by default")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="don't ask before seeding a remote host",
    )
    args = parser.parse_args()
    # Settings turns a plain postgresql:// URL into one for asyncpg.
    url = (
        Settings(database_url=args.url).database_url
        if args.url
        else settings.database_url
    )
    target = make_url(url)
    if target.host not in LOCAL_HOSTS and not args.yes:
        prompt = f"Replace the bank data in {target.database} on {target.host}? [y/N] "
        if input(prompt).strip().lower() != "y":
            return 1
    asyncio.run(seed(url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
