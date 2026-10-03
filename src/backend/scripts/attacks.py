"""Run the attack corpus through the control layer and report the pass rate.

Every case in scripts/attack_corpus.json is a user prompt, a tool call or a
tool result, and says whether the layer should block it or let it through. An
attack passes when the layer blocks it; a benign case passes when it doesn't,
so the report shows both the attacks that get through and the false alarms.

The layer is built the way the chat and the gateway build it for one role:
the role's sensitive data guard, then the heuristic injection guard, then the
semantic one if OPENAI_API_KEY is set. Guards that need the database, such as
the clearance and the budget, are left out: they don't look for attacks.

The report holds case IDs, labels and scores, never the text of a case.

Run from src/backend: `uv run python -m scripts.attacks`, or `./dev attacks`
from the repo root. Pass `--heuristic` to skip the semantic guard, `--json
<path>` to save the report, and `--fail-under 0.9` to exit with an error when
the pass rate is lower.
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter

from app.api.deps import semantic_guard, sensitive_data
from app.control.audit import EventAuditSink
from app.control.envelope import Action, Direction, Envelope
from app.control.layer import ControlLayer, build_layer
from app.control.pipeline import Mode
from app.db.policy import DEFAULT_ROLE
from scripts.policies import POLICIES

CORPUS = Path(__file__).resolve().parent / "attack_corpus.json"
# The server the gateway names the bank's tools after.
SERVER = "bank"
# Cases checked at the same time; each may call the semantic model.
CONCURRENCY = 8


class Case(BaseModel):
    id: str
    category: str
    source: Literal["user_prompt", "tool_call", "tool_result"]
    expect: Literal["block", "allow"]
    # The bank tool called, or that returned the result.
    tool: str = ""
    payload: dict[str, Any]

    def envelope(self) -> Envelope:
        """The envelope the chat or the gateway would build for the case."""
        if self.source == "user_prompt":
            return Envelope(
                Direction.INBOUND, "attacks", "llm", "user_prompt", self.payload
            )
        direction = (
            Direction.INBOUND if self.source == "tool_call" else Direction.OUTBOUND
        )
        return Envelope(direction, "attacks", SERVER, self.tool, self.payload)


@dataclass(frozen=True)
class Result:
    id: str
    category: str
    source: str
    expect: str
    action: str
    # The guard that blocked the case, if one did.
    guard: str | None
    # The highest score of each guard that gave one.
    scores: dict[str, float]

    @property
    def passed(self) -> bool:
        return (self.action == Action.BLOCK) == (self.expect == "block")


def load(path: Path = CORPUS) -> list[Case]:
    cases = TypeAdapter(list[Case]).validate_json(path.read_bytes())
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("The corpus has duplicate case IDs")
    return cases


class Discard:
    """An event sink that drops every event, so the runs stay out of the
    dashboard."""

    async def write(self, event: dict[str, Any]) -> None:
        pass


def layer(role: str, semantic: bool) -> ControlLayer:
    policy = POLICIES[role]
    patterns = sensitive_data(policy)
    threshold = policy.injection_threshold
    return build_layer(
        Mode.ENFORCE,
        threshold,
        EventAuditSink(Discard()),
        semantic_guard(threshold) if semantic else None,
        inbound=[patterns],
        outbound=[patterns],
    )


async def check(control: ControlLayer, case: Case) -> Result:
    decision = await control.inspect(case.envelope())
    blocked = [v.guard for v in decision.verdicts if v.action is Action.BLOCK]
    scores = {v.guard: v.score for v in decision.verdicts if v.score is not None}
    return Result(
        case.id,
        case.category,
        case.source,
        case.expect,
        decision.action,
        blocked[0] if blocked else None,
        scores,
    )


async def run(control: ControlLayer, cases: list[Case]) -> list[Result]:
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(case: Case) -> Result:
        async with limit:
            return await check(control, case)

    return await asyncio.gather(*(one(case) for case in cases))


def rate(passed: int, total: int) -> float:
    return passed / total if total else 1.0


def summary(results: list[Result]) -> dict[str, Any]:
    by_category: dict[str, list[Result]] = defaultdict(list)
    for result in results:
        by_category[result.category].append(result)
    attacks = [r for r in results if r.expect == "block"]
    benign = [r for r in results if r.expect == "allow"]
    passed = sum(r.passed for r in results)
    return {
        "pass_rate": rate(passed, len(results)),
        "passed": passed,
        "total": len(results),
        "attacks_blocked": sum(r.passed for r in attacks),
        "attacks": len(attacks),
        "false_alarms": sum(not r.passed for r in benign),
        "benign": len(benign),
        "categories": {
            name: {"passed": sum(r.passed for r in group), "total": len(group)}
            for name, group in sorted(by_category.items())
        },
        "failures": [asdict(r) for r in results if not r.passed],
    }


def render(report: dict[str, Any], guards: str) -> str:
    lines = [f"Attack corpus: {report['total']} cases, guards: {guards}", ""]
    width = max(map(len, report["categories"]), default=0)
    for name, counts in report["categories"].items():
        share = rate(counts["passed"], counts["total"])
        bar = "#" * round(share * 20)
        lines.append(
            f"  {name:<{width}}  {counts['passed']:>3}/{counts['total']:<3}"
            f"  {share:>6.1%}  {bar}"
        )
    lines += [
        "",
        f"Attacks blocked:  {report['attacks_blocked']}/{report['attacks']}"
        f"  ({rate(report['attacks_blocked'], report['attacks']):.1%})",
        f"False alarms:     {report['false_alarms']}/{report['benign']}"
        f"  ({rate(report['false_alarms'], report['benign']):.1%})",
        f"Pass rate:        {report['passed']}/{report['total']}"
        f"  ({report['pass_rate']:.1%})",
    ]
    if report["failures"]:
        lines += ["", "Failed cases:"]
        for failure in report["failures"]:
            scores = ", ".join(f"{g} {s:.2f}" for g, s in failure["scores"].items())
            got = failure["action"]
            if failure["guard"]:
                got += f" by {failure['guard']}"
            lines.append(
                f"  {failure['id']}: expected {failure['expect']}, got {got} ({scores})"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--role", default=DEFAULT_ROLE, choices=sorted(POLICIES), metavar="ROLE"
    )
    parser.add_argument(
        "--heuristic", action="store_true", help="skip the semantic guard"
    )
    parser.add_argument("--json", type=Path, help="save the report to this file")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        metavar="RATE",
        help="exit with an error when the pass rate is lower, from 0 to 1",
    )
    args = parser.parse_args()

    control = layer(args.role, semantic=not args.heuristic)
    inbound = control.pipelines[Direction.INBOUND].guards
    guards = ", ".join(guard.name for guard in inbound)
    report = summary(asyncio.run(run(control, load())))
    report["role"], report["guards"] = args.role, guards
    print(render(report, guards))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if report["pass_rate"] < args.fail_under:
        sys.exit(1)


if __name__ == "__main__":
    main()
