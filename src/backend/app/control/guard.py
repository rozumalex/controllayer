from typing import Protocol

from app.control.envelope import Envelope, Verdict


class Guard(Protocol):
    name: str

    async def inspect(self, envelope: Envelope) -> Verdict: ...
