from fastapi import APIRouter

from app.api.endpoints import chat, controls, health, traces
from app.core.config import settings

# Every endpoint router is included here, under the API prefix.
router = APIRouter(prefix=settings.api_prefix)
router.include_router(health.router)
router.include_router(chat.router)
router.include_router(traces.router)
router.include_router(controls.router)
