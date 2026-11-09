"""Regression tests for #28 (zero-division is surfaced, not silent) and #31 (saved stats cannot replace built-ins)."""
import json

import pytest

import nfl_stat_cli as cli

PLAYS = cli.SAMPLE_PBP_PLAYS


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)


# ---------------------------------------------------------------- #28

@pytest.mark.parametrize("expr", ["5 / 0", "5 % 0", "yards_gained / (down - down)", "yards_gained % (down - down)"])
def test_zero_division_and_modulo_are_counted(expr):
    cli.reset_div_zero_events()
    ctx = {"yards_gained": 7.0, "down": 2.0}
    assert cli.safe_eval_formula(expr, ctx) == 0.0
    assert cli.div_zero_event_count() == 1


def test_non_zero_division_and_guarded_formulas_are_not_counted():
    cli.reset_div_zero_events()
    ctx = {"a": 6.0, "b": 4.0, "z": 0.0}
    assert cli.safe_eval_formula("a / b + a % b", ctx) == 3.5
    assert cli.safe_eval_formula("ifelse(z > 0, a / z, 0.0)", ctx) == 0.0
    assert cli.safe_eval_formula("nz(z, 1.0) + a", ctx) == 7.0
    assert cli.div_zero_event_count() == 0


def _register_div_stat(engine, formula="yards_per_play / (plays - plays)"):
    return engine.register_custom_stat(
        name="zdiv", title="Z", group_by="qb", formula=formula, description="d",
        calculation_explained="c", persist=False,
    )


def test_leaderboard_records_zero_division_events(engine):
    _register_div_stat(engine)
    board = engine.evaluate_stat_leaderboard("zdiv", PLAYS)
    assert board and all(r["value"] == 0.0 for r in board)
    assert engine.last_zero_division_events >= len(board)


def test_modulo_by_zero_formula_is_recorded_too(engine):
    _register_div_stat(engine, "yards_per_play % (plays - plays)")
    engine.evaluate_stat_leaderboard("zdiv", PLAYS)
    assert engine.last_zero_division_events > 0


def test_events_reset_between_evaluations(engine):
    _register_div_stat(engine)
    engine.evaluate_stat_leaderboard("zdiv", PLAYS)
    assert engine.last_zero_division_events > 0
    engine.evaluate_stat_leaderboard("yards_per_play", PLAYS)
    assert engine.last_zero_division_events == 0


def test_general_view_shows_warning_for_zero_division_stat(engine):
    _register_div_stat(engine)
    out = cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "zdiv", 2024, view_mode="table"))
    assert "division/modulo by zero" in out or "divisions/modulo by zero" in out
    assert "nz(denominator" in out


def test_general_view_has_no_warning_for_clean_stat(engine):
    out = cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "yards_per_play", 2024, view_mode="table"))
    assert "by zero" not in out and "divisions" not in out


@pytest.fixture
def forced_events(monkeypatch):
    orig = cli.StatEngine.evaluate_stat_leaderboard

    def wrapper(self, *a, **k):
        res = orig(self, *a, **k)
        self.last_zero_division_events = 3
        return res

    monkeypatch.setattr(cli.StatEngine, "evaluate_stat_leaderboard", wrapper)


def test_every_leaderboard_renderer_appends_the_warning(engine, forced_events):
    qb = cli.strip_ansi(cli.render_qb_meaningful_wins_view(engine, PLAYS, 2024, None, view_mode="table"))
    eff = cli.strip_ansi(cli.render_play_efficiency_view(engine, PLAYS, 2024, "AFC", view_mode="table"))
    gen = cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "yards_per_play", 2024, view_mode="table"))
    for out in (qb, eff, gen):
        assert "3 divisions/modulo by zero" in out


def test_player_drilldown_appends_the_warning(engine, forced_events):
    for k in ("qb_impact_score", "qb_meaningful_win", "qb_meaningful_loss"):
        engine.stats[k] = cli.EXAMPLE_CUSTOM_STATS[k]
    qb_name = next(p["qb_name"] for p in PLAYS if p.get("qb_name"))
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, PLAYS, 2024, qb_name, interactive=False))
    assert "3 divisions/modulo by zero" in out


def test_singular_wording():
    assert "1 division/modulo by zero" in cli.strip_ansi(cli.zero_division_note(1))
    assert cli.zero_division_note(0) == ""


# ---------------------------------------------------------------- #31

def _write_state(path, stats):
    path.write_text(json.dumps({"schema_version": "2.0", "stats": stats}), encoding="utf-8")


def _item(name, formula, **extra):
    d = {"name": name, "title": name, "formula": formula, "group_by": "qb", "category": "custom"}
    d.update(extra)
    return d


def test_saved_entry_cannot_replace_builtin(tmp_path):
    built_in_formula = cli.DEFAULT_STATS["yards_per_play"].formula
    _write_state(tmp_path / "custom_stats.json", {"yards_per_play": _item("yards_per_play", "plays * 1000")})
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert eng.stats["yards_per_play"].formula == built_in_formula
    assert eng.stats["yards_per_play"] is cli.DEFAULT_STATS["yards_per_play"]
    assert any("built-in" in w and "yards_per_play" in w for w in eng.load_warnings)
    assert (tmp_path / "custom_stats.json.rejected").exists() or list(tmp_path.glob("*.rejected"))


def test_identical_copy_of_builtin_is_ignored_quietly(tmp_path):
    b = cli.DEFAULT_STATS["yards_per_play"]
    _write_state(tmp_path / "custom_stats.json", {"yards_per_play": _item("yards_per_play", b.formula, filter_expr=b.filter_expr)})
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert eng.load_warnings == []


def test_name_key_mismatch_cannot_smuggle_builtin_override(tmp_path):
    built_in_formula = cli.DEFAULT_STATS["epa_per_play"].formula
    _write_state(tmp_path / "custom_stats.json", {"innocent": _item("epa_per_play", "plays * 0")})
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert eng.stats["epa_per_play"].formula == built_in_formula
    assert "innocent" not in eng.stats
    assert eng.load_warnings


@pytest.mark.parametrize("formula", ["__import__('os').system('x')", "plays.real", "no_such_building_block + 1", "plays / " * 200 + "1"])
def test_invalid_saved_formulas_are_rejected_on_load(tmp_path, formula):
    _write_state(tmp_path / "custom_stats.json", {"bad": _item("bad", formula)})
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert "bad" not in eng.stats
    assert eng.load_warnings


def test_invalid_group_by_or_scope_rejected_on_load(tmp_path):
    _write_state(tmp_path / "custom_stats.json", {
        "g": _item("g", "plays + 1", group_by="not_a_group"),
        "s": _item("s", "plays + 1", scope="galaxy"),
        "ok": _item("ok", "plays + 1"),
    })
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert "g" not in eng.stats and "s" not in eng.stats and "ok" in eng.stats


def test_valid_saved_stats_still_load_and_roundtrip(tmp_path):
    first = cli.StatEngine(storage_dir=tmp_path)
    first.register_custom_stat(
        name="base_stat", title="Base", group_by="qb", formula="yards_per_play + 1",
        description="d", calculation_explained="c",
    )
    first.register_custom_stat(
        name="uses_base", title="Uses", group_by="qb", formula="base_stat * 2",
        description="d", calculation_explained="c",
    )
    second = cli.StatEngine(storage_dir=tmp_path)
    assert second.load_warnings == []
    assert second.stats["uses_base"].category == "custom"
    assert second.stats["uses_base"].dependencies == ["base_stat"]
    assert second.evaluate_stat_leaderboard("uses_base", PLAYS)


def test_saved_stat_dependencies_are_recomputed_not_trusted(tmp_path):
    _write_state(tmp_path / "custom_stats.json", {"d": _item("d", "plays + 1", dependencies=["evil"])})
    eng = cli.StatEngine(storage_dir=tmp_path)
    assert eng.stats["d"].dependencies == ["plays"]


def test_load_warnings_are_printed_to_stderr_by_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".nfl_stat_cli"
    state.mkdir()
    _write_state(state / "custom_stats.json", {"yards_per_play": _item("yards_per_play", "plays * 1000")})
    cli.main(["list-stats", "--no-color"])
    err = capsys.readouterr().err
    assert "built-in" in err and "yards_per_play" in err
