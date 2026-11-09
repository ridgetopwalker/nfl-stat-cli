"""Regression tests for #34: state/cache/IPC directories are created on first write, and player-name
autocomplete is bound to the active dataset instead of always offering the built-in sample names."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import nfl_stat_cli as cli

REPO = Path(__file__).resolve().parent.parent


def _sample_only_names():
    from nfl_stat_cli.contracts import NFL_CONTRACTS
    known = set()
    for c in NFL_CONTRACTS:
        parts = c.name.split()
        known |= {c.name, parts[-1], f"{parts[0][0]}.{parts[-1]}"}
    names = set()
    for p in cli.SAMPLE_PBP_PLAYS:
        for k in ("player_name", "receiver_player_name", "rusher_player_name", "qb_name"):
            if p.get(k):
                names.add(str(p[k]).strip())
    return sorted(names - known)


# ---------------------------------------------------------------- lazy directories

def test_importing_and_constructing_creates_nothing_in_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(REPO)}
    env.pop("NFL_STAT_IPC_DIR", None)
    code = (
        "import nfl_stat_cli as c\n"
        "e = c.StatEngine()\n"
        "b = c.NFLDataBridge(engine='offline')\n"
        "c.get_ipc_dir(create=False)\n"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True, cwd=str(tmp_path))
    assert list(home.iterdir()) == []


def test_state_dir_is_created_on_first_save(tmp_path):
    target = tmp_path / "state" / "deeper"
    eng = cli.StatEngine(storage_dir=target)
    assert not target.exists()
    eng.save_state()
    assert (target / "custom_stats.json").exists() and (target / "stat_page.json").exists()


def test_registering_a_persisted_stat_creates_the_state_dir(tmp_path):
    target = tmp_path / "s"
    eng = cli.StatEngine(storage_dir=target)
    eng.register_custom_stat(name="mine", title="m", group_by="qb", formula="plays + 1", description="d", calculation_explained="c")
    assert (target / "custom_stats.json").exists()


def test_cache_dir_is_created_on_first_use_not_on_construction(tmp_path):
    cache = tmp_path / "cache" / "x"
    bridge = cli.NFLDataBridge(cache_dir=cache, engine="offline")
    assert not cache.exists()
    assert bridge.load_pbp([2024])  # offline sample load never needs the cache
    assert not cache.exists()
    assert bridge.cache_dir == cache and cache.is_dir()


def test_cache_dir_can_be_reassigned(tmp_path):
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "a", engine="offline")
    bridge.cache_dir = tmp_path / "b"
    assert bridge.cache_dir == tmp_path / "b" and (tmp_path / "b").is_dir()
    assert not (tmp_path / "a").exists()


@pytest.fixture
def ipc_env(tmp_path, monkeypatch):
    target = tmp_path / "ipc"
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(target))
    return target


def test_read_only_ipc_calls_do_not_create_directories(ipc_env):
    assert cli.get_ipc_dir(create=False) == ipc_env
    assert not ipc_env.exists()
    rid = "err_20260101_000000_deadbeef"
    assert cli.wait_for_resolution(rid, timeout=0.0, poll_interval=0.01) is None
    assert not ipc_env.exists()


def test_writers_still_create_the_private_layout(ipc_env):
    path = cli.get_ipc_dir()
    for sub in ("pending", "resolved", "history"):
        assert (path / sub).is_dir()
    if os.name != "nt":
        assert (path.stat().st_mode & 0o777) == 0o700
    report = cli.create_error_report("q", {"intent": "x"}, "why")
    assert (ipc_env / "pending" / f"{report['id']}.json").exists()


def test_write_resolution_creates_dirs_and_wait_finds_it(ipc_env):
    rid = "err_20260101_000000_deadbeef"
    cli.write_resolution(rid, "fixed")
    assert cli.wait_for_resolution(rid, timeout=0.0)["id"] == rid


@pytest.mark.skipif(os.name == "nt", reason="symlink ownership checks are POSIX-only")
def test_read_only_call_still_refuses_a_symlinked_existing_dir(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(link))
    with pytest.raises(PermissionError):
        cli.get_ipc_dir(create=False)


# ---------------------------------------------------------------- autocomplete

def test_autocomplete_without_a_dataset_offers_no_sample_names():
    sample_only = _sample_only_names()
    assert sample_only, "fixture assumption: the sample data has names that are not contract names"
    completer = cli.CLICompleter(engine=None)
    options = completer.get_player_options()
    assert not set(sample_only) & set(options)


def test_autocomplete_uses_the_active_live_dataset_only():
    sample_only = _sample_only_names()
    live = [{"player_name": "Zed Livename", "qb_name": "Q.Livearm", "posteam": "KC"}]
    completer = cli.CLICompleter(engine=None, plays=live)
    options = completer.get_player_options()
    assert "Zed Livename" in options and "Q.Livearm" in options
    assert not set(sample_only) & set(options)
    assert completer.get_candidates("/player zed", 8, "zed")


def test_autocomplete_follows_the_sample_dataset_when_it_is_the_active_one():
    sample_only = _sample_only_names()
    completer = cli.CLICompleter(engine=None)
    completer.set_plays(cli.SAMPLE_PBP_PLAYS)
    assert set(sample_only) <= set(completer.get_player_options())


def test_autocomplete_cache_refreshes_when_dataset_changes():
    completer = cli.CLICompleter(engine=None)
    first = [{"player_name": "First Person"}]
    completer.set_plays(first)
    assert "First Person" in completer.get_player_options()
    completer.set_plays([{"player_name": "Second Person"}])
    opts = completer.get_player_options()
    assert "Second Person" in opts and "First Person" not in opts
    second = completer._plays
    second.append({"player_name": "Third Person"})  # same list grows: cache key includes the length
    assert "Third Person" in completer.get_player_options()


def test_existing_contract_completion_still_works():
    completer = cli.CLICompleter(engine=None)
    assert any("Mahomes" in m for m in completer.get_candidates("/player mah", 8, "mah") if m.lower().startswith("mah"))


def test_tui_binds_completer_to_the_loaded_plays(monkeypatch, tmp_path):
    bound = {}
    monkeypatch.setattr(cli, "_GLOBAL_COMPLETER", None)
    orig = cli.CLICompleter.set_plays

    def spy(self, plays):
        bound["plays"] = plays
        return orig(self, plays)

    monkeypatch.setattr(cli.CLICompleter, "set_plays", spy)
    monkeypatch.setattr(cli, "_HAS_READLINE", True)
    monkeypatch.setattr(cli, "setup_readline_completer", lambda engine=None: setattr(cli, "_GLOBAL_COMPLETER", cli.CLICompleter(engine)) or cli._GLOBAL_COMPLETER)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "/quit")
    live = [{"player_name": "Zed Livename", "season": 2025}]
    eng = cli.StatEngine(storage_dir=tmp_path)
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "c", engine="offline")
    try:
        cli.interactive_tui(eng, bridge, slm_model="off", default_season=2025, initial_plays=live)
    except SystemExit:
        pass
    assert bound.get("plays") is live


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_wait_for_resolution_rechecks_directories_that_appear_while_polling(tmp_path, monkeypatch):
    target = tmp_path / "ipc"
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(target))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def swap_in_symlink(_seconds):
        target.symlink_to(elsewhere, target_is_directory=True)

    monkeypatch.setattr(cli.time, "sleep", swap_in_symlink)
    with pytest.raises(PermissionError):
        cli.wait_for_resolution("err_20260101_000000_deadbeef", timeout=5.0, poll_interval=0.01)


def test_get_ipc_dir_read_only_tolerates_a_directory_vanishing(ipc_env, monkeypatch):
    ipc_env.mkdir()
    real_lstat = os.lstat

    def flaky(path, *a, **k):
        if Path(path).name == "pending":
            raise FileNotFoundError(path)
        return real_lstat(path, *a, **k)

    (ipc_env / "pending").mkdir()
    monkeypatch.setattr(cli.os, "lstat", flaky)
    assert cli.get_ipc_dir(create=False) == ipc_env
