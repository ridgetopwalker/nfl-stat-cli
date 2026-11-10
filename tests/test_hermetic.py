"""The test environment must never touch real user state or the network (issue #20)."""
import os
import socket
import subprocess
from pathlib import Path

import pytest
import pro_football_slm as cli

ROOT = Path(__file__).resolve().parents[1]


class _GuardTestSocket(socket.socket):
    """Exercise the Python network guard without opening a kernel socket."""

    @property
    def family(self):
        return socket.AF_INET



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
    # The guard must reject these addresses before touching an OS socket.
    sock = _GuardTestSocket.__new__(_GuardTestSocket)
    sock._io_refs = 0
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
    # The guard must reject these addresses before touching an OS socket.
    sock = _GuardTestSocket.__new__(_GuardTestSocket)
    sock._io_refs = 0
    try:
        with pytest.raises(OSError, match="blocked"):
            sock.connect_ex(("93.184.216.34", 80))
        with pytest.raises(OSError, match="blocked"):
            sock.connect_ex(("127.0.0.1", 11434))
    finally:
        sock.close()


def test_outer_environment_is_cleaned_for_each_test(tmp_path):
    import sys
    import shutil

    shutil.copy(ROOT / "tests" / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_environment.py").write_text('''import os
from pathlib import Path
import pytest

@pytest.mark.parametrize("iteration", [1, 2])
def test_safe_environment(iteration):
    assert os.environ["PFSLM_SLM_MODEL"] == "off"
    assert os.environ["PFSLM_OLLAMA_URL"] == "http://127.0.0.1:9"
    assert Path(os.environ["PFSLM_IPC_DIR"]).is_dir()
    assert "NFL_STAT_STRAY" not in os.environ
    # Pollute the process directly: the next test must restore all safe values.
    os.environ["PFSLM_OLLAMA_URL"] = "http://outer.invalid:11434"
    os.environ["PFSLM_SLM_MODEL"] = "unsafe"
    os.environ["PFSLM_IPC_DIR"] = "/unsafe"
    os.environ["NFL_STAT_STRAY"] = "stray"
''')
    env = dict(os.environ, PFSLM_OLLAMA_URL="http://outer.invalid:11434", NFL_STAT_STRAY="stray")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(tmp_path)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
