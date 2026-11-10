"""Pro Football SLM rebrand: script idempotency, env fallback, shim, data-dir migration."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import pro_football_slm as cli
from pro_football_slm import legacy_compat as compat

ROOT = Path(__file__).resolve().parents[1]
REBRAND = ROOT / "tools" / "rebrand.py"


def test_product_name_has_slm_and_no_nfl():
    assert cli.PRODUCT_NAME == "Pro Football SLM"
    assert "SLM" in cli.PRODUCT_NAME
    assert "NFL" not in cli.PRODUCT_NAME
    assert cli.PRODUCT_TAGLINE.startswith("Pro Football SLM:")


def test_banner_logo_has_no_nfl_product_branding():
    import re
    raw = cli.AsciiArtRenderer.banner()
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    logo = "\n".join(clean.splitlines()[:7])
    assert "NFL" not in logo
    assert "██████" in clean
    assert "Pro Football SLM" in clean
    assert "Not affiliated with or endorsed by the NFL" in clean


def test_rebrand_check_passes():
    res = subprocess.run([sys.executable, str(REBRAND), "--check"], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK" in res.stdout


def test_rebrand_script_idempotent(tmp_path):
    # Copy the already-rebranded tree and confirm a second apply is a no-op.
    import shutil
    dest = tmp_path / "tree"
    shutil.copytree(
        ROOT,
        dest,
        ignore=shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "*.pyc", "cache", "data", "*.zip", "dist", "build"),
    )
    preserved = ["nfl-stat", "nfl-stat.bat", "pfslm", "pfslm.bat", "pyproject.toml",
                 "tests/test_p1_6b_error_retention.py"]
    before = {name: (dest / name).read_bytes() for name in preserved}
    apply1 = subprocess.run([sys.executable, str(dest / "tools" / "rebrand.py")], cwd=str(dest), capture_output=True, text=True)
    assert apply1.returncode == 0, apply1.stdout + apply1.stderr
    assert "idempotent: second pass is a no-op" in apply1.stdout
    assert {name: (dest / name).read_bytes() for name in preserved} == before
    dry = subprocess.run([sys.executable, str(dest / "tools" / "rebrand.py"), "--dry-run"], cwd=str(dest), capture_output=True, text=True)
    assert dry.returncode == 0
    assert "\nedits: 0\n" in dry.stdout or dry.stdout.strip().endswith("edits: 0")


def test_env_get_prefers_pfslm_over_legacy(monkeypatch):
    compat.reset_compat_state_for_tests()
    monkeypatch.setenv("PFSLM_SLM_MODEL", "new-model")
    monkeypatch.setenv(compat.OLD_ENV_PREFIX + "SLM_MODEL", "old-model")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert compat.env_get("PFSLM_SLM_MODEL") == "new-model"
        assert w == []


def test_env_get_falls_back_to_legacy_with_one_time_notice(monkeypatch, capsys):
    compat.reset_compat_state_for_tests()
    monkeypatch.delenv("PFSLM_OLLAMA_URL", raising=False)
    monkeypatch.setenv(compat.OLD_ENV_PREFIX + "OLLAMA_URL", "http://legacy:11434")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert compat.env_get("PFSLM_OLLAMA_URL") == "http://legacy:11434"
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
    err = capsys.readouterr().err
    assert (compat.OLD_ENV_PREFIX + "OLLAMA_URL") in err and (compat.NEW_ENV_PREFIX + "OLLAMA_URL") in err
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert compat.env_get("PFSLM_OLLAMA_URL") == "http://legacy:11434"
    assert capsys.readouterr().err == ""


def test_shim_runs_without_notice(capsys):
    from pro_football_slm import shim
    with pytest.raises(SystemExit) as exc:
        shim.main(["--version"])
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert err == ""


def test_data_dir_migration_fresh(tmp_path):
    compat.reset_compat_state_for_tests()
    home = tmp_path / "home"
    home.mkdir()
    old = home / compat.OLD_DATA_DIRNAME
    (old / "cache").mkdir(parents=True)
    (old / "cache" / "x.bin").write_text("data", encoding="utf-8")
    (old / "error_ipc" / "pending").mkdir(parents=True)
    (old / "error_ipc" / "pending" / "a.json").write_text("{}", encoding="utf-8")
    new = compat.default_data_dir(home=home)
    assert new == home / compat.NEW_DATA_DIRNAME
    assert (new / "cache" / "x.bin").read_text(encoding="utf-8") == "data"
    assert (new / "error_ipc" / "pending" / "a.json").exists()
    assert (new / compat.MIGRATION_MARKER).is_file()
    assert not (old / "cache").exists()


def test_data_dir_already_migrated(tmp_path):
    compat.reset_compat_state_for_tests()
    home = tmp_path / "home2"
    new = home / compat.NEW_DATA_DIRNAME
    new.mkdir(parents=True)
    (new / compat.MIGRATION_MARKER).write_text("done\n", encoding="utf-8")
    old = home / compat.OLD_DATA_DIRNAME
    (old / "cache").mkdir(parents=True)
    (old / "cache" / "y.bin").write_text("keep-old", encoding="utf-8")
    status = compat.maybe_migrate_data_dir(old, new)
    assert status["action"] == "already_migrated"
    assert (old / "cache" / "y.bin").exists()


def test_data_dir_both_exist_no_overwrite(tmp_path):
    compat.reset_compat_state_for_tests()
    home = tmp_path / "home3"
    old = home / compat.OLD_DATA_DIRNAME
    new = home / compat.NEW_DATA_DIRNAME
    (old / "cache").mkdir(parents=True)
    (old / "cache" / "old.bin").write_text("old", encoding="utf-8")
    (new / "cache").mkdir(parents=True)
    (new / "cache" / "new.bin").write_text("new", encoding="utf-8")
    status = compat.maybe_migrate_data_dir(old, new)
    assert status["action"] == "both_exist_skipped"
    assert (new / "cache" / "new.bin").read_text(encoding="utf-8") == "new"
    assert (old / "cache" / "old.bin").read_text(encoding="utf-8") == "old"
    assert (new / compat.MIGRATION_MARKER).is_file()


def test_about_mentions_affiliation(capsys):
    assert cli.main(["--about"]) == 0
    out = capsys.readouterr().out
    assert "Pro Football SLM" in out
    assert "Not affiliated with or endorsed by the NFL" in out
    assert "American pro football stat engine" in out


@pytest.mark.skipif(shutil.which("bash") is None or not hasattr(os, "symlink"), reason="bash/symlinks not available")
@pytest.mark.parametrize("command", ["pro-football-slm", "nfl-stat", "pfslm"])
def test_launchers_version_without_notice(command, tmp_path):
    import os
    env = dict(os.environ)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(sys.executable)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(["bash", str(ROOT / command), "--version"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"pro-football-slm {cli.__version__}"
    assert result.stderr == ""


def test_module_version_without_notice():
    result = subprocess.run([sys.executable, "-m", "pro_football_slm", "--version"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_all_console_scripts_target_package():
    text = (ROOT / "pyproject.toml").read_text()
    for command in ("pro-football-slm", "pfslm", "nfl-stat"):
        assert f'{command} = "pro_football_slm:main"' in text


def test_about_forms_are_consistent(capsys):
    assert cli.main(["--about"]) == 0
    flag = capsys.readouterr().out
    assert cli.main(["about"]) == 0
    assert capsys.readouterr().out == flag
    assert flag.count("This software is MIT-licensed") == 1
    for line in (cli.PRODUCT_NAME, cli.PRODUCT_TAGLINE, cli.AFFILIATION_DISCLAIMER):
        assert flag.splitlines().count(line) == 1
    assert flag.startswith(f"{cli.PRODUCT_NAME}\n{cli.PRODUCT_TAGLINE}\n{cli.AFFILIATION_DISCLAIMER}\n\n")


@pytest.mark.parametrize("suffix,value,reader,expected", [
    ("R_TIMEOUT", "17", cli._r_timeout_seconds, 17),
    ("MAX_QUERY_CHARS", "19", cli.get_max_query_chars, 19),
    ("OLLAMA_URL", "http://legacy.invalid:11434", cli.NaturalLanguageStatAssistant.ollama_base_url,
     "http://legacy.invalid:11434"),
    ("DISABLE_NL_MUTATIONS", "1", cli.nl_mutations_allowed, False),
    ("ENABLE_ERROR_IPC", "0", cli.error_ipc_enabled, False),
    ("DISABLE_ERROR_IPC", "1", cli.error_ipc_enabled, False),
    ("ALLOW_GIT_UPDATE", "1", lambda: cli._truthy_env(cli.GIT_UPDATE_ENV), True),
    ("REQUIRE_LIVE", "1", lambda: cli.NFLDataBridge().require_live, True),
    ("SLM_MODEL", "off", cli.NaturalLanguageStatAssistant.detect_ollama_model, None),
])
def test_legacy_settings_reach_app(monkeypatch, suffix, value, reader, expected):
    compat.reset_compat_state_for_tests()
    monkeypatch.delenv(compat.NEW_ENV_PREFIX + suffix, raising=False)
    monkeypatch.setenv(compat.OLD_ENV_PREFIX + suffix, value)
    with pytest.warns(DeprecationWarning):
        assert reader() == expected


@pytest.mark.parametrize("suffix,reader", [
    ("EXPORT_DIR", cli.get_export_dir),
    ("IPC_DIR", lambda: cli.get_ipc_dir(create=False)),
])
def test_legacy_directory_overrides(monkeypatch, tmp_path, suffix, reader):
    compat.reset_compat_state_for_tests()
    monkeypatch.delenv(compat.NEW_ENV_PREFIX + suffix, raising=False)
    monkeypatch.setenv(compat.OLD_ENV_PREFIX + suffix, str(tmp_path))
    with pytest.warns(DeprecationWarning):
        assert reader() == tmp_path
