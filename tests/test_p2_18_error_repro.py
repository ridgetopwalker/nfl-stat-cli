"""#18: /error reports carry what is needed to reproduce an answer (code SHA, data source, snapshot, parser, shown rows)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import nfl_stat_cli as cli

REPO = Path(cli.__file__).resolve().parent.parent
SHA = "0123456789abcdef0123456789abcdef01234567"


def _plays(n=3, season=2025):
    return [{"season": season, "game_id": f"g{i}", "play_id": i, "posteam": "KC"} for i in range(n)]


def test_read_git_sha_from_branch_ref_detached_head_and_packed_refs(tmp_path):
    g = tmp_path / ".git"
    (g / "refs" / "heads").mkdir(parents=True)
    (g / "HEAD").write_text("ref: refs/heads/topic\n")
    (g / "refs" / "heads" / "topic").write_text(SHA + "\n")
    assert cli._read_git_sha(tmp_path) == SHA
    (g / "HEAD").write_text(SHA[::-1] + "\n")
    assert cli._read_git_sha(tmp_path) == SHA[::-1]
    (g / "HEAD").write_text("ref: refs/heads/packed\n")
    (g / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/packed\n")
    assert cli._read_git_sha(tmp_path) == SHA


def test_read_git_sha_handles_worktree_pointer_and_non_checkout(tmp_path):
    common = tmp_path / "main" / ".git"
    wt_git = common / "worktrees" / "wt"
    (common / "refs" / "heads").mkdir(parents=True)
    wt_git.mkdir(parents=True)
    (common / "refs" / "heads" / "topic").write_text(SHA + "\n")
    (wt_git / "HEAD").write_text("ref: refs/heads/topic\n")
    (wt_git / "commondir").write_text("../..\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_git}\n")
    assert cli._read_git_sha(wt) == SHA
    assert cli._read_git_sha(tmp_path / "nothing-here") is None


def test_sample_detection():
    assert cli._is_sample_source("built-in nflverse/sdv offline dataset")
    assert cli._is_sample_source("built-in-nflverse-sample")
    assert not cli._is_sample_source("nflreadpy cache (offline copy)")  # a real cached source is not the sample
    assert not cli._is_sample_source("nflreadpy / nfl_data_py (Python)")
    assert not cli._is_sample_source("nflverse / nflreadr (R)")


def test_snapshot_id_is_stable_order_independent_and_changes_with_data():
    a = _plays(5)
    assert cli.data_snapshot_id(a, 2025) == cli.data_snapshot_id(list(reversed(a)), 2025)
    assert cli.data_snapshot_id(a, 2025) != cli.data_snapshot_id(a[:-1], 2025)
    changed = [dict(p) for p in a]
    changed[0]["play_id"] = 999
    assert cli.data_snapshot_id(a, 2025) != cli.data_snapshot_id(changed, 2025)
    # other seasons do not affect the season's snapshot
    assert cli.data_snapshot_id(a, 2025) == cli.data_snapshot_id(a + _plays(2, season=2024), 2025)


def test_build_repro_context_fields_and_row_cap(monkeypatch):
    bridge = type("B", (), {"last_source_used": "nflverse / nflreadr (R)"})()
    table = {"title": "T", "headers": ["qb", "v"], "rows": [[f"q{i}", str(i)] for i in range(500)]}
    ctx = cli.build_repro_context(bridge, _plays(), 2025, {"slm_model_used": "qwen2.5:1.5b"}, slm_requested="qwen2.5:1.5b", result_table=table)
    assert ctx["data_source"] == "nflverse / nflreadr (R)" and ctx["is_sample"] is False
    assert ctx["slm_model"] == "qwen2.5:1.5b" and ctx["parser"] == "slm"
    assert ctx["season"] == 2025 and ctx["seasons_loaded"] == [2025] and ctx["plays_loaded"] == 3
    assert ctx["snapshot_id"].startswith("3-")
    assert ctx["result_row_count"] == 500 and len(ctx["result_rows"]) == cli.IPC_MAX_REPRO_ROWS
    assert ctx["result_headers"] == ["qb", "v"] and ctx["result_title"] == "T" and ctx["result_rows"][0] == ["q0", "0"]
    assert ctx["git_sha"] is None or len(ctx["git_sha"]) == 40
    ctx2 = cli.build_repro_context(None, [], 2025, {}, None)
    assert ctx2["parser"] == "rule" and ctx2["slm_model"] is None and ctx2["is_sample"] is None  # unknown source
    assert ctx2["result_row_count"] == 0 and ctx2["result_rows"] == []


def test_create_error_report_stores_repro_block(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    rep = cli.create_error_report("q", {}, "n", repro={"git_sha": SHA, "snapshot_id": "3-abc", "is_sample": True})
    data = json.loads((tmp_path / "ipc" / "pending" / f"{rep['id']}.json").read_text())
    assert data["repro"] == {"git_sha": SHA, "snapshot_id": "3-abc", "is_sample": True}
    bare = cli.create_error_report("q", {}, "n")
    assert bare["repro"]["version"] == cli.__version__ and "git_sha" in bare["repro"]


@pytest.mark.skipif(sys.platform == "win32", reason="piped TUI stdin")
def test_tui_error_report_contains_repro_fields(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(tmp_path / "home"), NFL_STAT_IPC_DIR=str(tmp_path / "ipc"))
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025"],
        input="epa per play\n/error looks wrong\nn\nquit\n", capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120,
    )
    assert res.returncode == 0, res.stderr
    reports = [p for p in (tmp_path / "ipc" / "pending").glob("err_*.json")]
    assert len(reports) == 1
    r = json.loads(reports[0].read_text())["repro"]
    assert r["is_sample"] is True and "offline" in r["data_source"]
    assert r["season"] == 2025 and r["plays_loaded"] > 0
    n, digest = r["snapshot_id"].split("-")
    assert int(n) > 0 and len(digest) == 16
    assert r["parser"] == "rule" and r["slm_model"] is None
    assert r["result_row_count"] > 0 and r["result_headers"] and isinstance(r["result_rows"][0], list)
    assert r["version"] == cli.__version__


@pytest.mark.skipif(sys.platform == "win32", reason="piped TUI stdin")
def test_report_after_refusal_does_not_reuse_the_previous_queries_table(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(tmp_path / "home"), NFL_STAT_IPC_DIR=str(tmp_path / "ipc"))
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025"],
        input="epa per play\nZorblax passing yards\n/error should know him\nn\nquit\n", capture_output=True, text=True,
        env=env, cwd=str(tmp_path), timeout=120,
    )
    assert res.returncode == 0, res.stderr
    r = json.loads(next((tmp_path / "ipc" / "pending").glob("err_*.json")).read_text())
    assert r["query"] == "Zorblax passing yards"
    assert r["repro"]["result_row_count"] == 0 and r["repro"]["result_rows"] == []


def test_snapshot_id_changes_when_epa_is_corrected_upstream():
    a = [dict(p, epa=0.5, wpa=0.01, yards_gained=7) for p in _plays(4)]
    b = [dict(p) for p in a]
    b[2]["epa"] = 0.6
    assert cli.data_snapshot_id(a, 2025) != cli.data_snapshot_id(b, 2025)
    assert cli.data_snapshot_id(a, 2025) == cli.data_snapshot_id([dict(p) for p in a], 2025)


def test_result_table_cells_are_sanitized_and_capped():
    table = {"title": "\x1b[31mT\x1b]0;x\x07" + "t" * 500, "headers": ["\x1b[1mh\x1b[0m"] * 100,
             "rows": [["\x1b[31mred\x1b[0m", "c" * 5000] + ["x"] * 100]}
    ctx = cli.build_repro_context(None, [], 2025, {}, None, result_table=table)
    assert "\x1b" not in json.dumps(ctx) and "\x07" not in json.dumps(ctx)
    assert len(ctx["result_title"]) <= 200 and len(ctx["result_headers"]) == 40
    row = ctx["result_rows"][0]
    assert row[0] == "red" and len(row[1]) <= 80 and len(row) == 40


def test_git_sha_rejects_odd_ref_names(tmp_path):
    g = tmp_path / ".git"
    g.mkdir()
    (tmp_path / "secret").write_text(SHA + "\n")
    (g / "HEAD").write_text("ref: ../secret\n")
    assert cli._read_git_sha(tmp_path) is None
    (g / "HEAD").write_text("ref: refs/../../secret\n")
    assert cli._read_git_sha(tmp_path) is None
    (g / "HEAD").write_text("ref: refs/..\\..\\secret\n")
    assert cli._read_git_sha(tmp_path) is None


def test_error_report_still_saved_when_repro_context_fails(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO), HOME=str(tmp_path / "home"), NFL_STAT_IPC_DIR=str(tmp_path / "ipc"))
    code = (
        "import nfl_stat_cli as c, sys\n"
        "def boom(*a, **k): raise RuntimeError('x')\n"
        "c.build_repro_context = boom\n"
        "sys.argv=['nfl-stat-cli','tui','--engine','offline','--season','2025']\n"
        "raise SystemExit(c.main())\n"
    )
    res = subprocess.run([sys.executable, "-c", code], input="epa per play\n/error wrong\nn\nquit\n", capture_output=True,
                         text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert res.returncode == 0, res.stderr
    r = json.loads(next((tmp_path / "ipc" / "pending").glob("err_*.json")).read_text())
    assert r["repro"]["repro_error"] is True
