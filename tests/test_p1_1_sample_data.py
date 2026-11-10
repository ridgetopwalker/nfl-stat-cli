"""Regression tests: built-in sample plays must never be presented as live data (issue #1)."""
import pytest

import pro_football_slm as cli


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)


def _bridge(tmp_path, **kw):
    return cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline", **kw)


def test_sample_fallback_is_flagged_and_labeled(tmp_path):
    bridge = _bridge(tmp_path)
    plays = bridge.load_pbp([2024, 2025])
    assert plays
    assert bridge.is_sample is True
    assert "SAMPLE DATA" in bridge.last_source_used
    assert "NOT live" in bridge.last_source_used
    assert all(p.get("is_sample") for p in plays)
    # last_error is always populated when falling back, so non-interactive warnings can't be skipped
    assert bridge.last_error


def test_load_resets_state_between_loads(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.last_error = "stale error from a previous load"
    bridge.load_pbp([2025])
    assert "stale error" not in (bridge.last_error or "")


def test_require_live_raises_instead_of_falling_back(tmp_path):
    bridge = _bridge(tmp_path, require_live=True)
    with pytest.raises(cli.LiveDataUnavailableError):
        bridge.load_pbp([2025])
    assert bridge.is_sample is False


def test_require_live_env_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("PFSLM_REQUIRE_LIVE", "1")
    with pytest.raises(cli.LiveDataUnavailableError):
        _bridge(tmp_path).load_pbp([2025])
    monkeypatch.setenv("PFSLM_REQUIRE_LIVE", "0")
    assert _bridge(tmp_path).load_pbp([2025])


def test_nl_result_has_sample_footer(tmp_path, engine):
    bridge = _bridge(tmp_path)
    plays = bridge.load_pbp([2024, 2025])
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("epa per play", engine, slm_model="off")
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    assert "SAMPLE DATA" in out
    assert "NOT real season statistics" in out


def test_no_footer_for_live_rows(engine):
    live_rows = [{"season": 2025, "is_sample": False}]
    assert cli.sample_data_footer(live_rows) == ""
    assert cli.sample_data_footer([]) == ""


def test_cli_require_live_flag_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    rc = cli.main(["stat", "epa_per_play", "--engine", "offline", "--require-live", "--season", "2025"])
    assert rc == 1
    assert "refusing to fall back to sample data" in capsys.readouterr().err


def test_cli_prints_sample_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("PFSLM_REQUIRE_LIVE", raising=False)
    cli.main(["stat", "epa_per_play", "--engine", "offline", "--season", "2025"])
    out = cli.strip_ansi(capsys.readouterr().out)
    assert "SAMPLE DATA - built-in demo plays" in out          # source label
    assert out.count("NOT real season statistics") >= 2         # top warning + closing footer


def test_cli_stat_page_and_play_commands_carry_sample_footer(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("PFSLM_REQUIRE_LIVE", raising=False)
    for argv in (["stat-page"], ["play", "--player", "Mahomes"], ["stat", "epa_per_play"]):
        capsys.readouterr()
        cli.main(argv + ["--engine", "offline", "--season", "2025"])
        out = cli.strip_ansi(capsys.readouterr().out)
        assert out.count("NOT real season statistics") >= 2, argv


def test_tui_warns_at_startup_in_prompt_and_in_nl_footer(tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(Path(cli.__file__).resolve().parent.parent), "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path), "NO_COLOR": "1"})
    env.pop("PFSLM_REQUIRE_LIVE", None)
    res = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "tui", "--engine", "offline", "--season", "2025", "--slm-model", "off"],
        input="epa per play\n/season 2024\nquit\n", capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "pro-football-slm [SAMPLE DATA] >" in out
    assert out.count("NOT real season statistics") >= 2  # startup warning + NL footer


def test_tui_require_live_fails_closed(tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(Path(cli.__file__).resolve().parent.parent), "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path), "NO_COLOR": "1", "PFSLM_REQUIRE_LIVE": "1"})
    res = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "tui", "--engine", "offline", "--season", "2025", "--slm-model", "off"],
        input="quit\n", capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
    )
    assert res.returncode == 1
    assert "refusing to fall back to sample data" in res.stderr


def test_backend_error_text_is_single_line_and_escape_free():
    out = cli._one_line("boom\x1b[2J\r\nsecond\x07 line")
    assert "\x1b" not in out and "\r" not in out and "\n" not in out and "\x07" not in out
    assert out.startswith("boom") and "second" in out
