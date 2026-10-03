import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgId, current_user, privileged_user
from app.core.schema.policy import Employee, EmployeeList, SignInEmployee
from app.db.models import Organization, User
from app.db.models.organization import DEMO_SLUG
from app.db.session import get_session

router = APIRouter(prefix="/employees", tags=["policy"])

Session = Annotated[AsyncSession, Depends(get_session)]


Search = Annotated[str | None, Query(description="Part of a name or email.")]


def staff(org_id: uuid.UUID | Any, q: str | None):
    """The organization's employees, the users with a job title, whose name
    or email has q."""
    query = select(User).where(User.org_id == org_id, User.title.is_not(None))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
    return query


@router.get(
    "",
    summary="List the employees and their roles",
    description="An employee is a user with a job title; the title is the "
    "role whose policy they work under. Only privileged users may list them.",
    dependencies=[Depends(privileged_user)],
)
async def list_employees(
    session: Session,
    org_id: OrgId,
    q: Search = None,
    role: Annotated[str | None, Query(description="Only this job title.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmployeeList:
    query = staff(org_id, q)
    if role:
        query = query.where(User.title == role)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    users = await session.scalars(
        query.order_by(User.name, User.id).limit(limit).offset(offset)
    )
    return EmployeeList(total=total or 0, employees=[employee(user) for user in users])


@router.get(
    "/sign-in",
    summary="List the employees to sign in as",
    description="Open to anyone, so it shows only what the sign-in screen "
    "needs, and only the staff of the demo organization.",
)
async def sign_in_employees(
    session: Session,
    q: Search = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> list[SignInEmployee]:
    demo = select(Organization.id).where(Organization.slug == DEMO_SLUG)
    query = staff(demo.scalar_subquery(), q)
    users = await session.scalars(query.order_by(User.name, User.id).limit(limit))
    return [
        SignInEmployee(
            id=user.id,
            name=user.name,
            role=user.title or "",
            team=user.team,
            clearance_level=user.clearance_level,
        )
        for user in users
    ]


@router.get(
    "/me",
    summary="The signed-in employee",
    description="The user named by the `User-Id` header, or 401 if none is.",
)
async def me(user: Annotated[User, Depends(current_user)]) -> Employee:
    return employee(user)


def employee(user: User) -> Employee:
    return Employee(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.title or "",
        division=user.division,
        team=user.team,
        office=user.office,
        clearance_level=user.clearance_level,
        employment_status=user.employment_status,
    )
