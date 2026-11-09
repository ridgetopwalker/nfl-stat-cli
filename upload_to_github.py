#!/usr/bin/env python3
"""
One-step uploader to create the private GitHub repository `ridgetopwalker/pro-football-slm`
and push all repository files using either the `gh` CLI or a GitHub Personal Access Token (`GITHUB_TOKEN`).
Works on both *nix (Linux/macOS) and Windows.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_OWNER = "ridgetopwalker"
REPO_NAME = "pro-football-slm"
REPO_DESC = "Cross-platform (*nix & Windows) colorized ASCII art NFL analytics & composable custom stat CLI powered by nflverse (R) and sportsdataverse-py (Python)."
FILES = [
    "LICENSE",
    "MANIFEST.in",
    ".gitignore",
    ".gitattributes",
    "README.md",
    "pyproject.toml",
    "pro_football_slm.py",
    "nflverse_bridge.R",
    "custom_stats_export.json",
    "install.bat",
    "install.ps1",
    "install.sh",
]


def push_via_gh_cli(repo_dir: Path) -> bool:
    if not shutil.which("gh") or not shutil.which("git"):
        return False
    try:
        if not (repo_dir / ".git").exists():
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
        subprocess.run(["git", "add"] + FILES + ["upload_to_github.py"], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit: pro-football-slm (nflverse R + sportsdataverse-py)"], cwd=repo_dir, check=False)
        subprocess.run(
            [
                "gh", "repo", "create", f"{REPO_OWNER}/{REPO_NAME}",
                "--private",
                "--description", REPO_DESC,
                "--source=.",
                "--remote=origin",
                "--push",
            ],
            cwd=repo_dir,
            check=True,
        )
        print(f"✔ Created private repository and pushed to https://github.com/{REPO_OWNER}/{REPO_NAME}")
        return True
    except Exception as exc:
        print(f"[gh cli fallback] {exc}")
        return False


def push_via_github_api(repo_dir: Path, token: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "pro-football-slm-uploader",
    }
    # 1. Create private repository
    create_payload = json.dumps({
        "name": REPO_NAME,
        "description": REPO_DESC,
        "private": True,
        "auto_init": False,
    }).encode("utf-8")
    req = urllib.request.Request("https://api.github.com/user/repos", data=create_payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            repo_info = json.loads(resp.read().decode("utf-8"))
            print(f"✔ Created private repository: {repo_info.get('html_url')}")
    except urllib.error.HTTPError as err:
        if err.code != 422:  # 422 = already exists
            raise

    # 2. Upload each file via Contents API
    for fname in FILES + ["upload_to_github.py"]:
        fpath = repo_dir / fname
        if not fpath.exists():
            continue
        b64_content = base64.b64encode(fpath.read_bytes()).decode("ascii")
        put_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{fname}"
        put_payload = json.dumps({
            "message": f"Add {fname}",
            "content": b64_content,
            "branch": "main",
        }).encode("utf-8")
        put_req = urllib.request.Request(put_url, data=put_payload, headers=headers, method="PUT")
        with urllib.request.urlopen(put_req) as resp:
            print(f"  ✔ Uploaded {fname} ({resp.status})")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    if push_via_gh_cli(here):
        sys.exit(0)
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if gh_token:
        push_via_github_api(here, gh_token)
        sys.exit(0)
    print("To upload immediately, either authenticate `gh auth login` and re-run `python3 upload_to_github.py`,")
    print("or set `GITHUB_TOKEN=<your_fine_grained_pat>` and run `python3 upload_to_github.py`.")
    sys.exit(1)
