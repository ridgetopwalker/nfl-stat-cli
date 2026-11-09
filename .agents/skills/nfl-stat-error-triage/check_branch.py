#!/usr/bin/env python3
"""Refuse to run fixer steps on a default branch.

Run before committing: `python3 check_branch.py`. Exits 0 only when the current branch is a non-default
working branch. Default branches are master, main, and whatever origin/HEAD points at.
The triage flow is branch + pull request only: this script exists so an agent cannot commit or push
to a default branch by accident.
"""
import subprocess
import sys

ALWAYS_DEFAULT = {"master", "main", "trunk", "develop", "HEAD"}


def _git(*args):
    res = subprocess.run(["git", *args], capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def default_branches():
    names = set(ALWAYS_DEFAULT)
    origin_head = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")  # e.g. origin/main
    if origin_head:
        names.add(origin_head.split("/", 1)[-1])
    return names


def main() -> int:
    branch = _git("symbolic-ref", "--short", "HEAD")  # also works before the first commit; empty when detached
    if not branch:
        print("Not on a named branch in a git checkout (detached HEAD?); refusing.", file=sys.stderr)
        return 1
    if branch in default_branches():
        print(f"Refusing: '{branch}' is a default branch. Create a working branch (e.g. fix/error-<id>) and open a PR.", file=sys.stderr)
        return 1
    print(f"OK: working branch '{branch}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
