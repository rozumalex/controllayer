from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    """An OpenAI chat completions request. The fields not named here, such as
    tools or temperature, go on to the model as they are."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(
        description=(
            "The bank assistant, `golden-socks-assistant`, or a model from the "
            "pool that the user's policy allows, see `GET /api/v1/models`."
        ),
        examples=["golden-socks-assistant"],
    )
    messages: list[dict[str, Any]] = Field(
        min_length=1,
        description="The conversation, oldest first, in OpenAI's format.",
        examples=[[{"role": "user", "content": "Summarise the issue for me."}]],
    )
    stream: bool = Field(
        default=False, description="Send the answer as server-sent events."
    )


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]
