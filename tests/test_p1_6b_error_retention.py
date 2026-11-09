"""Error-report retention cleanup for resolved/ and history/ (PR #45 follow-up)."""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

import nfl_stat_cli as cli


def _report_name(day_offset: int = 0, seq: int = 1) -> str:
    # Synthetic id; mtime (not the embedded date) drives age pruning in the implementation.
    return f"err_20200101_120000_{seq:08x}.json"


def _seed_report(folder: Path, name: str, mtime: float, body: str = "{}") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(body, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _ipc(tmp_path: Path) -> Path:
    ipc = tmp_path / "ipc"
    for sub in ("pending", "resolved", "history"):
        (ipc / sub).mkdir(parents=True, exist_ok=True)
    return ipc


def test_age_pruning_deletes_old_resolved_and_history_only(tmp_path, monkeypatch):
    monkeypatch.delenv("PFSLM_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("PFSLM_ERROR_RETENTION_MAX", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_MAX", raising=False)
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (40 * 86400)
    fresh = now - (5 * 86400)
    old_res = _seed_report(ipc / "resolved", _report_name(seq=1), old)
    old_hist = _seed_report(ipc / "history", _report_name(seq=2), old)
    new_res = _seed_report(ipc / "resolved", _report_name(seq=3), fresh)
    pending = _seed_report(ipc / "pending", _report_name(seq=4), old)
    extra = ipc / "resolved" / "notes.txt"
    extra.write_text("keep me", encoding="utf-8")
    os.utime(extra, (old, old))
    latest = ipc / "resolved" / "latest.json"
    latest.write_text("{}", encoding="utf-8")
    os.utime(latest, (old, old))

    result = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30, retention_max=500)

    assert result["deleted_age"] == 2
    assert result["deleted_cap"] == 0
    assert not old_res.exists()
    assert not old_hist.exists()
    assert new_res.exists()
    assert pending.exists()  # pending never touched
    assert extra.exists()
    assert latest.exists()
    assert (ipc / cli.ERROR_RETENTION_STAMP_NAME).is_file()


def test_cap_pruning_deletes_oldest_first_across_resolved_and_history(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    # All within the age window; cap of 3 should drop the two oldest.
    times = [now - (i * 3600) for i in range(5, 0, -1)]  # oldest first: -5h ... -1h
    paths = []
    for i, mt in enumerate(times, start=1):
        folder = ipc / ("resolved" if i % 2 else "history")
        paths.append(_seed_report(folder, _report_name(seq=i), mt))

    result = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30, retention_max=3)

    assert result["deleted_cap"] == 2
    assert result["deleted_age"] == 0
    assert result["kept"] == 3
    assert not paths[0].exists()  # oldest
    assert not paths[1].exists()
    assert paths[2].exists() and paths[3].exists() and paths[4].exists()


def test_pending_reports_are_never_deleted_even_when_old_and_over_cap(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (90 * 86400)
    for i in range(1, 6):
        _seed_report(ipc / "pending", _report_name(seq=i), old)
    # Also seed one resolved so cleanup has something to examine
    _seed_report(ipc / "resolved", _report_name(seq=9), now - 100)

    result = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=1, retention_max=1)

    pending_files = list((ipc / "pending").glob("err_*.json"))
    assert len(pending_files) == 5
    assert result["deleted_age"] == 0  # the only resolved file is fresh
    assert all(p.exists() for p in pending_files)


def test_env_var_precedence_pfslm_wins_and_invalid_falls_back(monkeypatch):
    monkeypatch.delenv("PFSLM_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("PFSLM_ERROR_RETENTION_MAX", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_MAX", raising=False)

    assert cli.error_retention_days() == 30
    assert cli.error_retention_max() == 500

    monkeypatch.setenv("NFL_STAT_ERROR_RETENTION_DAYS", "14")
    assert cli.error_retention_days() == 14
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "7")
    assert cli.error_retention_days() == 7  # PFSLM wins

    # invalid preferred falls through to the still-valid legacy value
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "nope")
    assert cli.error_retention_days() == 14
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "0")
    assert cli.error_retention_days() == 14
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "-3")
    assert cli.error_retention_days() == 14
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "99999")
    assert cli.error_retention_days() == 14
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "+5")  # sign not allowed
    assert cli.error_retention_days() == 14

    # both invalid -> default
    monkeypatch.setenv("NFL_STAT_ERROR_RETENTION_DAYS", "nope")
    assert cli.error_retention_days() == 30

    monkeypatch.setenv("NFL_STAT_ERROR_RETENTION_MAX", "100")
    assert cli.error_retention_max() == 100
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_MAX", "50")
    assert cli.error_retention_max() == 50
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_MAX", "abc")
    assert cli.error_retention_max() == 100  # falls through to legacy
    monkeypatch.setenv("NFL_STAT_ERROR_RETENTION_MAX", "xyz")
    assert cli.error_retention_max() == 500


def test_cheap_check_skips_when_stamp_is_fresh(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (60 * 86400)
    target = _seed_report(ipc / "resolved", _report_name(seq=1), old)
    stamp = ipc / cli.ERROR_RETENTION_STAMP_NAME
    stamp.write_text("already", encoding="utf-8")
    os.utime(stamp, (now - 60, now - 60))  # 1 minute ago

    skipped = cli.cleanup_error_reports(ipc, force=False, now=now, retention_days=30)
    assert skipped["skipped"] == 1
    assert target.exists()

    forced = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30)
    assert forced["skipped"] == 0
    assert forced["deleted_age"] == 1
    assert not target.exists()


def test_non_matching_files_and_symlinks_are_untouched(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (60 * 86400)
    good = _seed_report(ipc / "history", _report_name(seq=1), old)
    weird = ipc / "history" / "err_not_a_real_id.json"
    weird.write_text("{}", encoding="utf-8")
    os.utime(weird, (old, old))
    readme = ipc / "history" / "README.md"
    readme.write_text("docs", encoding="utf-8")
    os.utime(readme, (old, old))

    # Symlink that looks like a report name: must not be followed or removed as a report unlink of the link is ok
    # only if we treat symlinks as non-regular — implementation skips symlinks entirely.
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    os.utime(outside, (old, old))
    link = ipc / "history" / _report_name(seq=2)
    if hasattr(os, "symlink"):
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            link = None
    else:
        link = None

    result = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30, retention_max=500)

    assert not good.exists()
    assert weird.exists()
    assert readme.exists()
    assert outside.exists()
    if link is not None:
        assert link.exists()  # symlink skipped
        assert outside.read_text(encoding="utf-8") == '{"secret": true}'
    assert result["deleted_age"] == 1


def test_cleanup_never_raises_on_bad_ipc_dir(tmp_path):
    missing = tmp_path / "nope" / "missing"
    # force=True bypasses stamp; directory listing failures are swallowed
    result = cli.cleanup_error_reports(missing, force=True)
    assert isinstance(result, dict)
    assert result["deleted_age"] == 0


def test_create_error_report_triggers_cleanup_without_touching_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    monkeypatch.delenv("PFSLM_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_DAYS", raising=False)
    ipc = cli.get_ipc_dir()
    now = time.time()
    old = now - (60 * 86400)
    stale = _seed_report(ipc / "resolved", _report_name(seq=7), old)

    rep = cli.create_error_report("q", {"intent": "stat_query"}, "notes", season=2025)
    cli.validate_report_id(rep["id"])
    assert (ipc / "pending" / f"{rep['id']}.json").exists()
    assert not stale.exists()
    assert (ipc / cli.ERROR_RETENTION_STAMP_NAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink dir skip")
def test_symlinked_retention_subdir_is_skipped(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (60 * 86400)
    real = tmp_path / "real_history"
    real.mkdir()
    trapped = _seed_report(real, _report_name(seq=1), old)
    # Replace history/ with a symlink to real_history
    history = ipc / "history"
    history.rmdir()
    os.symlink(real, history)
    _seed_report(ipc / "resolved", _report_name(seq=2), old)

    result = cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30)

    assert trapped.exists()  # via symlinked history/ — skipped
    assert result["deleted_age"] == 1  # only the resolved one


def test_symlinked_stamp_is_replaced_not_followed(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    outside = tmp_path / "stamp_target"
    outside.write_text("do-not-clobber", encoding="utf-8")
    stamp = ipc / cli.ERROR_RETENTION_STAMP_NAME
    os.symlink(outside, stamp)
    _seed_report(ipc / "resolved", _report_name(seq=1), now - 100)

    cli.cleanup_error_reports(ipc, force=True, now=now, retention_days=30, retention_max=500)

    assert outside.read_text(encoding="utf-8") == "do-not-clobber"
    st = os.lstat(stamp)
    assert not stat.S_ISLNK(st.st_mode) and stat.S_ISREG(st.st_mode)


def test_stale_stamp_allows_non_forced_cleanup(tmp_path):
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (60 * 86400)
    target = _seed_report(ipc / "resolved", _report_name(seq=1), old)
    stamp = ipc / cli.ERROR_RETENTION_STAMP_NAME
    stamp.write_text("old", encoding="utf-8")
    os.utime(stamp, (now - cli.ERROR_RETENTION_MIN_INTERVAL_SECONDS - 10,
                     now - cli.ERROR_RETENTION_MIN_INTERVAL_SECONDS - 10))

    result = cli.cleanup_error_reports(ipc, force=False, now=now, retention_days=30)
    assert result["skipped"] == 0
    assert result["deleted_age"] == 1
    assert not target.exists()


def test_write_resolution_refreshes_history_mtime_before_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("NFL_STAT_IPC_DIR", str(tmp_path / "ipc"))
    ipc = cli.get_ipc_dir()
    now = time.time()
    rid = "err_20200101_120000_abcd1234"
    cli.validate_report_id(rid)
    pending = ipc / "pending" / f"{rid}.json"
    pending.write_text('{"id": "%s", "status": "pending"}' % rid, encoding="utf-8")
    os.utime(pending, (now - 90 * 86400, now - 90 * 86400))

    cli.write_resolution(report_id=rid, summary="fixed", commit="abc1234")

    history = ipc / "history" / f"{rid}.json"
    assert history.exists()
    # just-resolved history must survive a 30-day age prune in the same write_resolution call
    assert history.stat().st_mtime >= now - 5
    assert (ipc / "resolved" / f"{rid}.json").exists()
    assert not pending.exists()


def test_cleanup_uses_env_defaults_when_overrides_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_DAYS", "10")
    monkeypatch.setenv("PFSLM_ERROR_RETENTION_MAX", "2")
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NFL_STAT_ERROR_RETENTION_MAX", raising=False)
    ipc = _ipc(tmp_path)
    now = time.time()
    old = now - (20 * 86400)  # older than 10 days
    fresh_times = [now - i for i in range(3)]
    gone = _seed_report(ipc / "resolved", _report_name(seq=1), old)
    kept = [_seed_report(ipc / "history", _report_name(seq=10 + i), mt) for i, mt in enumerate(fresh_times)]

    result = cli.cleanup_error_reports(ipc, force=True, now=now)  # no explicit days/max

    assert not gone.exists()
    assert result["deleted_age"] == 1
    assert result["deleted_cap"] == 1  # 3 fresh -> cap 2
    assert sum(1 for p in kept if p.exists()) == 2


def test_cleanup_swallows_unexpected_errors(tmp_path, monkeypatch):
    ipc = _ipc(tmp_path)
    monkeypatch.setattr(cli, "_iter_retention_candidates", lambda _root: (_ for _ in ()).throw(RuntimeError("boom")))
    result = cli.cleanup_error_reports(ipc, force=True)
    assert result["deleted_age"] == 0
    assert isinstance(result, dict)
