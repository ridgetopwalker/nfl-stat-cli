#!/usr/bin/env python3
"""Idempotent rebrand: nfl-stat-cli -> Pro Football SLM / pro_football_slm.

Safe to re-run after later PRs land. Does mechanical renames and text rewrites only;
product-name constants, ASCII art, env fallback helper, data-dir migration, NOTICE,
and console-script shims belong in a separate manual commit.

Usage:
  python3 tools/rebrand.py              # apply renames + rewrites
  python3 tools/rebrand.py --dry-run    # print plan; write nothing
  python3 tools/rebrand.py --check      # exit 1 if anything left to rename

Does NOT rewrite github.com/ridgetopwalker/nfl-stat-cli (repo name stays).
Does NOT touch nflverse project names/URLs, this script, or the legacy-compat module.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Allow / exclude
# ---------------------------------------------------------------------------

TEXT_SUFFIXES = {
    ".py", ".md", ".R", ".r", ".sh", ".bash", ".bat", ".cmd", ".ps1",
    ".toml", ".cfg", ".ini", ".json", ".txt", ".yml", ".yaml",
    ".in", ".rst",
}
# Extensionless path basenames we still rewrite (launchers, etc.)
TEXT_BASENAMES = {
    "nfl-stat", "pro-football-slm", "pfslm", "Dockerfile", "Makefile",
    "LICENSE", "NOTICE", "MANIFEST.in",
}

EXCLUDE_DIR_NAMES = {
    ".git", ".venv", "venv", "ENV", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    "wheels", "node_modules", ".eggs",
}
EXCLUDE_SUFFIXES = {".zip", ".pyc", ".pyo", ".so", ".dylib", ".egg", ".whl", ".png", ".jpg", ".jpeg", ".gif"}

# Paths relative to repo root that the script must never rewrite.
EXCLUDE_REL_PATHS = {
    "tools/rebrand.py",
    # Legacy env/compat helpers keep NFL_STAT_* fallback spellings on purpose.
    "pro_football_slm/legacy_compat.py",
    "pro_football_slm/_legacy_env.py",
    "nfl_stat_cli/legacy_compat.py",  # pre-rename path, just in case
    # Rebrand tests intentionally exercise legacy env names / migration paths.
    "tests/test_rebrand.py",
}

# Directory / file moves: (old_rel, new_rel). Applied in order; parents first.
PATH_MOVES: List[Tuple[str, str]] = [
    (".agents/skills/nfl-stat-error-triage", ".agents/skills/pro-football-slm-error-triage"),
    ("nfl_stat_cli", "pro_football_slm"),
    ("nfl_stat_cli.py", "pro_football_slm.py"),
    ("nfl-stat", "pro-football-slm"),
    ("nfl-stat.bat", "pro-football-slm.bat"),
    ("nfl-stat-cli.bat", "pro-football-slm-cli.bat"),  # keep a Windows alias name
]

# Placeholders so we never rewrite the GitHub repo URL.
_GH_REPO_SLUG = "ridgetopwalker/nfl-stat-cli"
_GH_PLACEHOLDER = "<<<GITHUB_REPO_SLUG_DO_NOT_EDIT>>>"

# Ordered text substitutions applied to file contents (after URL protect).
# Longer / more specific patterns first.
CONTENT_SUBS: List[Tuple[str, str]] = [
    ("nfl-stat-error-triage", "pro-football-slm-error-triage"),
    ("reload_nfl_stat_cli", "reload_pro_football_slm"),
    ("nfl_stat_cli", "pro_football_slm"),
    ("NFL-STAT-CLI", "Pro Football SLM"),  # old banner / loading brand string
    ("nfl-stat-cli", "pro-football-slm"),
    ("NFL_STAT_", "PFSLM_"),
    (".nfl_stat_cli", ".pro_football_slm"),
    # Launcher / prompt leftovers (hyphenated short name without -cli)
    # Only rewrite standalone "nfl-stat" tokens, not github repo (already protected)
    # and not "pro-football-slm" (already new).
]

# Token rewrite for the short CLI name inside text (word-ish boundaries).
_NFL_STAT_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])nfl-stat(?![A-Za-z0-9_-])")

# Patterns that --check treats as unfinished work (excluding allowed leftovers).
CHECK_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("package dir nfl_stat_cli/", re.compile(r"")),  # special-cased
    ("import/module nfl_stat_cli", re.compile(r"\bnfl_stat_cli\b")),
    ("dist name nfl-stat-cli", re.compile(r"nfl-stat-cli")),
    ("env prefix NFL_STAT_", re.compile(r"\bNFL_STAT_")),
    ("data dir .nfl_stat_cli", re.compile(r"\.nfl_stat_cli\b")),
    ("skill nfl-stat-error-triage", re.compile(r"nfl-stat-error-triage")),
]


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def is_excluded(path: Path) -> bool:
    r = rel(path)
    if r in EXCLUDE_REL_PATHS:
        return True
    parts = Path(r).parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def is_text_candidate(path: Path) -> bool:
    if not path.is_file() or is_excluded(path):
        return False
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    if path.name in TEXT_BASENAMES:
        return True
    # Extensionless small files that look like scripts
    if path.suffix == "" and path.stat().st_size < 200_000:
        try:
            head = path.read_bytes()[:80]
        except OSError:
            return False
        if head.startswith(b"#!") or b"\0" not in head:
            # Heuristic: treat as text if no NUL in head and mostly decodable
            try:
                head.decode("utf-8")
                return True
            except UnicodeDecodeError:
                return False
    return False


def iter_repo_files() -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # prune excluded dirs in-place
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            if not is_excluded(p):
                yield p


def git_available() -> bool:
    return (ROOT / ".git").exists() or (ROOT / ".git").is_file()


def git_mv(src: Path, dst: Path, dry_run: bool) -> str:
    """Move via git mv when possible; fall back to rename. Returns action label."""
    if dst.exists():
        return f"skip (exists): {rel(src)} -> {rel(dst)}"
    if not src.exists():
        return f"skip (missing): {rel(src)}"
    if dry_run:
        return f"move: {rel(src)} -> {rel(dst)}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if git_available():
        res = subprocess.run(
            ["git", "mv", str(src), str(dst)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return f"git mv: {rel(src)} -> {rel(dst)}"
        # fall through if git mv fails (e.g. untracked)
    src.rename(dst)
    return f"rename: {rel(src)} -> {rel(dst)}"


def protect_github(text: str) -> str:
    # Protect the repo slug in https, ssh, raw, api, and badge URLs.
    return text.replace(_GH_REPO_SLUG, _GH_PLACEHOLDER)


def restore_github(text: str) -> str:
    return text.replace(_GH_PLACEHOLDER, _GH_REPO_SLUG)


def transform_text(text: str) -> str:
    out = protect_github(text)
    for old, new in CONTENT_SUBS:
        out = out.replace(old, new)
    # Intentionally do NOT rewrite bare "nfl-stat" tokens: the deprecated one-release
    # console-script shim and docs that mention the old command must survive a re-run.
    out = restore_github(out)
    return out


def needs_transform(text: str) -> bool:
    return transform_text(text) != text


def plan_moves() -> List[Tuple[str, str]]:
    planned: List[Tuple[str, str]] = []
    for old_s, new_s in PATH_MOVES:
        old, new = ROOT / old_s, ROOT / new_s
        if old.exists() and not new.exists():
            planned.append((old_s, new_s))
        elif old.exists() and new.exists() and old.resolve() != new.resolve():
            # Special case: nfl-stat-cli.bat -> pro-football-slm.bat when target
            # already created from nfl-stat.bat; drop the duplicate source later.
            planned.append((old_s, new_s + " (target exists; will remove source if identical role)"))
    return planned


def apply_moves(dry_run: bool) -> List[str]:
    actions: List[str] = []
    # Handle bat collapse carefully: if both nfl-stat.bat and nfl-stat-cli.bat exist,
    # move nfl-stat.bat first, then remove nfl-stat-cli.bat after rewriting is done
    # if the target already exists.
    for old_s, new_s in PATH_MOVES:
        old, new = ROOT / old_s, ROOT / new_s
        if not old.exists():
            actions.append(f"skip (missing): {old_s}")
            continue
        if new.exists():
            if old.resolve() == new.resolve():
                actions.append(f"skip (same): {old_s}")
                continue
            # Target already present (idempotent or prior partial run).
            if old_s.endswith(".bat") and new_s.endswith(".bat"):
                try:
                    same = old.read_bytes() == new.read_bytes()
                except OSError:
                    same = False
                if same:
                    if dry_run:
                        actions.append(f"remove duplicate launcher: {old_s} (identical to {new_s})")
                    else:
                        old.unlink()
                        actions.append(f"removed duplicate launcher: {old_s}")
                else:
                    actions.append(f"skip (differs): {old_s} vs {new_s}")
                continue
            actions.append(f"skip (target exists): {old_s} -> {new_s}")
            continue
        actions.append(git_mv(old, new, dry_run=dry_run))
    return actions


def apply_rewrites(dry_run: bool) -> Tuple[List[str], int]:
    actions: List[str] = []
    changed = 0
    for path in sorted(iter_repo_files(), key=lambda p: rel(p)):
        if not is_text_candidate(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = transform_text(original)
        if updated == original:
            continue
        actions.append(f"edit: {rel(path)}")
        changed += 1
        if not dry_run:
            path.write_text(updated, encoding="utf-8")
    return actions, changed


def check_remaining() -> List[str]:
    """Return human-readable leftover rename problems (empty => clean)."""
    problems: List[str] = []
    if (ROOT / "nfl_stat_cli").exists() and not (ROOT / "pro_football_slm").exists():
        problems.append("package directory nfl_stat_cli/ still present without pro_football_slm/")
    elif (ROOT / "nfl_stat_cli").exists() and (ROOT / "pro_football_slm").exists():
        problems.append("both nfl_stat_cli/ and pro_football_slm/ exist")
    if (ROOT / "nfl_stat_cli.py").exists():
        problems.append("nfl_stat_cli.py still present")
    if (ROOT / ".agents" / "skills" / "nfl-stat-error-triage").exists():
        problems.append(".agents/skills/nfl-stat-error-triage still present")

    for path in sorted(iter_repo_files(), key=lambda p: rel(p)):
        if not is_text_candidate(path):
            continue
        r = rel(path)
        if r in EXCLUDE_REL_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Ignore protected GitHub repo URL occurrences.
        scrubbed = protect_github(text)
        for label, cre in CHECK_PATTERNS:
            if label.startswith("package dir"):
                continue
            if cre.pattern == "":
                continue
            if cre.search(scrubbed):
                # Allow NFL_STAT_ only inside legacy_compat modules (already excluded)
                # and inside comments that document the fallback — still flag in check
                # except for explicit allow in shim launchers that only print a notice.
                if "NFL_STAT_" in label and "legacy" in r:
                    continue
                problems.append(f"{label} in {r}")
                break  # one problem per file is enough
        if "github.com/ridgetopwalker/pro-football-slm" in scrubbed or "ridgetopwalker/pro-football-slm.git" in scrubbed:
            problems.append(f"GitHub repo slug wrongly rewritten in {r}")
    return problems


def print_summary(moves: Sequence[str], edits: Sequence[str], mode: str) -> None:
    print(f"=== rebrand.py ({mode}) ===")
    print(f"root: {ROOT}")
    print(f"moves: {len([m for m in moves if not m.startswith('skip')])}")
    for m in moves:
        print(f"  {m}")
    print(f"edits: {len(edits)}")
    for e in edits:
        print(f"  {e}")
    print(f"ridgetopwalker/nfl-stat-cli repo slug left untouched: yes")
    print(f"excluded: {', '.join(sorted(EXCLUDE_REL_PATHS))}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print planned moves/edits; write nothing")
    g.add_argument("--check", action="store_true", help="exit 1 if anything remains to rename")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.check:
        problems = check_remaining()
        if problems:
            print("rebrand --check: FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("rebrand --check: OK")
        return 0

    dry = bool(args.dry_run)
    moves = apply_moves(dry_run=dry)
    edits, _n = apply_rewrites(dry_run=dry)
    print_summary(moves, edits, "dry-run" if dry else "apply")

    if not dry:
        # Second pass should be a no-op (idempotency smoke signal).
        moves2 = apply_moves(dry_run=True)
        edits2, n2 = apply_rewrites(dry_run=True)
        pending_moves = [m for m in moves2 if m.startswith("move:") or m.startswith("git mv:")]
        if pending_moves or n2:
            print("WARNING: second pass still has work (not fully idempotent):")
            for m in pending_moves:
                print(f"  {m}")
            for e in edits2:
                print(f"  {e}")
            return 2
        print("idempotent: second pass is a no-op")
    return 0


if __name__ == "__main__":
    sys.exit(main())
