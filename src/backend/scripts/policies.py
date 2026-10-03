"""The policy of each Golden Socks role, and the default for any other role.

A role is a job title in users. Tools are named as the gateway serves them
when the bank MCP server is registered as `bank`, as the README shows.
"""

from decimal import Decimal

from app.core.schema.policy import Budget, Clearance, PolicySettings, ToolAction
from app.db.policy import DEFAULT_ROLE

ALLOW, REDACT, BLOCK = ToolAction.ALLOW, ToolAction.REDACT, ToolAction.BLOCK

# Look up clients, accounts, trades and research.
READ = {
    "bank__search_clients": ALLOW,
    "bank__get_client": ALLOW,
    "bank__get_account": ALLOW,
    "bank__list_transactions": ALLOW,
    "bank__list_trades": ALLOW,
    "bank__search_research": ALLOW,
}
# Look after a client's relationship.
COVERAGE = {
    "bank__add_client_note": ALLOW,
    "bank__update_client_contact": ALLOW,
}
# Freeze an account, raise an AML alert, or open the account again.
CONTROL = {
    "bank__flag_transaction": ALLOW,
    "bank__restrict_account": ALLOW,
    "bank__lift_restriction": ALLOW,
}
# Move money and book or cancel trades for a client.
TRADING = {
    "bank__book_trade": ALLOW,
    "bank__cancel_trade": ALLOW,
    "bank__initiate_payment": ALLOW,
}


def budget(tokens: int | None, usd: int | None) -> Budget:
    return Budget(
        monthly_tokens=tokens, monthly_usd=Decimal(usd) if usd is not None else None
    )


POLICIES: dict[str, PolicySettings] = {
    # A new job title reads internal data, and calls no tool until its role
    # gets a policy.
    DEFAULT_ROLE: PolicySettings(
        injection_threshold=0.6,
        clearance=Clearance.INTERNAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1-mini"],
        budget=budget(500_000, 10),
        default_tool_action=BLOCK,
        tools={"bank__search_clients": ALLOW, "bank__search_research": ALLOW},
    ),
    # Juniors: read and take notes, but move nothing. Balances come back
    # redacted.
    "Analyst": PolicySettings(
        injection_threshold=0.6,
        clearance=Clearance.INTERNAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1-mini", "gpt-4o-mini"],
        budget=budget(2_000_000, 25),
        default_tool_action=BLOCK,
        tools={**READ, "bank__get_account": REDACT, "bank__add_client_note": ALLOW},
    ),
    "Associate": PolicySettings(
        injection_threshold=0.65,
        clearance=Clearance.INTERNAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1-mini", "gpt-4o-mini"],
        budget=budget(3_000_000, 40),
        default_tool_action=BLOCK,
        tools={**READ, **COVERAGE},
    ),
    # Seniors cover clients and trade for them. Freezing accounts stays with
    # risk and compliance.
    "Vice President": PolicySettings(
        injection_threshold=0.7,
        clearance=Clearance.CONFIDENTIAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1", "gpt-4.1-mini"],
        budget=budget(5_000_000, 100),
        default_tool_action=ALLOW,
        tools={
            "bank__initiate_payment": BLOCK,
            "bank__restrict_account": BLOCK,
            "bank__lift_restriction": BLOCK,
        },
    ),
    "Executive Director": PolicySettings(
        injection_threshold=0.7,
        clearance=Clearance.CONFIDENTIAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        budget=budget(8_000_000, 200),
        default_tool_action=ALLOW,
        tools={"bank__restrict_account": BLOCK, "bank__lift_restriction": BLOCK},
    ),
    "Managing Director": PolicySettings(
        injection_threshold=0.75,
        clearance=Clearance.RESTRICTED,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini", "o4-mini"],
        budget=budget(None, 500),
        default_tool_action=ALLOW,
        tools={"bank__restrict_account": BLOCK, "bank__lift_restriction": BLOCK},
    ),
    # Second line: sees everything, can stop money, never moves it.
    "Compliance Officer": PolicySettings(
        injection_threshold=0.7,
        clearance=Clearance.RESTRICTED,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        budget=budget(6_000_000, 150),
        default_tool_action=BLOCK,
        tools={**READ, **CONTROL, "bank__add_client_note": ALLOW},
    ),
    "Risk Manager": PolicySettings(
        injection_threshold=0.7,
        clearance=Clearance.CONFIDENTIAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        budget=budget(5_000_000, 120),
        default_tool_action=BLOCK,
        tools={
            **READ,
            "bank__flag_transaction": ALLOW,
            "bank__restrict_account": ALLOW,
        },
    ),
    # Middle office: settles payments and trades, sees client data redacted.
    "Operations Specialist": PolicySettings(
        injection_threshold=0.65,
        clearance=Clearance.CONFIDENTIAL,
        above_clearance=REDACT,
        allowed_models=["gpt-4.1-mini", "gpt-4o-mini"],
        budget=budget(3_000_000, 40),
        default_tool_action=BLOCK,
        tools={
            **READ,
            "bank__get_client": REDACT,
            "bank__search_research": BLOCK,
            "bank__initiate_payment": ALLOW,
            "bank__cancel_trade": ALLOW,
            "bank__flag_transaction": ALLOW,
        },
    ),
    # Behind the information barrier: research only, no client or trade data.
    "Research Analyst": PolicySettings(
        injection_threshold=0.7,
        clearance=Clearance.INTERNAL,
        above_clearance=BLOCK,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        budget=budget(4_000_000, 80),
        default_tool_action=BLOCK,
        tools={"bank__search_research": ALLOW},
    ),
    # Builds the systems, never touches client data.
    "Engineer": PolicySettings(
        injection_threshold=0.5,
        clearance=Clearance.PUBLIC,
        above_clearance=BLOCK,
        allowed_models=["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini", "o4-mini"],
        budget=budget(4_000_000, 60),
        default_tool_action=BLOCK,
    ),
}
