from sqlalchemy import select

from app.control.adapters.mcp_gateway import Connect, McpGateway, connect_http
from app.control.adapters.openai_chat import ChatControl
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings
from app.db.models import McpServer
from app.db.session import SessionLocal


def control_layer() -> ControlLayer:
    # Built on every request, so a setting changed at runtime applies to the
    # next one.
    return build_layer(settings.control_mode, settings.control_injection_threshold)


def chat_control() -> ChatControl:
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else MockUpstream()
    )
    return ChatControl(control_layer(), upstream, settings.control_log_payloads)


async def enabled_mcp_servers() -> list[McpServer]:
    async with SessionLocal() as session:
        servers = await session.scalars(select(McpServer).where(McpServer.enabled))
        return list(servers)


def mcp_connect() -> Connect:
    return connect_http


def mcp_gateway() -> McpGateway:
    return McpGateway(control_layer(), mcp_connect(), enabled_mcp_servers)
