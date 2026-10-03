"""Load the Golden Socks bank data into a database.

Empties the bank_ tables and copies every row from scripts/bank_data into
them, all in one transaction. The bank is the demo organization: the staff
in users are updated in place and belong to it, so the rows that refer to
them, such as the control events, are kept. Rows that predate organizations
join it too. It also saves the policies in scripts/policies.yaml for the
demo's roles that have none, so a policy someone changed is kept, and the
demo account that "Try the demo" signs in as. Other users and tables are
left alone, so it is safe to run again. Apply the migrations first.

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
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import PRIVILEGED
from app.core.config import Settings, settings
from app.core.passwords import hash_password
from app.db import models  # noqa: F401  registers the models in Base.metadata
from app.db.base import Base
from app.db.models import Organization, Policy, User
from app.db.models.organization import DEMO_SLUG
from scripts.policies import POLICIES

DATA_DIR = Path(__file__).resolve().parent / "bank_data"
# Seeding any other host asks first, so production is never seeded by mistake.
LOCAL_HOSTS = {"db", "localhost", "127.0.0.1"}
# The bank's staff are the users with an email at this domain.
STAFF_DOMAIN = "goldensocks.com"
# Columns the seed sets itself, which the data files don't have.
OWN_COLUMNS = {"org_id", "password_hash"}
# The demo account's job title, so its policy is the Vice President's: most
# tools, but no payments, and data above CONFIDENTIAL masked.
DEMO_ROLE = "Vice President"
# The tables whose rows belong to an organization, and may predate them.
ORG_TABLES = ["users", "mcp_servers", "control_events"]

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
        if set(columns) != set(table.columns.keys()) - OWN_COLUMNS:
            raise ValueError(f"{path.name} doesn't have the columns of {table.name}")
        parsers = [PARSERS[table.columns[c].type.python_type] for c in columns]
        rows = [
            tuple(
                parse(v) if v else None for parse, v in zip(parsers, row, strict=True)
            )
            for row in reader
        ]
    return columns, rows


async def upsert_staff(
    raw: Any, columns: list[str], rows: list[tuple[Any, ...]]
) -> None:
    """Update the staff in users to the rows, add the new ones and remove the
    ones the rows don't have. Other tables refer to users, so a staff member's
    row must stay rather than be deleted and copied again."""
    await raw.execute(
        "CREATE TEMP TABLE staff (LIKE users INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    await raw.copy_records_to_table("staff", records=rows, columns=columns)
    names = ", ".join(columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")
    await raw.execute(
        f"INSERT INTO users ({names}) SELECT {names} FROM staff "
        f"ON CONFLICT (id) DO UPDATE SET {updates}"
    )
    await raw.execute(
        "DELETE FROM users WHERE email LIKE $1 AND id NOT IN (SELECT id FROM staff)",
        f"%@{STAFF_DOMAIN}",
    )


async def seed(url: str) -> None:
    tables = seeded_tables()
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            missing = await connection.run_sync(
                lambda sync: [
                    t.name
                    for t in [*tables, Base.metadata.tables[Policy.__tablename__]]
                    if not inspect(sync).has_table(t.name)
                ]
            )
            if missing:
                raise SystemExit(
                    f"The database has no {', '.join(missing)}. "
                    "Apply the migrations first."
                )
            demo = await connection.scalar(
                insert(Organization)
                .values(slug=DEMO_SLUG, name="Golden Socks")
                .on_conflict_do_update(
                    index_elements=[Organization.slug], set_={"name": "Golden Socks"}
                )
                .returning(Organization.id)
            )
            names = ", ".join(t.name for t in tables if t.name != "users")
            await connection.execute(text(f"TRUNCATE {names}"))
            # COPY, through asyncpg, loads the rows far faster than INSERT.
            raw = (await connection.get_raw_connection()).driver_connection
            assert raw is not None
            for table in tables:
                columns, rows = load(table)
                if table.name == "users":
                    await upsert_staff(raw, columns, rows)
                else:
                    await raw.copy_records_to_table(
                        table.name, records=rows, columns=columns
                    )
                print(f"{table.name}: {len(rows)} rows")
            for name in ORG_TABLES:
                joined = await connection.execute(
                    text(f"UPDATE {name} SET org_id = :demo WHERE org_id IS NULL"),
                    {"demo": demo},
                )
                print(f"{name}: {joined.rowcount} joined the demo organization")
            added = await connection.execute(
                insert(Policy)
                .values(
                    [
                        {
                            "org_id": demo,
                            "role": role,
                            "settings": policy.model_dump(mode="json"),
                        }
                        for role, policy in POLICIES.items()
                    ]
                )
                .on_conflict_do_nothing(index_elements=[Policy.org_id, Policy.role])
            )
            print(f"policies: {added.rowcount} new of {len(POLICIES)}")
            account = {
                "email": settings.demo_email,
                "name": "Demo User",
                "title": DEMO_ROLE,
                "clearance_level": PRIVILEGED,
                "employment_status": "ACTIVE",
                "org_id": demo,
                "password_hash": await hash_password(settings.demo_password),
            }
            await connection.execute(
                insert(User)
                .values(account)
                .on_conflict_do_update(index_elements=[User.email], set_=account)
            )
            print(f"demo account: {settings.demo_email}, a {DEMO_ROLE}")
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
