from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schema.policy import Employee, EmployeeList
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/employees", tags=["policy"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "",
    summary="List the employees and their roles",
    description="An employee is a user with a job title; the title is the "
    "role whose policy they work under.",
)
async def list_employees(
    session: Session,
    q: Annotated[str | None, Query(description="Part of a name or email.")] = None,
    role: Annotated[str | None, Query(description="Only this job title.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmployeeList:
    query = select(User).where(User.title.is_not(None))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
    if role:
        query = query.where(User.title == role)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    users = await session.scalars(
        query.order_by(User.name, User.id).limit(limit).offset(offset)
    )
    return EmployeeList(
        total=total or 0,
        employees=[
            Employee(
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
            for user in users
        ],
    )
