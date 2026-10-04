"""Golden Socks, the bank behind the demo. Every name, number and identifier
is made up. scripts/generate_bank_data.py writes the rows and `./dev seed`
loads them. The bank's staff are rows in users.

The tables share the bank_ prefix, so they stay apart from the app's own.

Every organization has its own copy of the bank: the demo's, which the seed
loads, and one in each demo sandbox, copied from it (see app/db/sandbox.py).
So every key starts with org_id. The tables have no foreign keys: a sandbox
copies some 200,000 rows, and checking a key for each takes seconds, where
the copy alone takes a fraction of one. The rows come from the seed, a copy
or a bank tool that checks what it refers to.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Amounts in US dollars, to the cent.
Money = Numeric(18, 2)


class OrgOwned:
    """The organization whose copy of the bank the row is in, first in the
    key."""

    org_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, sort_order=-1)


class BankClient(OrgOwned, Base):
    __tablename__ = "bank_clients"
    __table_args__ = (
        Index("ix_bank_clients_org_id_client_name", "org_id", "client_name"),
    )

    client_id: Mapped[str] = mapped_column(primary_key=True)
    client_name: Mapped[str]
    client_type: Mapped[str]
    country: Mapped[str]
    country_code: Mapped[str]
    city: Mapped[str]
    sector: Mapped[str]
    relationship_division: Mapped[str]
    relationship_tier: Mapped[str]
    onboarding_status: Mapped[str]
    risk_rating: Mapped[str]
    kyc_status: Mapped[str]
    sanctions_screening: Mapped[str]
    primary_rm_id: Mapped[uuid.UUID]
    aum_usd_mn: Mapped[Decimal] = mapped_column(Money)
    credit_limit_usd_mn: Mapped[Decimal] = mapped_column(Money)
    annual_revenue_usd_mn: Mapped[Decimal] = mapped_column(Money)
    tax_id: Mapped[str]
    legal_address: Mapped[str]
    contact_name: Mapped[str]
    contact_email: Mapped[str]
    contact_phone: Mapped[str]
    beneficial_owner: Mapped[str]
    internal_notes: Mapped[str]


class BankAccount(OrgOwned, Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        Index("ix_bank_accounts_org_id_client_id", "org_id", "client_id"),
    )

    account_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str]
    account_type: Mapped[str]
    currency: Mapped[str]
    jurisdiction: Mapped[str]
    opening_date: Mapped[date]
    status: Mapped[str]
    cash_balance_usd: Mapped[Decimal] = mapped_column(Money)
    credit_exposure_usd: Mapped[Decimal] = mapped_column(Money)
    margin_requirement_usd: Mapped[Decimal] = mapped_column(Money)
    portfolio_value_usd: Mapped[Decimal] = mapped_column(Money)
    internal_rating: Mapped[str]
    account_number: Mapped[str]
    swift_bic: Mapped[str]
    iban_or_local_account: Mapped[str]
    authorized_signatory: Mapped[str]
    restriction_flag: Mapped[str]


class BankTrade(OrgOwned, Base):
    __tablename__ = "bank_trades"
    __table_args__ = (
        Index("ix_bank_trades_org_id_client_id", "org_id", "client_id"),
        Index("ix_bank_trades_org_id_account_id", "org_id", "account_id"),
    )

    trade_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str]
    account_id: Mapped[str]
    desk: Mapped[str]
    asset_class: Mapped[str]
    instrument: Mapped[str]
    side: Mapped[str]
    # Shares, contracts, or the face value or base currency amount.
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    notional_usd: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str]
    trade_timestamp: Mapped[datetime]
    settlement_date: Mapped[date]
    trader_id: Mapped[uuid.UUID]
    venue: Mapped[str]
    pnl_usd: Mapped[Decimal] = mapped_column(Money)
    var_1d_usd: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str]
    strategy: Mapped[str]
    counterparty: Mapped[str]
    internal_comment: Mapped[str | None]


class BankTransaction(OrgOwned, Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        Index("ix_bank_transactions_org_id_client_id", "org_id", "client_id"),
        Index("ix_bank_transactions_org_id_account_id", "org_id", "account_id"),
    )

    transaction_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str]
    account_id: Mapped[str]
    transaction_type: Mapped[str]
    amount_usd: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str]
    timestamp: Mapped[datetime]
    origin_country: Mapped[str]
    destination_country: Mapped[str]
    beneficiary_name: Mapped[str]
    beneficiary_account: Mapped[str]
    purpose: Mapped[str]
    channel: Mapped[str]
    aml_risk_score: Mapped[int]
    fraud_score: Mapped[int]
    status: Mapped[str]
    alert_id: Mapped[str | None]
    investigation_notes: Mapped[str | None]
    source_system: Mapped[str]


class BankResearch(OrgOwned, Base):
    __tablename__ = "bank_research"
    __table_args__ = (
        Index("ix_bank_research_org_id_coverage_symbol", "org_id", "coverage_symbol"),
    )

    research_id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    research_type: Mapped[str]
    asset_class: Mapped[str]
    sector: Mapped[str]
    coverage_symbol: Mapped[str]
    analyst_id: Mapped[uuid.UUID]
    publication_date: Mapped[date]
    audience: Mapped[str]
    rating: Mapped[str]
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    embargo_until: Mapped[date]
    client_access_tier: Mapped[str]
    summary: Mapped[str]
    internal_draft_notes: Mapped[str | None]
    source_model: Mapped[str]
    # A unique marker per report: if it shows up in an answer, the report
    # leaked.
    watermark: Mapped[str]


class BankDataCatalog(OrgOwned, Base):
    """The sensitivity of every field above: PUBLIC, INTERNAL, CONFIDENTIAL
    or RESTRICTED. table_name holds the name without the bank_ prefix."""

    __tablename__ = "bank_data_catalog"

    table_name: Mapped[str] = mapped_column(primary_key=True)
    field_name: Mapped[str] = mapped_column(primary_key=True)
    sensitivity: Mapped[str]
    rationale: Mapped[str]


class BankIdentityProfile(OrgOwned, Base):
    """The demo users and their permission: LOW, STANDARD or PRIVILEGED."""

    __tablename__ = "bank_identity_profiles"

    identity: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    permission: Mapped[str]
    description: Mapped[str]
