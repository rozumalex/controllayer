"""Blocks a user's questions past a number a minute, so one user or a script
in their name can't flood the model."""

from app.control.envelope import Action, Envelope, Verdict


class RateLimitGuard:
    """Blocks a prompt once the user has asked limit questions in the last
    minute. The score is the share of the limit used."""

    name = "rate_limit"

    def __init__(self, limit: int, recent: int) -> None:
        self.limit = limit
        self.recent = recent

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.tool != "user_prompt" or not self.limit:
            return Verdict(Action.ALLOW, self.name)
        used = self.recent / self.limit
        if self.recent < self.limit:
            return Verdict(Action.ALLOW, self.name, score=used)
        reason = f"rate limit: {self.limit} questions a minute"
        return Verdict(Action.BLOCK, self.name, score=used, reason=reason)
