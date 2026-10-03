from fastapi import APIRouter

from app.api.endpoints import health, openai
from app.core.config import settings

# Every endpoint router is included here, under the API prefix.
router = APIRouter(prefix=settings.api_prefix)
router.include_router(health.router)
router.include_router(openai.router)
