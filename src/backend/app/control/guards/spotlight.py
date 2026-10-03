import re
from typing import Any

from app.control.envelope import Action, Envelope, Verdict

OPEN = "<untrusted_tool_output>"
CLOSE = "</untrusted_tool_output>"
DELIMITER = re.compile(r"<\s*/?\s*untrusted_tool_output\s*>", re.IGNORECASE)


def strip_delimiters(text: str) -> str:
    """Removes the delimiters from a tool result, so it can't close the
    wrapper early. It repeats, because a removal can join a new one."""
    while True:
        text, count = DELIMITER.subn("", text)
        if not count:
            return text


def wrap(value: Any) -> Any:
    if isinstance(value, str):
        return f"{OPEN}{strip_delimiters(value)}{CLOSE}"
    if isinstance(value, dict):
        return {key: wrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [wrap(item) for item in value]
    return value


class SpotlightGuard:
    """Wraps every string of a tool result in delimiters, so the agent's model
    can tell data it fetched from instructions it was given."""

    name = "spotlight"

    async def inspect(self, envelope: Envelope) -> Verdict:
        return Verdict(
            Action.MODIFY,
            self.name,
            reason="wrapped as untrusted data",
            payload=wrap(envelope.payload),
        )
