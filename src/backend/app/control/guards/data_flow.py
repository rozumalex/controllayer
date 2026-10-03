"""Data flow guard: follows data across the tool calls of a session.

The other guards look at one message at a time. This one remembers what the
earlier tool results carried, and blocks a later call that would send data
out to a place the session has not seen: the agent reads a client's PII,
then pays to an account that no result named. It is the idea of Invariant
Labs' flow policies, for the bank's one way out that matters most.

A result is sensitive when it holds PII, by the sensitive data guard's
patterns, or data above the role's clearance, by the clearance guard. A call
sends data out when its arguments name a destination: a beneficiary account
or IBAN, or a new contact email or phone. A destination is seen when an
earlier result had the same value in an identifier field, such as account_id
or beneficiary_account. Free text doesn't count, so a note planted in a
record can't make an account look seen.

The guard remembers labels and keyed hashes only, never the values, and
saves them with its verdict, so the next request of the same user, such as
the next question or an external client's next call, starts from them."""

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Iterable, Iterator
from typing import Any

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.control.guard import Guard
from app.control.guards.sensitive_data import PII, redact
from app.core.config import settings
from app.core.schema.policy import ToolAction

# The fields of a result that name an account or a contact.
IDENTIFIER = re.compile(r"(?:^|_)(?:account(?:_id)?|iban|email|phone)$", re.I)
# The arguments of a call that name where the data goes.
DESTINATION = re.compile(
    r"(?:beneficiary|recipient|payee|destination|counterparty|to)_"
    r"(?:account(?:_id)?|iban|email|phone)|iban|contact_(?:email|phone)",
    re.I,
)
ABOVE_CLEARANCE = "above_clearance"
FIND_PII = {pattern.label: ToolAction.REDACT for pattern in PII}
# Without a key set, each process makes its own: the hashes then match only
# within one process.
KEY = settings.control_flow_hash_key.encode() or secrets.token_bytes(32)


def fingerprint(value: str) -> str:
    """A keyed hash of the value, so the events never hold it. Spaces and
    case don't count, so an IBAN matches with or without its spaces."""
    normal = "".join(value.split()).casefold()
    return hmac.new(KEY, normal.encode(), hashlib.sha256).hexdigest()[:32]


def fields(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    """Every text in the value with the name of the field that holds it. A
    text that is JSON, like a tool's text block, is read as its data."""
    if isinstance(value, dict):
        for name, item in value.items():
            yield from fields(item, str(name))
    elif isinstance(value, list):
        for item in value:
            yield from fields(item, key)
    elif isinstance(value, str):
        try:
            data = json.loads(value)
        except ValueError:
            data = None
        if isinstance(data, dict | list):
            yield from fields(data, key)
        else:
            yield key, value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        yield key, str(value)


class DataFlowGuard:
    """Blocks a call that sends data to a destination the session has not
    seen, once the session has read sensitive data.

    labels and seen are what earlier requests of the user found: the kinds of
    sensitive data read and the hashes of the identifiers seen. clearance is
    the role's clearance guard, to tell data above the clearance."""

    name = "data_flow"

    def __init__(
        self,
        labels: Iterable[str] = (),
        seen: Iterable[str] = (),
        clearance: Guard | None = None,
    ) -> None:
        self.labels = set(labels)
        self.seen = set(seen)
        self.clearance = clearance

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.direction is Direction.OUTBOUND:
            return await self.remember(envelope)
        if envelope.direction is not Direction.INBOUND:
            return Verdict(Action.ALLOW, self.name)
        destinations = {
            fingerprint(text)
            for key, text in fields(envelope.payload)
            if DESTINATION.fullmatch(key) and text.strip()
        }
        new = destinations - self.seen
        if not new or not self.labels:
            return Verdict(Action.ALLOW, self.name, score=0.0)
        reason = (
            f"sensitive data read in this session ({', '.join(sorted(self.labels))})"
            f", then {envelope.tool} to {len(new)} destination(s) no result named"
        )
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)

    async def remember(self, envelope: Envelope) -> Verdict:
        """Notes what a tool result carried, and saves it with the verdict."""
        found: dict[str, ToolAction] = {}
        redact(envelope.payload, FIND_PII, found)
        labels = set(found)
        if self.clearance:
            verdict = await self.clearance.inspect(envelope)
            if verdict.action is not Action.ALLOW:
                labels.add(ABOVE_CLEARANCE)
        seen = {
            fingerprint(text)
            for key, text in fields(envelope.payload)
            if IDENTIFIER.search(key) and text.strip()
        }
        self.labels |= labels
        self.seen |= seen
        memory = {"labels": sorted(labels), "seen": sorted(seen)}
        return Verdict(
            Action.ALLOW,
            self.name,
            score=0.0,
            memory=memory if labels or seen else None,
        )
