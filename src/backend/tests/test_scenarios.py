from app.core.checklist import CHECKLIST
from app.core.scenarios import STOPPED, load, ready, verdict
from app.core.simulator import fallback_story


def test_scenarios_load_and_are_ready() -> None:
    # when
    pack = load()

    # then
    assert pack.research_feed_note
    assert pack.scenarios
    assert all(ready(s) for s in pack.scenarios)
    assert {s.goal for s in pack.scenarios} == {item.id for item in CHECKLIST}


def test_verdict_prefers_loot_then_a_stop() -> None:
    # when / then
    assert verdict([{"achieved": ["steal_contacts"], "status": "blocked"}]) == (
        "succeeded"
    )
    assert verdict([{"achieved": [], "status": "blocked"}]) == "stopped"
    assert verdict([{"achieved": [], "status": "passed"}]) == "failed"
    assert STOPPED >= {"blocked", "false_alarm", "locked_out", "out_of_budget"}


def test_fallback_story_names_the_scenario() -> None:
    # given
    scenario = load().scenarios[0]
    turns = [{"status": "blocked", "guard": "prompt_injection", "tools": []}]

    # when
    story = fallback_story(scenario, "stopped", turns)

    # then
    assert scenario.title in story
    assert "prompt_injection" in story
