from typing import Any

from app.control.envelope import Action, Envelope, Verdict

OPEN = "<untrusted_tool_output>"
CLOSE = "</untrusted_tool_output>"


def wrap(value: Any) -> Any:
    if isinstance(value, str):
        return f"{OPEN}{value}{CLOSE}"
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
