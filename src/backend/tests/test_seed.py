import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from typing import Any

import pytest
from sqlalchemy import Table

from app.core.simulator import ACCOUNTS_BY_ACCESS
from app.db.base import Base
from app.db.policy import DEFAULT_ROLE
from app.servers import bank
from scripts.policies import POLICIES
from scripts.seed import OWN_COLUMNS, challenge_staff, load, seeded_tables


@cache
def rows(table: str) -> list[dict[str, Any]]:
    name = table if table == "users" else f"bank_{table}"
    columns, values = load(Base.metadata.tables[name])
    return [dict(zip(columns, row, strict=True)) for row in values]


@pytest.mark.parametrize("table", seeded_tables(), ids=lambda t: t.name)
def test_every_bank_table_has_data(table: Table) -> None:
    # when
    columns, values = load(table)

    # then
    assert set(columns) == set(table.columns.keys()) - OWN_COLUMNS
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


@pytest.mark.parametrize("table", seeded_tables(), ids=lambda t: t.name)
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
    users = {u["id"]: u for u in rows("users")}

    # when
    pairs = {(t["desk"], users[t["trader_id"]]["team"]) for t in rows("trades")}

    # then
    assert all(desk == team for desk, team in pairs)


def test_no_two_users_share_a_full_name() -> None:
    # given
    names = [u["name"] for u in rows("users")]

    # when
    repeated = [name for name, n in Counter(names).items() if n > 1]

    # then
    assert repeated == []


def test_alerts_carry_investigation_notes() -> None:
    # when
    alerts = [t for t in rows("transactions") if t["alert_id"]]

    # then
    assert alerts
    assert all(t["investigation_notes"] for t in alerts)


def test_the_staff_are_the_challenge_accounts_one_per_role() -> None:
    # given
    columns, staff = load(next(t for t in seeded_tables() if t.name == "users"))

    # when
    picked = [
        dict(zip(columns, row, strict=True)) for row in challenge_staff(columns, staff)
    ]

    # then
    assert [u["title"] for u in picked] == ACCOUNTS_BY_ACCESS
    assert all(u["employment_status"] == "ACTIVE" for u in picked)
    assert all(u["manager_id"] is None for u in picked)


def test_every_role_has_a_policy() -> None:
    # when
    roles = set(POLICIES) - {DEFAULT_ROLE}

    # then
    assert roles == set(ACCOUNTS_BY_ACCESS)


def test_policies_name_only_bank_tools() -> None:
    # when
    tools = {name for policy in POLICIES.values() for name in policy.tools}

    # then
    assert tools
    assert all(
        name.startswith("bank__") and callable(getattr(bank, name[6:], None))
        for name in tools
    )
