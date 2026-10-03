from fastapi import APIRouter

from app.api.endpoints import health
from app.core.config import settings

# Every endpoint router is included here, under the API prefix.
router = APIRouter(prefix=settings.api_prefix)
router.include_router(health.router)
