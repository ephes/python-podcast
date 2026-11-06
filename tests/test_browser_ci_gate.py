"""Keep the isolated production-asset browser regressions in the push gate."""

import shlex
from pathlib import Path

import yaml


def test_browser_ci_gates_navigation_and_dock_assets():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text())
    commands = [shlex.split(step.get("run", "")) for step in workflow["jobs"]["dock-transitions"]["steps"]]
    command = next(command for command in commands if "pytest" in command)
    assert {"tests/e2e/test_dock_transitions.py", "tests/e2e/test_enhanced_navigation.py"} <= set(command)
    assert "no:django" in command and "no:sugar" in command
    assert command[command.index("-m") + 1] == "e2e"
    assert command[command.index("-o") + 1] == "addopts="
