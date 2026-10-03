from pydantic import BaseModel, Field


class FxRatesDemo(BaseModel):
    poisoned: bool = Field(
        description="Whether the demo FX rates tool hides instructions for the "
        "model in its description."
    )
