"""Run the attack corpus through the control layer and report the pass rate.

Every case in scripts/attack_corpus.json is a user prompt, a tool call or a
tool result, and says whether the layer should block it or let it through. An
attack passes when the layer blocks it; a benign case passes when it doesn't,
so the report shows both the attacks that get through and the false alarms.

Each case is a seed: the mutations in scripts/mutations.py turn it into
variants, such as the same attack in Base64, with look-alike letters, inside a
code block or in German. The report gives the pass rate by category, by source
and by mutation.

The layer is built the way the chat and the gateway build it for one role:
the role's sensitive data guard, then the heuristic injection guard, then the
semantic one if OPENAI_API_KEY is set. Guards that need the database, such as
the clearance and the budget, are left out: they don't look for attacks.

The report holds case IDs, labels and scores, never the text of a case.

Run from src/backend: `uv run python -m scripts.attacks`, or `./dev attacks`
from the repo root. Pass `--heuristic` to skip the semantic guard,
`--seeds-only` to skip the mutations, `--json <path>` to save the report,
`--markdown <path>` to save a summary table for slides, and `--fail-under 0.9`
to exit with an error when the pass rate is lower.
"""

import argparse
import asyncio
import copy
import json
import sys
from collections import defaultdict
from collections.abc import Iterator
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
from scripts.mutations import MUTATIONS, Rewrite, translations
from scripts.policies import POLICIES

CORPUS = Path(__file__).resolve().parent / "attack_corpus.json"
# The server the gateway names the bank's tools after.
SERVER = "bank"
# Cases checked at the same time; each may call the semantic model.
CONCURRENCY = 8
# The most failed cases the printed report lists. The JSON report has them all.
LISTED = 30


class Case(BaseModel):
    id: str
    category: str
    source: Literal["user_prompt", "tool_call", "tool_result"]
    expect: Literal["block", "allow"]
    # The bank tool called, or that returned the result.
    tool: str = ""
    payload: dict[str, Any]
    # The mutation that made the case from a seed, or "none" for a seed.
    mutation: str = "none"

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
    mutation: str
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


type Keys = tuple[str | int, ...]


def leaves(value: Any, path: Keys = ()) -> Iterator[tuple[Keys, str]]:
    """Every string in a JSON-like value, with the keys that lead to it."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, (*path, index))


def mutate(case: Case, mutation: str, rewrite: Rewrite) -> Case | None:
    """The case with its longest text rewritten, which holds the attack in a
    tool call or result. None when the rewrite leaves the text as it is."""
    path, text = max(leaves(case.payload), key=lambda leaf: len(leaf[1]))
    new = rewrite(text)
    if new == text:
        return None
    payload = copy.deepcopy(case.payload)
    *parents, last = path
    node: Any = payload
    for key in parents:
        node = node[key]
    node[last] = new
    return case.model_copy(
        update={"id": f"{case.id}~{mutation}", "mutation": mutation, "payload": payload}
    )


def expand(seeds: list[Case]) -> list[Case]:
    """The seeds and every variant the mutations and translations make of them.
    A benign seed gets only the mutations that keep it benign, and a tool call
    or result only the ones that fit it."""
    translated = translations()
    cases = list(seeds)
    for case in seeds:
        rewrites: list[tuple[str, Rewrite]] = [
            (m.name, m.rewrite)
            for m in MUTATIONS
            if (m.benign or case.expect == "block")
            and (m.tools or case.source == "user_prompt")
        ]
        rewrites += [
            (f"translate_{language}", lambda _, text=text: text)
            for language, text in translated.get(case.id, {}).items()
        ]
        for name, rewrite in rewrites:
            if variant := mutate(case, name, rewrite):
                cases.append(variant)
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
        case.mutation,
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


def counts(results: list[Result]) -> dict[str, Any]:
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
    }


def breakdown(results: list[Result], key: str) -> dict[str, dict[str, Any]]:
    """The counts for each value of the key, such as each category."""
    groups: dict[str, list[Result]] = defaultdict(list)
    for result in results:
        groups[getattr(result, key)].append(result)
    return {name: counts(group) for name, group in sorted(groups.items())}


def summary(results: list[Result]) -> dict[str, Any]:
    return {
        **counts(results),
        "categories": breakdown(results, "category"),
        "sources": breakdown(results, "source"),
        "mutations": breakdown(results, "mutation"),
        "failures": [asdict(r) for r in results if not r.passed],
    }


def share(part: int, total: int) -> str:
    """The part as "3/4 (75.0%)", or "-" when there is nothing to count."""
    return f"{part}/{total} ({rate(part, total):.1%})" if total else "-"


def render(report: dict[str, Any], guards: str) -> str:
    lines = [f"Attack corpus: {report['total']} cases, guards: {guards}"]
    for title, key in (
        ("category", "categories"),
        ("source", "sources"),
        ("mutation", "mutations"),
    ):
        lines += ["", f"By {title}:"]
        width = max(map(len, report[key]), default=0)
        for name, group in report[key].items():
            bar = "#" * round(group["pass_rate"] * 20)
            lines.append(
                f"  {name:<{width}}  {group['passed']:>4}/{group['total']:<4}"
                f"  {group['pass_rate']:>6.1%}  {bar:<20}"
                f"  blocked {share(group['attacks_blocked'], group['attacks'])},"
                f" false alarms {share(group['false_alarms'], group['benign'])}"
            )
    lines += [
        "",
        f"Attacks blocked:  {share(report['attacks_blocked'], report['attacks'])}",
        f"False alarms:     {share(report['false_alarms'], report['benign'])}",
        f"Pass rate:        {share(report['passed'], report['total'])}",
    ]
    failures = report["failures"]
    if failures:
        lines += ["", f"Failed cases ({len(failures)}):"]
        for failure in failures[:LISTED]:
            scores = ", ".join(f"{g} {s:.2f}" for g, s in failure["scores"].items())
            got = failure["action"]
            if failure["guard"]:
                got += f" by {failure['guard']}"
            lines.append(
                f"  {failure['id']}: expected {failure['expect']}, got {got} ({scores})"
            )
        if len(failures) > LISTED:
            lines.append(f"  ... and {len(failures) - LISTED} more, see --json")
    return "\n".join(lines)


def markdown(report: dict[str, Any], guards: str) -> str:
    """The report as Markdown tables, ready for a slide."""
    header = (
        "| {} | Cases | Attacks blocked | False alarms | Pass rate |\n"
        "| --- | ---: | ---: | ---: | ---: |"
    )

    def row(name: str, group: dict[str, Any]) -> str:
        return (
            f"| {name} | {group['total']}"
            f" | {share(group['attacks_blocked'], group['attacks'])}"
            f" | {share(group['false_alarms'], group['benign'])}"
            f" | {group['pass_rate']:.1%} |"
        )

    lines = [
        "# Attack corpus report",
        "",
        f"{report['total']} cases: {report['attacks']} attacks and"
        f" {report['benign']} benign. Guards: {guards}.",
        "",
        header.format(""),
        row("**Total**", report),
    ]
    for title, key in (
        ("Category", "categories"),
        ("Source", "sources"),
        ("Mutation", "mutations"),
    ):
        lines += ["", f"## By {title.lower()}", "", header.format(title)]
        lines += [row(name, group) for name, group in report[key].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--role", default=DEFAULT_ROLE, choices=sorted(POLICIES), metavar="ROLE"
    )
    parser.add_argument(
        "--heuristic", action="store_true", help="skip the semantic guard"
    )
    parser.add_argument(
        "--seeds-only", action="store_true", help="skip the mutations of the seeds"
    )
    parser.add_argument("--json", type=Path, help="save the report to this file")
    parser.add_argument(
        "--markdown", type=Path, help="save a summary table for slides to this file"
    )
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
    cases = load() if args.seeds_only else expand(load())
    report = summary(asyncio.run(run(control, cases)))
    report["role"], report["guards"] = args.role, guards
    print(render(report, guards))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.markdown:
        args.markdown.write_text(markdown(report, guards))
    if report["pass_rate"] < args.fail_under:
        sys.exit(1)


if __name__ == "__main__":
    main()
