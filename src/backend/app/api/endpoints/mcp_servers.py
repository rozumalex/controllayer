import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from mcp_types import ToolAnnotations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OrgId, mcp_connect
from app.control.adapters.mcp_gateway import Connect, list_upstream_tools
from app.core.schema.mcp_servers import (
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    McpTool,
)
from app.db.models import McpServer
from app.db.session import get_session

# Whoever manages the servers decides which tools the organization's agents
# get. Each organization sees and manages only its own.
router = APIRouter(prefix="/mcp-servers", tags=["mcp servers"])

Session = Annotated[AsyncSession, Depends(get_session)]
ConnectDep = Annotated[Connect, Depends(mcp_connect)]


async def tools_of(server: McpServer, connect: Connect) -> list[McpTool]:
    try:
        tools = await list_upstream_tools(server, connect)
    except Exception as exc:
        detail = f"Can't list the tools of {server.url}: {exc!r}"
        raise HTTPException(422, detail) from exc
    return [
        McpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            read_only=(t.annotations or ToolAnnotations()).read_only_hint,
            destructive=(t.annotations or ToolAnnotations()).destructive_hint,
        )
        for t in tools
    ]


async def get_server(id: uuid.UUID, session: Session, org_id: OrgId) -> McpServer:
    server = await session.get(McpServer, id)
    # Another organization's server is not found either.
    if server is None or server.org_id != org_id:
        raise HTTPException(404, "MCP server not found")
    return server


Server = Annotated[McpServer, Depends(get_server)]


@router.get("", summary="List the MCP servers behind the control layer")
async def list_servers(session: Session, org_id: OrgId) -> list[McpServerRead]:
    servers = await session.scalars(
        select(McpServer).where(McpServer.org_id == org_id).order_by(McpServer.name)
    )
    return [McpServerRead.of(server) for server in servers]


@router.post(
    "",
    status_code=201,
    summary="Add an MCP server",
    description=(
        "The control layer connects to the server and lists its tools first, "
        "so a server it can't reach is refused with 422. Its tools are then "
        "given to the organization's agents through the gateway as "
        "`<name>__<tool>`."
    ),
)
async def create_server(
    request: McpServerCreate,
    session: Session,
    connect: ConnectDep,
    user: CurrentUser,
    org_id: OrgId,
) -> McpServerRead:
    server = McpServer(
        org_id=org_id,
        name=request.name,
        url=str(request.url),
        auth_header=request.auth_header,
        created_by_id=user.id,
        updated_by_id=user.id,
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
    request: McpServerUpdate, server: Server, session: Session, user: CurrentUser
) -> McpServerRead:
    server.enabled = request.enabled
    server.updated_by_id = user.id
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
