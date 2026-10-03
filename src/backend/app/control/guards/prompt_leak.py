"""Finds the assistant's instructions in the model's answer.

A user who talks the model into repeating its system prompt learns what the
bank told it, and how to talk it out of that. The guard looks for runs of
words from the instructions in the answer: a few words in common happen by
chance, a run of WORDS words in a row means the model is quoting them. Case,
punctuation and line breaks don't count, so reformatting doesn't hide a leak.
A translated or paraphrased leak is the semantic guard's job."""

import re

from app.control.envelope import Action, Direction, Envelope, Verdict

# Words in a row that count as quoting the instructions.
WORDS = 8


def runs(text: str) -> set[tuple[str, ...]]:
    """Every run of WORDS words in the text, in lower case."""
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + WORDS]) for i in range(len(words) - WORDS + 1)}


class PromptLeakGuard:
    """Blocks an answer that quotes the system prompt. The score is the share
    of the instructions quoted."""

    name = "prompt_leak"

    def __init__(self, system_prompt: str) -> None:
        self.runs = runs(system_prompt)

    async def inspect(self, envelope: Envelope) -> Verdict:
        if envelope.direction is not Direction.RESPONSE:
            return Verdict(Action.ALLOW, self.name)
        quoted = self.runs & runs(str(envelope.payload.get("content", "")))
        score = len(quoted) / len(self.runs) if self.runs else 0.0
        if not quoted:
            return Verdict(Action.ALLOW, self.name, score=score)
        reason = f"system prompt quoted: {len(quoted)} runs of {WORDS} words"
        return Verdict(Action.BLOCK, self.name, score=score, reason=reason)
