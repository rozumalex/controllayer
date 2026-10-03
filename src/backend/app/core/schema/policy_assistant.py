from pydantic import BaseModel, Field

from app.core.schema.policy import PolicySettings


class AssistantRequest(BaseModel):
    instruction: str = Field(
        description="A rule in plain language, such as \"Analysts can't make "
        'payments". It is sent to the model and never stored or logged.'
    )


class Change(BaseModel):
    setting: str = Field(description="Such as `tools.bank__send_payment`.")
    before: str
    after: str


class RoleProposal(BaseModel):
    role: str = Field(description="A job title, or `*` for the default policy.")
    before: PolicySettings
    after: PolicySettings
    changes: list[Change]


class Proposal(BaseModel):
    roles: list[RoleProposal] = Field(description="Only the roles it changes.")
    dropped: list[str] = Field(
        description="The changes the model proposed that the policy can't hold, "
        "such as an unknown role or tool."
    )


class RoleUpdate(BaseModel):
    role: str
    before: PolicySettings = Field(description="As the proposal read it.")
    after: PolicySettings


class ApplyRequest(BaseModel):
    roles: list[RoleUpdate] = Field(min_length=1)
