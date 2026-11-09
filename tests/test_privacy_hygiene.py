"""The public tree must not carry personal email addresses or local machine paths (issue #35).

Only the *current* tree is checked. Git history is deliberately not rewritten.
"""
import codecs
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Free-mail providers (full domains, so company mail such as "mail.example.com" is not flagged).
# Project contact addresses use the project domain instead.
FREE_MAIL_DOMAINS = (
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "hotmail.com", "hotmail.co.uk",
    "outlook.com", "outlook.fr", "outlook.de", "live.com", "msn.com", "icloud.com", "me.com", "mac.com",
    "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.net", "gmx.de", "mail.com", "hey.com",
    "fastmail.com", "yandex.com", "yandex.ru", "qq.com", "163.com", "126.com", "zoho.com",
)
FREE_MAIL = re.compile(
    r"(?<![\w.+-])(?P<local>[\w.+-]+)@(?:" + "|".join(re.escape(d) for d in FREE_MAIL_DOMAINS) + r")(?![\w-])", re.I
)
PLACEHOLDER_EMAIL_LOCALS = {"you", "user", "name", "example", "yourname", "username", "email", "someone", "test"}

# Absolute paths that embed a person's account name on Windows, Linux or macOS.
LOCAL_PATH = re.compile(
    r"(?<![A-Za-z])(?i:[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2})(?P<win>[^\\/\s\"'<>%${}*]+)"
    r"|(?<![\w.-])(?:/mnt)?/[a-z]/(?i:Users)/(?P<wsl>[^/\s\"'<>%${}*]+)"
    r"|(?<![\w.-])/home/(?P<linux>[A-Za-z_][\w.-]*)(?![\w.-])"
    r"|(?<![\w.-])/Users/(?P<mac>[A-Za-z][\w.-]*)(?![\w.-])"
)
PLACEHOLDER_USERS = {
    "user", "username", "you", "yourname", "example", "runner", "runneradmin", "me", "name",
    "public", "default", "shared", "ubuntu", "vscode", "appuser", "node", "root",
    "circleci", "travis", "vagrant", "app", "git",
}

# TODO(#44): remove PENDING_44 and the xfail test below once the triage skill no longer
# embeds local paths (it is reworked on its own branch).
PENDING_44 = ".agents/skills/nfl-stat-error-triage/"

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".eggs",
    ".idea", ".vscode", "node_modules", "build", "dist", ".error_ipc",
}


def _walk(root):
    names = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        names += [Path(dirpath, f).relative_to(root).as_posix() for f in filenames]
    return names


def tracked_files(root=ROOT):
    """Tracked files (git ls-files); falls back to walking the tree outside a git checkout of `root`."""
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, check=True).stdout
        if Path(os.fsdecode(top).strip()).resolve() == Path(root).resolve():
            out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
            names = [os.fsdecode(n) for n in out.split(b"\0") if n]
            if names:
                return names
    except (OSError, subprocess.CalledProcessError):
        pass
    return _walk(root)


def read_text(path):
    """Decode any text file (UTF-8/16 with or without BOM, else cp1252); None for binary files."""
    data = Path(path).read_bytes()
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def scan(files, root=ROOT):
    hits = []
    for name in files:
        path = Path(root) / name
        if not path.is_file():
            continue
        text = read_text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in FREE_MAIL.finditer(line):
                if m.group("local").lower() not in PLACEHOLDER_EMAIL_LOCALS:
                    hits.append(f"{name}:{lineno}: free-mail address")
            for m in LOCAL_PATH.finditer(line):
                user = (m.group("win") or m.group("wsl") or m.group("linux") or m.group("mac") or "").lower()
                if user and user not in PLACEHOLDER_USERS:
                    hits.append(f"{name}:{lineno}: local machine path")
    return hits


BS = "\\"
# Built from fragments so this file does not trip the scanner itself.
SHOULD_FLAG = {
    "free-mail": "person.name@" + "gmail.com",
    "free-mail-uk": "person@" + "hotmail.co.uk",
    "windows-path": "C:" + BS + "Users" + BS + "jdoe" + BS + "proj",
    "windows-path-double-backslash": "C:" + BS * 2 + "Users" + BS * 2 + "jdoe",
    "windows-path-forward-slash": "c:/us" + "ers/jdoe/proj",
    "linux-path": "/ho" + "me/jdoe/proj",
    "linux-path-end-of-line": "cd /ho" + "me/jdoe",
    "mac-path": "/Us" + "ers/jdoe/proj",
    "markdown-backticks": "`/ho" + "me/jdoe`",
    "path-in-list": "PATH=/ho" + "me/jdoe:/usr/bin",
    "wsl-path": "/mnt/c/Us" + "ers/jdoe/proj",
    "git-bash-path": "/c/Us" + "ers/jdoe/proj",
}
SHOULD_PASS = {
    "project-address": "dev@ridgetopwalker.com",
    "company-mail-subdomain": "ops@mail.example.com",
    "placeholder-email": "you@" + "gmail.com",
    "windows-placeholder": "C:" + BS + "Users" + BS + "<user>" + BS + "ok",
    "windows-env-var": "C:" + BS + "Users" + BS + "%USERNAME%" + BS + "ok",
    "linux-placeholder": "/ho" + "me/user/ok",
    "container-user": "/ho" + "me/vscode/ws",
    "mac-shared": "/Us" + "ers/Shared/x",
    "route-not-a-path": "GET https://example.com/api/users/42/home/x",
    "relative-lookalike": "app/ho" + "me/index/page",
    "scheme-lookalike": "redis://us" + "ers/0 and uid:/us" + "ers/x",
    "windows-glob": "C:" + BS + "Users" + BS + "*" + BS + "AppData",
    "ci-user": "/ho" + "me/circleci/project",
}


@pytest.mark.parametrize("label", sorted(SHOULD_FLAG))
def test_scanner_flags(tmp_path, label):
    (tmp_path / "x.txt").write_text(SHOULD_FLAG[label])
    assert len(scan(["x.txt"], root=tmp_path)) == 1


@pytest.mark.parametrize("label", sorted(SHOULD_PASS))
def test_scanner_allows(tmp_path, label):
    (tmp_path / "x.txt").write_text(SHOULD_PASS[label])
    assert scan(["x.txt"], root=tmp_path) == []


def test_scanner_reads_utf16_and_cp1252_files(tmp_path):
    (tmp_path / "a.ps1").write_bytes(codecs.BOM_UTF16_LE + SHOULD_FLAG["windows-path"].encode("utf-16-le"))
    (tmp_path / "b.bat").write_bytes(("caf\xe9 " + SHOULD_FLAG["free-mail"]).encode("cp1252"))
    (tmp_path / "c.bin").write_bytes(b"\x00\x01" + SHOULD_FLAG["free-mail"].encode())
    assert len(scan(["a.ps1", "b.bat", "c.bin"], root=tmp_path)) == 2


def test_file_discovery_falls_back_outside_git(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("x = 1")
    assert tracked_files(tmp_path) == ["pkg/a.py"]


def test_tree_has_no_personal_email_or_local_paths():
    files = [n for n in tracked_files() if not n.startswith(PENDING_44)]
    assert files, "scanner found no files"
    assert scan(files) == []


@pytest.mark.xfail(raises=AssertionError, reason="local paths in the triage skill are being removed on the #44 branch", strict=True)
def test_error_triage_skill_has_no_local_paths():
    """strict: once #44 removes the paths this XPASSes and fails, which is the signal to delete PENDING_44."""
    files = [n for n in tracked_files() if n.startswith(PENDING_44)]
    assert files, "the exempted folder is gone: remove PENDING_44"
    assert scan(files) == []
