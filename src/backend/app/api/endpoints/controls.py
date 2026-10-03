from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.control.layer import GUARDS, GuardSpec
from app.core.schema.controls import GuardControl, GuardSettingsModel
from app.db.controls import defaults, saved
from app.db.models import GuardSetting
from app.db.session import get_session

router = APIRouter(prefix="/controls", tags=["controls"])

Session = Annotated[AsyncSession, Depends(get_session)]

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No guard has this name."}}


def spec_of(name: str) -> GuardSpec:
    spec = next((spec for spec in GUARDS if spec.name == name), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="Guard not found.")
    return spec


async def controls(session: AsyncSession) -> dict[str, GuardControl]:
    custom = await saved(session)
    current = defaults() | custom
    return {
        spec.name: GuardControl.of(spec, current[spec.name], spec.name in custom)
        for spec in GUARDS
    }


@router.get(
    "",
    response_model=list[GuardControl],
    summary="List the guards with their settings",
)
async def list_controls(session: Session) -> list[GuardControl]:
    return list((await controls(session)).values())


@router.put(
    "/{guard}",
    response_model=GuardControl,
    summary="Change the settings of a guard",
    description="The next request runs with them.",
    responses={**NOT_FOUND, 422: {"description": "A setting the guard can't take."}},
)
async def update_control(
    guard: str, body: GuardSettingsModel, session: Session
) -> GuardControl:
    spec = spec_of(guard)
    if not set(body.directions) <= set(spec.directions):
        allowed = ", ".join(spec.directions)
        raise HTTPException(422, f"{spec.title} runs only {allowed}.")
    if unknown := set(body.disabled_rules) - {rule.name for rule in spec.rules}:
        raise HTTPException(422, f"{spec.title} has no rule {', '.join(unknown)}.")
    if spec.scored and body.threshold is None:
        raise HTTPException(422, f"{spec.title} needs a threshold.")
    if not spec.scored:
        body = body.model_copy(update={"threshold": None})
    data = body.model_dump(mode="json")
    await session.execute(
        insert(GuardSetting)
        .values(guard=guard, settings=data)
        .on_conflict_do_update(
            index_elements=[GuardSetting.guard],
            set_={"settings": data, "updated_at": func.now()},
        )
    )
    await session.commit()
    return (await controls(session))[guard]


@router.delete(
    "/{guard}",
    response_model=GuardControl,
    summary="Reset a guard to its default settings",
    responses=NOT_FOUND,
)
async def reset_control(guard: str, session: Session) -> GuardControl:
    spec_of(guard)
    await session.execute(delete(GuardSetting).where(GuardSetting.guard == guard))
    await session.commit()
    return (await controls(session))[guard]
