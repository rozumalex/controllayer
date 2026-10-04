"""Blocks a tool whose results keep carrying injections: the server behind it
is compromised, so every call to it is a risk, for every user of the
organization.

A result counts once, however often it comes back: the same poisoned
record read again and again is one bad record, not a bad tool, and the
injection guards withhold it each time anyway. The user who called the tool
did nothing wrong, so these blocks never count toward their lockout."""

from collections.abc import Mapping

from app.control.envelope import Action, Direction, Envelope, Verdict

# A tool, as its server and its name.
Tool = tuple[str, str]


class SpoiledToolGuard:
    """Blocks a call to a tool once limit of its different results were
    blocked as injections in the last window seconds. The block lifts by
    itself when the window has passed with no more of them."""

    name = "spoiled_tool"

    def __init__(
        self, limit: int, window_seconds: int, poisoned: Mapping[Tool, int]
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        # How many different poisoned results each tool sent in the window.
        self.poisoned = poisoned

    async def inspect(self, envelope: Envelope) -> Verdict:
        if not self.limit or envelope.direction is not Direction.INBOUND:
            return Verdict(Action.ALLOW, self.name)
        count = self.poisoned.get((envelope.server, envelope.tool), 0)
        if count < self.limit:
            return Verdict(Action.ALLOW, self.name, score=count / self.limit)
        reason = (
            f"tool blocked: {count} poisoned results in {self.window_seconds} seconds"
        )
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
