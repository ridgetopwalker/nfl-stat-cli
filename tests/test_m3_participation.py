"""Generated synthetic participation, never committed rows."""
import json
import pytest
from pro_football_slm.officiating import load_table, PARTICIPATION_COLUMNS


def test_participation_flag_season_and_allowlist(tmp_path):
    fixture = tmp_path / "fixtures"
    fixture.mkdir()
    row = {"game_id": "2024_01_BAL_KC", "play_id": 1, "season": 2024,
           "offense_players": "dummy", "offense_formation": "SHOTGUN",
           "spread_line": 123, "headshot_url": "excluded", "birth_date": "excluded"}
    (fixture / "participation_2024.json").write_text(json.dumps([row]))
    for season, enabled in ((2024, False), (2022, True), (2026, True)):
        with pytest.raises(ValueError, match="not available for this season"):
            load_table("participation", season, tmp_path, units=enabled, fixture_dir=fixture)
    rows = load_table("participation", 2024, tmp_path, units=True, fixture_dir=fixture)
    assert rows[0]["offense_players"] == "dummy"
    assert set(rows[0]) == set(PARTICIPATION_COLUMNS)
    with pytest.raises(ValueError, match="learned"):
        load_table("participation", 2024, tmp_path / "learned", units=True, fixture_dir=fixture)


def test_participation_cached_projection(tmp_path, monkeypatch):
    (tmp_path / "participation_2024.json").write_text(json.dumps([
        {"game_id": "2024_01_BAL_KC", "season": 2024, "play_id": 1,
         "offense_players": "dummy", "spread_line": 123}]))
    def no_network(*args, **kwargs):
        raise AssertionError("cached rows must not fetch")
    monkeypatch.setattr("urllib.request.build_opener", no_network)
    rows = load_table("participation", 2024, tmp_path, units=True)
    assert "spread_line" not in rows[0]


def test_participation_uncached_download_projects_and_caches(tmp_path, monkeypatch):
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    stream = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([{
        "game_id": "2024_01_BAL_KC", "play_id": 1, "season": 2024,
        "offense_players": "dummy", "spread_line": 999,
        "birth_date": "excluded", "headshot_url": "excluded"}]), stream)
    payload = stream.getvalue()
    calls = []
    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            assert url.endswith('/pbp_participation/pbp_participation_2024.parquet')
            return io.BytesIO(payload)
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    rows = load_table("participation", 2024, tmp_path, units=True)
    assert set(rows[0]) == set(PARTICIPATION_COLUMNS)
    cached = json.loads((tmp_path / "participation_2024.json").read_text())
    assert cached == rows
    assert load_table("participation", 2024, tmp_path, units=True) == rows
    assert len(calls) == 1
