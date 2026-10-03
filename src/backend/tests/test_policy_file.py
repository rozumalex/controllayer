from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.schema.policy import ToolAction
from scripts.policies import PATH, POLICIES, load


def test_strictness_levels_get_stricter() -> None:
    # given
    levels = yaml.safe_load(PATH.read_text())["levels"]

    # when
    thresholds = [
        levels[name]["injection_threshold"]
        for name in ("permissive", "balanced", "strict")
    ]

    # then
    assert thresholds == sorted(thresholds, reverse=True)
    assert levels["strict"]["above_clearance"] == ToolAction.BLOCK
    assert set(levels["strict"]["pii"].values()) == {ToolAction.BLOCK}


def test_a_role_overrides_its_level_and_merges_its_tool_groups() -> None:
    # when
    analyst = POLICIES["Analyst"]

    # then
    assert analyst.injection_threshold == 0.65
    assert analyst.tools["bank__get_account"] is ToolAction.REDACT
    assert analyst.tools["bank__list_trades"] is ToolAction.ALLOW


def test_load_rejects_an_invalid_policy(tmp_path: Path) -> None:
    # given
    path = tmp_path / "policies.yaml"
    path.write_text(
        "policies:\n"
        "  Analyst:\n"
        "    injection_threshold: 2\n"
        "    clearance: INTERNAL\n"
        "    above_clearance: allow\n"
        "    allowed_models: [gpt-4.1-mini]\n"
        "    budget: {}\n"
        "    default_tool_action: block\n"
    )

    # when / then
    with pytest.raises(ValidationError):
        load(path)
