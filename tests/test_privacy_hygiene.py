"""The public tree must not carry personal email addresses or local machine paths (issue #35).

Only the *current* tree is checked. Git history is deliberately not rewritten.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Free-mail addresses: project contact addresses use the project domain instead.
FREE_MAIL = re.compile(
    r"[\w.+-]+@(?:gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|icloud|me|aol|proton|protonmail)\.(?:com|me)\b",
    re.I,
)
# Absolute paths that embed a person's account name on Windows, Linux or macOS.
LOCAL_PATH = re.compile(
    r"(?:[A-Za-z]:\\{1,2}Users\\{1,2}(?P<win>[^\\/\s\"'<>]+))"
    r"|(?:/home/(?P<linux>[A-Za-z_][\w.-]*)/)"
    r"|(?:/Users/(?P<mac>[A-Za-z][\w.-]*)/)"
)
PLACEHOLDER_USERS = {"user", "username", "you", "yourname", "example", "runner", "me", "name"}

# Tracked separately in #44 (the error-triage skill is being reworked on its own branch).
PENDING_44 = ".agents/skills/nfl-stat-error-triage/"

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", ".error_ipc"}
TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".txt", ".in", ".sh", ".ps1", ".bat", ".json", ".yml", ".yaml",
    ".cfg", ".ini", ".R", ".gitignore", ".gitattributes", "",
}


def tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        names = [n for n in out.decode().split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
            names += [str((Path(dirpath) / f).relative_to(ROOT)).replace(os.sep, "/") for f in filenames]
    return [n for n in names if (ROOT / n).is_file() and Path(n).suffix in TEXT_SUFFIXES]


def scan(files):
    hits = []
    for name in files:
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if FREE_MAIL.search(line):
                hits.append(f"{name}:{lineno}: free-mail address")
            for m in LOCAL_PATH.finditer(line):
                user = (m.group("win") or m.group("linux") or m.group("mac") or "").lower()
                if user and user not in PLACEHOLDER_USERS:
                    hits.append(f"{name}:{lineno}: local machine path")
    return hits


def test_scanner_detects_what_it_should(tmp_path):
    sample = tmp_path / "x.md"
    # Built from fragments so this file does not trip the scanner itself.
    bs = "\\"
    lines = [
        "person.name@" + "gmail.com",
        "C:" + bs + "Users" + bs + "jdoe" + bs + "proj",
        "/ho" + "me/jdoe/proj",
        "/Us" + "ers/jdoe/proj",
        "C:" + bs + "Users" + bs + "<user>" + bs + "ok",
        "/ho" + "me/user/ok",
        "dev@ridgetopwalker.com",
    ]
    sample.write_text("\n".join(lines))
    global ROOT
    old, ROOT = ROOT, tmp_path
    try:
        hits = scan(["x.md"])
    finally:
        ROOT = old
    assert len(hits) == 4, hits  # email + three real-looking paths; placeholders and the project address pass


def test_tree_has_no_personal_email_or_local_paths():
    files = [n for n in tracked_text_files() if not n.startswith(PENDING_44)]
    assert files, "scanner found no files"
    assert scan(files) == []


@pytest.mark.xfail(reason="local paths in the triage skill are being removed on the #44 branch", strict=False)
def test_error_triage_skill_has_no_local_paths():
    files = [n for n in tracked_text_files() if n.startswith(PENDING_44)]
    assert scan(files) == []
