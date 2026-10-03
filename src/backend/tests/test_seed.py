from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Table

from app.db.base import Base
from scripts.seed import bank_tables, load


@pytest.mark.parametrize("table", bank_tables(), ids=lambda t: t.name)
def test_every_bank_table_has_data(table: Table) -> None:
    # when
    columns, rows = load(table)

    # then
    assert set(columns) == set(table.columns.keys())
    assert rows


def test_load_parses_values_by_column_type() -> None:
    # given
    table = Base.metadata.tables["bank_trades"]

    # when
    columns, rows = load(table)

    # then
    trade = dict(zip(columns, rows[0], strict=True))
    assert trade["trade_id"] == "TRD-00000001"
    assert trade["quantity"] == 438196
    assert trade["price_demo"] == Decimal("1481.515")
    assert trade["trade_timestamp"] == datetime(2026, 6, 27, 13, 32)
    assert trade["settlement_date"] == date(2026, 6, 29)


def test_load_turns_empty_values_into_null() -> None:
    # given
    table = Base.metadata.tables["bank_research"]

    # when
    columns, rows = load(table)

    # then
    target_price = columns.index("target_price_demo")
    assert None in [row[target_price] for row in rows]


def test_load_reads_the_identity_profiles() -> None:
    # when
    columns, rows = load(Base.metadata.tables["bank_identity_profiles"])

    # then
    permission = columns.index("permission")
    assert {row[permission] for row in rows} == {"LOW", "STANDARD", "PRIVILEGED"}
