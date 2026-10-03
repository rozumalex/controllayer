"""Deterministic PII and secrets guard: finds them in free text by pattern.

The clearance guard hides the fields the bank's data catalog knows. This guard
covers the text the catalog can't label: user prompts, notes, research and
tool call arguments. The role's policy says what happens to each kind of PII:
allow, redact or block. A kind the policy doesn't name has the catalog level
of the field that holds it, so the clearance decides, as it does for fields.
Secrets are never anyone's to see: a prompt, tool call or tool result that
carries one is blocked, so no model gets it.

A pattern with a checksum, such as a card number, matches only when the
checksum holds, so an order number doesn't count as a card."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.control.envelope import Action, Direction, Envelope, Verdict
from app.control.guards.policy import (
    SEPARATOR,
    above,
    result_clearance,
    tool_action,
)
from app.core.schema.policy import Clearance, PiiKind, ToolAction

# A field named like a secret holds one, whatever its value looks like.
SECRET_NAME = r"password|passwd|pwd|secret|api[_-]?key|(?:access_|auth_)?token"
SECRET_FIELD = re.compile(SECRET_NAME, re.I)
PASSWORD = "password"
# The envelope tool of a user prompt in the chat.
PROMPT = "user_prompt"


@dataclass(frozen=True)
class Pattern:
    """A kind of sensitive data. If the regex has a group named value, only
    that group is redacted, and the rest of the match is kept."""

    # A PiiKind for PII.
    label: str
    regex: re.Pattern[str]
    # The catalog level of the data; None for a secret.
    level: Clearance | None
    valid: Callable[[str], bool] = lambda _: True


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def luhn(text: str) -> bool:
    numbers = [int(d) for d in reversed(digits(text))]
    doubled = [n * 2 - 9 if n > 4 else n * 2 for n in numbers[1::2]]
    return (sum(numbers[::2]) + sum(doubled)) % 10 == 0


def iban(text: str) -> bool:
    code = re.sub(r"\s", "", text).upper()
    moved = code[4:] + code[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def pesel(text: str) -> bool:
    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    numbers = [int(d) for d in text]
    total = sum(w * n for w, n in zip(weights, numbers[:10], strict=True))
    return (10 - total % 10) % 10 == numbers[10]


PII = [
    # Contact data is confidential in the catalog.
    Pattern(
        PiiKind.EMAIL,
        re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
        Clearance.CONFIDENTIAL,
    ),
    Pattern(
        PiiKind.PHONE,
        re.compile(r"(?<![\w+])\+\d{1,3}(?:[ -]?\d){6,12}\b"),
        Clearance.CONFIDENTIAL,
    ),
    # Account numbers and national identifiers are restricted.
    Pattern(
        PiiKind.IBAN,
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
        Clearance.RESTRICTED,
        iban,
    ),
    Pattern(
        PiiKind.PAYMENT_CARD,
        re.compile(r"(?<![\d+-])\d(?:[ -]?\d){12,18}(?![\d-])"),
        Clearance.RESTRICTED,
        luhn,
    ),
    Pattern(
        PiiKind.PESEL, re.compile(r"(?<!\d)\d{11}(?!\d)"), Clearance.RESTRICTED, pesel
    ),
]

SECRETS = [
    Pattern(
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r".*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
            re.S,
        ),
        None,
    ),
    Pattern("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    Pattern(
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{60,})\b"),
        None,
    ),
    Pattern("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), None),
    Pattern("api_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"), None),
    Pattern("stripe_key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}"), None),
    Pattern("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), None),
    Pattern(
        "jwt",
        re.compile(r"\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,}"),
        None,
    ),
    Pattern("bearer_token", re.compile(r"\bBearer\s+[\w.~+/-]{20,}=*", re.I), None),
    Pattern(
        PASSWORD,
        re.compile(
            rf"\b(?:{SECRET_NAME})\b[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s\"',;]{{6,}})",
            re.I,
        ),
        None,
    ),
]

# Secrets first, so a PII pattern doesn't break a key apart.
PATTERNS = [*SECRETS, *PII]
SECRET_LABELS = {pattern.label for pattern in SECRETS}


class SensitiveDataGuard:
    """Applies the role's policy to the PII in prompts and tool results, and
    blocks every secret, by pattern.

    A tool the policy marks redact has all its PII redacted at least. In a
    tool call, PII passes, because the agent needs it to look things up."""

    name = "sensitive_data"

    def __init__(
        self,
        pii: Mapping[PiiKind, ToolAction],
        clearance: Clearance,
        above_clearance: ToolAction,
        tools: Mapping[str, ToolAction],
        default: ToolAction,
    ) -> None:
        self.pii = pii
        self.clearance = clearance
        self.above_clearance = above_clearance
        self.tools = tools
        self.default = default

    def actions(self, envelope: Envelope) -> dict[str, ToolAction]:
        """What happens to each kind of data found in the envelope."""
        actions = {pattern.label: ToolAction.BLOCK for pattern in SECRETS}
        if envelope.direction is Direction.INBOUND and envelope.tool != PROMPT:
            return actions
        clearance, above_clearance = self.clearance, self.above_clearance
        redacts = False
        if envelope.direction is Direction.OUTBOUND:
            name = f"{envelope.server}{SEPARATOR}{envelope.tool}"
            redacts = tool_action(self.tools, self.default, name) is ToolAction.REDACT
            clearance, above_clearance = result_clearance(
                self.tools, self.default, name, clearance, above_clearance
            )
        for pattern in PII:
            level = pattern.level or Clearance.RESTRICTED
            fallback = above_clearance if above(level, clearance) else ToolAction.ALLOW
            action = self.pii.get(PiiKind(pattern.label), fallback)
            # A tool the policy marks redact redacts what it would allow.
            if redacts and action is ToolAction.ALLOW:
                action = ToolAction.REDACT
            actions[pattern.label] = action
        return actions

    async def inspect(self, envelope: Envelope) -> Verdict:
        found: dict[str, ToolAction] = {}
        payload = redact(envelope.payload, self.actions(envelope), found)
        if not found:
            return Verdict(Action.ALLOW, self.name, score=0.0)
        secrets = sorted(k for k in found if k in SECRET_LABELS)
        if secrets:
            reason = f"secret: {', '.join(secrets)}"
            return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
        blocked = sorted(k for k, a in found.items() if a is ToolAction.BLOCK)
        if blocked:
            reason = f"PII blocked by policy: {', '.join(blocked)}"
            return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
        reason = f"redacted: {', '.join(sorted(found))}"
        return Verdict(
            Action.MODIFY, self.name, score=1.0, reason=reason, payload=payload
        )


def scrub(value: Any) -> Any:
    """The value with every secret and all PII redacted, for the logs."""
    everything = {pattern.label: ToolAction.REDACT for pattern in PATTERNS}
    return redact(value, everything, {})


def redact(
    value: Any, actions: Mapping[str, ToolAction], found: dict[str, ToolAction]
) -> Any:
    """The value with every match the actions don't allow replaced by its
    kind. Keys are kept: they are the tool's names for things, not data."""
    if isinstance(value, str):
        return redact_text(value, actions, found)
    if isinstance(value, list):
        return [redact(v, actions, found) for v in value]
    if not isinstance(value, dict):
        return value
    redacted = {}
    for key, item in value.items():
        if isinstance(item, str) and item and SECRET_FIELD.fullmatch(str(key)):
            found[PASSWORD] = actions[PASSWORD]
            redacted[key] = f"[redacted: {PASSWORD}]"
        else:
            redacted[key] = redact(item, actions, found)
    return redacted


def redact_text(
    text: str, actions: Mapping[str, ToolAction], found: dict[str, ToolAction]
) -> str:
    for pattern in PATTERNS:
        action = actions.get(pattern.label, ToolAction.ALLOW)
        if action is ToolAction.ALLOW:
            continue

        def replace(
            match: re.Match[str],
            pattern: Pattern = pattern,
            action: ToolAction = action,
        ) -> str:
            group = "value" if "value" in match.re.groupindex else 0
            if not pattern.valid(match.group(group)):
                return match.group()
            found[pattern.label] = action
            start, end = match.span(group)
            before = match.string[match.start() : start]
            after = match.string[end : match.end()]
            return f"{before}[redacted: {pattern.label}]{after}"

        text = pattern.regex.sub(replace, text)
    return text
