from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.api.endpoints import (
    chat,
    employees,
    health,
    mcp_servers,
    policy,
    traces,
)
from app.core.config import settings

# Every endpoint router is included here, under the API prefix. All but health
# and the employees, whom the sign-in screen lists, need a signed-in user.
router = APIRouter(prefix=settings.api_prefix)
signed_in = [Depends(current_user)]
router.include_router(health.router)
router.include_router(employees.router)
router.include_router(chat.router, dependencies=signed_in)
router.include_router(traces.router, dependencies=signed_in)
router.include_router(mcp_servers.router, dependencies=signed_in)
router.include_router(policy.router, dependencies=signed_in)
