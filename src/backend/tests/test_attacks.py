import asyncio

from app.db.policy import DEFAULT_ROLE
from scripts.attacks import CORPUS, Result, layer, load, render, run, summary


def result(id: str, category: str, expect: str, action: str) -> Result:
    return Result(id, category, "user_prompt", expect, action, None, {})


def test_corpus_loads() -> None:
    # given
    path = CORPUS

    # when
    cases = load(path)

    # then
    assert {case.expect for case in cases} == {"block", "allow"}
    assert {case.source for case in cases} == {
        "user_prompt",
        "tool_call",
        "tool_result",
    }


def test_heuristic_raises_no_false_alarms() -> None:
    # given
    control = layer(DEFAULT_ROLE, semantic=False)
    benign = [case for case in load() if case.expect == "allow"]

    # when
    report = summary(asyncio.run(run(control, benign)))

    # then
    assert report["false_alarms"] == 0, report["failures"]


def test_heuristic_blocks_obvious_attacks() -> None:
    # given
    control = layer(DEFAULT_ROLE, semantic=False)
    cases = [
        case
        for case in load()
        if case.category in ("instruction_override", "secret_leak")
    ]

    # when
    report = summary(asyncio.run(run(control, cases)))

    # then
    assert report["pass_rate"] == 1.0, report["failures"]


def test_summary_counts_attacks_and_false_alarms() -> None:
    # given
    results = [
        result("a", "override", "block", "block"),
        result("b", "override", "block", "allow"),
        result("c", "benign", "allow", "block"),
        result("d", "benign", "allow", "modify"),
    ]

    # when
    report = summary(results)

    # then
    assert report["pass_rate"] == 0.5
    assert (report["attacks_blocked"], report["attacks"]) == (1, 2)
    assert (report["false_alarms"], report["benign"]) == (1, 2)
    assert [f["id"] for f in report["failures"]] == ["b", "c"]


def test_render_holds_no_case_text() -> None:
    # given
    control = layer(DEFAULT_ROLE, semantic=False)
    cases = load()

    # when
    output = render(summary(asyncio.run(run(control, cases))), "heuristic")

    # then
    for case in cases:
        for text in case.payload.values():
            assert not isinstance(text, str) or text not in output
