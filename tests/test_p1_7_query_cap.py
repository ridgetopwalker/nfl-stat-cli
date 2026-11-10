"""Regression tests: query text is length-capped before parsing, so quadratic regexes cannot be fed long input (issue #7)."""
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import pro_football_slm as cli


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


def _interpret(engine, q):
    return cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")


def test_cap_constant_is_300():
    assert cli.MAX_QUERY_CHARS == 300
    assert cli.get_max_query_chars() == 300


def test_exactly_300_chars_is_accepted(engine):
    q = "epa per play " + "a" * (300 - len("epa per play "))
    assert len(q) == 300
    parsed = _interpret(engine, q)
    assert parsed["intent"] != "query_too_long"


def test_301_chars_is_rejected_before_parsing(engine):
    q = "epa per play " + "a" * (301 - len("epa per play "))
    assert len(q) == 301
    parsed = _interpret(engine, q)
    assert parsed["intent"] == "query_too_long"
    assert parsed["status"] == "rejected"
    assert parsed["query_length"] == 301 and parsed["max_chars"] == 300
    assert len(parsed["query"]) < 100  # no echo of the oversized input
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, []))
    assert "Query too long" in out
    assert "limited to 300 characters (received 301)" in out


def test_rejection_does_not_run_any_regex_work(engine, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("regex work ran on an over-long query")
    monkeypatch.setattr(cli.re, "search", boom)
    monkeypatch.setattr(cli.re, "match", boom)
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "query_local_slm", boom)
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("x" * 5000, engine, slm_model="auto")
    assert parsed["intent"] == "query_too_long"


@pytest.mark.parametrize("n", [1_000, 12_000, 48_000, 500_000])
def test_pathological_input_completes_fast(engine, n):
    q = "most successful " + ("least " * n)
    start = time.perf_counter()
    parsed = _interpret(engine, q)
    elapsed = time.perf_counter() - start
    assert parsed["intent"] == "query_too_long"
    assert elapsed < 0.5, f"{elapsed:.2f}s for {len(q)} chars"


def test_pathological_input_at_the_cap_is_bounded(engine):
    q = ("most successful " + "least " * 100)[:300]
    start = time.perf_counter()
    _interpret(engine, q)
    assert time.perf_counter() - start < 1.0


def test_short_queries_unaffected(engine):
    assert _interpret(engine, "epa per play")["intent"] == "stat_query"


def test_rejected_preview_has_no_control_characters(engine):
    parsed = _interpret(engine, "\x1b[31mred\x07\r\n" + "x" * 400)
    assert parsed["intent"] == "query_too_long"
    assert not any(ord(ch) < 32 or ord(ch) == 127 for ch in parsed["query"])


def test_cap_env_override_can_only_lower(monkeypatch):
    monkeypatch.setenv("PFSLM_MAX_QUERY_CHARS", "50")
    assert cli.get_max_query_chars() == 50
    monkeypatch.setenv("PFSLM_MAX_QUERY_CHARS", "99999")
    assert cli.get_max_query_chars() == 300
    monkeypatch.setenv("PFSLM_MAX_QUERY_CHARS", "junk")
    assert cli.get_max_query_chars() == 300
    for bad in ("0", "-5"):
        monkeypatch.setenv("PFSLM_MAX_QUERY_CHARS", bad)
        assert cli.get_max_query_chars() == 300


def _env(tmp_path):
    import os
    env = dict(os.environ)
    env.pop("PFSLM_MAX_QUERY_CHARS", None)
    env.update({"PYTHONPATH": str(Path(cli.__file__).resolve().parent.parent), "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path), "NO_COLOR": "1"})
    return env


def test_cli_ask_rejects_long_query(tmp_path):
    env = _env(tmp_path)
    res = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "ask", "most successful " + "least " * 5000, "--slm-model", "off"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=30,
    )
    assert res.returncode == 1
    assert "Query too long" in res.stdout
    assert "limited to 300 characters" in res.stdout


def test_tui_play_command_does_not_override_rejection(tmp_path):
    env = _env(tmp_path)
    res = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "tui", "--engine", "offline", "--season", "2025", "--slm-model", "off"],
        input="/play " + "x" * 400 + "\nmost successful " + "least " * 3000 + "\nquit\n",
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.count("Query too long") == 2
