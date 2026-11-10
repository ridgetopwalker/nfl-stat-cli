"""Issue #9: R bridge cache must be atomic and validated, and share the Python path's row predicate.

All tests are hermetic: Rscript and subprocess are faked, caches live in tmp_path, data is synthetic.
"""
import csv
import io
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import nfl_stat_cli as cli

HEADER = ["season", "week", "game_id", "play_id", "posteam", "defteam", "play_type", "pass_attempt",
          "rush_attempt", "penalty", "timeout", "desc", "epa"]

# (play_id, posteam, play_type, pass_attempt, rush_attempt, penalty, timeout, desc)
RAW_PLAYS = [
    (1, "ZZZ", "pass", 1, 0, 0, 0, "pass to a receiver"),
    (2, "ZZZ", "run", 0, 1, 0, 0, "run up the middle"),
    (3, "ZZZ", "kickoff", 0, 0, 0, 0, "kickoff into the end zone"),
    (4, "ZZZ", "no_play", 0, 0, 1, 0, "false start, no play"),
    (5, "ZZZ", "no_play", 0, 0, 0, 1, "timeout called"),
    (6, "ZZZ", "punt", 0, 0, 0, 0, "punt, penalty declined"),      # kept by the shared desc rule
    (7, "ZZZ", "run", 0, 0, 0, 0, "typed run without attempt flag"),  # kept by play_type rule
    (8, "", "pass", 1, 0, 0, 0, "no possession team"),            # never kept
    (9, "ZZZ", "field_goal", 0, 0, 0, 0, "field goal is good"),
]
EXPECTED_IDS = {1, 2, 4, 5, 6, 7}


def _csv_text(plays=RAW_PLAYS, season=2025):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for pid, team, pt, pa, ra, pen, to, desc in plays:
        w.writerow([season, 1, f"{season}_01_YYY_ZZZ", pid, team, "YYY", pt, pa, ra, pen, to, desc, 0.1])
    return buf.getvalue()


class FakeR:
    """Stand-in for subprocess.run + shutil.which. `writer(path)` produces the output file."""

    def __init__(self, monkeypatch, writer, returncode=0, raises=None):
        self.calls = []
        self.writer = writer
        self.returncode = returncode
        self.raises = raises
        monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/Rscript")
        monkeypatch.setattr(cli.subprocess, "run", self._run)

    def _run(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        out = Path(cmd[cmd.index("--output") + 1])
        if self.writer:
            self.writer(out)
        if self.raises:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr="")


def _write(text):
    return lambda path: Path(path).write_text(text, encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NFL_STAT_R_TIMEOUT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))


def _bridge(tmp_path):
    return cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="r")


def _ids(rows):
    return {int(r["play_id"]) for r in rows}


# --- row parity between backends -------------------------------------------------------------

def test_r_backend_keeps_exactly_the_rows_the_python_backend_keeps(monkeypatch, tmp_path):
    FakeR(monkeypatch, _write(_csv_text()))
    r_rows = _bridge(tmp_path)._try_nflverse_r([2025])

    # Python/dataframe path fed the same raw records
    records = [dict(zip(HEADER, [2025, 1, "2025_01_YYY_ZZZ", pid, team, "YYY", pt, pa, ra, pen, to, desc, 0.1]))
               for pid, team, pt, pa, ra, pen, to, desc in RAW_PLAYS]
    fake_df = SimpleNamespace(to_dict=lambda orient="records": records)
    py_rows = _bridge(tmp_path)._normalize_dataframe(fake_df)

    assert _ids(py_rows) == EXPECTED_IDS
    assert _ids(r_rows) == _ids(py_rows)


def test_bridge_scripts_export_all_possession_plays_and_stay_identical():
    root = Path(__file__).resolve().parent.parent
    packaged = (root / "nfl_stat_cli" / "nflverse_bridge.R").read_text(encoding="utf-8")
    top = (root / "nflverse_bridge.R").read_text(encoding="utf-8")
    assert packaged == top
    assert "out_df <- as.data.frame(pbp)[!is.na(pbp$posteam), keep_cols, drop = FALSE]" in packaged
    assert "pass_attempt == 1) | (!is.na(pbp$rush_attempt)" not in packaged
    # every column the shared row predicate reads must be exported
    for col in ("posteam", "play_type", "pass_attempt", "rush_attempt", "penalty", "timeout", "desc"):
        assert f'"{col}"' in packaged


# --- cache validation ------------------------------------------------------------------------

def test_truncated_cache_is_not_reused(monkeypatch, tmp_path):
    b = _bridge(tmp_path)
    good = _csv_text()
    truncated = good[: good.rindex("\n", 0, len(good) - 25)] + "\n2025,1,2025_01_YYY_ZZZ,99,ZZ"  # cut mid-row, > 256 bytes
    assert len(truncated) > 256
    # seed a fresh-looking (mtime = now) truncated cache file under the name the loader will use
    probe = FakeR(monkeypatch, _write(good))
    b._try_nflverse_r([2025])
    cache_file = next((tmp_path / "cache").glob("nflverse_pbp_*.csv"))
    cache_file.write_text(truncated, encoding="utf-8")
    probe.calls.clear()

    rows = b._try_nflverse_r([2025])
    assert len(probe.calls) == 1, "truncated cache must trigger a refetch"
    assert _ids(rows) == EXPECTED_IDS
    assert cache_file.read_text(encoding="utf-8") == good


def test_valid_fresh_cache_is_reused_without_running_r(monkeypatch, tmp_path):
    b = _bridge(tmp_path)
    fake = FakeR(monkeypatch, _write(_csv_text()))
    b._try_nflverse_r([2025])
    assert len(fake.calls) == 1
    rows = b._try_nflverse_r([2025])
    assert len(fake.calls) == 1
    assert _ids(rows) == EXPECTED_IDS


def test_cache_with_out_of_range_seasons_is_rejected(monkeypatch, tmp_path):
    b = _bridge(tmp_path)
    fake = FakeR(monkeypatch, _write(_csv_text()))
    b._try_nflverse_r([2025])
    cache_file = next((tmp_path / "cache").glob("nflverse_pbp_*.csv"))
    cache_file.write_text(_csv_text(season=2019), encoding="utf-8")  # row seasons not in the request
    fake.calls.clear()
    b._try_nflverse_r([2025])
    assert len(fake.calls) == 1


# --- atomic writes ---------------------------------------------------------------------------

def test_timeout_leaves_no_partial_cache_file(monkeypatch, tmp_path):
    def partial(path):
        Path(path).write_text(_csv_text()[:400], encoding="utf-8")

    FakeR(monkeypatch, partial, raises=subprocess.TimeoutExpired(cmd="Rscript", timeout=1))
    b = _bridge(tmp_path)
    assert b._try_nflverse_r([2025]) is None
    assert list((tmp_path / "cache").iterdir()) == []
    assert "timed out" in (b.last_error or "")


def test_invalid_output_is_never_promoted_to_the_cache(monkeypatch, tmp_path):
    FakeR(monkeypatch, _write("season,posteam\n"))  # header only
    b = _bridge(tmp_path)
    assert b._try_nflverse_r([2025]) is None
    assert list((tmp_path / "cache").iterdir()) == []
    assert "rejected" in (b.last_error or "")


def test_nonzero_exit_leaves_no_files(monkeypatch, tmp_path):
    FakeR(monkeypatch, _write("garbage"), returncode=1)
    b = _bridge(tmp_path)
    assert b._try_nflverse_r([2025]) is None
    assert list((tmp_path / "cache").iterdir()) == []


# --- season key / timeout --------------------------------------------------------------------

def test_season_order_and_duplicates_share_one_cache_entry(monkeypatch, tmp_path):
    fake = FakeR(monkeypatch, _write(_csv_text(season=2025)))
    b = _bridge(tmp_path)
    b._try_nflverse_r([2025, 2024, 2025])
    names = {p.name for p in (tmp_path / "cache").glob("nflverse_pbp_*.csv")}
    assert len(names) == 1 and next(iter(names)).endswith("_2024_2025.csv")
    cmd = fake.calls[0][0]
    assert cmd[cmd.index("--seasons") + 1] == "2024,2025"
    b._try_nflverse_r((2024, 2025))
    assert len(fake.calls) == 1  # second call, different order/type: cache hit


def test_default_timeout_is_raised_and_env_overrides_it(monkeypatch, tmp_path):
    fake = FakeR(monkeypatch, _write(_csv_text()))
    _bridge(tmp_path)._try_nflverse_r([2025])
    assert fake.calls[0][1]["timeout"] == 300

    monkeypatch.setenv("NFL_STAT_R_TIMEOUT", "7")
    fake2 = FakeR(monkeypatch, _write(_csv_text()))
    cli.NFLDataBridge(cache_dir=tmp_path / "cache2", engine="r")._try_nflverse_r([2025])
    assert fake2.calls[0][1]["timeout"] == 7


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5"])
def test_invalid_timeout_env_falls_back_to_default(monkeypatch, bad):
    monkeypatch.setenv("NFL_STAT_R_TIMEOUT", bad)
    assert cli._r_timeout_seconds() == 300


def test_cache_missing_columns_the_row_predicate_needs_is_rejected(monkeypatch, tmp_path):
    b = _bridge(tmp_path)
    fake = FakeR(monkeypatch, _write(_csv_text()))
    b._try_nflverse_r([2025])
    cache_file = next((tmp_path / "cache").glob("nflverse_pbp_*.csv"))
    # keep season/posteam but drop the attempt/play_type columns: would silently change the row set
    cache_file.write_text("season,posteam,desc\n" + "2025,ZZZ,penalty on the play and some padding text here\n" * 12, encoding="utf-8")
    assert cache_file.stat().st_size > 256
    fake.calls.clear()
    rows = b._try_nflverse_r([2025])
    assert len(fake.calls) == 1
    assert _ids(rows) == EXPECTED_IDS


@pytest.mark.parametrize("bad", ["2024", b"2024", [2024.5]])
def test_normalize_seasons_rejects_strings_and_fractional_years(bad):
    with pytest.raises((TypeError, ValueError)):
        cli._normalize_seasons(bad)


def test_bad_seasons_argument_is_reported_not_raised(monkeypatch, tmp_path):
    FakeR(monkeypatch, _write(_csv_text()))
    b = _bridge(tmp_path)
    assert b._try_nflverse_r("2024") is None
    assert "invalid seasons" in (b.last_error or "")


def test_stale_temp_files_from_killed_runs_are_swept(monkeypatch, tmp_path):
    FakeR(monkeypatch, _write(_csv_text()))
    b = _bridge(tmp_path)
    stale = tmp_path / "cache" / ".nflverse_pbp_v2_2020.csv.1.tmp"
    stale.parent.mkdir(parents=True, exist_ok=True)  # cache dir is created lazily on master
    stale.write_text("x", encoding="utf-8")
    old = stale.stat().st_mtime - 3 * 86400
    os.utime(stale, (old, old))
    b._try_nflverse_r([2025])
    assert not stale.exists()
