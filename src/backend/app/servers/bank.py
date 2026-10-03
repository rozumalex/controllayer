"""The Golden Socks core banking tools, served as an MCP server: the example
tool set that the control layer protects.

The server has no guards of its own. Like a real system of record, it checks
the business rules (an account must be open to pay from it, a settled trade
can't be cancelled), and returns whole rows, restricted fields included. Who
may call which tool, and which fields reach the agent, is the control layer's
job once the server is registered in the gateway.

Agents read clients, accounts, transactions, trades and research. They write
only where a bank would let an operator act: payments and AML alerts,
account restrictions, trades, and client contacts and notes. Research, the
data catalog, the identity profiles and the staff are read only.

It is mounted in the API at /api/bank/mcp and takes the bearer token in
BANK_MCP_TOKEN.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hmac import compare_digest
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    BankAccount,
    BankClient,
    BankResearch,
    BankTrade,
    BankTransaction,
    User,
)
from app.db.session import SessionLocal

bank = MCPServer(
    "golden-socks-bank",
    instructions=(
        "Core banking at Golden Socks: look up clients, accounts, payments, "
        "trades and research, and act on them. Amounts are in US dollars."
    ),
)

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=False
)
# Moves money or blocks a client: hard to undo.
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)

Limit = Annotated[int, Field(ge=1, le=100)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
CENT = Decimal("0.01")


def plain(value: Any) -> Any:
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, date):  # datetime too
        return value.isoformat()
    return value


def row(record: Base) -> dict[str, Any]:
    """Every column of a row, as JSON values."""
    return {c.key: plain(getattr(record, c.key)) for c in record.__table__.columns}


def utcnow() -> datetime:
    # The bank's timestamps are UTC, stored without a zone.
    return datetime.now(UTC).replace(tzinfo=None)


def stamped(text: str | None, entry: str) -> str:
    """Appends an entry to a notes field, dated, so the history stays."""
    line = f"[{utcnow():%Y-%m-%d %H:%M} UTC] {entry}"
    return f"{text}\n{line}" if text else line


async def found[T: Base](
    session: AsyncSession, model: type[T], key: str, lock: bool = False
) -> T:
    record = await session.get(model, key, with_for_update=lock)
    if record is None:
        raise ToolError(f"No {model.__name__.removeprefix('Bank').lower()} {key}")
    return record


async def next_id(session: AsyncSession, column: Any, prefix: str, digits: int) -> str:
    """The next identifier in a sequence such as TXN-000000001."""
    last = await session.scalar(
        select(func.max(column)).where(column.like(f"{prefix}%"))
    )
    number = int(last.removeprefix(prefix)) + 1 if last else 1
    return f"{prefix}{number:0{digits}d}"


async def rows(statement: Select[Any], key: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        records = await session.scalars(statement)
        return {key: [row(r) for r in records]}


def open_for_business(account: BankAccount) -> None:
    if account.status != "OPEN" or account.restriction_flag != "NONE":
        raise ToolError(
            f"Account {account.account_id} is {account.status} "
            f"({account.restriction_flag}): no new activity"
        )


# Reading


@bank.tool(annotations=READ)
async def search_clients(
    name: str | None = None,
    country_code: str | None = None,
    sector: str | None = None,
    risk_rating: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
    limit: Limit = 20,
) -> dict[str, Any]:
    """Finds clients by part of their name, country code, sector or risk
    rating."""
    statement = select(BankClient).order_by(BankClient.client_id).limit(limit)
    if name:
        statement = statement.where(BankClient.client_name.icontains(name))
    if country_code:
        statement = statement.where(BankClient.country_code == country_code.upper())
    if sector:
        statement = statement.where(BankClient.sector.icontains(sector))
    if risk_rating:
        statement = statement.where(BankClient.risk_rating == risk_rating)
    return await rows(statement, "clients")


@bank.tool(annotations=READ)
async def get_client(client_id: str) -> dict[str, Any]:
    """A client's full profile, with their accounts."""
    async with SessionLocal() as session:
        client = await found(session, BankClient, client_id)
        accounts = await session.scalars(
            select(BankAccount)
            .where(BankAccount.client_id == client_id)
            .order_by(BankAccount.account_id)
        )
        return {"client": row(client), "accounts": [row(a) for a in accounts]}


@bank.tool(annotations=READ)
async def get_account(account_id: str) -> dict[str, Any]:
    """An account, with its balance available for new payments: the cash
    balance less the payments still pending."""
    async with SessionLocal() as session:
        account = await found(session, BankAccount, account_id)
        return {
            "account": row(account),
            "available_balance_usd": str(await available(session, account)),
        }


@bank.tool(annotations=READ)
async def list_transactions(
    client_id: str | None = None,
    account_id: str | None = None,
    status: Literal["PENDING", "HELD", "REVIEW", "COMPLETED"] | None = None,
    min_aml_risk_score: Annotated[int, Field(ge=0, le=100)] = 0,
    limit: Limit = 20,
) -> dict[str, Any]:
    """A client's or an account's transactions, newest first."""
    if not (client_id or account_id):
        raise ToolError("Give a client_id or an account_id")
    statement = (
        select(BankTransaction)
        .where(BankTransaction.aml_risk_score >= min_aml_risk_score)
        .order_by(BankTransaction.timestamp.desc())
        .limit(limit)
    )
    if client_id:
        statement = statement.where(BankTransaction.client_id == client_id)
    if account_id:
        statement = statement.where(BankTransaction.account_id == account_id)
    if status:
        statement = statement.where(BankTransaction.status == status)
    return await rows(statement, "transactions")


@bank.tool(annotations=READ)
async def list_trades(
    client_id: str | None = None,
    account_id: str | None = None,
    status: Literal["PENDING", "BOOKED", "SETTLED", "CANCELLED"] | None = None,
    limit: Limit = 20,
) -> dict[str, Any]:
    """A client's or an account's trades, newest first."""
    if not (client_id or account_id):
        raise ToolError("Give a client_id or an account_id")
    statement = (
        select(BankTrade).order_by(BankTrade.trade_timestamp.desc()).limit(limit)
    )
    if client_id:
        statement = statement.where(BankTrade.client_id == client_id)
    if account_id:
        statement = statement.where(BankTrade.account_id == account_id)
    if status:
        statement = statement.where(BankTrade.status == status)
    return await rows(statement, "trades")


@bank.tool(annotations=READ)
async def search_research(
    symbol: str | None = None,
    sector: str | None = None,
    text: str | None = None,
    limit: Limit = 10,
) -> dict[str, Any]:
    """Research reports by covered symbol, sector or words in the title,
    newest first."""
    statement = (
        select(BankResearch).order_by(BankResearch.publication_date.desc()).limit(limit)
    )
    if symbol:
        statement = statement.where(BankResearch.coverage_symbol == symbol.upper())
    if sector:
        statement = statement.where(BankResearch.sector.icontains(sector))
    if text:
        statement = statement.where(BankResearch.title.icontains(text))
    return await rows(statement, "research")


# Payments and AML

PAYMENT_TYPES = ["WIRE", "SEPA", "ACH", "FX_TRANSFER"]


async def available(session: AsyncSession, account: BankAccount) -> Decimal:
    pending = await session.scalar(
        select(func.sum(BankTransaction.amount_usd)).where(
            BankTransaction.account_id == account.account_id,
            BankTransaction.status.in_(["PENDING", "HELD", "REVIEW"]),
            BankTransaction.transaction_type.in_(PAYMENT_TYPES),
        )
    )
    return account.cash_balance_usd - (pending or 0)


@bank.tool(annotations=DESTRUCTIVE)
async def initiate_payment(
    account_id: str,
    amount_usd: Amount,
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")],
    beneficiary_name: str,
    beneficiary_account: str,
    destination_country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")],
    purpose: Literal[
        "Invoice", "Treasury", "Investment", "Payroll", "Subscription", "Other"
    ],
    payment_type: Literal["WIRE", "SEPA", "ACH", "FX_TRANSFER"] = "WIRE",
) -> dict[str, Any]:
    """Sends money out of an account. The payment waits as PENDING until
    payment operations release it; the balance moves when it settles."""
    async with SessionLocal.begin() as session:
        # Locked, so two payments can't both spend the same balance.
        account = await found(session, BankAccount, account_id, lock=True)
        open_for_business(account)
        if amount_usd > await available(session, account):
            raise ToolError(f"Insufficient available balance in {account_id}")
        payment = BankTransaction(
            transaction_id=await next_id(
                session, BankTransaction.transaction_id, "TXN-", 9
            ),
            client_id=account.client_id,
            account_id=account_id,
            transaction_type=payment_type,
            amount_usd=amount_usd.quantize(CENT),
            currency=currency,
            timestamp=utcnow(),
            origin_country=account.jurisdiction,
            destination_country=destination_country,
            beneficiary_name=beneficiary_name,
            beneficiary_account=beneficiary_account,
            purpose=purpose,
            channel="API",
            # Scored by the AML and fraud engines downstream.
            aml_risk_score=0,
            fraud_score=0,
            status="PENDING",
            source_system="API_GATEWAY",
        )
        session.add(payment)
        return {"transaction": row(payment)}


@bank.tool(annotations=WRITE)
async def flag_transaction(transaction_id: str, reason: str) -> dict[str, Any]:
    """Raises an AML alert on a transaction. A payment that has not gone out
    yet is held until the alert is cleared."""
    async with SessionLocal.begin() as session:
        transaction = await found(session, BankTransaction, transaction_id, lock=True)
        if transaction.alert_id is None:
            prefix = f"ALT-{utcnow():%Y}-"
            transaction.alert_id = await next_id(
                session, BankTransaction.alert_id, prefix, 6
            )
        if transaction.status == "PENDING":
            transaction.status = "HELD"
        elif transaction.status == "COMPLETED":
            transaction.status = "REVIEW"
        transaction.investigation_notes = stamped(
            transaction.investigation_notes, f"{transaction.alert_id} raised: {reason}"
        )
        return {"transaction": row(transaction)}


# Accounts


@bank.tool(annotations=DESTRUCTIVE)
async def restrict_account(
    account_id: str, restriction: Literal["RISK_REVIEW", "LEGAL_HOLD"]
) -> dict[str, Any]:
    """Freezes an account: no new payments or trades until the restriction is
    lifted."""
    async with SessionLocal.begin() as session:
        account = await found(session, BankAccount, account_id, lock=True)
        if account.status == "CLOSED":
            raise ToolError(f"Account {account_id} is closed")
        account.status = "RESTRICTED"
        account.restriction_flag = restriction
        return {"account": row(account)}


@bank.tool(annotations=WRITE)
async def lift_restriction(account_id: str) -> dict[str, Any]:
    """Opens a restricted account again. A legal hold can only be lifted by
    legal, not through this tool."""
    async with SessionLocal.begin() as session:
        account = await found(session, BankAccount, account_id, lock=True)
        if account.status != "RESTRICTED":
            raise ToolError(f"Account {account_id} is not restricted")
        if account.restriction_flag == "LEGAL_HOLD":
            raise ToolError(f"Account {account_id} is under a legal hold")
        account.status = "OPEN"
        account.restriction_flag = "NONE"
        return {"account": row(account)}


# Trading


def settlement_date(asset_class: str, day: date) -> date:
    """T+1 for equities, T+2 for the rest, counting weekdays only."""
    days = 1 if asset_class == "Equities" else 2
    while days:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day


@bank.tool(annotations=WRITE)
async def book_trade(
    account_id: str,
    trader_email: str,
    desk: Literal[
        "Equities - Cash",
        "Equities - Derivatives",
        "FICC - Rates",
        "FICC - Credit",
        "FICC - FX",
        "Prime Services",
        "Commodities",
    ],
    asset_class: Literal["Equities", "Rates", "Credit", "FX", "Commodities"],
    instrument: str,
    side: Literal["BUY", "SELL"],
    quantity: Annotated[int, Field(gt=0)],
    price: Annotated[Decimal, Field(gt=0)],
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")],
    venue: str = "OTC",
    counterparty: str = "Golden Socks",
    comment: str | None = None,
) -> dict[str, Any]:
    """Books a client trade. For FX, the quantity is the base currency amount;
    for everything else, the number of shares, contracts or the face value."""
    async with SessionLocal.begin() as session:
        account = await found(session, BankAccount, account_id, lock=True)
        open_for_business(account)
        trader = await session.scalar(select(User).where(User.email == trader_email))
        if trader is None or trader.employment_status != "ACTIVE":
            raise ToolError(f"{trader_email} is not an active trader")
        now = utcnow()
        notional = Decimal(quantity) * (1 if asset_class == "FX" else price)
        trade = BankTrade(
            trade_id=await next_id(session, BankTrade.trade_id, "TRD-", 8),
            client_id=account.client_id,
            account_id=account_id,
            desk=desk,
            asset_class=asset_class,
            instrument=instrument,
            side=side,
            quantity=quantity,
            price=price,
            notional_usd=notional.quantize(CENT),
            currency=currency,
            trade_timestamp=now,
            settlement_date=settlement_date(asset_class, now.date()),
            trader_id=trader.id,
            venue=venue,
            pnl_usd=Decimal(0),
            # Risk computes the VaR overnight.
            var_1d_usd=Decimal(0),
            status="BOOKED",
            strategy="Client Flow",
            counterparty=counterparty,
            internal_comment=comment,
        )
        session.add(trade)
        return {"trade": row(trade)}


@bank.tool(annotations=WRITE)
async def cancel_trade(trade_id: str, reason: str) -> dict[str, Any]:
    """Cancels a trade that has not settled yet."""
    async with SessionLocal.begin() as session:
        trade = await found(session, BankTrade, trade_id, lock=True)
        if trade.status not in ("PENDING", "BOOKED"):
            raise ToolError(f"Trade {trade_id} is {trade.status}")
        trade.status = "CANCELLED"
        trade.internal_comment = stamped(trade.internal_comment, f"Cancelled: {reason}")
        return {"trade": row(trade)}


# Clients


@bank.tool(annotations=WRITE)
async def update_client_contact(
    client_id: str,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
) -> dict[str, Any]:
    """Changes the named contact of a client, or their email or phone."""
    changes = {
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
    }
    changes = {key: value for key, value in changes.items() if value}
    if not changes:
        raise ToolError("Nothing to change")
    async with SessionLocal.begin() as session:
        client = await found(session, BankClient, client_id, lock=True)
        for key, value in changes.items():
            setattr(client, key, value)
        client.internal_notes = stamped(
            client.internal_notes, f"Contact changed: {', '.join(changes)}"
        )
        return {"client": row(client)}


@bank.tool(annotations=WRITE)
async def add_client_note(client_id: str, note: str) -> dict[str, Any]:
    """Adds a dated note to a client's relationship notes."""
    async with SessionLocal.begin() as session:
        client = await found(session, BankClient, client_id, lock=True)
        client.internal_notes = stamped(client.internal_notes, note)
        return {"client": row(client)}


class BankMcpApp:
    """The server over Streamable HTTP, as an ASGI app for the API to mount.

    A session manager runs only once, and the API starts again in each test,
    so every start makes a new one.
    """

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        bank.streamable_http_app(
            stateless_http=True,
            json_response=True,
            # The token guards it, and the Host differs between Compose and
            # production.
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        async with bank.session_manager.run():
            yield

    def authorized(self, scope: Scope) -> bool:
        token = settings.bank_mcp_token
        given = dict(scope["headers"]).get(b"authorization", b"")
        return bool(token) and compare_digest(given, f"Bearer {token}".encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.authorized(scope):
            response = JSONResponse(
                {"detail": "A valid bank token is required"},
                401,
                {"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await bank.session_manager.handle_request(scope, receive, send)


bank_mcp_app = BankMcpApp()
