"""Packaging hygiene checks (issues #11, #33, #36)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tracked_files():
    """Files tracked by git (local, gitignored build output does not count); falls back to the filesystem."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        return [name for name in out.decode().split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        return [p.name for p in ROOT.iterdir()]


def test_no_stale_zip_or_duplicate_r_bridge():
    assert not [n for n in tracked_files() if n.endswith(".zip")], "release archives must not be tracked"
    assert not (ROOT / "nflverse_bridge.R").exists(), "R bridge lives only inside the package"
    assert (ROOT / "nfl_stat_cli" / "nflverse_bridge.R").is_file()
    assert "*.zip" in (ROOT / ".gitignore").read_text().splitlines()


def test_manifest_does_not_list_removed_files():
    manifest = (ROOT / "MANIFEST.in").read_text().splitlines()
    assert "include nflverse_bridge.R" not in manifest
    assert "include nfl_stat_cli/*.R" in manifest


def test_no_top_level_import_shim_or_launcher_references():
    assert not (ROOT / "nfl_stat_cli.py").exists(), "top-level shim next to the package makes imports ambiguous"
    assert "nfl_stat_cli.py" not in (ROOT / "MANIFEST.in").read_text()
    for name in ("nfl-stat", "nfl-stat.bat", "nfl-stat-cli.bat", "install.sh", "install.ps1"):
        text = (ROOT / name).read_text()
        assert "nfl_stat_cli.py" not in text, name
        assert "-m nfl_stat_cli" in text, name


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_launcher_runs_package_from_any_directory(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONPATH", None)
    result = subprocess.run(["bash", str(ROOT / "nfl-stat"), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_launcher_puts_project_dir_on_pythonpath(tmp_path):
    """Independent of whether the package happens to be pip-installed: the launcher itself must set PYTHONPATH."""
    stub = tmp_path / "bin" / "python3"
    stub.parent.mkdir()
    stub.write_text('#!/usr/bin/env bash\necho "PYTHONPATH=$PYTHONPATH"\necho "ARGS=$*"\n')
    stub.chmod(0o755)
    env = dict(os.environ, PATH=str(stub.parent) + os.pathsep + os.environ.get("PATH", ""))
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(tmp_path)
    result = subprocess.run(["bash", str(ROOT / "nfl-stat"), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"PYTHONPATH={ROOT}" in result.stdout
    assert "ARGS=-m nfl_stat_cli --help" in result.stdout


def test_windows_launchers_run_the_package_without_stale_errorlevel():
    for name in ("nfl-stat.bat", "nfl-stat-cli.bat"):
        text = (ROOT / name).read_text()
        assert "-m nfl_stat_cli" in text and "PYTHONPATH" in text
        assert "if errorlevel 1" in text and "%ERRORLEVEL%" not in text, name


def test_stale_upload_helper_removed():
    # upload_to_github.py claimed the repo was private, omitted the package and tests, and
    # pushed with a token; the repository now exists and is published via normal git/PRs.
    assert not (ROOT / "upload_to_github.py").exists()


def test_metadata_is_honest_and_export_json_not_shipped():
    meta = (ROOT / "pyproject.toml").read_text()
    assert "Production/Stable" not in meta
    assert "Development Status :: 3 - Alpha" in meta
    assert 'requires-python = ">=3.9"' in meta
    assert "Python :: 3.8" not in meta
    assert "custom_stats_export.json" not in (ROOT / "MANIFEST.in").read_text()
    assert not (ROOT / "custom_stats_export.json").exists() or \
        "custom_stats_export.json" in (ROOT / ".gitignore").read_text()
