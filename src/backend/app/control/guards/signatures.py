"""Attack signature guard: blocks the patterns of known exploits on AI systems.

The signatures come from a feed outside the code, a JSON file or URL that a
security team maintains, so a new attack is blocked without a deploy. The
feed is read again when it changes: a file when its modification time does,
a URL every few seconds. If a new version is broken, the last good one stays.

It covers what an agent passes on to code: commands that run code, unsafe
deserialization such as pickle, and model files and code from untrusted
repositories."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.control.envelope import Action, Envelope, Verdict
from app.control.guards.prompt_injection import strings, unescape
from app.control.http import SharedClient
from app.core.schema.signature import Signature, SignatureFeed

logger = logging.getLogger("app.control.signatures")

# The feed that comes with the app.
BUNDLED = Path(__file__).parent.parent / "signatures.json"
FEED_HTTP = SharedClient(timeout=5)


@dataclass(frozen=True)
class Compiled:
    version: str
    signatures: list[tuple[Signature, re.Pattern[str]]]


def compile_feed(feed: SignatureFeed) -> Compiled:
    """The enabled signatures, compiled. One with a broken pattern is left
    out, so a typo doesn't turn off the rest."""
    compiled = []
    for signature in feed.signatures:
        if not signature.enabled:
            continue
        try:
            compiled.append((signature, re.compile(signature.pattern)))
        except re.error as error:
            logger.warning("signature %s left out: %s", signature.id, error)
    return Compiled(feed.version, compiled)


class Feed:
    """The signatures from a file path or an http(s) URL."""

    def __init__(self, source: str | Path = BUNDLED, refresh: float = 30) -> None:
        self.source = str(source)
        self.refresh = refresh
        self.current: Compiled | None = None
        # The file's modification time, or when the URL was last fetched.
        self.stamp: float | None = None

    @property
    def remote(self) -> bool:
        return self.source.startswith(("http://", "https://"))

    async def load(self) -> Compiled | None:
        """The current signatures, or None if the feed never loaded. Two
        messages at once may both read a changed feed, which does no harm."""
        try:
            if self.remote:
                await self.fetch()
            else:
                await self.read()
        except (OSError, httpx.HTTPError, ValidationError) as error:
            # Keep the last good version, and try again on the next call.
            logger.error("signature feed %s failed: %s", self.source, error)
        return self.current

    async def read(self) -> None:
        path = Path(self.source)
        mtime = (await asyncio.to_thread(path.stat)).st_mtime
        if mtime == self.stamp:
            return
        # Set first, so a broken version is reported once, not on every
        # message. The fix changes the time, so it is read.
        self.stamp = mtime
        text = await asyncio.to_thread(path.read_text, "utf-8")
        self.update(SignatureFeed.model_validate_json(text))

    async def fetch(self) -> None:
        now = time.monotonic()
        if self.stamp is not None and now - self.stamp < self.refresh:
            return
        # Set first, so a failing URL is tried once per refresh, not on
        # every message.
        self.stamp = now
        response = await FEED_HTTP.get().get(self.source)
        response.raise_for_status()
        self.update(SignatureFeed.model_validate_json(response.content))

    def update(self, feed: SignatureFeed) -> None:
        self.current = compile_feed(feed)
        logger.info(
            "signature feed %s: version %s, %d signatures",
            self.source,
            self.current.version,
            len(self.current.signatures),
        )


class SignatureGuard:
    """Blocks a message that matches a signature at or above the threshold.
    The score is the highest severity matched."""

    name = "attack_signatures"

    def __init__(self, feed: Feed, threshold: float = 0.7) -> None:
        self.feed = feed
        self.threshold = threshold

    async def inspect(self, envelope: Envelope) -> Verdict:
        compiled = await self.feed.load()
        if compiled is None:
            return Verdict(Action.ALLOW, self.name, reason="signature feed unavailable")
        hits: dict[str, float] = {}
        for text in strings(envelope.payload):
            # Also URL or HTML decoded, so %2e%2e%2f is still ../
            variants = {text, unescape(text)}
            for signature, pattern in compiled.signatures:
                if signature.id not in hits and any(map(pattern.search, variants)):
                    hits[signature.id] = signature.severity
        score = max(hits.values(), default=0.0)
        action = Action.BLOCK if score >= self.threshold else Action.ALLOW
        reason = f"matched: {', '.join(sorted(hits))}" if hits else ""
        return Verdict(action, self.name, score=score, reason=reason)
