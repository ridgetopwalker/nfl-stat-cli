#!/usr/bin/env python3
"""Signal that an nfl-stat error report is fixed, so the waiting nfl-stat session can pick it up.

Usage: python3 resolve.py <local|wsl> <report_id> <commit> "<summary>" [--pull]

  local  write the resolution into $NFL_STAT_IPC_DIR (default ~/.nfl_stat_cli/error_ipc) using the
         nfl_stat_cli package of this checkout (override the checkout with $NFL_STAT_REPO).
  wsl    do the same inside WSL: needs $NFL_STAT_WSL_REPO (checkout path inside WSL), optionally
         $NFL_STAT_WSL_PYTHON (default: python3) and $NFL_STAT_WSL_IPC_DIR (exported as NFL_STAT_IPC_DIR there).
  --pull (wsl only) first run `git pull --ff-only` in that WSL checkout. Off by default; this is an agent-side
         step, nfl-stat itself never runs git on /reload.

<report_id> must look like err_YYYYMMDD_HHMMSS_xxxxxxxx (the id format written by `/error`).
The waiting session then shows the summary and, only if the user agrees, reloads the code in place.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPORT_ID_RE = re.compile(r"err_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}", re.ASCII)
SKILL_DIR = Path(__file__).resolve().parent

# Run inside the target checkout; all values arrive through argv (never formatted into code).
SNIPPET = (
    "import sys, json; sys.path.insert(0, sys.argv[1]); import nfl_stat_cli as cli; "
    "print(json.dumps(cli.write_resolution(report_id=sys.argv[2], summary=sys.argv[3], commit=sys.argv[4])))"
)


def repo_root() -> str:
    override = os.environ.get("NFL_STAT_REPO", "").strip()
    return override or str(SKILL_DIR.parents[2])


def check_id(rid: str) -> str:
    if not REPORT_ID_RE.fullmatch(rid or ""):
        raise SystemExit(f"Invalid report id {rid[:40]!r}: expected err_YYYYMMDD_HHMMSS_xxxxxxxx")
    return rid


def resolve_local(rid: str, commit: str, summary: str, repo: str = "") -> int:
    check_id(rid)
    cmd = [sys.executable, "-c", SNIPPET, repo or repo_root(), rid, summary, commit]
    return subprocess.run(cmd, check=True, env=dict(os.environ)).returncode


def resolve_wsl(rid: str, commit: str, summary: str, pull: bool = False) -> int:
    check_id(rid)
    repo = os.environ.get("NFL_STAT_WSL_REPO", "").strip()
    if not repo:
        raise SystemExit("Set NFL_STAT_WSL_REPO to the nfl-stat-cli checkout path inside WSL.")
    py = os.environ.get("NFL_STAT_WSL_PYTHON", "").strip() or "python3"
    if pull:
        subprocess.run(["wsl.exe", "git", "-C", repo, "pull", "--ff-only"], check=True)
    ipc = os.environ.get("NFL_STAT_WSL_IPC_DIR", "").strip()
    prefix = ["wsl.exe", "env", f"NFL_STAT_IPC_DIR={ipc}"] if ipc else ["wsl.exe"]
    return subprocess.run(prefix + [py, "-c", SNIPPET, repo, rid, summary, commit], check=True).returncode


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pull = "--pull" in argv
    argv = [a for a in argv if a != "--pull"]
    if len(argv) != 4 or argv[0] not in ("local", "wsl"):
        print(__doc__)
        return 2
    source, rid, commit, summary = argv
    if source == "wsl":
        return resolve_wsl(rid, commit, summary, pull=pull)
    return resolve_local(rid, commit, summary)


if __name__ == "__main__":
    sys.exit(main())
