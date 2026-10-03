from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    CODE_EXECUTION = "code_execution"
    DESERIALIZATION = "deserialization"
    SUPPLY_CHAIN = "supply_chain"
    TEMPLATE_INJECTION = "template_injection"
    SSRF = "ssrf"
    PATH_TRAVERSAL = "path_traversal"


class Signature(BaseModel):
    """One known attack, as a pattern to look for in the text."""

    id: str
    name: str
    category: Category
    # A match blocks when the severity reaches the guard's threshold. Below
    # it, the match is only logged.
    severity: float = Field(ge=0, le=1)
    # A Python regular expression. Use inline flags such as (?i) for options.
    pattern: str
    # CVEs and write-ups about the attack.
    references: list[str] = []
    enabled: bool = True


class SignatureFeed(BaseModel):
    """The file or URL the attack signatures come from."""

    version: str
    signatures: list[Signature]
