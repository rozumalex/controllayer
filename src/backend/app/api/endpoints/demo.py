from fastapi import APIRouter

from app.core.schema.demo import FxRatesDemo
from app.servers.fx import poison

# Switches for the live demo. They change the demo servers for everyone.
router = APIRouter(prefix="/demo", tags=["demo"])


@router.put(
    "/fx-rates",
    summary="Poison the demo FX rates tool, or clean it",
    description=(
        "Changes the description of `get_fx_rate` on the demo FX rates server "
        "at once, as a server that turns malicious after it was approved "
        "would. The gateway then hides the tool from agents."
    ),
)
async def set_fx_rates(request: FxRatesDemo) -> FxRatesDemo:
    poison(request.poisoned)
    return request
