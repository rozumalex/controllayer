# Import every model here, so Alembic autogenerate sees it in Base.metadata.
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
from app.db.models.mcp_server import McpServer
from app.db.models.user import User

__all__ = [
    "BankAccount",
    "BankClient",
    "BankDataCatalog",
    "BankIdentityProfile",
    "BankResearch",
    "BankTrade",
    "BankTransaction",
    "ControlEvent",
    "McpServer",
    "User",
]
