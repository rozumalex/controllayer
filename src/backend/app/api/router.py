from fastapi import APIRouter, Depends

from app.api.deps import current_user, privileged_user
from app.api.endpoints import (
    auth,
    chat,
    employees,
    health,
    identity,
    mcp_servers,
    policy,
    sso,
    traces,
)
from app.core.config import settings

# Every endpoint router is included here, under the API prefix. All but health
# and auth need a signed-in user, and the admin ones need a privileged user.
# The employees router checks each of its endpoints.
router = APIRouter(prefix=settings.api_prefix)
signed_in = [Depends(current_user)]
privileged = [Depends(privileged_user)]
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(sso.router)
router.include_router(employees.router)
router.include_router(chat.router, dependencies=signed_in)
router.include_router(traces.router, dependencies=privileged)
router.include_router(mcp_servers.router, dependencies=privileged)
router.include_router(policy.router, dependencies=privileged)
router.include_router(identity.router, dependencies=privileged)
