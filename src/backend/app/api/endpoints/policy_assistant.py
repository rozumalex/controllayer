import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OrgId
from app.api.endpoints.policy import Gateway, Session, idp_roles, stage
from app.core.policy_assistant import (
    AssistantError,
    PolicyDrafter,
    apply_edits,
    changes,
    context,
    policy_drafter,
)
from app.core.schema.policy import PolicySettings
from app.core.schema.policy_assistant import (
    ApplyRequest,
    AssistantRequest,
    Proposal,
    RoleProposal,
)
from app.db.models import User
from app.db.policy import DEFAULT_ROLE, default_policy, role_policy

# Logs counts only: the admin's text and the model's answer stay out.
logger = logging.getLogger("app.policy_assistant")

router = APIRouter(prefix="/policy/assistant", tags=["policy"])

Drafter = Annotated[PolicyDrafter | None, Depends(policy_drafter)]
MAX_LENGTH = 2000


async def current_policies(
    session: AsyncSession, org_id: uuid.UUID
) -> dict[str, PolicySettings]:
    """The policy each role works under, by role, the default first. A role
    is a job title someone holds or one the organization's IdP gives."""
    titles = await session.scalars(
        select(User.title)
        .where(User.org_id == org_id, User.title.is_not(None))
        .distinct()
    )
    roles = {title for title in titles if title} | await idp_roles(session, org_id)
    policies = {DEFAULT_ROLE: await default_policy(session, org_id)}
    for role in sorted(roles):
        policies[role] = await role_policy(session, org_id, role)
    return policies


@router.post(
    "",
    summary="Propose policy changes from a rule in plain language",
    description="A model turns the rule into changes, and each is checked "
    "against the policy schema. Nothing is saved. The rule is never stored "
    "or logged.",
)
async def propose(
    request: AssistantRequest,
    session: Session,
    org_id: OrgId,
    gateway: Gateway,
    drafter: Drafter,
) -> Proposal:
    if drafter is None:
        raise HTTPException(
            503, "No model is available. Set OPENAI_API_KEY or OLLAMA_URL."
        )
    instruction = request.instruction.strip()
    if not instruction or len(instruction) > MAX_LENGTH:
        raise HTTPException(422, f"Write a rule of 1 to {MAX_LENGTH} characters")
    policies = await current_policies(session, org_id)
    tools = {tool.name for tool in await gateway.list_tools()}
    tools.update(tool for policy in policies.values() for tool in policy.tools)
    try:
        edits = await drafter.draft(context(policies, tools), instruction)
    except AssistantError as error:
        logger.warning("policy assistant failed: %s", error)
        raise HTTPException(
            502, "The model gave no usable answer. Try again."
        ) from None
    after, dropped = apply_edits(policies, edits, tools)
    roles = [
        RoleProposal(
            role=role,
            before=policies[role],
            after=after[role],
            changes=changes(policies[role], after[role]),
        )
        for role in policies
        if after[role] != policies[role]
    ]
    logger.info(
        "policy assistant proposed %d edits: %d roles changed, %d dropped",
        len(edits),
        len(roles),
        len(dropped),
    )
    return Proposal(roles=roles, dropped=dropped)


@router.post(
    "/apply",
    status_code=204,
    summary="Save a proposal",
    description="Saves every role's policy at once, as a manual edit does. "
    "Fails with 409 if a policy changed since the proposal read it.",
)
async def apply(
    request: ApplyRequest, session: Session, user: CurrentUser, org_id: OrgId
) -> Response:
    policies = await current_policies(session, org_id)
    for update in request.roles:
        if update.role not in policies:
            raise HTTPException(404, f"No one is a {update.role}")
        if policies[update.role] != update.before:
            raise HTTPException(
                409, f"The {update.role} policy changed since. Propose again."
            )
    for update in request.roles:
        await stage(session, update.role, update.after, user)
    await session.commit()
    logger.info("policy assistant applied changes to %d roles", len(request.roles))
    return Response(status_code=204)
