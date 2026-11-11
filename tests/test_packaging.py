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
    assert (ROOT / "pro_football_slm" / "nflverse_bridge.R").is_file()
    assert "*.zip" in (ROOT / ".gitignore").read_text().splitlines()


def test_manifest_does_not_list_removed_files():
    manifest = (ROOT / "MANIFEST.in").read_text().splitlines()
    assert "include nflverse_bridge.R" not in manifest
    assert "include pro_football_slm/*.R" in manifest


def test_no_top_level_import_shim_or_launcher_references():
    assert not (ROOT / "pro_football_slm.py").exists(), "top-level shim next to the package makes imports ambiguous"
    assert "pro_football_slm.py" not in (ROOT / "MANIFEST.in").read_text()
    for name in ("pro-football-slm", "pfslm", "nfl-stat", "nfl-stat.bat", "pro-football-slm.bat", "pfslm.bat", "install.sh", "install.ps1"):
        text = (ROOT / name).read_text()
        assert "pro_football_slm.py" not in text, name
        assert "-m pro_football_slm" in text, name


def _launcher_project(tmp_path, launcher):
    """A copy of the launcher in a directory with no .venv, so the PATH python3 is the one used."""
    project = tmp_path / "proj"
    (project / "bin").mkdir(parents=True)
    shutil.copy(ROOT / launcher, project / launcher)
    (project / "pro_football_slm").symlink_to(ROOT / "pro_football_slm", target_is_directory=True)
    env = dict(os.environ, HOME=str(tmp_path / "home"))
    env.pop("PYTHONPATH", None)
    return project, env


@pytest.mark.skipif(shutil.which("bash") is None or not hasattr(os, "symlink"), reason="bash/symlinks not available")
@pytest.mark.parametrize("launcher", ["pro-football-slm", "nfl-stat", "pfslm"])
def test_launcher_runs_package_from_any_directory(tmp_path, launcher):
    project, env = _launcher_project(tmp_path, launcher)
    (project / "bin" / "python3").symlink_to(sys.executable)
    env["PATH"] = str(project / "bin") + os.pathsep + env.get("PATH", "")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = subprocess.run(["bash", str(project / launcher), "--help"], cwd=elsewhere, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None or not hasattr(os, "symlink"), reason="bash/symlinks not available")
@pytest.mark.parametrize("launcher", ["pro-football-slm", "nfl-stat", "pfslm"])
def test_launcher_puts_project_dir_on_pythonpath(tmp_path, launcher):
    """Independent of whether the package happens to be pip-installed: the launcher itself must set PYTHONPATH."""
    project, env = _launcher_project(tmp_path, launcher)
    stub = project / "bin" / "python3"
    stub.write_text('#!/usr/bin/env bash\necho "PYTHONPATH=$PYTHONPATH"\necho "ARGS=$*"\n')
    stub.chmod(0o755)
    env["PATH"] = str(project / "bin") + os.pathsep + env.get("PATH", "")
    result = subprocess.run(["bash", str(project / launcher), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"PYTHONPATH={project.resolve()}" in result.stdout
    assert "ARGS=-m pro_football_slm --help" in result.stdout


def test_windows_launchers_run_the_package_without_stale_errorlevel():
    for name in ("nfl-stat.bat", "pro-football-slm.bat", "pfslm.bat"):
        text = (ROOT / name).read_text()
        assert "-m pro_football_slm" in text and "PYTHONPATH" in text
        assert "if errorlevel 1" in text and "%ERRORLEVEL%" not in text, name


def test_stale_upload_helper_removed():
    # upload_to_github.py claimed the repo was private, omitted the package and tests, and
    # pushed with a token; the repository now exists and is published via normal git/PRs.
    assert not (ROOT / "upload_to_github.py").exists()


def test_metadata_is_honest_and_export_json_not_shipped():
    meta = (ROOT / "pyproject.toml").read_text()
    assert "Production/Stable" not in meta
    assert "Development Status :: 3 - Alpha" in meta
    assert 'requires-python = ">=3.10"' in meta
    assert "Python :: 3.8" not in meta
    assert "Python :: 3.9" not in meta
    assert "custom_stats_export.json" not in (ROOT / "MANIFEST.in").read_text()
    assert not (ROOT / "custom_stats_export.json").exists() or \
        "custom_stats_export.json" in (ROOT / ".gitignore").read_text()


def test_windows_launcher_copies_do_not_drift():
    bat = (ROOT / "nfl-stat.bat").read_text().replace("\r\n", "\n").strip()
    for name in ("pro-football-slm.bat", "pfslm.bat"):
        assert (ROOT / name).read_text().replace("\r\n", "\n").strip() == bat
    ps1 = (ROOT / "install.ps1").read_text().replace("\r\n", "\n")
    embedded = ps1.split('$LauncherContent = @"\n', 1)[1].split('\n"@', 1)[0].strip()
    assert embedded == bat, "install.ps1 generates a different launcher than the checked-in .bat files"
