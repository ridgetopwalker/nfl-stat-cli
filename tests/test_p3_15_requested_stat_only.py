"""Regression tests for #15: a leaderboard evaluates the requested stat (and its dependencies), not every registered stat."""
import pytest

import nfl_stat_cli as cli

PLAYS = cli.SAMPLE_PBP_PLAYS


@pytest.fixture
def engine(tmp_path):
    eng = cli.StatEngine(storage_dir=tmp_path)
    for name, sdef in cli.EXAMPLE_CUSTOM_STATS.items():
        eng.stats[name] = sdef
    eng.register_custom_stat(
        name="big_gain", title="Big gains", group_by="qb", formula="yards_gained", description="d",
        calculation_explained="c", scope="play", agg="sum", persist=False,
    )
    eng.register_custom_stat(
        name="big_gain_per_play", title="Big per play", group_by="qb", formula="big_gain / plays", description="d",
        calculation_explained="c", persist=False,
    )
    return eng


@pytest.fixture
def full_evaluation(monkeypatch):
    """Reference behaviour: ignore `only` so every registered stat is evaluated, as before the fix."""
    orig = cli.StatEngine.evaluate_all_metrics_for_group

    def full(self, plays, only=None, _closure=None):
        return orig(self, plays, only=None)

    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", full)


def _board(engine, stat, **kw):
    return engine.evaluate_stat_leaderboard(stat, PLAYS, **kw)


def _comparable(rows):
    keep = ("entity", "team", "conf", "position", "value", "plays", "games_played", "yards_per_play", "total_yards",
            "yac_per_play", "epa_per_play", "success_rate_pct", "completion_pct", "games_won", "games_lost")
    return [{k: r[k] for k in keep} for r in rows]


def test_every_stat_gives_the_same_leaderboard_as_full_evaluation(engine, monkeypatch):
    names = list(engine.stats)
    assert len(names) > 40
    fast = {n: _comparable(_board(engine, n)) for n in names}
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig(self, plays, only=None))
    for n in names:
        assert fast[n] == _comparable(_board(engine, n)), n


@pytest.mark.parametrize("group", ["qb", "posteam", "defteam", "play_concept"])
def test_group_overrides_match_full_evaluation(engine, monkeypatch, group):
    fast = _comparable(_board(engine, "big_gain_per_play", group_override=group))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig(self, plays, only=None))
    assert fast == _comparable(_board(engine, "big_gain_per_play", group_override=group))


def test_dependency_closure_follows_formulas_filters_and_chains(engine):
    closure = engine.stat_dependency_closure(["big_gain_per_play"])
    assert {"big_gain_per_play", "big_gain"} <= closure
    assert not {"qb_impact_score", "passer_rating", "qb_meaningful_win"} & closure
    assert "qb_impact_score" in engine.stat_dependency_closure(["qb_meaningful_win"])
    assert engine.stat_dependency_closure(["no_such_stat"]) == set()
    engine.stats["filtered"] = cli.StatDefinition(
        name="filtered", title="f", category="custom", group_by="qb", formula="plays", description="", calculation_explained="",
        filter_expr="big_gain > 0", scope="season", agg="formula", dependencies=["plays"],
    )
    assert "big_gain" in engine.stat_dependency_closure(["filtered"])


def test_only_requested_stats_are_evaluated(engine, monkeypatch):
    calls = []
    orig = cli.safe_eval_formula
    monkeypatch.setattr(cli, "safe_eval_formula", lambda expr, ctx: calls.append(expr) or orig(expr, ctx))
    _board(engine, "yards_per_play")
    fast = len(calls)
    calls.clear()
    orig_all = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig_all(self, plays, only=None))
    _board(engine, "yards_per_play")
    full = len(calls)
    assert 0 < fast and fast * 3 <= full, (fast, full)


def test_unrelated_stats_are_not_evaluated(engine, monkeypatch):
    seen = []
    orig = cli.safe_eval_formula
    monkeypatch.setattr(cli, "safe_eval_formula", lambda expr, ctx: seen.append(expr) or orig(expr, ctx))
    _board(engine, "big_gain_per_play")
    assert engine.stats["big_gain"].formula in seen
    for unrelated in ("qb_impact_score", "qb_meaningful_win", "passer_rating", "explosive_pass_rate"):
        assert engine.stats[unrelated].formula not in seen, unrelated


def test_a_broken_unrelated_stat_no_longer_affects_the_requested_one(engine):
    engine.stats["broken"] = cli.StatDefinition(
        name="broken", title="b", category="custom", group_by="qb", formula="undefined_thing + 1", description="",
        calculation_explained="", scope="season", agg="formula", dependencies=[],
    )
    with_broken = _comparable(_board(engine, "yards_per_play"))
    del engine.stats["broken"]
    assert with_broken == _comparable(_board(engine, "yards_per_play"))


def test_qb_record_fields_are_none_unless_the_stat_needs_them(engine):
    rows = _board(engine, "yards_per_play", group_override="qb")
    assert rows and all(r["qb_impact_score"] is None and r["qb_meaningful_win"] is None and r["no_decisions"] is None for r in rows)
    rows = _board(engine, "qb_impact_score", group_override="qb", also=("qb_meaningful_win", "qb_meaningful_loss"))
    assert all(isinstance(r["qb_meaningful_win"], int) and isinstance(r["no_decisions"], int) for r in rows)


def test_qb_wins_view_still_shows_records(tmp_path):
    eng = cli.StatEngine(storage_dir=tmp_path)
    out = cli.strip_ansi(cli.render_qb_meaningful_wins_view(eng, PLAYS, 2024, None, view_mode="table"))
    assert "None" not in out and "ND" in out


def test_qb_wins_view_matches_full_evaluation(tmp_path, monkeypatch):
    eng = cli.StatEngine(storage_dir=tmp_path)
    fast = cli.strip_ansi(cli.render_qb_meaningful_wins_view(eng, PLAYS, 2024, None, view_mode="table"))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig(self, plays, only=None))
    assert fast == cli.strip_ansi(cli.render_qb_meaningful_wins_view(eng, PLAYS, 2024, None, view_mode="table"))


def test_general_view_output_is_unchanged(engine, monkeypatch):
    fast = cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "epa_per_play", 2024, view_mode="table"))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig(self, plays, only=None))
    assert fast == cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "epa_per_play", 2024, view_mode="table"))


def test_default_call_without_only_still_evaluates_everything(engine):
    metrics = engine.evaluate_all_metrics_for_group(PLAYS[:10])
    assert set(engine.stats) <= set(metrics)


def _mk(name, formula, scope="season", agg="formula", filter_expr="", deps=()):
    return cli.StatDefinition(
        name=name, title=name, category="custom", group_by="qb", formula=formula, description="", calculation_explained="",
        filter_expr=filter_expr, scope=scope, agg=agg, dependencies=list(deps),
    )


def _parity(engine, monkeypatch, stat):
    fast = _comparable(_board(engine, stat))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    with monkeypatch.context() as m:
        m.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None, _closure=None: orig(self, plays, only=None))
        full = _comparable(_board(engine, stat))
    assert fast == full
    return fast


def test_filter_expr_play_fields_keep_parity_and_stat_refs_enter_the_closure(engine, monkeypatch):
    engine.stats["gated_yards"] = _mk("gated_yards", "total_yards", filter_expr="yards_gained > 0", deps=["total_yards"])
    _parity(engine, monkeypatch, "gated_yards")
    engine.stats["gate"] = _mk("gate", "ifelse(plays > 2, 1.0, 0.0)")
    engine.stats["refs_gate"] = _mk("refs_gate", "total_yards", filter_expr="gate > 0", deps=["total_yards"])
    assert "gate" in engine.stat_dependency_closure(["refs_gate"])


def test_game_scoped_stat_depending_on_play_and_season_stats_keeps_parity(engine, monkeypatch):
    engine.stats["g_big"] = _mk("g_big", "big_gain / nz(plays, 1)", scope="game", agg="sum", deps=["big_gain", "plays"])
    engine.stats["season_of_game"] = _mk("season_of_game", "g_big * 2", deps=["g_big"])
    rows = _parity(engine, monkeypatch, "season_of_game")
    assert rows


def test_registered_stat_shadowing_a_base_metric_keeps_parity(engine, monkeypatch):
    engine.stats["pass_attempts"] = _mk("pass_attempts", "plays * 2")
    engine.stats["uses_shadow"] = _mk("uses_shadow", "pass_attempts / 2")
    assert "pass_attempts" in engine.stat_dependency_closure(["uses_shadow"])
    _parity(engine, monkeypatch, "uses_shadow")


def test_stale_dependency_list_does_not_lose_a_referenced_stat(engine, monkeypatch):
    engine.stats["loaded"] = _mk("loaded", "big_gain / nz(plays, 1)", deps=[])  # as if loaded from JSON with empty dependencies
    assert "big_gain" in engine.stat_dependency_closure(["loaded"])
    _parity(engine, monkeypatch, "loaded")


def test_unparseable_formula_falls_back_to_every_stat(engine):
    engine.stats["weird"] = _mk("weird", "((")
    assert engine.stat_dependency_closure(["weird"]) == set(engine.stats)
