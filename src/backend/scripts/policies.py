"""The policy of each Golden Socks role, and the default for any other role,
read from policies.yaml. That file documents every setting."""

from pathlib import Path

import yaml

from app.core.schema.policy import PolicySettings

PATH = Path(__file__).resolve().parent / "policies.yaml"


def load(path: Path = PATH) -> dict[str, PolicySettings]:
    """The policies in the file, by role. Raises if one is not valid."""
    data = yaml.safe_load(path.read_text())
    return {
        role: PolicySettings.model_validate(settings)
        for role, settings in data["policies"].items()
    }


POLICIES = load()
