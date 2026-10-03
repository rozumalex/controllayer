from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.schema.policy import Employee


class EmailSignIn(BaseModel):
    email: str = Field(max_length=320, examples=["eve@acme.com"])

    @field_validator("email")
    @classmethod
    def looks_like_an_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, _, domain = value.partition("@")
        if not local or "." not in domain:
            raise ValueError("Enter an email address")
        return value


class EmailCode(EmailSignIn):
    code: str = Field(pattern=r"^\d{6}$", description="The code from the email.")


class CodeSent(BaseModel):
    sent: Literal[True] = True


class GoogleSignIn(BaseModel):
    credential: str = Field(
        max_length=8192, description="The ID token from Sign in with Google."
    )


class SignedIn(BaseModel):
    token: str = Field(
        description=(
            "Send it as `Authorization: Bearer <token>`, or as the API key of an "
            "OpenAI client."
        )
    )
    user: Employee
