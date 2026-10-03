import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.db.models import McpServer


class McpServerCreate(BaseModel):
    # No underscores, so the gateway can split <name>__<tool> at the first "__".
    name: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        max_length=64,
        description="Lowercase letters, digits and dashes. Prefixes the tools.",
        examples=["bank"],
    )
    url: HttpUrl = Field(
        description="The server's Streamable HTTP endpoint.",
        examples=["http://bank-mcp:5000/mcp"],
    )
    auth_header: str | None = Field(
        default=None,
        description="The Authorization header to send, such as `Bearer <token>`.",
    )


class McpServerUpdate(BaseModel):
    enabled: bool = Field(description="Whether agents get the server's tools.")


class McpServerRead(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    enabled: bool
    has_auth: bool = Field(description="Whether an Authorization header is set.")
    created_at: datetime

    @classmethod
    def of(cls, server: McpServer) -> McpServerRead:
        return cls(
            id=server.id,
            name=server.name,
            url=server.url,
            enabled=server.enabled,
            has_auth=server.auth_header is not None,
            created_at=server.created_at,
        )


class McpTool(BaseModel):
    name: str
    description: str | None
    input_schema: dict[str, Any]
    # The server's own hints, so not proof: a server can label any tool read
    # only.
    read_only: bool | None = Field(description="The tool changes nothing.")
    destructive: bool | None = Field(
        description="The tool's changes are hard to undo, such as moving money."
    )
    changed: bool = Field(
        description="The definition differs from the approved one, so agents "
        "don't get the tool until it is approved again."
    )
