"""Sanity checks for the GitHub Actions workflow (issue #20)."""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

if not WORKFLOW.is_file():  # e.g. tests run from an unpacked sdist
    pytest.skip("workflow file not present in this checkout", allow_module_level=True)


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_workflow_triggers_on_push_and_pull_request(workflow):
    triggers = workflow.get("on", workflow.get(True))  # PyYAML parses a bare `on` key as True
    assert "push" in triggers and "pull_request" in triggers


def test_workflow_is_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_workflow_runs_pytest_on_supported_pythons(workflow):
    job = workflow["jobs"]["test"]
    assert {"3.10", "3.13"} <= set(job["strategy"]["matrix"]["python-version"])
    assert "3.9" not in job["strategy"]["matrix"]["python-version"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python -m pytest -q" in commands


def test_workflow_builds_and_checks_wheel(workflow):
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["build"]["steps"])
    assert "python -m build" in commands
    assert "nfl_stat_cli/nflverse_bridge.R" in commands


def test_workflow_actions_are_pinned_to_commit_shas(workflow):
    import re
    uses = [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}(\s+#.*)?", ref), ref


def test_workflow_avoids_dangerous_triggers(workflow):
    text = WORKFLOW.read_text()
    assert "pull_request_target" not in text
    assert "secrets." not in text
