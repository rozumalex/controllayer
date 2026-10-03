"""Heuristic prompt injection guard: the cheap first stage of the cascade.

A classifier and an LLM judge can come after it later, for the grey zone."""

import re
from collections.abc import Iterator
from typing import Any

from app.control.envelope import Action, Envelope, Verdict

# Each pattern has the score it gives on a match. The guard keeps the highest.
PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "override",
        0.9,
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above"
            r"|earlier|all|your)\b.{0,40}\b(instructions?|prompts?|rules|context)",
            re.I | re.S,
        ),
    ),
    (
        "new_instructions",
        0.8,
        re.compile(r"\b(new|updated|real) (system )?instructions?\s*:", re.I),
    ),
    (
        "role_tag",
        0.8,
        re.compile(
            r"<\|?(system|im_start|im_end|assistant)\|?>|\[/?INST\]|^\s*system\s*:",
            re.I | re.M,
        ),
    ),
    (
        "persona",
        0.7,
        re.compile(
            r"\byou are now\b|\bact as (an? )?(unrestricted|jailbroken|DAN)\b"
            r"|\bdeveloper mode\b",
            re.I,
        ),
    ),
    (
        "exfiltration",
        0.7,
        re.compile(
            r"\b(send|post|upload|forward|email)\b.{0,60}\b(api[_ ]?keys?|tokens?"
            r"|passwords?|secrets?|credentials|env(ironment)? variables)\b",
            re.I | re.S,
        ),
    ),
    (
        "markdown_image_leak",
        0.7,
        re.compile(r"!\[[^\]]*\]\(https?://[^)]*[?&][^)]*=", re.I),
    ),
    (
        "hidden_unicode",
        0.7,
        # Zero-width characters, bidi overrides and the Unicode tag block,
        # which hide text from a human reader but not from the model.
        # U+200D, the zero-width joiner, is left out: emoji such as 👩‍💻 use it.
        re.compile(
            "[\u200b\u200c\u200e\u200f\u202a-\u202e\u2060-\u2064\U000e0000-\U000e007f]"
        ),
    ),
]


def strings(value: Any) -> Iterator[str]:
    """Every string in a JSON-like value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from strings(item)


class PromptInjectionGuard:
    name = "prompt_injection"

    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    async def inspect(self, envelope: Envelope) -> Verdict:
        hits = {
            label: score
            for text in strings(envelope.payload)
            for label, score, pattern in PATTERNS
            if pattern.search(text)
        }
        score = max(hits.values(), default=0.0)
        action = Action.BLOCK if score >= self.threshold else Action.ALLOW
        reason = f"matched: {', '.join(sorted(hits))}" if hits else ""
        return Verdict(action, self.name, score=score, reason=reason)
