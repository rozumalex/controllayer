"""Heuristic prompt injection guard: the cheap, deterministic first stage.

It blocks the obvious attacks without a model call. Before it matches, it
undoes the usual disguises: URL and HTML encoding, look-alike letters, hidden
characters, and Base64 or hex payloads. What it misses, such as a reworded
attack, is left to the semantic guard after it."""

import base64
import binascii
import html
import re
import unicodedata
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

from app.control.envelope import Action, Envelope, Verdict

# Each pattern has the score it gives on a match. The guard keeps the highest.
PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "override",
        0.9,
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}"
            r"\b(previous|prior|above|earlier|all|your)\b.{0,40}"
            r"\b(instructions?|prompts?|rules|context|guidelines|guardrails"
            r"|directives?)",
            re.I | re.S,
        ),
    ),
    (
        # The same in Polish, the language of the demo's users.
        "override_pl",
        0.9,
        re.compile(
            r"\b(zignoruj|ignoruj|pomiń|pomin|zapomnij|olej)\w*\b.{0,40}"
            r"\b(poprzedni|wcześniejsz|wczesniejsz|wszystki|powyższ|powyzsz"
            r"|swoj|twoj)\w*\b.{0,40}\b(instrukcj|polece|zasad|regu)\w*",
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
            r"<\|?(system|im_start|im_end|assistant)\|?>|\[/?INST\]"
            r"|^\s*(system|developer)\s*:|^#{1,3}\s*system\b",
            re.I | re.M,
        ),
    ),
    (
        "prompt_leak",
        0.8,
        re.compile(
            r"\b(reveal|show|print|repeat|output|display|dump|leak|tell me)\b.{0,40}"
            r"\b(system prompt|hidden (instructions|prompt)|initial instructions"
            r"|your (instructions|prompt|rules))\b",
            re.I | re.S,
        ),
    ),
    (
        "persona",
        0.7,
        re.compile(
            r"\byou are now\b|\bact as (an? )?(unrestricted|jailbroken|DAN)\b"
            r"|\bdeveloper mode\b|\bjailbreak(ed)?\b",
            re.I,
        ),
    ),
    (
        # Asks the model to keep something from the user, as a poisoned tool
        # description does. "the user's" is left out: it names their data.
        "concealment",
        0.8,
        re.compile(
            r"\b(do not|don['’]?t|never)\s+(tell|mention|inform|reveal|disclose)\b"
            r".{0,40}\bthe user\b(?!['’]s)",
            re.I | re.S,
        ),
    ),
    (
        # A tag that marks text as orders for the model, such as <IMPORTANT>.
        "instruction_tag",
        0.8,
        re.compile(r"<\s*/?\s*(important|instructions?|secret)\s*>", re.I),
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
]

# Zero-width characters, bidi overrides and the Unicode tag block, which hide
# text from a human reader but not from the model. Characters that normal text
# uses are left out: the zero-width joiner U+200D (emoji such as 👩‍💻), the
# non-joiner U+200C (Persian) and the direction marks U+200E and U+200F
# (Hebrew, Arabic).
HIDDEN = re.compile("[\u200b\u202a-\u202e\u2060-\u2064\U000e0000-\U000e007f]")
HIDDEN_SCORE = 0.7

# Cyrillic and Greek letters that look like Latin ones. NFKC leaves them, so
# "іgnore" with a Cyrillic і would slip past the patterns.
CONFUSABLES = str.maketrans(
    "аеорсухіјѕԁԛԝАВЕКМНОРСТХІЈЅαοτνικΑΒΕΗΙΚΜΝΟΡΤΧΥΖ",
    "aeopcyxijsdqwABEKMHOPCTXIJSaotvikABEHIKMNOPTXYZ",
)
# Base64 and hex runs long enough to hold an instruction.
BASE64 = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
HEX = re.compile(r"\b(?:[0-9a-fA-F]{2}){8,}\b")
# The most payloads decoded from one string, so a huge tool result full of
# Base64 can't stall the guard.
MAX_DECODED = 20


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


def unescape(text: str) -> str:
    """The text with URL and HTML encoding undone, a few layers deep."""
    for _ in range(3):
        plain = html.unescape(unquote(text))
        if plain == text:
            break
        text = plain
    return text


def normalize(text: str) -> str:
    """The text as the model reads it, for the patterns to match."""
    text = unicodedata.normalize("NFKC", unescape(text)).translate(CONFUSABLES)
    # Format characters (category Cf) are invisible, so an attacker can put
    # them inside a word to break it up.
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"\s+", " ", text)


def readable(data: bytes) -> str | None:
    """The bytes as text, if they look like words and not binary data."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    letters = sum(c.isalpha() or c.isspace() for c in text)
    if " " not in text.strip() or letters < 0.8 * len(text):
        return None
    return text


def decoded(text: str) -> Iterator[str]:
    """Text hidden in the string as Base64 or hex."""
    found = 0
    for match in HEX.finditer(text):
        if found >= MAX_DECODED:
            return
        if plain := readable(binascii.unhexlify(match.group())):
            found += 1
            yield plain
    for match in BASE64.finditer(text):
        if found >= MAX_DECODED:
            return
        token = match.group().rstrip("=")
        try:
            data = base64.urlsafe_b64decode(
                token.replace("+", "-").replace("/", "_") + "=" * (-len(token) % 4)
            )
        except ValueError:
            continue
        if plain := readable(data):
            found += 1
            yield plain


def scan(text: str) -> dict[str, float]:
    """The patterns that match the text, with their scores."""
    text = normalize(text)
    hits = {label: score for label, score, p in PATTERNS if p.search(text)}
    for plain in decoded(text):
        for label, score, pattern in PATTERNS:
            if pattern.search(normalize(plain)):
                hits[f"{label}_encoded"] = score
    return hits


class PromptInjectionGuard:
    name = "prompt_injection"

    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    async def inspect(self, envelope: Envelope) -> Verdict:
        hits: dict[str, float] = {}
        for text in strings(envelope.payload):
            # Checked after decoding, so an encoded hidden character counts.
            if HIDDEN.search(unescape(text)):
                hits["hidden_unicode"] = HIDDEN_SCORE
            hits.update(scan(text))
        score = max(hits.values(), default=0.0)
        action = Action.BLOCK if score >= self.threshold else Action.ALLOW
        reason = f"matched: {', '.join(sorted(hits))}" if hits else ""
        return Verdict(action, self.name, score=score, reason=reason)
