"""Legacy name compatibility for the nfl-stat-cli -> Pro Football SLM rename.

Keeps one-release fallbacks for NFL_STAT_* environment variables and the
~/.nfl_stat_cli data directory. Excluded from tools/rebrand.py rewrites so the
old spellings remain available for the fallback path.
"""
from __future__ import annotations

import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import Dict, Optional, Set

OLD_ENV_PREFIX = "NFL_STAT_"
NEW_ENV_PREFIX = "PFSLM_"
OLD_DATA_DIRNAME = ".nfl_stat_cli"
NEW_DATA_DIRNAME = ".pro_football_slm"
MIGRATION_MARKER = ".migrated_from_nfl_stat_cli"

_warned_env: Set[str] = set()
_migration_attempted = False


def reset_compat_state_for_tests() -> None:
    """Clear one-time notice / migration flags (tests only)."""
    global _migration_attempted
    _warned_env.clear()
    _migration_attempted = False


def _emit_env_deprecation(old_name: str, new_name: str) -> None:
    if old_name in _warned_env:
        return
    _warned_env.add(old_name)
    msg = (
        f"{old_name} is deprecated; use {new_name}. "
        f"The old name still works for one release."
    )
    try:
        sys.stderr.write(f"pro-football-slm: {msg}\n")
    except Exception:
        pass
    try:
        warnings.warn(msg, DeprecationWarning, stacklevel=3)
    except Exception:
        # e.g. filteractions('error') — stderr notice already emitted
        pass


def env_get(name: str, default: Optional[str] = None, *, legacy_only: bool = False) -> Optional[str]:
    """Read PFSLM_* first, then fall back to NFL_STAT_* with a one-time notice.

    ``name`` may be a full ``PFSLM_FOO`` / ``NFL_STAT_FOO`` key, or a bare suffix
    such as ``FOO`` / ``_FOO`` (normalized to ``PFSLM_FOO``).
    ``legacy_only`` supports validated settings whose invalid preferred value
    must fall back to a valid legacy value.
    """
    if name.startswith(NEW_ENV_PREFIX):
        new_name = name
        old_name = OLD_ENV_PREFIX + name[len(NEW_ENV_PREFIX):]
    elif name.startswith(OLD_ENV_PREFIX):
        # Prefer the new spelling even if the caller passed the old key.
        old_name = name
        new_name = NEW_ENV_PREFIX + name[len(OLD_ENV_PREFIX):]
    else:
        suffix = name[1:] if name.startswith("_") else name
        new_name = NEW_ENV_PREFIX + suffix
        old_name = OLD_ENV_PREFIX + suffix

    if not legacy_only and new_name in os.environ:
        return os.environ.get(new_name)
    if old_name in os.environ:
        _emit_env_deprecation(old_name, new_name)
        return os.environ.get(old_name)
    return default


def env_truthy(name: str) -> bool:
    raw = env_get(name, "") or ""
    return raw.strip().lower() in ("1", "true", "yes", "on")


def default_data_dir(home: Optional[Path] = None) -> Path:
    """Return ~/.pro_football_slm, migrating from ~/.nfl_stat_cli once if needed."""
    base = Path(home) if home is not None else Path.home()
    new_dir = base / NEW_DATA_DIRNAME
    old_dir = base / OLD_DATA_DIRNAME
    maybe_migrate_data_dir(old_dir, new_dir)
    return new_dir


def maybe_migrate_data_dir(old_dir: Path, new_dir: Path) -> Dict[str, str]:
    """
    One-time migration of cache/ and error_ipc/ from the old data dir.

    Rules: move only if the new dir is missing (or empty of those subtrees);
    never overwrite existing targets; leave a marker only after a clean pass;
    best-effort if another process races (does not overwrite). Returns a small status dict for tests/logging.
    """
    global _migration_attempted
    status = {"action": "none", "old": str(old_dir), "new": str(new_dir)}
    try:
        if new_dir.exists() and (new_dir / MIGRATION_MARKER).is_file():
            status["action"] = "already_migrated"
            return status
        if not old_dir.exists():
            status["action"] = "no_old_dir"
            return status

        # If new dir already has content we care about, do not clobber.
        interesting = ("cache", "error_ipc")
        new_has = any((new_dir / sub).exists() for sub in interesting) if new_dir.exists() else False
        if new_has:
            # Record marker so we stop probing, but leave both trees alone.
            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                marker = new_dir / MIGRATION_MARKER
                if not marker.exists():
                    marker.write_text(
                        f"left_in_place_both_dirs_present\nold={old_dir}\n",
                        encoding="utf-8",
                    )
            except OSError:
                pass
            status["action"] = "both_exist_skipped"
            return status

        if _migration_attempted:
            status["action"] = "skipped_concurrent"
            return status
        _migration_attempted = True

        new_dir.mkdir(parents=True, exist_ok=True)
        moved = []
        for sub in interesting:
            src = old_dir / sub
            dst = new_dir / sub
            if not src.exists():
                continue
            if dst.exists():
                continue
            try:
                shutil.move(str(src), str(dst))
                moved.append(sub)
            except OSError as exc:
                status["error"] = str(getattr(exc, "strerror", None) or exc)
                # Stop without writing a marker so a later run can retry remaining subs.
                break
        if "error" in status:
            status["action"] = "partial"
            status["moved"] = ",".join(moved)
            return status
        marker = new_dir / MIGRATION_MARKER
        if not marker.exists():
            marker.write_text(
                "migrated_from=" + str(old_dir) + "\nmoved=" + ",".join(moved) + "\n",
                encoding="utf-8",
            )
        status["action"] = "migrated" if moved else "marker_only"
        status["moved"] = ",".join(moved)
    except OSError as exc:
        status["action"] = "error"
        status["error"] = str(getattr(exc, "strerror", None) or exc)
    return status
