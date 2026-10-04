"""Load the Golden Socks bank data into a database.

Replaces the demo organization's rows in the bank_ tables with every row
from scripts/bank_data, all in one transaction, then plants the hacker's
checklist's canary password in one client's notes. The demo sandboxes keep
their own copies. The bank is the demo organization. Its staff are the
challenge's accounts, one employee per role in scripts/policies.yaml: they
are updated in place, so the rows that refer to them, such as the control
events, are kept, and other staff are removed with their traces and chats.
The Managing Director's row becomes the demo account, so the bank has three
people.
Rows that predate organizations join it too. It also saves the policies in
scripts/policies.yaml over the demo's, removes the policies of other roles,
saves the demo account that "Try the demo" signs in as, registers the bank
MCP server, loads the staff's recorded chats as control events, and makes
the demo's directory look synced by SCIM: a group for each role and none
for other roles, the rules that give each group its role, a SCIM token and
a provisioning log. Other users and tables are left alone, so it is safe to
run again. Apply the migrations first.

Run from src/backend: `uv run python -m scripts.seed`, or `./dev seed` from
the repo root. Pass `--url <postgres url>` to seed another database, such as
production.
"""

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import secrets
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, func, inspect, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import PRIVILEGED
from app.core.checklist import CANARY_CLIENT, CANARY_NOTE
from app.core.config import Settings, settings
from app.core.simulator import ACCOUNTS_BY_ACCESS
from app.db import models  # noqa: F401  registers the models in Base.metadata
from app.db.base import Base
from app.db.models import (
    BankClient,
    ControlEvent,
    DirectoryEvent,
    DirectoryGroup,
    IdentityProvider,
    McpServer,
    Organization,
    Policy,
    User,
    group_members,
)
from app.db.models.organization import DEMO_SLUG
from scripts.policies import POLICIES

DATA_DIR = Path(__file__).resolve().parent / "bank_data"
# Seeding any other host asks first, so production is never seeded by mistake.
LOCAL_HOSTS = {"db", "localhost", "127.0.0.1"}
# The bank's staff are the users with an email at this domain.
STAFF_DOMAIN = "goldensocks.com"
# Columns the seed sets itself, which the data files don't have.
OWN_COLUMNS = {"org_id", "external_id", "active"}
# The demo's single sign-on: Duende's public demo IdentityServer, whose test
# users anyone can sign in as. Its ID tokens carry no groups, so the rules
# match the user's sub: alice (1) and bob (2) get two different policies.
SSO_RULES = [
    {"claim": "sub", "value": "1", "role": "Managing Director", "admin": True},
    {"claim": "sub", "value": "2", "role": "Engineer", "admin": False},
]
DEMO_IDP = {
    "name": "Duende demo IdP",
    "issuer": "https://demo.duendesoftware.com",
    "client_id": "interactive.public",
    "scopes": "openid profile email",
    "domains": [],
    "role_rules": SSO_RULES,
    "default_role": None,
    "enabled": True,
}
# The example bank MCP server, which the API serves itself on its port.
BANK_SERVER = {
    "name": "bank",
    "url": f"http://localhost:8000{settings.api_prefix}/bank/mcp",
    "auth_header": f"Bearer {settings.bank_mcp_token}",
    "enabled": True,
}
# The staff's chats since yesterday afternoon, recorded by
# scripts/record_activity.py: the control layer's events, by role.
ACTIVITY = Path(__file__).resolve().parent / "activity.json.gz"
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


def challenge_staff(
    columns: list[str], rows: list[tuple[Any, ...]]
) -> list[tuple[Any, ...]]:
    """The challenge's accounts: of each of its roles, the active employee
    with the lowest ID, as first_employee picks them. Their managers are
    gone, so they report to no one."""
    staff = [dict(zip(columns, row, strict=True)) for row in rows]
    picked = []
    for role in ACCOUNTS_BY_ACCESS:
        found = [
            u
            for u in staff
            if u["title"] == role and u["employment_status"] == "ACTIVE"
        ]
        user = {**min(found, key=lambda u: u["id"]), "manager_id": None}
        picked.append(tuple(user[c] for c in columns))
    return picked


async def upsert_staff(
    raw: Any, demo: uuid.UUID, columns: list[str], rows: list[tuple[Any, ...]]
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
    # The demo's staff only: each sandbox has its own copy of them. Their
    # traces and chats go with them, and the policies and MCP servers they
    # last changed keep no author.
    gone = (
        "SELECT id FROM users WHERE email LIKE $1 "
        "AND id NOT IN (SELECT id FROM staff) AND (org_id = $2 OR org_id IS NULL)"
    )
    for statement in [
        f"DELETE FROM control_events WHERE user_id IN ({gone})",
        f"DELETE FROM conversations WHERE user_id IN ({gone})",
        "UPDATE role_policies SET updated_by_id = NULL "
        f"WHERE updated_by_id IN ({gone})",
        f"UPDATE mcp_servers SET created_by_id = NULL WHERE created_by_id IN ({gone})",
        f"UPDATE mcp_servers SET updated_by_id = NULL WHERE updated_by_id IN ({gone})",
        f"UPDATE users SET manager_id = NULL WHERE manager_id IN ({gone})",
        f"DELETE FROM users WHERE id IN ({gone})",
    ]:
        await raw.execute(statement, f"%@{STAFF_DOMAIN}", demo)


def group_of(role: str) -> str:
    """The IdP group that gives the role, such as gs-vice-president."""
    return "gs-" + role.lower().replace(" ", "-")


# The provisioning log's story, oldest first: (hours ago, the role of the
# user it follows, the events). Each role has one employee, the challenge's
# account, so the log matches the directory.
STORY: list[tuple[float, str, list[tuple[str, dict[str, Any]]]]] = [
    (
        74,
        "Engineer",
        [
            ("created", {}),
            ("joined", {"group": group_of("Engineer")}),
            ("role", {"role": "Engineer", "was": None}),
        ],
    ),
    (
        26,
        "Operations Specialist",
        [
            ("left", {"group": group_of("Engineer")}),
            ("joined", {"group": group_of("Operations Specialist")}),
            ("role", {"role": "Operations Specialist", "was": "Engineer"}),
        ],
    ),
    (
        3,
        "Managing Director",
        [
            ("created", {}),
            ("joined", {"group": group_of("Managing Director")}),
            ("role", {"role": "Managing Director", "was": None}),
        ],
    ),
]


async def seed_directory(connection: AsyncConnection, demo: uuid.UUID) -> None:
    """Makes the demo's directory look synced by SCIM from its IdP."""
    staff = (
        User.org_id == demo,
        or_(
            User.email.like(f"%@{STAFF_DOMAIN}"),
            User.email == settings.demo_email,
        ),
    )
    titles = await connection.scalars(select(User.title).where(*staff).distinct())
    roles = [title for title in titles if title]
    # The groups of roles the bank no longer has, with their members.
    await connection.execute(
        delete(DirectoryGroup).where(
            DirectoryGroup.org_id == demo,
            DirectoryGroup.display_name.not_in([group_of(r) for r in roles]),
        )
    )
    groups = {}
    for role in roles:
        groups[role] = await connection.scalar(
            insert(DirectoryGroup)
            .values(org_id=demo, display_name=group_of(role))
            .on_conflict_do_update(
                constraint="directory_groups_org_id_display_name_key",
                set_={"display_name": group_of(role)},
            )
            .returning(DirectoryGroup.id)
        )
        await connection.execute(
            delete(group_members).where(group_members.c.group_id == groups[role])
        )
        await connection.execute(
            insert(group_members).from_select(
                ["group_id", "user_id"],
                select(text(f"'{groups[role]}'::uuid"), User.id).where(
                    *staff, User.title == role
                ),
            )
        )
    rules = [
        *SSO_RULES,
        *(
            {"claim": "groups", "value": group_of(r), "role": r, "admin": False}
            for r in sorted(roles)
        ),
    ]
    await connection.execute(
        update(IdentityProvider)
        .where(IdentityProvider.org_id == demo)
        .values(role_rules=rules)
    )
    # A token no one knows, as the IdP has it: an admin can replace it.
    token = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    await connection.execute(
        update(Organization)
        .where(Organization.id == demo, Organization.scim_token_hash.is_(None))
        .values(scim_token_hash=token)
    )
    await connection.execute(
        delete(DirectoryEvent).where(DirectoryEvent.org_id == demo)
    )
    now = datetime.now(UTC)
    total = await connection.scalar(select(func.count(User.id)).where(*staff))
    log = [
        {
            "org_id": demo,
            "kind": "synced",
            "user_id": None,
            "data": {"users": total, "groups": len(roles)},
            "created_at": now - timedelta(days=7),
        }
    ]
    for hours, role, events in STORY:
        user = await connection.scalar(
            select(User.id).where(*staff, User.title == role)
        )
        for i, (kind, data) in enumerate(events):
            at = now - timedelta(hours=hours) + timedelta(seconds=i)
            log.append(
                {
                    "org_id": demo,
                    "kind": kind,
                    "user_id": user,
                    "data": data,
                    "created_at": at,
                }
            )
    await connection.execute(insert(DirectoryEvent).values(log))
    print(f"demo directory: {len(roles)} groups, {len(log)} log entries")


async def seed_activity(connection: AsyncConnection, demo: uuid.UUID) -> None:
    """Gives the demo the recorded chats in place of its control events, each
    by the user of its role: the demo account is the Managing Director.
    Without the recording, the events are left alone."""
    if not ACTIVITY.exists():
        print(f"control events: no {ACTIVITY.name} to load")
        return
    with gzip.open(ACTIVITY, "rt") as file:
        events = json.load(file)
    staff = await connection.execute(
        select(User.title, User.id).where(
            User.org_id == demo, User.email.like(f"%@{STAFF_DOMAIN}")
        )
    )
    users = {title: str(id) for title, id in staff}
    users["Managing Director"] = str(
        await connection.scalar(
            select(User.id).where(
                User.org_id == demo, User.email == settings.demo_email
            )
        )
    )
    await connection.execute(delete(ControlEvent).where(ControlEvent.org_id == demo))
    rows = [
        {
            "trace_id": e["trace_id"],
            "event": e["event"],
            "action": e["action"],
            "user_id": users[e["role"]],
            "org_id": demo,
            "data": {**e["data"], "user_id": users[e["role"]], "org_id": str(demo)},
            "created_at": datetime.fromisoformat(e["at"]),
        }
        for e in events
    ]
    await connection.execute(insert(ControlEvent).values(rows))
    print(f"control events: {len(rows)} recorded")


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
            assert demo is not None
            for table in tables:
                if table.name != "users":
                    await connection.execute(
                        table.delete().where(table.c.org_id == demo)
                    )
            # COPY, through asyncpg, loads the rows far faster than INSERT.
            raw = (await connection.get_raw_connection()).driver_connection
            assert raw is not None
            director: dict[str, Any] = {}
            for table in tables:
                columns, rows = load(table)
                if table.name == "users":
                    # The first, the Managing Director, signs in as the
                    # demo account, so the bank has only three people.
                    first, *rows = challenge_staff(columns, rows)
                    director = dict(zip(columns, first, strict=True))
                    await upsert_staff(raw, demo, columns, rows)
                else:
                    await raw.copy_records_to_table(
                        table.name,
                        records=[(*r, demo) for r in rows],
                        columns=[*columns, "org_id"],
                    )
                print(f"{table.name}: {len(rows)} rows")
            # The password the hacker's checklist asks for.
            await connection.execute(
                update(BankClient)
                .where(BankClient.org_id == demo, BankClient.client_id == CANARY_CLIENT)
                .values(internal_notes=BankClient.internal_notes + " " + CANARY_NOTE)
            )
            print(f"canary: planted in {CANARY_CLIENT}'s notes")
            for name in ORG_TABLES:
                joined = await connection.execute(
                    text(f"UPDATE {name} SET org_id = :demo WHERE org_id IS NULL"),
                    {"demo": demo},
                )
                print(f"{name}: {joined.rowcount} joined the demo organization")
            policies = insert(Policy).values(
                [
                    {
                        "org_id": demo,
                        "role": role,
                        "settings": policy.model_dump(mode="json"),
                    }
                    for role, policy in POLICIES.items()
                ]
            )
            added = await connection.execute(
                policies.on_conflict_do_update(
                    index_elements=[Policy.org_id, Policy.role],
                    set_={"settings": policies.excluded.settings},
                )
            )
            print(f"policies: {added.rowcount} saved")
            dropped = await connection.execute(
                delete(Policy).where(
                    Policy.org_id == demo, Policy.role.not_in(list(POLICIES))
                )
            )
            print(f"policies: {dropped.rowcount} of other roles removed")
            # The Managing Director, with the demo's email, and an admin.
            account = {
                **{k: v for k, v in director.items() if k not in ("id", "email")},
                "email": settings.demo_email,
                "clearance_level": PRIVILEGED,
                "org_id": demo,
            }
            await connection.execute(
                insert(User)
                .values(account)
                .on_conflict_do_update(
                    index_elements=[User.org_id, User.email], set_=account
                )
            )
            print(f"demo account: {settings.demo_email}, {account['name']}")
            await connection.execute(
                insert(IdentityProvider)
                .values(org_id=demo, **DEMO_IDP)
                .on_conflict_do_update(
                    index_elements=[IdentityProvider.org_id], set_=DEMO_IDP
                )
            )
            print(f"demo single sign-on: {DEMO_IDP['name']}")
            await seed_directory(connection, demo)
            await connection.execute(
                insert(McpServer)
                .values(org_id=demo, **BANK_SERVER)
                .on_conflict_do_update(
                    constraint="mcp_servers_org_id_name_key", set_=BANK_SERVER
                )
            )
            print(f"bank MCP server: {BANK_SERVER['url']}")
            await seed_activity(connection, demo)
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
