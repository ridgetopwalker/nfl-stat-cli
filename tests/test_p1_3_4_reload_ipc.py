"""Regression tests: /reload never runs git, and error IPC never force-reloads or trusts files blindly (issues #3, #4)."""
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


def _fake_git_env(tmp_path):
    """PATH with a fake `git` that logs every invocation; returns (env, log_path)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git_calls.log"
    script = bindir / "git"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> '{log}'\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(Path(cli.__file__).resolve().parent.parent)
    env["HOME"] = str(tmp_path / "home")
    env["NFL_STAT_IPC_DIR"] = str(tmp_path / "ipc")
    env.pop("NFL_STAT_ALLOW_GIT_UPDATE", None)
    return env, log


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX shell shim for git")
@pytest.mark.parametrize("cmd", ["/reload", "/update", "/refresh"])
def test_tui_reload_commands_never_invoke_git(tmp_path, cmd):
    env, log = _fake_git_env(tmp_path)
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025"],
        input=f"{cmd}\nquit\n", capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "successfully reloaded" in out
    assert not log.exists(), f"git was invoked: {log.read_text()}"


def test_reload_function_does_not_run_subprocess(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(("run", a)))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(("Popen", a)))
    # pull_git=True is accepted for compatibility but ignored
    mod = cli.reload_nfl_stat_cli(pull_git=True)
    assert hasattr(mod, "reload_nfl_stat_cli")
    assert calls == []  # recorded rather than raised: the old code swallowed exceptions around git pull


def test_git_update_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NFL_STAT_ALLOW_GIT_UPDATE", raising=False)
    def boom(*a, **k):
        raise AssertionError("git must not run when update is not allowed")
    monkeypatch.setattr(subprocess, "run", boom)
    ok, msg = cli.git_update_package()
    assert ok is False and "disabled" in msg


def test_git_update_requires_tty(monkeypatch):
    monkeypatch.setenv("NFL_STAT_ALLOW_GIT_UPDATE", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    ok, msg = cli.git_update_package()
    assert ok is False and "interactive" in msg


def test_git_update_is_ff_only_and_pinned_to_package_root(monkeypatch):
    monkeypatch.setenv("NFL_STAT_ALLOW_GIT_UPDATE", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    pkg_root = Path(cli.__file__).resolve().parent.parent
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/git")
    calls = []

    class R:
        returncode = 0
        stdout = "Already up to date.\n"
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return R()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    if not (pkg_root / ".git").exists():
        pytest.skip("not a git checkout")
    ok, msg = cli.git_update_package()
    assert ok and "up to date" in msg.lower()
    cmd, kw = calls[0]
    assert cmd[-2:] == ["pull", "--ff-only"] and "-C" in cmd
    assert Path(kw["cwd"]) == pkg_root


# ---- error IPC ----------------------------------------------------------------------------

@pytest.fixture
def ipc(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    return tmp_path / "ipc"


def _report():
    return cli.create_error_report("q", {"intent": "x"}, "oops", season=2025)


def test_report_ids_are_unique_and_well_formed(ipc):
    ids = {_report()["id"] for _ in range(20)}
    assert len(ids) == 20
    for i in ids:
        assert cli.validate_report_id(i) == i


@pytest.mark.parametrize("bad", ["err_20250101_010101_abcdef12\n", "err_\u0662\u0660\u0662\u0665\u0660\u0661\u0660\u0661_010101_abcdef12", "../../evil", "err_20250101_010101", "err_20250101_010101_zzzzzzzz", "latest", "", "err_1/../x", None])
def test_invalid_report_ids_rejected(ipc, bad):
    with pytest.raises(ValueError):
        cli.validate_report_id(bad)
    with pytest.raises(ValueError):
        cli.write_resolution(bad, "s")
    with pytest.raises(ValueError):
        cli.wait_for_resolution(bad, timeout=0)


def test_traversal_id_writes_nothing_outside_ipc(ipc, tmp_path):
    with pytest.raises(ValueError):
        cli.write_resolution("../../escape", "s")
    assert not list(tmp_path.rglob("escape*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_ipc_dir_is_owner_only(ipc):
    d = cli.get_ipc_dir()
    for sub in ("", "pending", "resolved", "history"):
        mode = stat.S_IMODE((d / sub if sub else d).stat().st_mode)
        assert mode == 0o700


def test_wait_for_resolution_times_out(ipc):
    rep = _report()
    start = time.monotonic()
    assert cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=0.1) is None
    assert time.monotonic() - start < 2


def test_wait_for_resolution_returns_payload_without_reloading(ipc, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "reload_nfl_stat_cli", lambda *a, **k: called.append(1))
    rep = _report()
    cli.write_resolution(rep["id"], "fixed", commit="abc123")
    data = cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=1)
    assert data["id"] == rep["id"] and data["commit"] == "abc123"
    assert called == []  # waiting for a resolution never force-reloads


def test_foreign_resolution_for_other_id_is_ignored(ipc):
    rep, other = _report(), _report()
    cli.write_resolution(other["id"], "other fix")
    assert cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=0.1) is None


def test_atomic_json_reports_are_valid(ipc):
    rep = _report()
    p = cli.get_ipc_dir() / "pending" / f"{rep['id']}.json"
    assert json.loads(p.read_text())["id"] == rep["id"]
    assert not list(p.parent.glob(".*.tmp")) and not [f for f in p.parent.iterdir() if f.name.startswith(".")]


def test_sanitize_ipc_text_strips_ansi_and_controls():
    evil = "ok\x1b[2J\x1b[31mred\x1b]0;title\x07\x1b(B\x00\r\nline"
    out = cli.sanitize_ipc_text(evil)
    assert "\x1b" not in out and "\x07" not in out and "\x00" not in out and "\r" not in out and "\n" not in out
    assert "ok" in out and "red" in out
    assert len(cli.sanitize_ipc_text("a" * 5000)) == 500


@pytest.mark.skipif(sys.platform == "win32", reason="uses piped TUI stdin")
def test_tui_error_command_is_opt_in_and_never_force_reloads(tmp_path):
    env, log = _fake_git_env(tmp_path)
    env.pop("NFL_STAT_ENABLE_ERROR_IPC", None)
    base_args = [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025"]

    # Explicit opt-out: no report written
    env["NFL_STAT_DISABLE_ERROR_IPC"] = "1"
    res = subprocess.run(base_args, input="epa per play\n/error bad\nquit\n", capture_output=True, text=True, env=env, cwd=str(tmp_path))
    out = cli.strip_ansi(res.stdout)
    assert "turned off" in out
    assert not (tmp_path / "ipc" / "pending").exists() or not list((tmp_path / "ipc" / "pending").glob("err_*.json"))
    env.pop("NFL_STAT_DISABLE_ERROR_IPC")

    # Enabled: a resolution file planted with ANSI text must not trigger a reload without consent
    env["NFL_STAT_ENABLE_ERROR_IPC"] = "1"
    ipc_dir = tmp_path / "ipc"

    def plant():
        deadline = time.time() + 20
        while time.time() < deadline:
            pend = list((ipc_dir / "pending").glob("err_*.json")) if (ipc_dir / "pending").exists() else []
            pend = [p for p in pend if p.name != "latest.json"]
            if pend:
                rid = pend[0].stem
                (ipc_dir / "resolved").mkdir(parents=True, exist_ok=True)
                (ipc_dir / "resolved" / f"{rid}.json").write_text(json.dumps({
                    "id": rid, "status": "resolved", "commit": "deadbeef",
                    "summary": "pwn\x1b[2J\x1b[31mED"}))
                return
            time.sleep(0.05)

    t = threading.Thread(target=plant)
    t.start()
    proc = subprocess.Popen(base_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(tmp_path))
    proc.stdin.write("epa per play\n/error wrong answer\ny\n")
    proc.stdin.flush()
    time.sleep(3)  # allow the wait loop to observe the planted resolution
    out, err = proc.communicate("n\nquit\n", timeout=60)  # decline the reload prompt
    t.join()
    assert "\x1b[2J" not in out
    assert "A resolution signal was received" in cli.strip_ansi(out)
    assert "Not reloading" in cli.strip_ansi(out)
    assert "Reloading nfl-stat-cli" not in cli.strip_ansi(out)
    assert "Error during hot-reload" not in cli.strip_ansi(out)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink/permission checks")
def test_ipc_dir_symlink_is_refused(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(link))
    with pytest.raises(PermissionError):
        cli.get_ipc_dir()


@pytest.mark.skipif(os.name == "nt", reason="uses mkfifo")
def test_special_and_oversized_resolution_files_are_ignored(ipc):
    rep = _report()
    res_dir = cli.get_ipc_dir() / "resolved"
    os.mkfifo(res_dir / f"{rep['id']}.json")  # would block open() forever if read
    start = time.monotonic()
    assert cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=0.2) is None
    assert time.monotonic() - start < 2
    os.unlink(res_dir / f"{rep['id']}.json")
    (res_dir / f"{rep['id']}.json").write_text(json.dumps({"id": rep["id"], "status": "resolved", "summary": "x" * 200000}))
    assert cli.wait_for_resolution(rep["id"], poll_interval=0.01, timeout=0.2) is None
