import hashlib
import json
import logging
from typing import Any, Protocol

from app.control.envelope import Envelope, Verdict

logger = logging.getLogger("app.control.audit")


class EventSink(Protocol):
    """Where the control layer's events go: one dict per event, each with an
    "event" name and the "trace_id" of its request."""

    async def write(self, event: dict[str, Any]) -> None: ...


class LogEventSink:
    """Writes each event as one JSON line."""

    def __init__(self, logger: logging.Logger = logger) -> None:
        self.logger = logger

    async def write(self, event: dict[str, Any]) -> None:
        self.logger.info(json.dumps(event, default=str))


class FanOutSink:
    """Writes each event to every sink, in order."""

    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    async def write(self, event: dict[str, Any]) -> None:
        for sink in self.sinks:
            await sink.write(event)


class AuditSink(Protocol):
    async def record(
        self, envelope: Envelope, verdict: Verdict, latency_ms: float
    ) -> None: ...


def payload_hash(envelope: Envelope) -> str:
    data = json.dumps(envelope.payload, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()


class EventAuditSink:
    """Writes one event per verdict. It stores a hash of the payload, not the
    payload, because tool results may hold secrets."""

    def __init__(self, sink: EventSink | None = None) -> None:
        self.sink = sink or LogEventSink()

    async def record(
        self, envelope: Envelope, verdict: Verdict, latency_ms: float
    ) -> None:
        event = {
            "event": "verdict",
            "trace_id": envelope.trace_id,
            "direction": envelope.direction,
            "agent_id": envelope.agent_id,
            "server": envelope.server,
            "tool": envelope.tool,
            "guard": verdict.guard,
            "action": verdict.action,
            "score": verdict.score,
            "reason": verdict.reason,
            "latency_ms": round(latency_ms, 3),
            "payload_sha256": payload_hash(envelope),
        }
        await self.sink.write(event)
