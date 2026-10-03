import hashlib
import json
import logging
from typing import Protocol

from app.control.envelope import Envelope, Verdict

logger = logging.getLogger("app.control.audit")


class AuditSink(Protocol):
    async def record(
        self, envelope: Envelope, verdict: Verdict, latency_ms: float
    ) -> None: ...


def payload_hash(envelope: Envelope) -> str:
    data = json.dumps(envelope.payload, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()


class LogAuditSink:
    """Writes one JSON line per verdict. It stores a hash of the payload, not
    the payload, because tool results may hold secrets."""

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
        logger.info(json.dumps(event))
