import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import mcp_connect, require_admin
from app.control.adapters.mcp_gateway import Connect, list_upstream_tools
from app.core.schema.mcp_servers import (
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    McpTool,
)
from app.db.models import McpServer
from app.db.session import get_session

# Whoever manages the servers decides which tools every agent gets, so only
# the admin may.
router = APIRouter(
    prefix="/mcp-servers", tags=["mcp servers"], dependencies=[Depends(require_admin)]
)

Session = Annotated[AsyncSession, Depends(get_session)]
ConnectDep = Annotated[Connect, Depends(mcp_connect)]


async def tools_of(server: McpServer, connect: Connect) -> list[McpTool]:
    try:
        tools = await list_upstream_tools(server, connect)
    except Exception as exc:
        detail = f"Can't list the tools of {server.url}: {exc!r}"
        raise HTTPException(422, detail) from exc
    return [
        McpTool(name=t.name, description=t.description, input_schema=t.input_schema)
        for t in tools
    ]


async def get_server(id: uuid.UUID, session: Session) -> McpServer:
    server = await session.get(McpServer, id)
    if server is None:
        raise HTTPException(404, "MCP server not found")
    return server


Server = Annotated[McpServer, Depends(get_server)]


@router.get("", summary="List the MCP servers behind the control layer")
async def list_servers(session: Session) -> list[McpServerRead]:
    servers = await session.scalars(select(McpServer).order_by(McpServer.name))
    return [McpServerRead.of(server) for server in servers]


@router.post(
    "",
    status_code=201,
    summary="Add an MCP server",
    description=(
        "The control layer connects to the server and lists its tools first, "
        "so a server it can't reach is refused with 422. Its tools are then "
        "served to every agent at `/api/mcp` as `<name>__<tool>`."
    ),
)
async def create_server(
    request: McpServerCreate, session: Session, connect: ConnectDep
) -> McpServerRead:
    server = McpServer(
        name=request.name, url=str(request.url), auth_header=request.auth_header
    )
    await tools_of(server, connect)
    session.add(server)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, f"A server named {request.name} exists") from exc
    return McpServerRead.of(server)


@router.patch("/{id}", summary="Turn an MCP server on or off")
async def update_server(
    request: McpServerUpdate, server: Server, session: Session
) -> McpServerRead:
    server.enabled = request.enabled
    await session.commit()
    return McpServerRead.of(server)


@router.delete("/{id}", status_code=204, summary="Remove an MCP server")
async def delete_server(server: Server, session: Session) -> Response:
    await session.delete(server)
    await session.commit()
    return Response(status_code=204)


@router.get("/{id}/tools", summary="List the tools of an MCP server")
async def list_tools(server: Server, connect: ConnectDep) -> list[McpTool]:
    return await tools_of(server, connect)
