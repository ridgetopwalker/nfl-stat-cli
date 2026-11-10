"""The test environment must never touch real user state or the network (issue #20)."""
import os
import socket
import subprocess
from pathlib import Path

import pytest
import pro_football_slm as cli

ROOT = Path(__file__).resolve().parents[1]


def test_home_is_a_temp_dir():
    home = Path.home().resolve()
    assert home == Path(os.environ["HOME"]).resolve()
    assert home != ROOT.resolve() and ROOT.resolve() not in home.parents
    engine = cli.StatEngine()
    storage = Path(engine.storage_dir).resolve()
    assert home in storage.parents or storage == home


def test_ipc_dir_is_outside_the_repo():
    ipc = Path(cli.get_ipc_dir()).resolve()
    assert ROOT.resolve() not in ipc.parents
    assert ipc != (ROOT / ".error_ipc").resolve()
    assert (ipc / "pending").is_dir()


def test_no_slm_probe(monkeypatch):
    monkeypatch.delenv("PFSLM_SLM_MODEL", raising=False)
    # Even with the env override removed the probe cannot reach a service.
    assert cli.NaturalLanguageStatAssistant.detect_ollama_model("auto") is None


def test_outbound_network_is_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError, match="blocked"):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()


@pytest.mark.parametrize("argv", [
    ["git", "pull"],
    ["git", "-C", ".", "pull", "--ff-only"],
    ["git", "-c", "http.proxy=x", "push", "origin", "HEAD"],
    ["git", "fetch", "--all"],
    ["git", "clone", "https://example.invalid/x.git"],
    ["git", "ls-remote", "origin"],
    ["git", "remote", "update"],
])
def test_git_network_operations_are_blocked(argv):
    with pytest.raises(RuntimeError, match="blocked"):
        subprocess.run(argv, cwd=ROOT)
    with pytest.raises(RuntimeError, match="blocked"):
        subprocess.run(args=argv, cwd=ROOT)


def test_git_blocked_through_check_call_and_popen():
    with pytest.raises(RuntimeError, match="blocked"):
        subprocess.check_call(["git", "pull"], cwd=ROOT)
    with pytest.raises(RuntimeError, match="blocked"):
        subprocess.Popen(["git", "push"], cwd=ROOT)


def test_local_git_commands_still_work():
    result = subprocess.run(["git", "log", "--grep", "pull", "-n", "1", "--format=%h"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode in (0, 128)  # 128: not a git checkout (e.g. unpacked sdist)


def test_connect_ex_is_guarded_too():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError, match="blocked"):
            sock.connect_ex(("93.184.216.34", 80))
        with pytest.raises(OSError, match="blocked"):
            sock.connect_ex(("127.0.0.1", 11434))
    finally:
        sock.close()
