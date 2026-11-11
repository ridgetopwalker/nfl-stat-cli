"""Installer behaviour: failures must be visible and live data must be explicit (issue #30)."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = (ROOT / "install.sh").read_text()
INSTALL_PS1 = (ROOT / "install.ps1").read_text()
BASH = shutil.which("bash")

FAKE_PYTHON = """#!/usr/bin/env bash
case "$*" in
  *"version_info"*) exit ${FAKE_PY_OLD:-0};;
  *"-m venv"*) exit 1;;
  *"-m pip install"*" -r "*) exit ${FAKE_LIVE_RC:-0};;
  *"-m pip install -e"*) exit ${FAKE_E_RC:-0};;
  *"-m pip install"*nfl_data_py*) exit ${FAKE_LEGACY_INSTALL_RC:-0};;
  *"import nflreadpy"*) exit ${FAKE_IMPORT_RC:-1};;
  *"import nfl_data_py"*) exit ${FAKE_LEGACY_RC:-1};;
  *) exit 0;;
esac
"""

# Commands install.sh needs; deliberately no Rscript/sudo/brew/apt so the sandbox can never reach them.
SYSTEM_TOOLS = (
    "bash", "dirname", "cat", "mktemp", "rm", "tput", "sed", "tail", "head", "chmod", "ln", "mkdir",
    "grep", "readlink", "tr", "env", "uname", "cut", "basename", "ls", "cp", "mv", "touch", "sleep",
)


def _requirements(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
            out[name] = line
    return out


def test_nflreadpy_is_gated_to_python_310():
    text = (ROOT / "requirements-live.txt").read_text()
    assert re.search(r'^nflreadpy.*; python_version >= "3\.10"$', text, re.M)


def test_requirements_live_matches_pyproject_lower_bounds():
    live = _requirements(ROOT / "requirements-live.txt")
    pyproject = (ROOT / "pyproject.toml").read_text()
    block = re.search(r"^live = \[(.*?)\]", pyproject, re.S | re.M).group(1)
    extra = {}
    for spec in re.findall(r'"([^"]+)"', block):
        extra[re.split(r"[<>=!~]", spec, maxsplit=1)[0].strip().lower().replace("_", "-")] = spec
    for name in ("pandas", "polars", "pyarrow", "nflreadpy"):
        lower = re.search(r">=([\d.]+)", live[name]).group(1)
        assert f">={lower}" in extra[name], name
        assert "<" in live[name], f"{name} must have an upper bound"
    assert "nfl-data-py" not in live and "nfl_data_py" not in live


def test_installers_do_not_swallow_pip_or_r_failures():
    for line in INSTALL_SH.splitlines():
        if "|| true" in line:
            assert "pip" not in line and "Rscript" not in line, line
    code = "\n".join(line for line in INSTALL_SH.splitlines() if not line.lstrip().startswith("#"))
    assert "get-pip.py" not in code and "curl" not in code
    assert "nfl_data_py" not in re.sub(r'(?m)^.*(legacy|LEGACY|import nfl_data_py|nfl_data_py>=).*$', "", INSTALL_SH)
    assert "--sample-only" in INSTALL_SH and "-SkipLivePackages" in INSTALL_PS1
    for token in ("Stop-Install", "$LASTEXITCODE -ne 0"):
        assert token in INSTALL_PS1


def test_powershell_installer_verifies_python_download():
    assert "Get-FileHash" in INSTALL_PS1
    assert re.search(r'\$PythonInstallerSha256 = "[0-9a-f]{64}"', INSTALL_PS1)
    assert "3.12.8" not in INSTALL_PS1


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh not installed")
def test_powershell_installer_parses():
    script = (
        "$e=$null;$t=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile($env:NFL_PS1,[ref]$t,[ref]$e);"
        "exit $e.Count"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True, text=True, env=dict(os.environ, NFL_PS1=str(ROOT / "install.ps1")),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(BASH is None, reason="bash not available")
class TestInstallShBehaviour:
    @pytest.fixture
    def sandbox(self, tmp_path):
        work = tmp_path / "proj"
        bindir = work / "bin"
        bindir.mkdir(parents=True)
        for name in ("install.sh", "requirements-live.txt", "pyproject.toml", "pro_football_slm.py"):
            if (ROOT / name).exists():
                shutil.copy(ROOT / name, work / name)
        for tool in SYSTEM_TOOLS:
            found = shutil.which(tool)
            if found:
                (bindir / tool).symlink_to(found)
        fake = bindir / "python3"
        fake.write_text(FAKE_PYTHON)
        fake.chmod(0o755)
        env = {"PATH": str(bindir), "TMPDIR": str(tmp_path), "HOME": str(tmp_path / "home"), "TERM": "dumb"}
        return work, env

    def add_stub(self, sandbox, name, body="echo STUB-$0 \"$@\""):
        work, _ = sandbox
        stub = work / "bin" / name
        stub.write_text("#!/usr/bin/env bash\n" + body + "\n")
        stub.chmod(0o755)

    def run(self, sandbox, *args, **extra_env):
        work, env = sandbox
        env = dict(env, **extra_env)
        return subprocess.run([BASH, "install.sh", *args], cwd=work, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_help_and_unknown_option(self, sandbox):
        result = self.run(sandbox, "--help")
        assert result.returncode == 0 and "--sample-only" in result.stdout and "--yes" in result.stdout
        result = self.run(sandbox, "--bogus")
        assert result.returncode == 2
        assert "Unknown option" in result.stderr

    def test_live_package_failure_stops_the_install(self, sandbox):
        for args in (("-v",), ()):
            result = self.run(sandbox, *args, FAKE_LIVE_RC="1")
            assert result.returncode != 0, result.stdout
            assert "--sample-only" in result.stderr
            assert "INSTALLATION COMPLETE" not in result.stdout

    def test_failure_flushes_collected_warnings(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_LIVE_RC="1")
        assert "Could not create a .venv" in result.stderr  # the likely root cause is reported with the error

    def test_success_that_leaves_sample_data_is_not_reported_as_success(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_IMPORT_RC="1")
        assert result.returncode != 0
        assert "SAMPLE" in result.stderr
        assert "--with-legacy-nfl-data-py" in result.stderr  # the opt-in legacy route is named

    def test_sample_only_is_explicit_and_labelled(self, sandbox):
        result = self.run(sandbox, "--sample-only", "-v", FAKE_LIVE_RC="1")
        assert result.returncode == 0, result.stderr
        assert "SAMPLE" in result.stdout

    def test_legacy_loader_is_opt_in(self, sandbox):
        result = self.run(sandbox, "--with-legacy-nfl-data-py", "-v", FAKE_IMPORT_RC="1", FAKE_LEGACY_RC="0")
        assert result.returncode == 0, result.stderr
        failing = self.run(sandbox, "--with-legacy-nfl-data-py", "-v", FAKE_LEGACY_INSTALL_RC="1")
        assert failing.returncode != 0
        assert "legacy nfl_data_py" in failing.stderr

    def test_full_success(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_IMPORT_RC="0")
        assert result.returncode == 0, result.stderr
        assert "INSTALLATION COMPLETE" in result.stdout

    def test_old_python_is_rejected(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_PY_OLD="1")
        assert result.returncode != 0
        assert "3.10 or newer" in result.stderr

    def test_failed_package_install_is_fatal(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_E_RC="1", FAKE_IMPORT_RC="0")
        assert result.returncode != 0
        assert "pip install -e . failed" in result.stderr

    def test_sudo_is_never_run_without_consent(self, sandbox):
        (sandbox[0] / "bin" / "python3").unlink()
        self.add_stub(sandbox, "apt-get")
        self.add_stub(sandbox, "sudo")
        result = self.run(sandbox, "-v")  # stdin is not a terminal and --yes was not given
        assert result.returncode != 0
        assert "needs administrator rights" in result.stderr and "--yes" in result.stderr
        assert "STUB-" not in result.stdout

    def test_yes_allows_sudo_but_a_missing_python_still_fails_loudly(self, sandbox):
        (sandbox[0] / "bin" / "python3").unlink()
        self.add_stub(sandbox, "apt-get")
        self.add_stub(sandbox, "sudo", 'echo "STUB-SUDO $*"')
        result = self.run(sandbox, "-v", "--yes")
        assert "STUB-SUDO" in result.stdout
        assert result.returncode != 0
        assert "python3 is still not on PATH" in result.stderr


@pytest.mark.skipif(not shutil.which("pwsh") or BASH is None, reason="pwsh and bash required")
def test_powershell_installer_stops_when_live_packages_fail(tmp_path):
    """Run install.ps1 under pwsh with a fake python whose requirements install fails."""
    work = tmp_path / "proj"
    (work / "bin").mkdir(parents=True)
    for name in ("install.ps1", "requirements-live.txt"):
        shutil.copy(ROOT / name, work / name)
    fake = work / "bin" / "python"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *version_info.major*) echo 3.13; exit 0;;\n'
        '  *"-m venv"*) exit 1;;\n'
        '  *"-m pip install"*" -r "*) echo "no matching distribution"; exit 1;;\n'
        "  *) exit 0;;\n"
        "esac\n"
    )
    fake.chmod(0o755)
    (tmp_path / "tmp").mkdir()
    env = dict(os.environ, TEMP=str(tmp_path / "tmp"), PATH=str(work / "bin") + os.pathsep + os.environ["PATH"])
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(work / "install.ps1"), "-v"], cwd=work, env=env, capture_output=True, text=True)
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "SkipLivePackages" in out
    assert "Could not create a .venv" in out  # warnings are flushed with the error


def test_manifest_and_readme_cover_live_requirements():
    assert "include requirements-live.txt" in (ROOT / "MANIFEST.in").read_text().splitlines()
    readme = (ROOT / "README.md").read_text()
    assert "--sample-only" in readme and "-SkipLivePackages" in readme


def test_installers_publish_primary_short_and_legacy_commands():
    loops = re.findall(r"for command in ([^;]+); do\s+link_path_command ([^\n]+)", INSTALL_SH)
    assert len(loops) == 2
    assert all(commands.split() == ["pro-football-slm", "pfslm", "nfl-stat"] for commands, _ in loops)
    assert {body for _, body in loops} == {'"$HOME/.local/bin" "$command"', '"/usr/local/bin" "$command"'}
    loop = re.search(r'foreach \(\$LauncherName in @\(([^)]+)\)\)\s*\{\s*Set-Content', INSTALL_PS1)
    assert loop
    assert re.findall(r'"([^"]+)"', loop[1]) == ["pro-football-slm.bat", "pfslm.bat", "nfl-stat.bat"]
    assert '"$SCRIPT_DIR/pro-football-slm" --version' in INSTALL_SH
    assert '"pro-football-slm.bat") --version' in INSTALL_PS1


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_path_links_preserve_files_and_replace_symlinks(tmp_path):
    home = tmp_path / "home"
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    existing = bindir / "pro-football-slm"
    existing.write_text("unrelated command\n")
    (bindir / "pfslm").symlink_to(tmp_path / "missing-old-target")
    # Exercise the actual helper without running installation or touching system PATH dirs.
    helper = INSTALL_SH.split("link_path_command() {", 1)[1].split("\nprompt_add_to_path()", 1)[0]
    script = 'link_path_command() {' + helper + '\nfor command in pro-football-slm pfslm nfl-stat; do\n link_path_command "$HOME/.local/bin" "$command"\ndone\n'
    result = subprocess.run([BASH, "-c", script], env=dict(os.environ, HOME=str(home), SCRIPT_DIR=str(ROOT)), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert existing.read_text() == "unrelated command\n"
    assert not existing.is_symlink()
    assert "Warning:" in result.stderr and str(existing) in result.stderr
    for name in ("pfslm", "nfl-stat"):
        assert (bindir / name).is_symlink()
        assert os.readlink(bindir / name) == str(ROOT / name)
