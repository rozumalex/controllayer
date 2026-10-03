import uuid

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.db.models import IdentityProvider


class RoleRule(BaseModel):
    claim: str = Field(
        min_length=1, max_length=255, examples=["groups"], description="A claim name."
    )
    value: str = Field(
        min_length=1,
        max_length=255,
        examples=["sg-ai-compliance"],
        description="The value it must hold, or one of its items for a list.",
    )
    role: str = Field(min_length=1, max_length=255, examples=["Compliance Officer"])
    admin: bool = Field(
        default=False, description="Whether the user administers the organization."
    )


class IdentityProviderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255, examples=["Acme Okta"])
    issuer: HttpUrl = Field(examples=["https://acme.okta.com"])
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str | None = Field(
        default=None,
        max_length=4096,
        description="Only for providers that won't take PKCE alone. Leave it out "
        "to keep the saved one; send an empty string to remove it.",
    )
    scopes: str = Field(default="openid profile email", max_length=1024)
    domains: list[str] = Field(
        default=[], description="Email domains that sign in through it."
    )
    role_rules: list[RoleRule] = Field(default=[])
    default_role: str | None = Field(default=None, max_length=255)
    enabled: bool = True

    @field_validator("domains")
    @classmethod
    def plain_domains(cls, value: list[str]) -> list[str]:
        domains = sorted({d.strip().lower().lstrip("@") for d in value if d.strip()})
        for domain in domains:
            if "." not in domain or "@" in domain or " " in domain:
                raise ValueError(f"Not a domain: {domain}")
        return domains

    @field_validator("scopes")
    @classmethod
    def with_openid(cls, value: str) -> str:
        scopes = value.split()
        return " ".join(scopes if "openid" in scopes else ["openid", *scopes])

    @field_validator("default_role")
    @classmethod
    def empty_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class IdentityProviderRead(BaseModel):
    id: uuid.UUID
    name: str
    issuer: str
    client_id: str
    has_secret: bool = Field(description="Whether a client secret is saved.")
    scopes: str
    domains: list[str]
    role_rules: list[RoleRule]
    default_role: str | None
    enabled: bool
    redirect_uri: str = Field(
        description="The sign-in redirect URI to register with the provider."
    )

    @classmethod
    def of(cls, idp: IdentityProvider, redirect_uri: str) -> IdentityProviderRead:
        return cls(
            id=idp.id,
            name=idp.name,
            issuer=idp.issuer,
            client_id=idp.client_id,
            has_secret=bool(idp.client_secret),
            scopes=idp.scopes,
            domains=idp.domains,
            role_rules=[RoleRule(**rule) for rule in idp.role_rules],
            default_role=idp.default_role,
            enabled=idp.enabled,
            redirect_uri=redirect_uri,
        )


class ScimStatus(BaseModel):
    base_url: str = Field(description="The SCIM base URL to paste into the IdP.")
    has_token: bool = Field(description="Whether a SCIM token is set.")


class ScimToken(BaseModel):
    token: str = Field(description="Shown once: paste it into the IdP.")
    base_url: str = Field(description="The SCIM base URL to paste with it.")
