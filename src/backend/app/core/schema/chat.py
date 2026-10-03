from pydantic import BaseModel, Field

from app.control.envelope import Action, Direction


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        description="The user's message.",
        examples=["Summarise the issue for me."],
    )


class VerdictResponse(BaseModel):
    direction: Direction
    tool: str = Field(description="What was checked, such as `user_prompt`.")
    guard: str
    action: Action
    score: float | None
    reason: str


class ChatResponse(BaseModel):
    trace_id: str = Field(description="The id of this request in the logs.")
    reply: str = Field(description="The model's answer, or why it was blocked.")
    blocked: bool = Field(description="Whether the control layer stopped it.")
    verdicts: list[VerdictResponse] = Field(
        description="Every verdict the control layer gave, in order."
    )
