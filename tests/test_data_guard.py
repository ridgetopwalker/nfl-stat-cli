"""Participation data stays outside tracked artifacts, including learned data."""
from pathlib import Path
import subprocess

import pytest

from pro_football_slm.data_guard import check_data_artifacts, MAX_DATA_BYTES


def test_tracked_data_artifacts():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    assert check_data_artifacts(root, filter(None, tracked)) == []


@pytest.mark.parametrize("column", ["offense_players", "defense_players", "offense_formation",
                                    "defense_positions", "offense_personnel", "defense_jersey_numbers"])
def test_participation_columns_rejected(tmp_path, column):
    path = tmp_path / "synthetic.json"
    path.write_text('{"' + column + '": "obvious dummy"}', encoding="utf-8")
    assert "participation columns" in check_data_artifacts(tmp_path, [path.name])[0]


def test_oversized_and_compressed_data_rejected(tmp_path):
    (tmp_path / "large.csv").write_bytes(b"x" * (MAX_DATA_BYTES + 1))
    (tmp_path / "rows.csv.gz").write_bytes(b"synthetic compressed placeholder")
    failures = check_data_artifacts(tmp_path, ["large.csv", "rows.csv.gz"])
    assert len(failures) == 2
    assert "oversized" in failures[0]
    assert "compressed" in failures[1]


def test_source_and_small_pbp_allowed(tmp_path):
    (tmp_path / "data.csv").write_text("game_id,play_id\ndummy,1\n", encoding="utf-8")
    (tmp_path / "source.py").write_text("offense_players = []", encoding="utf-8")
    assert check_data_artifacts(tmp_path, ["data.csv", "source.py"]) == []
