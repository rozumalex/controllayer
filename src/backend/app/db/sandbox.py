"""Demo sandboxes: each visitor of the demo gets a copy of the demo
organization of their own, so no one else sees what they do, such as an
attack that locks an account out, a changed policy or a payment.

The browser makes a random key, keeps it, and signs in to the demo with it.
The first sign-in gives the key a sandbox, and later ones find it again.
The database makes a copy, one INSERT ... SELECT a table, in one
transaction: some 200,000 rows, which take a second or two. So a few copies
wait in a pool, and a first sign-in claims one in milliseconds, then starts
the copy that takes its place.
"""

import hashlib
import secrets
import uuid
from typing import Any

from sqlalchemy import (
    String,
    Table,
    Uuid,
    case,
    cast,
    exists,
    func,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    BankAccount,
    BankClient,
    BankDataCatalog,
    BankIdentityProfile,
    BankResearch,
    BankTrade,
    BankTransaction,
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
from app.db.session import SessionLocal


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def outside_sandboxes() -> ColumnElement[bool]:
    """Whether a user is outside every sandbox. A sandbox's users are copies,
    emails and all, so a sign-in by email looks only at the others."""
    return ~exists().where(Organization.id == User.org_id, Organization.sandbox)


def remapped(column: Any, org_id: uuid.UUID) -> ColumnElement[Any]:
    """The ID of a row's copy in the sandbox. It follows from the original's,
    so the copies that refer to it get it too, without a lookup."""
    return cast(func.md5(cast(column, String) + str(org_id)), Uuid)


def table_of(model: type[Base]) -> Table:
    return Base.metadata.tables[model.__tablename__]


async def copy(
    session: AsyncSession,
    model: type[Base],
    demo: uuid.UUID,
    org_id: uuid.UUID,
    **changed: ColumnElement[Any] | None,
) -> None:
    """Copies the demo's rows of a model's table into the sandbox, with the
    changed columns' values. A column changed to None takes its database
    default."""
    table = table_of(model)
    changed["org_id"] = literal(org_id, Uuid)
    values: dict[str, ColumnElement[Any]] = {
        c.name: value
        for c in table.columns
        if (value := changed.get(c.name, c)) is not None
    }
    await session.execute(
        insert(table).from_select(
            list(values),
            select(*values.values()).where(table.c.org_id == demo),
            # A Python default, such as uuid4, would be one value for every
            # row: the database's gives each its own.
            include_defaults=False,
        )
    )


async def copy_demo(session: AsyncSession, demo: uuid.UUID, org_id: uuid.UUID) -> None:
    """Copies everything of the demo organization into the sandbox but its
    history: the control events and conversations start empty."""

    def remap(model: type[Base], *names: str) -> dict[str, ColumnElement[Any]]:
        return {name: remapped(table_of(model).c[name], org_id) for name in names}

    # users first: the other tables refer to them.
    await copy(session, User, demo, org_id, **remap(User, "id", "manager_id"))
    await copy(session, Policy, demo, org_id, **remap(Policy, "updated_by_id"))
    await copy(session, IdentityProvider, demo, org_id, id=None)
    await copy(session, DirectoryGroup, demo, org_id, **remap(DirectoryGroup, "id"))
    await session.execute(
        insert(group_members).from_select(
            ["group_id", "user_id"],
            select(
                remapped(group_members.c.group_id, org_id),
                remapped(group_members.c.user_id, org_id),
            )
            .join(DirectoryGroup, DirectoryGroup.id == group_members.c.group_id)
            .where(DirectoryGroup.org_id == demo),
        )
    )
    log = remap(DirectoryEvent, "user_id")
    await copy(session, DirectoryEvent, demo, org_id, id=None, **log)
    # The bank's server serves the sandbox's own copy of the bank.
    url = McpServer.url
    await copy(
        session,
        McpServer,
        demo,
        org_id,
        id=None,
        url=case((url.like("%/bank/mcp"), url + f"?org={org_id}"), else_=url),
        **remap(McpServer, "created_by_id", "updated_by_id"),
    )
    bank: dict[type[Base], list[str]] = {
        BankClient: ["primary_rm_id"],
        BankAccount: [],
        BankTrade: ["trader_id"],
        BankTransaction: [],
        BankResearch: ["analyst_id"],
        BankDataCatalog: [],
        BankIdentityProfile: [],
    }
    for model, names in bank.items():
        await copy(session, model, demo, org_id, **remap(model, *names))


async def demo_org(session: AsyncSession) -> Organization | None:
    return await session.scalar(
        select(Organization).where(Organization.slug == DEMO_SLUG)
    )


async def new_sandbox(
    session: AsyncSession, demo: Organization, hashed: str | None = None
) -> uuid.UUID:
    """A new copy of the demo organization, for the key's hash or, with none,
    for the pool. The caller commits."""
    org_id = await session.scalar(
        insert(Organization)
        .values(
            slug=f"demo-{secrets.token_hex(8)}",
            name=demo.name,
            sandbox=True,
            sandbox_key_hash=hashed,
        )
        .returning(Organization.id)
    )
    assert org_id is not None
    await copy_demo(session, demo.id, org_id)
    return org_id


async def claim(session: AsyncSession, hashed: str) -> uuid.UUID | None:
    """Gives the key's hash a sandbox from the pool, the oldest first. None
    when the pool is empty."""
    spare = (
        select(Organization.id)
        .where(Organization.sandbox, Organization.sandbox_key_hash.is_(None))
        .order_by(Organization.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    return await session.scalar(
        update(Organization)
        .where(Organization.id == spare)
        .values(sandbox_key_hash=hashed)
        .returning(Organization.id)
    )


async def fill_pool() -> None:
    """Copies the demo organization until DEMO_SANDBOX_POOL sandboxes wait to
    be claimed. Runs after a sign-in claims one, and when the API starts."""
    async with SessionLocal() as session:
        demo = await demo_org(session)
        if demo is None:
            return
        spare = await session.scalar(
            select(func.count()).where(
                Organization.sandbox, Organization.sandbox_key_hash.is_(None)
            )
        )
        for _ in range(settings.demo_sandbox_pool - (spare or 0)):
            await new_sandbox(session, demo)
            await session.commit()


async def sandbox_account(session: AsyncSession, key: str) -> User | None:
    """The demo account of the browser's sandbox. The first sign-in with the
    key claims one from the pool, or copies the demo organization when the
    pool is empty. None if the demo isn't set up."""
    demo = await demo_org(session)
    if demo is None:
        return None
    hashed = key_hash(key)
    by_key = select(Organization.id).where(Organization.sandbox_key_hash == hashed)
    org_id = await session.scalar(by_key)
    if org_id is None:
        try:
            org_id = await claim(session, hashed) or await new_sandbox(
                session, demo, hashed
            )
            await session.commit()
        except IntegrityError:
            # A sign-in with the same key at the same moment got there first.
            await session.rollback()
            org_id = await session.scalar(by_key)
    return await session.scalar(
        select(User).where(User.org_id == org_id, User.email == settings.demo_email)
    )
