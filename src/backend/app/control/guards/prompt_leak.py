"""Finds the assistant's instructions in the model's answer.

A user who talks the model into repeating its system prompt learns what the
bank told it, and how to talk it out of that. The guard looks for words from
the instructions in the answer, in the same order. A model that says what it
can do may repeat a line of them, such as its list of tasks, 18 words long,
so the guard blocks only SPAN or more words in a row: more than a model
repeats to describe itself, and about as much as one long sentence. A
streamed answer is checked a piece at a time, so the guard keeps the end of
the text it has seen, and finds a quote cut in two. Case, punctuation and line
breaks don't count, so reformatting doesn't hide a leak. A translated or
paraphrased leak is the semantic guard's job."""

import re

from app.control.envelope import Action, Direction, Envelope, Verdict

# Words in a row that count as quoting the instructions.
SPAN = 20
# The answer is compared with the instructions in runs of this many words.
WORDS = 8


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def runs(found: list[str]) -> set[tuple[str, ...]]:
    """Every run of WORDS words in the list."""
    return {tuple(found[i : i + WORDS]) for i in range(len(found) - WORDS + 1)}


class PromptLeakGuard:
    """Blocks an answer that quotes SPAN words of the system prompt in a row.
    The score is the share of the instructions quoted. Built for one chat
    request, as it remembers the end of the answer checked so far."""

    name = "prompt_leak"

    def __init__(self, system_prompt: str) -> None:
        self.runs = runs(words(system_prompt))
        self.seen: list[str] = []

    def longest_quote(self, found: list[str]) -> int:
        """The most words in a row that are also in a row in the
        instructions, or 0 when fewer than WORDS."""
        longest = streak = 0
        for i in range(len(found) - WORDS + 1):
            streak = streak + 1 if tuple(found[i : i + WORDS]) in self.runs else 0
            longest = max(longest, streak)
        return longest + WORDS - 1 if longest else 0

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.direction is not Direction.RESPONSE:
            return Verdict(Action.ALLOW, self.name)
        found = self.seen + words(str(envelope.payload.get("content", "")))
        self.seen = found[-SPAN:]
        quoted = self.runs & runs(found)
        score = len(quoted) / len(self.runs) if self.runs else 0.0
        longest = self.longest_quote(found)
        if longest < SPAN:
            return Verdict(Action.ALLOW, self.name, score=score)
        reason = f"system prompt quoted: {longest} words in a row"
        return Verdict(Action.BLOCK, self.name, score=score, reason=reason)
