from fastapi import APIRouter

from app.core.schema.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    summary="Check service health",
    description="Returns `ok` when the service is up and able to handle requests.",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
