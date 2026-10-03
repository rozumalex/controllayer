from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from time import perf_counter
import re

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Mock AI Control Layer", version="0.1.0")

AUDIT: deque[dict] = deque(maxlen=500)
COUNTS = {"requests": 0, "allow": 0, "block": 0, "redact": 0}
LATENCIES: list[float] = []

INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"reveal (the )?(hidden )?system prompt",
    r"unrestricted administrator",
    r"bypass (your )?(previous )?rules",
    r"earlier operating constraints are obsolete",
    r"disclose (the )?(concealed|hidden) configuration",
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DEMO_SECRET_RE = re.compile(r"\bsk-test-[A-Za-z0-9_-]{8,}\b")

PERMISSION_RANK = {"LOW": 1, "STANDARD": 2, "PRIVILEGED": 3}
SENSITIVITY_REQUIRED = {
    "PUBLIC": 1,
    "INTERNAL": 2,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}


class EvaluateRequest(BaseModel):
    prompt: str
    context: str = ""
    identity: str = "judge"
    permission: str = "STANDARD"
    data_sensitivity: str = "PUBLIC"
    model: str = "default"
    max_tokens: int = Field(default=256, ge=1)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return round(ordered[index], 2)


def record(req: EvaluateRequest, result: dict, latency_ms: float) -> dict:
    COUNTS["requests"] += 1
    COUNTS[result["decision"].lower()] += 1
    LATENCIES.append(latency_ms)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "identity": req.identity,
        "permission": req.permission,
        "data_sensitivity": req.data_sensitivity,
        "decision": result["decision"],
        "control": result["control"],
        "method": result["method"],
        "reason": result["reason"],
        "technique": result.get("technique"),
        "confidence": result.get("confidence"),
        "latency_ms": latency_ms,
    }
    AUDIT.appendleft(event)
    result["latency_ms"] = latency_ms
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
    started = perf_counter()
    combined = f"{req.prompt}\n{req.context}"
    lowered = combined.lower()

    # LLM01: prompt injection wins over permissions. Even privileged identities
    # do not get to override the control layer.
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in INJECTION_PATTERNS):
        result = {
            "decision": "BLOCK",
            "control": "LLM01",
            "method": "signature/mock-semantic",
            "reason": "Prompt injection or instruction override detected",
            "technique": "AML.T0051.000",
            "confidence": 0.97,
            "output": None,
        }
        return record(req, result, round((perf_counter() - started) * 1000, 2))

    # LLM10: simple resource guard for the mock.
    if req.max_tokens > 4096:
        result = {
            "decision": "BLOCK",
            "control": "LLM10",
            "method": "deterministic",
            "reason": "Requested max_tokens exceeds policy limit of 4096",
            "technique": None,
            "confidence": 1.0,
            "output": None,
        }
        return record(req, result, round((perf_counter() - started) * 1000, 2))

    permission = req.permission.upper()
    sensitivity = req.data_sensitivity.upper()
    permission_rank = PERMISSION_RANK.get(permission, 0)
    required_rank = SENSITIVITY_REQUIRED.get(sensitivity, 99)

    # Explicit demo secret is always protected unless privileged.
    if DEMO_SECRET_RE.search(combined) and permission != "PRIVILEGED":
        result = {
            "decision": "BLOCK",
            "control": "LLM02",
            "method": "deterministic",
            "reason": "Secret-like value detected and caller is not privileged",
            "technique": None,
            "confidence": 1.0,
            "output": None,
        }
        return record(req, result, round((perf_counter() - started) * 1000, 2))

    # Permission × data-sensitivity matrix.
    if permission_rank < required_rank:
        result = {
            "decision": "BLOCK",
            "control": "ACCESS",
            "method": "policy",
            "reason": f"{permission} permission cannot access {sensitivity} data",
            "technique": None,
            "confidence": 1.0,
            "output": None,
        }
        return record(req, result, round((perf_counter() - started) * 1000, 2))

    # LLM02: standard users may work with confidential records, but PII is redacted.
    if EMAIL_RE.search(combined) and permission != "PRIVILEGED":
        safe_output = EMAIL_RE.sub("[REDACTED_EMAIL]", req.context or req.prompt)
        result = {
            "decision": "REDACT",
            "control": "LLM02",
            "method": "deterministic",
            "reason": "Email address redacted by data policy",
            "technique": None,
            "confidence": 1.0,
            "output": safe_output,
        }
        return record(req, result, round((perf_counter() - started) * 1000, 2))

    result = {
        "decision": "ALLOW",
        "control": "NONE",
        "method": "policy",
        "reason": "Request passed configured mock controls",
        "technique": None,
        "confidence": 1.0,
        "output": f"[MOCK MODEL] Accepted request: {req.prompt}",
    }
    return record(req, result, round((perf_counter() - started) * 1000, 2))


@app.get("/metrics")
def metrics():
    total = COUNTS["requests"]
    return {
        **COUNTS,
        "block_rate_pct": round(COUNTS["block"] / total * 100, 1) if total else 0.0,
        "p50_latency_ms": percentile(LATENCIES, 0.50),
        "p95_latency_ms": percentile(LATENCIES, 0.95),
    }


@app.get("/audit")
def audit(limit: int = 50):
    return list(AUDIT)[: max(1, min(limit, 500))]


@app.post("/reset")
def reset():
    AUDIT.clear()
    LATENCIES.clear()
    COUNTS.update({"requests": 0, "allow": 0, "block": 0, "redact": 0})
    return {"status": "reset"}
