"""#19: the triage skill is branch + PR only (no unattended push to default branches) and ships a default-branch guard."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import nfl_stat_cli as cli

SKILL = Path(cli.__file__).resolve().parent.parent / ".agents" / "skills" / "nfl-stat-error-triage"


def _git(cwd, *args, check=True):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check, env=env)


def _guard(cwd):
    return subprocess.run([sys.executable, str(SKILL / "check_branch.py")], cwd=str(cwd), capture_output=True, text=True,
                          env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull))


def test_skill_has_no_default_branch_push_instructions():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert not re.search(r"git push[^\n]*\b(master|main)\b", text), "skill must not tell the agent to push default branches"
    assert "master:main" not in text
    assert not re.search(r"(?i)\bpush(?:es|ing)? (?:origin )?(?:to )?(?:master|main)\b", text.replace("never push", "").replace("Never commit to, push to", ""))
    lowered = text.lower()
    for must in ("branch + pull request only", "never commit to, push to, or force-push a default branch", "human",
                 "untrusted data", "no hot reload", "check_branch.py"):
        assert must in lowered, must


def test_skill_scripts_never_run_git_push_or_commit():
    for name in ("watch_errors.py", "resolve.py"):
        src = (SKILL / name).read_text(encoding="utf-8")
        assert not re.search(r"""["']git["'][^\]\n]*["'](?:push|commit)["']|git push|git commit""", src), name
        assert "push" not in src.lower().replace("pull", "")


@pytest.mark.parametrize("branch", ["master", "main", "trunk", "develop"])
def test_guard_refuses_default_branches(tmp_path, branch):
    _git(tmp_path, "init", "-q", "-b", branch)
    res = _guard(tmp_path)
    assert res.returncode == 1 and "default branch" in res.stderr


def test_guard_allows_a_working_branch_and_refuses_detached_head(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "fix/error-abc")
    res = _guard(tmp_path)
    assert res.returncode == 0 and "fix/error-abc" in res.stdout
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x")
    _git(tmp_path, "checkout", "-q", "--detach")
    assert _guard(tmp_path).returncode == 1


def test_guard_refuses_the_remote_default_branch_whatever_its_name(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "release-line")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x")
    _git(tmp_path, "update-ref", "refs/remotes/origin/release-line", "HEAD")
    _git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release-line")
    res = _guard(tmp_path)
    assert res.returncode == 1 and "release-line" in res.stderr


def test_guard_refuses_outside_a_repo(tmp_path):
    assert _guard(tmp_path).returncode == 1
