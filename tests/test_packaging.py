"""Packaging hygiene checks (issues #11, #33, #36)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_stale_zip_or_duplicate_r_bridge():
    assert not list(ROOT.glob("*.zip")), "release archives must not live in the repo root"
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


def test_launcher_runs_package_from_any_directory(tmp_path):
    import shutil
    import subprocess
    import sys
    if not shutil.which("bash"):
        import pytest
        pytest.skip("bash not available")
    import os
    env = dict(os.environ, HOME=str(tmp_path))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONPATH", None)
    result = subprocess.run(["bash", str(ROOT / "nfl-stat"), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
