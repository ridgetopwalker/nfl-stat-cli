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
