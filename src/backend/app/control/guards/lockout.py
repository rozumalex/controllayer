"""Locks a user out once the layer has blocked too many of their requests in a
short time: a run of blocked requests is someone probing the guards, often
with a stolen account, not an employee at work."""

from app.control.envelope import Action, Envelope, Verdict


class LockoutGuard:
    """Blocks every message once limit of the user's requests were blocked in
    the last window seconds. The lock lifts by itself when the window has
    passed with no more blocks. The score is the share of the limit used."""

    name = "lockout"

    def __init__(self, limit: int, window_seconds: int, blocked: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.blocked = blocked

    async def inspect(self, envelope: Envelope) -> Verdict:
        if not self.limit:
            return Verdict(Action.ALLOW, self.name)
        used = self.blocked / self.limit
        if self.blocked < self.limit:
            return Verdict(Action.ALLOW, self.name, score=used)
        reason = (
            f"account locked: {self.blocked} blocked requests in "
            f"{self.window_seconds} seconds"
        )
        return Verdict(Action.BLOCK, self.name, score=1.0, reason=reason)
