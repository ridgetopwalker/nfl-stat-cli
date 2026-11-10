#!/usr/bin/env python3
"""Signal that a pro-football-slm error report is fixed, so the waiting pro-football-slm session can pick it up.

Usage: python3 resolve.py <local|wsl> <report_id> <commit> [--pull] -- "<summary>"
       (put `--` before the summary if it can start with a dash)

  local  write the resolution into $PFSLM_IPC_DIR (default ~/.pro_football_slm/error_ipc) using the
         pro_football_slm package of this checkout (override the checkout with $PFSLM_REPO).
  wsl    do the same inside WSL: needs $PFSLM_WSL_REPO (absolute checkout path inside WSL), optionally
         $PFSLM_WSL_PYTHON (default: python3) and $PFSLM_WSL_IPC_DIR (exported as PFSLM_IPC_DIR there).
  --pull (wsl only) first run `git pull --ff-only` in that WSL checkout. Off by default; this is an agent-side
         step, pro-football-slm itself never runs git on /reload.

<report_id> must look like err_YYYYMMDD_HHMMSS_xxxxxxxx (the id format written by `/error`).
The waiting session then shows the summary and, only if the user agrees, reloads the code in place.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPORT_ID_RE = re.compile(r"err_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}", re.ASCII)
SKILL_DIR = Path(__file__).resolve().parent

# Run inside the target checkout; all values arrive through argv (never formatted into code).
SNIPPET = (
    "import sys, json; sys.path.insert(0, sys.argv[1]); import pro_football_slm as cli; "
    "print(json.dumps(cli.write_resolution(report_id=sys.argv[2], summary=sys.argv[3], commit=sys.argv[4])))"
)


def repo_root() -> str:
    override = os.environ.get("PFSLM_REPO", "").strip()
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
    repo = os.environ.get("PFSLM_WSL_REPO", "").strip()
    if not repo:
        raise SystemExit("Set PFSLM_WSL_REPO to the pro-football-slm checkout path inside WSL.")
    if not repo.startswith("/"):
        raise SystemExit("PFSLM_WSL_REPO must be an absolute path inside WSL (no ~ or $HOME: no shell expands it).")
    py = os.environ.get("PFSLM_WSL_PYTHON", "").strip() or "python3"
    # `wsl.exe -e` executes the program directly (no login shell), so the free-text summary is never
    # re-parsed by a shell.
    if pull:
        subprocess.run(["wsl.exe", "-e", "git", "-C", repo, "pull", "--ff-only"], check=True)
    ipc = os.environ.get("PFSLM_WSL_IPC_DIR", "").strip()
    prefix = ["wsl.exe", "-e", "env", f"PFSLM_IPC_DIR={ipc}"] if ipc else ["wsl.exe", "-e"]
    return subprocess.run(prefix + [py, "-c", SNIPPET, repo, rid, summary, commit], check=True).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], usage="%(prog)s {local,wsl} report_id commit [--pull] -- summary", allow_abbrev=False)
    ap.add_argument("source", choices=["local", "wsl"])
    ap.add_argument("report_id")
    ap.add_argument("commit")
    ap.add_argument("summary")
    ap.add_argument("--pull", action="store_true", help="wsl only: git pull --ff-only in the WSL checkout first")
    args = ap.parse_args(argv)
    if args.source == "wsl":
        return resolve_wsl(args.report_id, args.commit, args.summary, pull=args.pull)
    return resolve_local(args.report_id, args.commit, args.summary)


if __name__ == "__main__":
    sys.exit(main())
