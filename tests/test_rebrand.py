"""Pro Football SLM rebrand: script idempotency, env fallback, shim, data-dir migration."""
from __future__ import annotations

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


def test_rebrand_script_idempotent():
    dry1 = subprocess.run([sys.executable, str(REBRAND), "--dry-run"], cwd=str(ROOT), capture_output=True, text=True)
    assert dry1.returncode == 0, dry1.stdout + dry1.stderr
    assert "edits: 0" in dry1.stdout
    dry2 = subprocess.run([sys.executable, str(REBRAND), "--dry-run"], cwd=str(ROOT), capture_output=True, text=True)
    assert dry2.returncode == 0
    assert "edits: 0" in dry2.stdout


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


def test_shim_prints_rename_notice(capsys):
    from pro_football_slm import shim
    with pytest.raises(SystemExit) as exc:
        shim.main(["--version"])
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "deprecated" in err.lower() and "pro-football-slm" in err


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
