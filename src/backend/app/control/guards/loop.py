"""Stops an agent stuck in a loop, before it hammers the bank's servers.

A runaway agent shows in two ways: it makes the same tool call again and
again, or it makes many calls in a short time, each a little different. The
guard counts the user's tool calls in a window and blocks a call past either
limit. It knows a call by its server, its tool and a hash of its arguments,
never by the arguments themselves."""

from collections.abc import Sequence

from app.control.audit import payload_hash
from app.control.envelope import Action, Direction, Envelope, Verdict

# One tool call as the guard counts it: server, tool and arguments hash.
Call = tuple[str, str, str]


def call_of(envelope: Envelope) -> Call:
    return envelope.server, envelope.tool, payload_hash(envelope)


class LoopGuard:
    """Blocks a tool call once the user made repeats identical calls, or
    calls tool calls of any kind, in the window. 0 turns a limit off.

    recent is the user's calls in the window before this request, from the
    database. The guard adds every call it sees after that, because the
    chat's agent makes all the calls of one question in one request. The
    score is the larger share of a limit used."""

    name = "loop"

    def __init__(self, repeats: int, calls: int, recent: Sequence[Call] = ()) -> None:
        self.repeats = repeats
        self.calls = calls
        self.recent = list(recent)

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.direction is not Direction.INBOUND:
            return Verdict(Action.ALLOW, self.name)
        call = call_of(envelope)
        same, total = self.recent.count(call), len(self.recent)
        # Blocked calls count too, so an agent that keeps trying stays
        # blocked until it stops for a whole window.
        self.recent.append(call)
        counts = [(same, self.repeats), (total, self.calls)]
        score = max((n / limit for n, limit in counts if limit), default=0.0)
        if self.repeats and same >= self.repeats:
            reason = f"loop: the same tool call more than {self.repeats} times"
            return Verdict(Action.BLOCK, self.name, score=score, reason=reason)
        if self.calls and total >= self.calls:
            reason = f"loop: more than {self.calls} tool calls"
            return Verdict(Action.BLOCK, self.name, score=score, reason=reason)
        return Verdict(Action.ALLOW, self.name, score=score)
