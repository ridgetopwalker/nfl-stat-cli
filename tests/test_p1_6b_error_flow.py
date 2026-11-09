"""End-to-end /error flow (follow-up to #6 and #4): capture -> resolve -> reload, with no git and no force-reload."""
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import nfl_stat_cli as cli

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="piped TUI stdin + POSIX git shim")

ARGS = [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025"]


def _env(tmp_path, enabled=True):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "git_calls.log"
    shim = bindir / "git"
    shim.write_text(f"#!/bin/sh\necho \"$@\" >> '{log}'\nexit 0\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}{os.pathsep}{env.get('PATH', '')}",
        PYTHONPATH=str(Path(cli.__file__).resolve().parent.parent),
        HOME=str(tmp_path / "home"),
        NFL_STAT_IPC_DIR=str(tmp_path / "ipc"),
    )
    env.pop("NFL_STAT_ALLOW_GIT_UPDATE", None)
    env.pop("NFL_STAT_DISABLE_ERROR_IPC", None)
    if enabled:
        env["NFL_STAT_ENABLE_ERROR_IPC"] = "1"
    else:
        env.pop("NFL_STAT_ENABLE_ERROR_IPC", None)
    return env, log


def _run(tmp_path, stdin_text, env):
    res = subprocess.run(ARGS, input=stdin_text, capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert res.returncode == 0, res.stderr
    return cli.strip_ansi(res.stdout)


def _pending(tmp_path):
    d = tmp_path / "ipc" / "pending"
    files = sorted(p for p in d.glob("err_*.json")) if d.exists() else []
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def test_error_after_cant_answer_captures_query_parse_and_reason(tmp_path):
    env, log = _env(tmp_path)
    out = _run(tmp_path, "Zorblax passing yards\n/error Zorblax is a typo, I meant Mahomes\nn\nquit\n", env)
    assert "I can't answer that" in out
    reports = _pending(tmp_path)
    assert len(reports) == 1
    rep = reports[0]
    cli.validate_report_id(rep["id"])
    assert rep["query"] == "Zorblax passing yards"
    assert rep["user_explanation"] == "Zorblax is a typo, I meant Mahomes"
    assert rep["parsed"]["intent"] == "stat_query"
    assert rep["status"] == "pending"
    # what the CLI actually told the user is captured too, including the can't-answer reason
    assert "can't answer" in rep["response"].lower() and "Zorblax" in rep["response"]
    assert "\x1b" not in rep["response"]
    assert (tmp_path / "ipc" / "pending" / "latest.json").exists()
    assert not log.exists()


def test_error_after_explicit_unanswered_parse_keeps_reason(tmp_path):
    env, log = _env(tmp_path)
    _run(tmp_path, "compare Mahomes and Allen\n/error\nwanted both players\nn\nquit\n", env)
    rep = _pending(tmp_path)[0]
    assert rep["parsed"]["status"] == "unanswered"
    assert "side-by-side player comparisons" in rep["parsed"]["reason"]
    assert rep["user_explanation"] == "wanted both players"
    assert "side-by-side" in rep["response"]


def test_error_after_wrong_answer_captures_what_was_shown(tmp_path):
    env, log = _env(tmp_path)
    _run(tmp_path, "epa per play\n/error this should be per game, not per play\nn\nquit\n", env)
    rep = _pending(tmp_path)[0]
    assert rep["query"] == "epa per play"
    assert rep["parsed"]["stat_name"] == "epa_per_play"
    assert "per game" in rep["user_explanation"]
    assert "epa_per_play" in rep["response"] or "EPA" in rep["response"]
    assert not log.exists()


def test_error_without_prior_query_writes_nothing(tmp_path):
    env, _ = _env(tmp_path)
    out = _run(tmp_path, "/error hmm\nquit\n", env)
    assert "No natural-language query has been run" in out
    assert _pending(tmp_path) == []


def test_resolve_then_reload_in_same_session_runs_no_git(tmp_path):
    env, log = _env(tmp_path)
    ipc = tmp_path / "ipc"

    def resolver():
        deadline = time.time() + 30
        while time.time() < deadline:
            reps = _pending(tmp_path)
            if reps:
                rid = reps[0]["id"]
                # the same call an agent/developer script makes, with the new id format
                env_backup = os.environ.get("NFL_STAT_IPC_DIR")
                os.environ["NFL_STAT_IPC_DIR"] = str(ipc)
                try:
                    cli.write_resolution(report_id=rid, summary="fixed in abc1234", commit="abc1234")
                finally:
                    if env_backup is None:
                        os.environ.pop("NFL_STAT_IPC_DIR", None)
                    else:
                        os.environ["NFL_STAT_IPC_DIR"] = env_backup
                return
            time.sleep(0.05)

    t = threading.Thread(target=resolver)
    t.start()
    out = _run(tmp_path, "epa per play\n/error wrong\ny\ny\nquit\n", env)
    t.join()
    assert "A resolution signal was received" in out
    assert "abc1234" in out and "fixed in abc1234" in out
    assert "Reloading" in out or "Query Interpretation" in out.split("A resolution signal was received", 1)[1]
    assert "Error during hot-reload" not in out
    assert not log.exists(), f"git was invoked: {log.read_text()}"
    # resolved report moved out of pending into history
    assert _pending(tmp_path) == []
    assert list((ipc / "history").glob("err_*.json"))
    assert list((ipc / "resolved").glob("err_*.json"))


def test_reload_shows_latest_resolution_note_without_git(tmp_path):
    env, log = _env(tmp_path)
    ipc = tmp_path / "ipc"
    out1 = _run(tmp_path, "epa per play\n/error wrong\nn\nquit\n", env)
    rid = _pending(tmp_path)[0]["id"]
    res = subprocess.run(
        [sys.executable, "-c",
         "import nfl_stat_cli as c; c.write_resolution(report_id=%r, summary='parser fixed', commit='deadbee')" % rid],
        env=env, capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert res.returncode == 0, res.stderr
    out2 = _run(tmp_path, "/reload\nquit\n", env)
    assert "successfully reloaded" in out2
    assert "parser fixed" in out2
    assert not log.exists()


def test_old_style_report_ids_are_rejected_by_resolution_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    for bad in ("err_20240101_000000", "../x", "err_20240101_000000_ZZZZZZZZ", ""):
        with pytest.raises(ValueError):
            cli.write_resolution(report_id=bad, summary="x")


def test_create_error_report_tolerates_non_json_values_and_caps_response(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    rep = cli.create_error_report(
        "q", {"intent": "stat_query", "when": Path("/x"), "weird": {1, 2}.__class__}, "notes", season=2025,
        response_text="\x1b[31m" + "r" * 20000,
    )
    cli.validate_report_id(rep["id"])
    data = json.loads((tmp_path / "ipc" / "pending" / f"{rep['id']}.json").read_text(encoding="utf-8"))
    assert data["query"] == "q" and data["user_explanation"] == "notes"
    assert "\x1b" not in data["response"] and len(data["response"]) == cli.IPC_MAX_RESPONSE_CHARS
