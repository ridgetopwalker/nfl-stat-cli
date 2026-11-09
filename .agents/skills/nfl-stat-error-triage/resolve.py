#!/usr/bin/env python3
"""Signal that an nfl-stat error report is fixed, on the side (windows|wsl) that filed it.

Usage: py -3 resolve.py <windows|wsl> <report_id> <commit> "<summary>"
Also pulls origin/master into the WSL checkout first when source is wsl.
"""
import subprocess
import sys

WIN_REPO = r"<local-path>\sources\nfl-stat-cli"
WSL_REPO = "<local-path>/nfl-stat-cli"
WSL_PY = f"{WSL_REPO}/.venv/bin/python"

SNIPPET = """
import sys
sys.path.insert(0, {repo!r})
import nfl_stat_cli as cli
print(cli.write_resolution(report_id={rid!r}, summary={summary!r}, commit={commit!r}))
"""


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    source, rid, commit, summary = sys.argv[1:]
    if source == "wsl":
        subprocess.run(["wsl.exe", "git", "-C", WSL_REPO, "pull", "origin", "master"], check=True)
        code = SNIPPET.format(repo=WSL_REPO, rid=rid, summary=summary, commit=commit)
        subprocess.run(["wsl.exe", WSL_PY, "-"], input=code, text=True, check=True)
    else:
        code = SNIPPET.format(repo=WIN_REPO, rid=rid, summary=summary, commit=commit)
        subprocess.run([sys.executable, "-"], input=code, text=True, check=True, cwd=WIN_REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
