"""Hermetic test environment (issue #20).

Every test runs with:
  * a throw-away HOME / USERPROFILE (nothing is read from or written to the real
    ``~/.pro_football_slm`` cache and custom-stat store); this is also applied for the whole session
    before the package is imported,
  * an isolated error-IPC directory (nothing is written to the repository's
    ``.error_ipc`` where a running watcher could act on it),
  * no local SLM (Ollama) probing,
  * outbound network sockets blocked (loopback stays allowed, except the Ollama/discard ports),
  * ``git pull`` / ``push`` / ``fetch`` / ``clone`` / ``ls-remote`` / ``remote update`` blocked
    when started through ``subprocess`` (run/call/check_*/Popen).

Limits (documented on purpose): the socket and git guards only cover the pytest process.
Child processes started by tests inherit the environment variables (temp HOME, SLM off,
unreachable Ollama URL, IPC dir) but not the in-process guards.
"""
import inspect
import ipaddress
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

BLOCKED_GIT_SUBCOMMANDS = {"pull", "push", "fetch", "clone", "ls-remote"}
BLOCKED_LOCAL_PORTS = {9, 11434}  # discard + the default Ollama port


def _set_home(monkeypatch, home):
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)


def pytest_configure(config):
    """Isolate HOME before any test module (and therefore the package) is imported."""
    config._nfl_session_mp = pytest.MonkeyPatch()
    config._nfl_session_home = tempfile.TemporaryDirectory(prefix="nfl-test-home-")
    _set_home(config._nfl_session_mp, config._nfl_session_home.name)
    config._nfl_session_mp.setenv("PFSLM_SLM_MODEL", "off")


def pytest_unconfigure(config):
    config._nfl_session_mp.undo()
    config._nfl_session_home.cleanup()


def _git_subcommand(argv):
    """Return the git subcommand for ``argv`` (skipping -C <dir>, -c k=v and other global options)."""
    args = iter(argv[1:])
    for arg in args:
        if arg in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            next(args, None)
        elif arg.startswith("-"):
            continue
        else:
            return arg, list(args)
    return None, []


def _is_blocked_git(argv):
    if not argv or Path(argv[0]).name not in ("git", "git.exe"):
        return False
    sub, rest = _git_subcommand(argv)
    return sub in BLOCKED_GIT_SUBCOMMANDS or (sub == "remote" and "update" in rest)


@pytest.fixture(autouse=True)
def _hermetic_environment(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    ipc = tmp_path_factory.mktemp("error_ipc")
    _set_home(monkeypatch, home)
    monkeypatch.setenv("PFSLM_SLM_MODEL", "off")
    # Even if a test forgets to disable the SLM, the probe cannot reach a real Ollama server.
    monkeypatch.setenv("PFSLM_OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PFSLM_IPC_DIR", str(ipc))

    import pro_football_slm as cli

    # Builds that do not yet honour PFSLM_IPC_DIR resolve the IPC dir inside the repo checkout.
    # Detect that from the source (calling it would create the directory we want to avoid) and
    # redirect it; test_hermetic.py asserts the resulting property either way.
    try:
        honours_env = "PFSLM_IPC_DIR" in inspect.getsource(cli.get_ipc_dir)
    except (OSError, TypeError):
        honours_env = False
    if not honours_env:
        def _tmp_ipc_dir() -> Path:
            for sub in ("", "pending", "resolved", "history"):
                (ipc / sub).mkdir(parents=True, exist_ok=True)
            return ipc
        monkeypatch.setattr(cli, "get_ipc_dir", _tmp_ipc_dir)

    def _check_address(address):
        host = address[0] if isinstance(address, tuple) else address
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        try:
            loopback = ipaddress.ip_address(str(host).split("%")[0]).is_loopback or str(host) == "localhost"
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise OSError(f"network access blocked in tests: {address!r}")
        if port in BLOCKED_LOCAL_PORTS:
            # Behave like an absent service so callers that catch ConnectionError keep working.
            raise ConnectionRefusedError(f"local service access blocked in tests: {address!r}")

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address, *args, **kwargs):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check_address(address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check_address(address)
        return real_connect_ex(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    # One hook on Popen covers subprocess.run/call/check_call/check_output. Shell strings are only
    # checked for a leading "git ..." command; os.system and chained shell commands are not covered.
    real_popen_init = subprocess.Popen.__init__

    def guarded_popen_init(self, args, *pargs, **kwargs):
        argv = [str(part) for part in args] if isinstance(args, (list, tuple)) else str(args).split()
        if _is_blocked_git(argv):
            raise RuntimeError(f"git network operation blocked in tests: {argv!r}")
        return real_popen_init(self, args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded_popen_init)
