import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.endpoints.mcp import endpoint as mcp_endpoint
from app.api.router import router as api_router
from app.core.config import settings
from app.core.sentry import init_sentry
from app.db.session import engine

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
PROJECT = tomllib.loads(PYPROJECT.read_text())["project"]

init_sentry()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_endpoint.run():
        yield
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
