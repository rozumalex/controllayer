from pydantic import BaseModel, Field


class Consent(BaseModel):
    """The authorization request, as /api/oauth/authorize passed it to the
    consent page, and the user's answer."""

    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(max_length=2048)
    explicit: bool = Field(
        default=False, description="Whether the request named the redirect URI."
    )
    code_challenge: str = Field(min_length=43, max_length=128)
    state: str | None = Field(default=None, max_length=2048)
    scope: str | None = Field(default=None, max_length=2048)
    resource: str | None = Field(default=None, max_length=2048)
    allow: bool = Field(description="Whether the user lets the client in.")


class ConsentRedirect(BaseModel):
    redirect: str = Field(
        description="Where to send the browser: the client's redirect URI with "
        "the code, or with the error."
    )
