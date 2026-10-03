from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        description="The user's message.",
        examples=["Summarise the issue for me."],
    )


class ChatResponse(BaseModel):
    trace_id: str = Field(description="The id of this request in the logs.")
    reply: str = Field(description="The model's answer, or why it was blocked.")
    blocked: bool = Field(description="Whether the control layer stopped it.")
