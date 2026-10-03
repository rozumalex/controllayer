import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OrgId, mcp_gateway
from app.control.adapters.mcp_gateway import McpGateway
from app.core.schema.policy import (
    GatewayTool,
    PolicyOverview,
    PolicyRead,
    PolicySettings,
    RolePolicy,
    available_models,
)
from app.db.models import IdentityProvider, Policy, User
from app.db.policy import DEFAULT_ROLE, default_policy
from app.db.session import get_session

router = APIRouter(prefix="/policy", tags=["policy"])

Session = Annotated[AsyncSession, Depends(get_session)]
Gateway = Annotated[McpGateway, Depends(mcp_gateway)]


async def save(
    session: AsyncSession, role: str, settings: PolicySettings, user: User
) -> None:
    values = {
        "org_id": user.org_id,
        "role": role,
        "settings": settings.model_dump(mode="json"),
        "updated_by_id": user.id,
    }
    await session.execute(
        insert(Policy)
        .values(values)
        .on_conflict_do_update(
            index_elements=[Policy.org_id, Policy.role],
            set_={
                "settings": values["settings"],
                "updated_by_id": user.id,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()


async def reset(session: AsyncSession, org_id: uuid.UUID, role: str) -> None:
    policy = await session.get(Policy, (org_id, role))
    if policy is not None:
        await session.delete(policy)
        await session.commit()


async def idp_roles(session: AsyncSession, org_id: uuid.UUID) -> set[str]:
    """The roles the organization's IdP gives: its rules' and its default."""
    idp = await session.scalar(
        select(IdentityProvider).where(IdentityProvider.org_id == org_id)
    )
    if idp is None:
        return set()
    roles = {rule["role"] for rule in idp.role_rules}
    return roles | {idp.default_role} if idp.default_role else roles


async def known_role(role: str, session: Session, org_id: OrgId) -> str:
    """A job title that someone in the organization holds, or a role its IdP
    gives, so a role can get its policy before anyone with it signs in."""
    query = select(User.id).where(User.org_id == org_id, User.title == role)
    if not await session.scalar(query.limit(1)):
        if role not in await idp_roles(session, org_id):
            raise HTTPException(404, f"No one is a {role}")
    return role


Role = Annotated[str, Depends(known_role)]


@router.get(
    "",
    summary="Show the policy of every role",
    description="A role is a job title in users. A role without a policy of "
    "its own follows the default policy.",
)
async def get_policy(session: Session, org_id: OrgId) -> PolicyOverview:
    policies = await session.scalars(select(Policy).where(Policy.org_id == org_id))
    saved = {p.role: p for p in policies}
    fallback = await default_policy(session, org_id)
    headcount = await session.execute(
        select(User.title, func.count())
        .where(User.org_id == org_id, User.title.is_not(None))
        .group_by(User.title)
        .order_by(User.title)
    )
    from_idp = await idp_roles(session, org_id)
    people: dict[str, int] = {role: n for role, n in headcount if role is not None}
    roles = []
    for role in sorted(people.keys() | from_idp):
        policy = saved.get(role)
        roles.append(
            RolePolicy(
                role=role,
                employees=people.get(role, 0),
                customized=policy is not None,
                settings=PolicySettings(**policy.settings) if policy else fallback,
                from_idp=role in from_idp,
            )
        )
    return PolicyOverview(
        models=available_models(),
        default=PolicyRead(customized=DEFAULT_ROLE in saved, settings=fallback),
        roles=roles,
    )


@router.put("/default", summary="Save the default policy")
async def save_default(
    request: PolicySettings, session: Session, user: CurrentUser, _: OrgId
) -> PolicyRead:
    await save(session, DEFAULT_ROLE, request, user)
    return PolicyRead(customized=True, settings=request)


@router.delete(
    "/default",
    status_code=204,
    summary="Reset the default policy to the environment's settings",
)
async def reset_default(session: Session, org_id: OrgId) -> Response:
    await reset(session, org_id, DEFAULT_ROLE)
    return Response(status_code=204)


@router.put("/roles/{role}", summary="Save a role's policy")
async def save_role(
    request: PolicySettings, role: Role, session: Session, user: CurrentUser
) -> PolicyRead:
    await save(session, role, request, user)
    return PolicyRead(customized=True, settings=request)


@router.delete(
    "/roles/{role}",
    status_code=204,
    summary="Make a role follow the default policy again",
)
async def reset_role(role: Role, session: Session, org_id: OrgId) -> Response:
    await reset(session, org_id, role)
    return Response(status_code=204)


@router.get(
    "/tools",
    summary="List the gateway tools a policy can allow, redact or block",
    description="The tools of every enabled MCP server. A server that can't "
    "be reached is left out.",
)
async def list_tools(gateway: Gateway) -> list[GatewayTool]:
    tools = await gateway.list_tools()
    return [
        GatewayTool(
            name=tool.name,
            description=tool.description,
            read_only=bool(tool.annotations and tool.annotations.read_only_hint),
            destructive=bool(tool.annotations and tool.annotations.destructive_hint),
        )
        for tool in sorted(tools, key=lambda t: t.name)
    ]
