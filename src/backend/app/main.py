import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.routing import Route

from app.api.router import router as api_router
from app.control.http import OPENAI_HTTP
from app.core.config import settings
from app.core.sentry import init_sentry
from app.db.session import engine
from app.servers.bank import bank_mcp_app

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
PROJECT = tomllib.loads(PYPROJECT.read_text())["project"]

init_sentry()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with bank_mcp_app.run():
        yield
    await OPENAI_HTTP.aclose()
    await engine.dispose()


app = FastAPI(
    title=PROJECT["name"],
    description=PROJECT["description"],
    version=PROJECT["version"],
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)
app.include_router(api_router)
# The example bank tools, for the gateway to connect to like any MCP server.
# A Route, not a Mount, so the path has no trailing slash to redirect to.
app.router.routes.append(Route(f"{settings.api_prefix}/bank/mcp", bank_mcp_app))
