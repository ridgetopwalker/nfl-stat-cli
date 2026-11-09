"""The .agents error-triage scripts follow NFL_STAT_IPC_DIR and the new report id format (follow-up to #4, tracked in #44)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import nfl_stat_cli as cli

REPO = Path(cli.__file__).resolve().parent.parent
SKILL = REPO / ".agents" / "skills" / "nfl-stat-error-triage"


def _env(tmp_path, **extra):
    env = dict(os.environ)
    for k in ("NFL_STAT_IPC_DIR", "NFL_STAT_WATCH_DIRS", "NFL_STAT_REPO", "NFL_STAT_WSL_IPC_DIR", "NFL_STAT_WSL_REPO"):
        env.pop(k, None)
    env.update(HOME=str(tmp_path / "home"), PYTHONPATH=str(REPO), NFL_STAT_IPC_DIR=str(tmp_path / "ipc"))
    env.update(extra)
    return env


def _run(script, args, env, cwd):
    return subprocess.run([sys.executable, str(SKILL / script), *args], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=60)


def _make_report(tmp_path, query="Zorblax passing yards"):
    old = os.environ.get("NFL_STAT_IPC_DIR")
    os.environ["NFL_STAT_IPC_DIR"] = str(tmp_path / "ipc")
    try:
        return cli.create_error_report(query, {"intent": "ambiguous", "status": "unanswered", "reason": "r"}, "notes", season=2025,
                                       response_text="I can't answer that")
    finally:
        if old is None:
            os.environ.pop("NFL_STAT_IPC_DIR", None)
        else:
            os.environ["NFL_STAT_IPC_DIR"] = old


def test_watcher_reads_nfl_stat_ipc_dir_and_new_ids(tmp_path):
    rep = _make_report(tmp_path)
    res = _run("watch_errors.py", ["--timeout", "5", "--interval", "0.1"], _env(tmp_path), tmp_path)
    assert res.returncode == 0, res.stderr
    assert f"NEW_ERROR_REPORT source=local id={rep['id']}" in res.stdout
    payload = json.loads(res.stdout.split("\n", 1)[1])
    assert payload["query"] == "Zorblax passing yards" and payload["response"] == "I can't answer that"


def test_watcher_ignores_old_ids_latest_and_other_folders(tmp_path):
    pend = tmp_path / "ipc" / "pending"
    pend.mkdir(parents=True)
    (pend / "err_20240101_000000.json").write_text(json.dumps({"id": "err_20240101_000000"}))  # old id format
    (pend / "latest.json").write_text(json.dumps({"id": "err_20240101_000000_abcdef12"}))
    (pend / "err_20240101_000000_abcdef12.json").write_text(json.dumps({"id": "err_20240101_000000_ffffffff"}))  # id mismatch
    (tmp_path / "elsewhere" / "pending").mkdir(parents=True)
    res = _run("watch_errors.py", ["--timeout", "0.5", "--interval", "0.1"], _env(tmp_path), tmp_path)
    assert res.returncode == 1 and "NEW_ERROR_REPORT" not in res.stdout


def test_watcher_extra_dirs_and_default_dir(tmp_path):
    extra = tmp_path / "extra"
    (extra / "pending").mkdir(parents=True)
    rid = "err_20260101_010203_0a1b2c3d"
    (extra / "pending" / f"{rid}.json").write_text(json.dumps({"id": rid, "query": "q"}))
    res = _run("watch_errors.py", ["--timeout", "5", "--interval", "0.1"], _env(tmp_path, NFL_STAT_WATCH_DIRS=str(extra)), tmp_path)
    assert res.returncode == 0 and rid in res.stdout

    # with NFL_STAT_IPC_DIR unset the default folder under HOME is used
    env = _env(tmp_path)
    env.pop("NFL_STAT_IPC_DIR")
    default_pending = tmp_path / "home" / ".nfl_stat_cli" / "error_ipc" / "pending"
    default_pending.mkdir(parents=True)
    rid2 = "err_20260101_010204_00ff00ff"
    (default_pending / f"{rid2}.json").write_text(json.dumps({"id": rid2, "query": "q2"}))
    res = _run("watch_errors.py", ["--timeout", "5", "--interval", "0.1"], env, tmp_path)
    assert res.returncode == 0 and rid2 in res.stdout


def test_resolve_writes_into_nfl_stat_ipc_dir_and_session_can_read_it(tmp_path):
    rep = _make_report(tmp_path)
    summary = "fixed; it's \"quoted\" and has 'quotes' \\ and ; rm -rf x"
    res = _run("resolve.py", ["local", rep["id"], "abc1234", summary], _env(tmp_path), tmp_path)
    assert res.returncode == 0, res.stderr
    resolved = json.loads((tmp_path / "ipc" / "resolved" / f"{rep['id']}.json").read_text())
    assert resolved["id"] == rep["id"] and resolved["status"] == "resolved"
    assert resolved["commit"] == "abc1234" and resolved["summary"] == summary
    assert not (tmp_path / "ipc" / "pending" / f"{rep['id']}.json").exists()
    assert (tmp_path / "ipc" / "history" / f"{rep['id']}.json").exists()
    # the code the waiting session uses accepts it
    old = os.environ.get("NFL_STAT_IPC_DIR")
    os.environ["NFL_STAT_IPC_DIR"] = str(tmp_path / "ipc")
    try:
        got = cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=1)
    finally:
        if old is None:
            os.environ.pop("NFL_STAT_IPC_DIR", None)
        else:
            os.environ["NFL_STAT_IPC_DIR"] = old
    assert got and got["summary"] == summary


@pytest.mark.parametrize("bad", ["err_20240101_000000", "../etc/passwd", "err_20240101_000000_XYZXYZXY", ""])
def test_resolve_rejects_malformed_ids(tmp_path, bad):
    res = _run("resolve.py", ["local", bad, "abc", "x"], _env(tmp_path), tmp_path)
    assert res.returncode != 0
    assert not (tmp_path / "ipc" / "resolved").exists() or not list((tmp_path / "ipc" / "resolved").glob("*.json"))


def test_resolve_usage_and_wsl_needs_config(tmp_path):
    assert _run("resolve.py", [], _env(tmp_path), tmp_path).returncode == 2
    res = _run("resolve.py", ["wsl", "err_20260101_010203_0a1b2c3d", "c", "s"], _env(tmp_path), tmp_path)
    assert res.returncode != 0 and "NFL_STAT_WSL_REPO" in (res.stdout + res.stderr)


def test_skill_files_have_no_personal_paths_or_old_ipc_layout():
    personal = re.compile(r"(?i)c:\\users\\|/home/[a-z]|/users/[a-z]|/work" + "space/")
    for name in ("SKILL.md", "watch_errors.py", "resolve.py"):
        text = (SKILL / name).read_text(encoding="utf-8")
        assert not personal.search(text), name
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "NFL_STAT_IPC_DIR" in skill and "err_YYYYMMDD_HHMMSS_xxxxxxxx" in skill


def _load_resolve():
    import importlib.util
    spec = importlib.util.spec_from_file_location("nfl_resolve_script", SKILL / "resolve.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resolve_wsl_runs_without_a_shell_and_passes_summary_as_one_argument(monkeypatch):
    mod = _load_resolve()
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})())
    monkeypatch.setenv("NFL_STAT_WSL_REPO", "/srv/checkout")
    monkeypatch.setenv("NFL_STAT_WSL_IPC_DIR", "/srv/ipc")
    summary = "x; rm -rf ~ && $(whoami) `id`"
    assert mod.main(["wsl", "err_20260101_010203_0a1b2c3d", "abc1234", summary, "--pull"]) == 0
    pull, run = calls
    assert pull[:3] == ["wsl.exe", "-e", "git"] and "--ff-only" in pull
    assert run[:3] == ["wsl.exe", "-e", "env"] and "NFL_STAT_IPC_DIR=/srv/ipc" in run
    assert run.count(summary) == 1  # one argv element, never joined into a shell string


def test_resolve_summary_containing_the_word_pull_is_kept(tmp_path):
    rep = _make_report(tmp_path)
    res = _run("resolve.py", ["local", rep["id"], "abc1234", "pull it"], _env(tmp_path), tmp_path)
    assert res.returncode == 0, res.stderr
    assert json.loads((tmp_path / "ipc" / "resolved" / f"{rep['id']}.json").read_text())["summary"] == "pull it"


def test_watcher_ignore_option_and_symlinked_pending_dir(tmp_path):
    rep = _make_report(tmp_path)
    res = _run("watch_errors.py", ["--timeout", "0.5", "--interval", "0.1", "--ignore", rep["id"]], _env(tmp_path), tmp_path)
    assert res.returncode == 1 and "NEW_ERROR_REPORT" not in res.stdout
    # a symlinked pending folder is not followed
    real = tmp_path / "real_pending"
    real.mkdir()
    (real / f"{rep['id']}.json").write_text((tmp_path / "ipc" / "pending" / f"{rep['id']}.json").read_text())
    other = tmp_path / "other"
    other.mkdir()
    os.symlink(real, other / "pending")
    res = _run("watch_errors.py", ["--timeout", "0.5", "--interval", "0.1"],
               _env(tmp_path, NFL_STAT_IPC_DIR=str(other)), tmp_path)
    assert res.returncode == 1


def test_watcher_ignores_oversized_report_files(tmp_path):
    pend = tmp_path / "ipc" / "pending"
    pend.mkdir(parents=True)
    rid = "err_20260101_010203_0a1b2c3d"
    (pend / f"{rid}.json").write_text(json.dumps({"id": rid, "query": "x" * 400000}))
    res = _run("watch_errors.py", ["--timeout", "0.5", "--interval", "0.1"], _env(tmp_path), tmp_path)
    assert res.returncode == 1


def test_resolve_accepts_dash_leading_summary_after_double_dash_and_rejects_abbrev_flags(tmp_path):
    rep = _make_report(tmp_path)
    res = _run("resolve.py", ["local", rep["id"], "abc1234", "--", "-1 off-by-one in the parser"], _env(tmp_path), tmp_path)
    assert res.returncode == 0, res.stderr
    assert json.loads((tmp_path / "ipc" / "resolved" / f"{rep['id']}.json").read_text())["summary"] == "-1 off-by-one in the parser"
    res = _run("resolve.py", ["local", rep["id"], "abc1234", "--pu", "x"], _env(tmp_path), tmp_path)
    assert res.returncode == 2


def test_resolve_wsl_requires_an_absolute_repo_path(monkeypatch):
    mod = _load_resolve()
    monkeypatch.setenv("NFL_STAT_WSL_REPO", "~/checkout")
    with pytest.raises(SystemExit) as exc:
        mod.main(["wsl", "err_20260101_010203_0a1b2c3d", "c", "s"])
    assert "absolute" in str(exc.value)
