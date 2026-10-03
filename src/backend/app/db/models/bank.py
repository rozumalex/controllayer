"""Golden Socks, the bank behind the demo. Every name, number and identifier
is made up. scripts/generate_bank_data.py writes the rows and `./dev seed`
loads them. The bank's staff are rows in users.

The tables share the bank_ prefix, so they stay apart from the app's own.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Amounts in US dollars, to the cent.
Money = Numeric(18, 2)


class BankClient(Base):
    __tablename__ = "bank_clients"

    client_id: Mapped[str] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(index=True)
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
    primary_rm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
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


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    account_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("bank_clients.client_id"), index=True
    )
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


class BankTrade(Base):
    __tablename__ = "bank_trades"

    trade_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("bank_clients.client_id"), index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.account_id"), index=True
    )
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
    trader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    venue: Mapped[str]
    pnl_usd: Mapped[Decimal] = mapped_column(Money)
    var_1d_usd: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str]
    strategy: Mapped[str]
    counterparty: Mapped[str]
    internal_comment: Mapped[str | None]


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    transaction_id: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("bank_clients.client_id"), index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.account_id"), index=True
    )
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


class BankResearch(Base):
    __tablename__ = "bank_research"

    research_id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    research_type: Mapped[str]
    asset_class: Mapped[str]
    sector: Mapped[str]
    coverage_symbol: Mapped[str] = mapped_column(index=True)
    analyst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
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


class BankDataCatalog(Base):
    """The sensitivity of every field above: PUBLIC, INTERNAL, CONFIDENTIAL
    or RESTRICTED. table_name holds the name without the bank_ prefix."""

    __tablename__ = "bank_data_catalog"

    table_name: Mapped[str] = mapped_column(primary_key=True)
    field_name: Mapped[str] = mapped_column(primary_key=True)
    sensitivity: Mapped[str]
    rationale: Mapped[str]


class BankIdentityProfile(Base):
    """The demo users and their permission: LOW, STANDARD or PRIVILEGED."""

    __tablename__ = "bank_identity_profiles"

    identity: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    permission: Mapped[str]
    description: Mapped[str]
