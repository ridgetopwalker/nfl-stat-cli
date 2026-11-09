"""Regression tests: user-supplied export paths are confined to the exports directory (issue #2)."""
import os
import sys

import pytest

import nfl_stat_cli as cli


@pytest.fixture
def export_env(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setenv("NFL_STAT_EXPORT_DIR", str(exports))
    monkeypatch.setattr(cli, "LAST_RESULT_RECORDS", [{"player": "A", "yards": 10}])
    monkeypatch.setattr(cli, "LAST_RENDERED_TABLE", None)
    monkeypatch.setattr(cli, "LAST_RAW_OUTPUT", "")
    return exports


@pytest.mark.parametrize("bad", [
    "../x.csv",
    "../../tmp/out.csv",
    "a/../../x.json",
    "a\\..\\..\\x.json",
    "/tmp/out.json",
    "\\\\server\\share\\x.csv",
    "C:\\Users\\x\\out.csv",
    "~/out.csv",
    "",
    "   ",
    "..",
    "out.txt",
    "out.sh",
    "bad\x00name.csv",
    "a\x1b[31m.csv",
    "x.\x1b]0;t\x07json",
    "line\nbreak.csv",
    "cr\r.csv",
    "evil\u202egnp.csv",
    "zero\u200bwidth.csv",
    "sep\u2028x.csv",
])
def test_resolve_export_path_rejects_unsafe(tmp_path, bad):
    with pytest.raises(cli.ExportPathError):
        cli.resolve_export_path(bad, base_dir=tmp_path)


def test_resolve_export_path_accepts_and_confines(tmp_path):
    base = tmp_path.resolve()
    assert cli.resolve_export_path("out.csv", base_dir=tmp_path) == base / "out.csv"
    assert cli.resolve_export_path("out", base_dir=tmp_path) == base / "out.csv"
    assert cli.resolve_export_path("out", base_dir=tmp_path, default_suffix=".json") == base / "out.json"
    assert cli.resolve_export_path("./sub/dir/Out.JSON", base_dir=tmp_path) == base / "sub" / "dir" / "Out.JSON"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_resolve_export_path_rejects_symlink_escape(tmp_path):
    base = tmp_path / "exports"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, base / "link")
    with pytest.raises(cli.ExportPathError):
        cli.resolve_export_path("link/x.csv", base_dir=base)
    # symlinked file pointing outside is also rejected
    (outside / "target.csv").write_text("x")
    os.symlink(outside / "target.csv", base / "file.csv")
    with pytest.raises(cli.ExportPathError):
        cli.resolve_export_path("file.csv", base_dir=base)


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


def _run(engine, query):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off")
    return parsed, cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, []))


def test_nl_export_traversal_is_blocked_and_nothing_written(engine, export_env, tmp_path):
    parsed, out = _run(engine, "export data to ../../escaped.csv")
    assert parsed["intent"] == "export_data"
    assert "Export blocked" in out
    assert not list(tmp_path.rglob("escaped.csv"))


def test_nl_export_absolute_path_is_blocked(engine, export_env, tmp_path):
    target = tmp_path / "abs_out.json"
    _, out = _run(engine, f"export data to {target.as_posix()}")
    assert "Export blocked" in out
    assert not target.exists()


def test_nl_export_stats_traversal_is_blocked(engine, export_env, tmp_path):
    parsed, out = _run(engine, "export stats to ../../stats_escape.json")
    assert parsed["intent"] == "export_stats"
    assert "Export blocked" in out
    assert not list(tmp_path.rglob("stats_escape.json"))


def test_nl_export_writes_inside_exports_dir(engine, export_env):
    _, out = _run(engine, "export data to result.csv")
    assert "Exported" in out
    assert (export_env / "result.csv").exists()
    _, out2 = _run(engine, "export stats to stats.json")
    assert "Exported custom stats catalog" in out2
    assert (export_env / "stats.json").exists()


def test_nl_export_refuses_overwrite(engine, export_env):
    existing = export_env / "keep.csv"
    existing.write_text("original")
    _, out = _run(engine, "export data to keep.csv")
    assert "Refusing to overwrite" in out
    assert existing.read_text() == "original"


def test_confirm_overwrite_prompts_only_when_interactive(tmp_path, monkeypatch):
    f = tmp_path / "a.csv"
    assert cli._confirm_overwrite(f, interactive=False) is True  # nothing to overwrite
    f.write_text("x")
    assert cli._confirm_overwrite(f, interactive=False) is False
    monkeypatch.setattr(cli, "prompt_input", lambda *_a, **_k: "n")
    assert cli._confirm_overwrite(f, interactive=True) is False
    monkeypatch.setattr(cli, "prompt_input", lambda *_a, **_k: "y")
    assert cli._confirm_overwrite(f, interactive=True) is True


def test_nl_export_interactive_overwrite_prompts(engine, export_env, monkeypatch):
    existing = export_env / "keep.csv"
    existing.write_text("original")
    answers = iter(["n", "y"])
    monkeypatch.setattr(cli, "prompt_input", lambda *_a, **_k: next(answers))
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("export data to keep.csv", engine, slm_model="off")
    out1 = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, [], interactive=True))
    assert "Refusing to overwrite" in out1 and existing.read_text() == "original"
    out2 = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, [], interactive=True))
    assert "Exported" in out2 and existing.read_text() != "original"


@pytest.mark.skipif(sys.platform == "win32", reason="piped TUI stdin")
def test_tui_export_commands_are_confined(tmp_path):
    import subprocess
    from pathlib import Path
    exports = tmp_path / "exports"
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(Path(cli.__file__).resolve().parent.parent), "HOME": str(tmp_path),
                "NFL_STAT_EXPORT_DIR": str(exports), "NO_COLOR": "1"})
    escape_target = tmp_path / "escaped.csv"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--engine", "offline", "--season", "2025", "--slm-model", "off"],
        input=f"epa per play\n/export ../escaped.csv\n/export {escape_target.as_posix()}\n/export ok.csv\n/export-stats ../x.json\n/export-stats cat.json\nquit\n",
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert out.count("Export blocked") == 3
    assert not escape_target.exists() and not (tmp_path / "x.json").exists()
    assert (exports / "ok.csv").exists() and (exports / "cat.json").exists()
