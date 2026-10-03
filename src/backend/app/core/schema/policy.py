import uuid
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class Clearance(StrEnum):
    """The sensitivity levels of the bank's data catalog, lowest first."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


def available_models() -> list[str]:
    """The models a policy may allow: the model pool."""
    return sorted(settings.models)


class ToolAction(StrEnum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


class PiiKind(StrEnum):
    """The PII the sensitive data guard finds in free text."""

    EMAIL = "email"
    PHONE = "phone"
    IBAN = "iban"
    PAYMENT_CARD = "payment_card"
    PESEL = "pesel"


class Budget(BaseModel):
    monthly_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Tokens a month for each employee; none is unlimited.",
    )
    monthly_usd: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="US dollars a month for each employee; none is unlimited.",
    )


class PolicySettings(BaseModel):
    injection_threshold: float = Field(
        ge=0, le=1, description="A prompt injection score at or above it blocks."
    )
    clearance: Clearance = Field(
        description="The most sensitive data the role sees as it is."
    )
    above_clearance: ToolAction = Field(
        description="What happens to data above the clearance: redact or block."
    )
    pii: dict[PiiKind, ToolAction] = Field(
        default={},
        description="What happens to each kind of PII in prompts and tool "
        "results: allow, redact or block. A kind it doesn't name is handled "
        "by the clearance, like the catalog field that holds it.",
    )
    allowed_models: list[str] = Field(description="The LLMs the role may use.")
    budget: Budget
    default_tool_action: ToolAction = Field(
        description="For gateway tools that `tools` doesn't name."
    )
    tools: dict[str, ToolAction] = Field(
        default={},
        description="Gateway tools, as `<server>__<tool>`, and what happens "
        "when the role calls them: allow, redact the result, or block.",
    )

    @field_validator("above_clearance")
    @classmethod
    def redact_or_block(cls, value: ToolAction) -> ToolAction:
        if value is ToolAction.ALLOW:
            raise ValueError("Data above the clearance is redacted or blocked")
        return value

    @field_validator("allowed_models")
    @classmethod
    def available(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(available_models())
        if unknown:
            raise ValueError(f"Unknown models: {', '.join(sorted(unknown))}")
        return sorted(set(value))


class PolicyRead(BaseModel):
    customized: bool = Field(description="False while it follows the defaults.")
    settings: PolicySettings


class RolePolicy(PolicyRead):
    role: str = Field(description="A job title in users.")
    employees: int


class PolicyOverview(BaseModel):
    models: list[str] = Field(description="The models a policy may allow.")
    default: PolicyRead = Field(description="For every role without its own.")
    roles: list[RolePolicy]


class GatewayTool(BaseModel):
    name: str = Field(description="`<server>__<tool>`, as policies name it.")
    description: str | None
    read_only: bool
    destructive: bool


class Employee(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    division: str | None
    team: str | None
    office: str | None
    clearance_level: str | None
    employment_status: str | None


class EmployeeList(BaseModel):
    total: int
    employees: list[Employee]
