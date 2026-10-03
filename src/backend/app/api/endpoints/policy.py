from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, mcp_gateway
from app.control.adapters.mcp_gateway import McpGateway
from app.core.schema.policy import (
    GatewayTool,
    PolicyOverview,
    PolicyRead,
    PolicySettings,
    RolePolicy,
    available_models,
)
from app.db.models import Policy, User
from app.db.policy import DEFAULT_ROLE, default_policy
from app.db.session import get_session

router = APIRouter(prefix="/policy", tags=["policy"])

Session = Annotated[AsyncSession, Depends(get_session)]
Gateway = Annotated[McpGateway, Depends(mcp_gateway)]


async def save(
    session: AsyncSession, role: str, settings: PolicySettings, user: User
) -> None:
    values = {
        "role": role,
        "settings": settings.model_dump(mode="json"),
        "updated_by_id": user.id,
    }
    await session.execute(
        insert(Policy)
        .values(values)
        .on_conflict_do_update(
            index_elements=[Policy.role],
            set_={
                "settings": values["settings"],
                "updated_by_id": user.id,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()


async def reset(session: AsyncSession, role: str) -> None:
    policy = await session.get(Policy, role)
    if policy is not None:
        await session.delete(policy)
        await session.commit()


async def known_role(role: str, session: Session) -> str:
    """A job title that at least one employee holds."""
    if not await session.scalar(select(User.id).where(User.title == role).limit(1)):
        raise HTTPException(404, f"No employee is a {role}")
    return role


Role = Annotated[str, Depends(known_role)]


@router.get(
    "",
    summary="Show the policy of every role",
    description="A role is a job title in users. A role without a policy of "
    "its own follows the default policy.",
)
async def get_policy(session: Session) -> PolicyOverview:
    saved = {p.role: p for p in await session.scalars(select(Policy))}
    fallback = await default_policy(session)
    headcount = await session.execute(
        select(User.title, func.count())
        .where(User.title.is_not(None))
        .group_by(User.title)
        .order_by(User.title)
    )
    roles = []
    for role, employees in headcount:
        assert role is not None
        policy = saved.get(role)
        roles.append(
            RolePolicy(
                role=role,
                employees=employees,
                customized=policy is not None,
                settings=PolicySettings(**policy.settings) if policy else fallback,
            )
        )
    return PolicyOverview(
        models=available_models(),
        default=PolicyRead(customized=DEFAULT_ROLE in saved, settings=fallback),
        roles=roles,
    )


@router.put("/default", summary="Save the default policy")
async def save_default(
    request: PolicySettings, session: Session, user: CurrentUser
) -> PolicyRead:
    await save(session, DEFAULT_ROLE, request, user)
    return PolicyRead(customized=True, settings=request)


@router.delete(
    "/default",
    status_code=204,
    summary="Reset the default policy to the environment's settings",
)
async def reset_default(session: Session) -> Response:
    await reset(session, DEFAULT_ROLE)
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
async def reset_role(role: Role, session: Session) -> Response:
    await reset(session, role)
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
