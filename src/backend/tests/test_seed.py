import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from typing import Any

import pytest
from sqlalchemy import Table

from app.db.base import Base
from scripts.seed import bank_tables, load


@cache
def rows(table: str) -> list[dict[str, Any]]:
    columns, values = load(Base.metadata.tables[f"bank_{table}"])
    return [dict(zip(columns, row, strict=True)) for row in values]


@pytest.mark.parametrize("table", bank_tables(), ids=lambda t: t.name)
def test_every_bank_table_has_data(table: Table) -> None:
    # when
    columns, values = load(table)

    # then
    assert set(columns) == set(table.columns.keys())
    assert values


def test_load_parses_values_by_column_type() -> None:
    # when
    trade = rows("trades")[0]

    # then
    assert isinstance(trade["quantity"], int)
    assert isinstance(trade["price"], Decimal)
    assert isinstance(trade["trade_timestamp"], datetime)
    assert isinstance(trade["settlement_date"], date)


def test_load_turns_empty_values_into_null() -> None:
    # when
    research = rows("research")

    # then
    assert None in {r["target_price"] for r in research}


def test_load_reads_the_identity_profiles() -> None:
    # when
    profiles = rows("identity_profiles")

    # then
    assert {p["permission"] for p in profiles} == {"LOW", "STANDARD", "PRIVILEGED"}


@pytest.mark.parametrize("table", bank_tables(), ids=lambda t: t.name)
def test_no_placeholder_values(table: Table) -> None:
    # given
    markers = re.compile(r"\b(demo|example|synthetic|test|dummy|fake)\b", re.I)

    # when
    values = rows(table.name.removeprefix("bank_"))
    text = " ".join(str(v) for row in values for v in row.values())

    # then
    assert markers.findall(text) == []


def test_client_aum_is_the_sum_of_its_accounts() -> None:
    # given
    held: dict[str, Decimal] = defaultdict(Decimal)
    for a in rows("accounts"):
        held[a["client_id"]] += a["cash_balance_usd"] + a["portfolio_value_usd"]

    # when
    gaps = [
        c["client_id"]
        for c in rows("clients")
        if abs(c["aum_usd_mn"] * 1_000_000 - held[c["client_id"]]) > 10_000
    ]

    # then
    assert gaps == []


def test_trades_book_on_the_clients_open_accounts() -> None:
    # given
    accounts = {a["account_id"]: a for a in rows("accounts")}

    # when
    wrong = [
        t["trade_id"]
        for t in rows("trades")
        if accounts[t["account_id"]]["client_id"] != t["client_id"]
        or accounts[t["account_id"]]["status"] != "OPEN"
    ]

    # then
    assert wrong == []


def test_traders_sit_on_the_trade_desk() -> None:
    # given
    employees = {e["employee_id"]: e for e in rows("employees")}

    # when
    pairs = {
        (t["desk"], employees[t["trader_id"]]["desk_or_team"]) for t in rows("trades")
    }

    # then
    assert all(desk == team for desk, team in pairs)


def test_alerts_carry_investigation_notes() -> None:
    # when
    alerts = [t for t in rows("transactions") if t["alert_id"]]

    # then
    assert alerts
    assert all(t["investigation_notes"] for t in alerts)
