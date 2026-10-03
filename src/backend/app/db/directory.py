"""The organization's directory as its IdP keeps it: users and groups, which
SCIM provisioning pushes. A user's groups set their role through the IdP's
role rules, as the claims of a sign-in do."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuthToken,
    DirectoryGroup,
    IdentityProvider,
    User,
    group_members,
)

# The clearance that opens the admin pages, see app.api.deps.
PRIVILEGED = "PRIVILEGED"


def role_for(claims: dict[str, Any], idp: IdentityProvider) -> tuple[str, bool] | None:
    """The role and whether the user administers the organization: from the
    first rule whose claim has the value, or the default role, which gives no
    admin rights. None when neither applies."""
    for rule in idp.role_rules:
        value = claims.get(rule.get("claim", ""))
        values = value if isinstance(value, list) else [value]
        if str(rule.get("value")) in {str(v) for v in values if v is not None}:
            return rule["role"], bool(rule.get("admin"))
    if idp.default_role:
        return idp.default_role, False
    return None


async def group_names(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    names = await session.scalars(
        select(DirectoryGroup.display_name)
        .join(group_members, group_members.c.group_id == DirectoryGroup.id)
        .where(group_members.c.user_id == user_id)
    )
    return list(names)


async def with_groups(
    session: AsyncSession, user_id: uuid.UUID | None, claims: dict[str, Any]
) -> dict[str, Any]:
    """The claims with the user's directory groups added to its groups claim,
    as some IdPs leave groups out of their tokens once SCIM syncs them."""
    if user_id is None:
        return claims
    synced = await group_names(session, user_id)
    if not synced:
        return claims
    claimed = claims.get("groups") or []
    claimed = claimed if isinstance(claimed, list) else [claimed]
    return {**claims, "groups": sorted({*map(str, claimed), *synced})}


def give_role(user: User, role: tuple[str, bool] | None) -> None:
    """Without a role, the user works under the default policy."""
    title, admin = role or (None, False)
    user.title = title
    user.clearance_level = PRIVILEGED if admin else "STANDARD"


async def assign_role(session: AsyncSession, user: User) -> None:
    """Sets the user's role from their directory groups, if the organization
    has an IdP. The caller commits."""
    idp = await session.scalar(
        select(IdentityProvider).where(IdentityProvider.org_id == user.org_id)
    )
    if idp is None:
        return
    claims = await with_groups(session, user.id, {"email": user.email})
    give_role(user, role_for(claims, idp))


async def deactivate(session: AsyncSession, user: User) -> None:
    """The user can't sign in again, and their sessions end now. The caller
    commits."""
    user.active = False
    await session.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
