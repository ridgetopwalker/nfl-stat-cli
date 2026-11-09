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
  *"-m venv"*) exit 1;;
  *"-m pip install"*" -r "*) exit ${FAKE_LIVE_RC:-0};;
  *"import nflreadpy"*) exit ${FAKE_IMPORT_RC:-1};;
  *) exit 0;;
esac
"""


def _requirements(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip().lower()
            out[name] = line
    return out


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
        (work / "bin").mkdir(parents=True)
        for name in ("install.sh", "requirements-live.txt", "pyproject.toml", "nfl_stat_cli.py"):
            if (ROOT / name).exists():
                shutil.copy(ROOT / name, work / name)
        fake = work / "bin" / "python3"
        fake.write_text(FAKE_PYTHON)
        fake.chmod(0o755)
        env = dict(os.environ, PATH=str(work / "bin") + os.pathsep + os.environ.get("PATH", ""), TMPDIR=str(tmp_path))
        for key in ("FAKE_LIVE_RC", "FAKE_IMPORT_RC", "PYTHONPATH"):
            env.pop(key, None)
        return work, env

    def run(self, sandbox, *args, **extra_env):
        work, env = sandbox
        env = dict(env, **extra_env)
        return subprocess.run([BASH, "install.sh", *args], cwd=work, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_unknown_option_is_rejected(self, sandbox):
        result = self.run(sandbox, "--bogus")
        assert result.returncode == 2
        assert "Unknown option" in result.stderr

    def test_live_package_failure_stops_the_install(self, sandbox):
        for args in (("-v",), ()):
            result = self.run(sandbox, *args, FAKE_LIVE_RC="1")
            assert result.returncode != 0, result.stdout
            assert "--sample-only" in result.stderr
            assert "INSTALLATION COMPLETE" not in result.stdout

    def test_success_that_leaves_sample_data_is_not_reported_as_success(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_IMPORT_RC="1")
        assert result.returncode != 0
        assert "SAMPLE" in result.stderr

    def test_sample_only_is_explicit_and_labelled(self, sandbox):
        result = self.run(sandbox, "--sample-only", "-v", FAKE_LIVE_RC="1")
        assert result.returncode == 0, result.stderr
        assert "SAMPLE" in result.stdout

    def test_full_success(self, sandbox):
        result = self.run(sandbox, "-v", FAKE_IMPORT_RC="0")
        assert result.returncode == 0, result.stderr
        assert "INSTALLATION COMPLETE" in result.stdout


def test_manifest_and_readme_cover_live_requirements():
    assert "include requirements-live.txt" in (ROOT / "MANIFEST.in").read_text().splitlines()
    readme = (ROOT / "README.md").read_text()
    assert "--sample-only" in readme and "-SkipLivePackages" in readme
