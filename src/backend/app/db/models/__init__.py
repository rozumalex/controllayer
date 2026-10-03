# Import every model here, so Alembic autogenerate sees it in Base.metadata.
from app.db.models.auth_token import AuthToken
from app.db.models.bank import (
    BankAccount,
    BankClient,
    BankDataCatalog,
    BankIdentityProfile,
    BankResearch,
    BankTrade,
    BankTransaction,
)
from app.db.models.control_event import ControlEvent
from app.db.models.directory_group import DirectoryGroup, group_members
from app.db.models.email_code import EmailCode
from app.db.models.identity_provider import IdentityProvider, SsoLogin
from app.db.models.mcp_server import McpServer
from app.db.models.oauth import OAuthClient, OAuthCode
from app.db.models.organization import Organization
from app.db.models.policy import Policy
from app.db.models.user import User

__all__ = [
    "AuthToken",
    "BankAccount",
    "BankClient",
    "BankDataCatalog",
    "BankIdentityProfile",
    "BankResearch",
    "BankTrade",
    "BankTransaction",
    "ControlEvent",
    "DirectoryGroup",
    "EmailCode",
    "IdentityProvider",
    "McpServer",
    "OAuthClient",
    "OAuthCode",
    "Organization",
    "Policy",
    "SsoLogin",
    "User",
    "group_members",
]
