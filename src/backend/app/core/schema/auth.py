from pydantic import BaseModel, Field, field_validator

from app.core.schema.policy import Employee


class SignIn(BaseModel):
    email: str = Field(max_length=320, examples=["demo@controllayer.net"])
    password: str = Field(max_length=1024, examples=["demo"])

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().lower()


class SignUp(SignIn):
    organization: str = Field(
        min_length=1, max_length=255, description="The new organization's name."
    )
    name: str = Field(min_length=1, max_length=255, description="Your name.")
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("email")
    @classmethod
    def looks_like_an_email(cls, value: str) -> str:
        local, _, domain = value.partition("@")
        if not local or "." not in domain:
            raise ValueError("Enter an email address")
        return value


class GoogleSignIn(BaseModel):
    credential: str = Field(
        max_length=8192, description="The ID token from Sign in with Google."
    )
    organization: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="The organization to start, for an email with no account.",
    )


class SignedIn(BaseModel):
    token: str = Field(
        description=(
            "Send it as `Authorization: Bearer <token>`, or as the API key of an "
            "OpenAI client."
        )
    )
    user: Employee
