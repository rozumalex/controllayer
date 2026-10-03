from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    """An OpenAI chat completion request. Fields not listed here, such as
    `tools` or `temperature`, are kept and sent on to the model."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(
        default="",
        description="Ignored: the layer always uses the model set on the server.",
    )
    messages: list[dict[str, Any]] = Field(
        min_length=1,
        examples=[[{"role": "user", "content": "Summarise the issue for me."}]],
    )
    stream: bool = False
