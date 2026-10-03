import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import mcp_types as types
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from app.api.deps import control_layer
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.core.config import settings
from app.db.models import (
    BankAccount,
    BankClient,
    BankResearch,
    BankTrade,
    BankTransaction,
    User,
)
from app.db.session import SessionLocal
from app.servers.bank import DESTRUCTIVE, READ, WRITE, bank, settlement_date
from tests.test_mcp_gateway import INJECTION, Upstream

URL = "/api/bank/mcp"
TRADER = "eleanor.fairbanks@goldensocks.com"
PAYMENT = {
    "account_id": "ACC-0000001",
    "amount_usd": "250000.00",
    "currency": "USD",
    "beneficiary_name": "Harborford Asset Management SE",
    "beneficiary_account": "DE89 3704 0044 0532 0130 00",
    "destination_country": "DE",
    "purpose": "Invoice",
}
TRADE = {
    "account_id": "ACC-0000001",
    "trader_email": TRADER,
    "desk": "Equities - Cash",
    "asset_class": "Equities",
    "instrument": "SAP",
    "side": "BUY",
    "quantity": 1000,
    "price": "97.50",
    "currency": "EUR",
}


def account(account_id: str, **fields: Any) -> BankAccount:
    values = {
        "client_id": "CLT-000001",
        "account_type": "Prime Brokerage",
        "currency": "USD",
        "jurisdiction": "US",
        "opening_date": date(2015, 12, 1),
        "status": "OPEN",
        "cash_balance_usd": Decimal("1000000.00"),
        "credit_exposure_usd": Decimal(0),
        "margin_requirement_usd": Decimal(0),
        "portfolio_value_usd": Decimal(0),
        "internal_rating": "BBB+",
        "account_number": "2183660280",
        "swift_bic": "GOSOUS33",
        "iban_or_local_account": "025881398 2625020021",
        "authorized_signatory": "Eleanor Fairbanks",
        "restriction_flag": "NONE",
    }
    return BankAccount(account_id=account_id, **values | fields)


async def seed() -> None:
    trader = User(
        id=uuid.uuid4(),
        email=TRADER,
        name="Eleanor Fairbanks",
        employment_status="ACTIVE",
    )
    client = BankClient(
        client_id="CLT-000001",
        client_name="Beaconcrest Partners LP",
        client_type="Hedge Fund",
        country="United States",
        country_code="US",
        city="New York",
        sector="Financials",
        relationship_division="Global Banking & Markets",
        relationship_tier="Growth",
        onboarding_status="ACTIVE",
        risk_rating="MEDIUM",
        kyc_status="APPROVED",
        sanctions_screening="CLEAR",
        primary_rm_id=trader.id,
        aum_usd_mn=Decimal("585.19"),
        credit_limit_usd_mn=Decimal("179.36"),
        annual_revenue_usd_mn=Decimal("20.48"),
        tax_id="91-1771816",
        legal_address="71 State Street, New York 10032",
        contact_name="Eleanor Fairbanks",
        contact_email="eleanor.fairbanks@beaconcrestpartners.com",
        contact_phone="+1 837 825 8997",
        beneficial_owner="Widely held",
        internal_notes="Prime brokerage across 2 accounts.",
    )
    settled = BankTrade(
        trade_id="TRD-00000001",
        client_id="CLT-000001",
        account_id="ACC-0000001",
        desk="FICC - FX",
        asset_class="FX",
        instrument="USDJPY",
        side="BUY",
        quantity=9500000,
        price=Decimal("141.536"),
        notional_usd=Decimal("9500000"),
        currency="JPY",
        trade_timestamp=datetime(2026, 4, 6),
        settlement_date=date(2026, 4, 8),
        trader_id=trader.id,
        venue="OTC",
        pnl_usd=Decimal("1130.34"),
        var_1d_usd=Decimal("139437.39"),
        status="SETTLED",
        strategy="Client Flow",
        counterparty="Harborford Asset Management SE",
    )
    research = BankResearch(
        research_id="RES-0000001",
        title="SAP (SAP): Q1 2023 earnings preview",
        research_type="Equity Research",
        asset_class="Equities",
        sector="Technology",
        coverage_symbol="SAP",
        analyst_id=trader.id,
        publication_date=date(2023, 1, 2),
        audience="INTERNAL_ONLY",
        rating="NEUTRAL",
        target_price=Decimal("99.00"),
        embargo_until=date(2023, 1, 3),
        client_access_tier="Strategic",
        summary="We rate SAP Neutral.",
        source_model="Analyst Model",
        watermark="GIR-230102-NS45J3",
    )
    frozen = account("ACC-0000002", status="RESTRICTED", restriction_flag="LEGAL_HOLD")
    # The models have no relationships, so each step goes in after the rows it
    # refers to.
    steps = [[trader], [client], [account("ACC-0000001"), frozen], [settled, research]]
    async with SessionLocal.begin() as session:
        for rows in steps:
            session.add_all(rows)
            await session.flush()


@pytest.fixture
def data(db: None) -> None:
    asyncio.run(seed())


def call(tool: str, **arguments: Any) -> types.CallToolResult:
    async def run() -> types.CallToolResult:
        async with Client(bank) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def ok(tool: str, **arguments: Any) -> dict[str, Any]:
    result = call(tool, **arguments)
    assert result.is_error is not True, result.content
    assert result.structured_content is not None
    return result.structured_content


def message(result: types.CallToolResult) -> str:
    return "".join(b.text for b in result.content if isinstance(b, types.TextContent))


async def fetch[T](model: type[T], key: str) -> T | None:
    async with SessionLocal() as session:
        return await session.get(model, key)


def test_tools_say_whether_they_change_data() -> None:
    # when
    tools = {t.name: t.annotations for t in asyncio.run(bank.list_tools())}

    # then
    assert tools["get_client"] == READ
    assert tools["book_trade"] == WRITE
    assert tools["initiate_payment"] == DESTRUCTIVE


def test_get_client_gives_profile_with_accounts(data: None) -> None:
    # when
    result = ok("get_client", client_id="CLT-000001")

    # then
    assert result["client"]["tax_id"] == "91-1771816"
    assert [a["account_id"] for a in result["accounts"]] == [
        "ACC-0000001",
        "ACC-0000002",
    ]


def test_search_clients_by_part_of_name(data: None) -> None:
    # when
    result = ok("search_clients", name="beacon")

    # then
    assert [c["client_id"] for c in result["clients"]] == ["CLT-000001"]


def test_unknown_client_is_an_error(data: None) -> None:
    # when
    result = call("get_client", client_id="CLT-999999")

    # then
    assert result.is_error is True
    assert "No client CLT-999999" in message(result)


def test_payment_waits_and_reserves_balance(data: None) -> None:
    # when
    payment = ok("initiate_payment", **PAYMENT)["transaction"]

    # then
    assert payment["transaction_id"] == "TXN-000000001"
    assert payment["status"] == "PENDING"
    available = ok("get_account", account_id="ACC-0000001")["available_balance_usd"]
    assert Decimal(available) == Decimal("750000.00")


def test_payment_over_available_balance_is_refused(data: None) -> None:
    # given
    ok("initiate_payment", **PAYMENT | {"amount_usd": "900000.00"})

    # when
    result = call("initiate_payment", **PAYMENT | {"amount_usd": "200000.00"})

    # then
    assert result.is_error is True
    assert "Insufficient available balance" in message(result)
    assert asyncio.run(fetch(BankTransaction, "TXN-000000002")) is None


def test_payment_from_frozen_account_is_refused(data: None) -> None:
    # when
    result = call("initiate_payment", **PAYMENT | {"account_id": "ACC-0000002"})

    # then
    assert result.is_error is True
    assert "LEGAL_HOLD" in message(result)


def test_flagged_payment_is_held_with_alert(data: None) -> None:
    # given
    payment = ok("initiate_payment", **PAYMENT)["transaction"]

    # when
    flagged = ok(
        "flag_transaction",
        transaction_id=payment["transaction_id"],
        reason="Beneficiary not seen before",
    )["transaction"]

    # then
    assert flagged["status"] == "HELD"
    assert flagged["alert_id"].endswith("-000001")
    assert "Beneficiary not seen before" in flagged["investigation_notes"]


def test_restricted_account_opens_again(data: None) -> None:
    # given
    ok("restrict_account", account_id="ACC-0000001", restriction="RISK_REVIEW")

    # when
    lifted = ok("lift_restriction", account_id="ACC-0000001")["account"]

    # then
    assert (lifted["status"], lifted["restriction_flag"]) == ("OPEN", "NONE")


def test_legal_hold_is_not_lifted(data: None) -> None:
    # when
    result = call("lift_restriction", account_id="ACC-0000002")

    # then
    assert result.is_error is True
    assert "legal hold" in message(result)


def test_booked_trade_settles_on_next_business_day(data: None) -> None:
    # when
    trade = ok("book_trade", **TRADE)["trade"]

    # then
    assert trade["trade_id"] == "TRD-00000002"
    assert trade["status"] == "BOOKED"
    assert Decimal(trade["notional_usd"]) == Decimal("97500.00")


def test_settlement_skips_weekend() -> None:
    # given
    friday = date(2026, 10, 2)

    # when / then
    assert settlement_date("Rates", friday) == date(2026, 10, 6)


def test_trade_by_unknown_trader_is_refused(data: None) -> None:
    # when
    result = call("book_trade", **TRADE | {"trader_email": "x@evil.com"})

    # then
    assert result.is_error is True
    assert "not an active trader" in message(result)


def test_booked_trade_is_cancelled(data: None) -> None:
    # given
    trade = ok("book_trade", **TRADE)["trade"]

    # when
    cancelled = ok("cancel_trade", trade_id=trade["trade_id"], reason="Fat finger")

    # then
    assert cancelled["trade"]["status"] == "CANCELLED"


def test_settled_trade_is_not_cancelled(data: None) -> None:
    # when
    result = call("cancel_trade", trade_id="TRD-00000001", reason="Undo")

    # then
    assert result.is_error is True
    assert "SETTLED" in message(result)


def test_contact_change_is_noted(data: None) -> None:
    # when
    client = ok(
        "update_client_contact", client_id="CLT-000001", contact_phone="+1 212 555"
    )["client"]

    # then
    assert client["contact_phone"] == "+1 212 555"
    assert "Contact changed: contact_phone" in client["internal_notes"]


def test_note_is_added_to_history(data: None) -> None:
    # when
    client = ok("add_client_note", client_id="CLT-000001", note="Met the CFO")

    # then
    notes = client["client"]["internal_notes"].splitlines()
    assert notes[0] == "Prime brokerage across 2 accounts."
    assert notes[1].endswith("Met the CFO")


def test_research_by_symbol(data: None) -> None:
    # when
    result = ok("search_research", symbol="sap")

    # then
    assert [r["research_id"] for r in result["research"]] == ["RES-0000001"]


@pytest.mark.parametrize("token", ["", "bank-secret"])
@pytest.mark.parametrize("header", [None, "Bearer wrong"])
def test_http_needs_the_bank_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    header: str | None,
) -> None:
    # given
    monkeypatch.setattr(settings, "bank_mcp_token", token)
    headers = {"Authorization": header} if header else {}

    # when / then
    assert client.post(URL, headers=headers, json={}).status_code == 401


def test_http_lists_the_tools(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "bank_mcp_token", "bank-secret")
    headers = {
        "Authorization": "Bearer bank-secret",
        "Accept": "application/json, text/event-stream",
    }
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    # when
    response = client.post(URL, headers=headers, json=request)

    # then
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {"get_client", "initiate_payment"} <= names


@asynccontextmanager
async def connect(server: UpstreamServer) -> AsyncIterator[Client]:
    async with Client(bank) as client:
        yield client


def test_gateway_blocks_injected_note_before_it_is_written(data: None) -> None:
    # given
    async def servers() -> list[Upstream]:
        return [Upstream("bank")]

    gateway = McpGateway(control_layer(), connect, servers)
    arguments = {"client_id": "CLT-000001", "note": INJECTION}

    # when
    result = asyncio.run(gateway.call_tool("bank__add_client_note", arguments, "a"))

    # then
    assert result.is_error is True
    client = asyncio.run(fetch(BankClient, "CLT-000001"))
    assert client is not None
    assert INJECTION not in client.internal_notes


def test_gateway_lets_a_plain_payment_through(data: None) -> None:
    # given
    async def servers() -> list[Upstream]:
        return [Upstream("bank")]

    gateway = McpGateway(control_layer(), connect, servers)

    # when
    result = asyncio.run(gateway.call_tool("bank__initiate_payment", PAYMENT, "a"))

    # then
    assert result.is_error is not True

    async def pending() -> list[str]:
        async with SessionLocal() as session:
            statement = select(BankTransaction.status)
            return list(await session.scalars(statement))

    assert asyncio.run(pending()) == ["PENDING"]
