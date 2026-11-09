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

    def full(self, plays, only=None):
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
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None: orig(self, plays, only=None))
    for n in names:
        assert fast[n] == _comparable(_board(engine, n)), n


@pytest.mark.parametrize("group", ["qb", "posteam", "defteam", "play_concept"])
def test_group_overrides_match_full_evaluation(engine, monkeypatch, group):
    fast = _comparable(_board(engine, "big_gain_per_play", group_override=group))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None: orig(self, plays, only=None))
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
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None: orig_all(self, plays, only=None))
    _board(engine, "yards_per_play")
    full = len(calls)
    assert full > 0 and fast * 5 <= full, (fast, full)


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
    assert _comparable(_board(engine, "yards_per_play"))


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
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None: orig(self, plays, only=None))
    assert fast == cli.strip_ansi(cli.render_qb_meaningful_wins_view(eng, PLAYS, 2024, None, view_mode="table"))


def test_general_view_output_is_unchanged(engine, monkeypatch):
    fast = cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "epa_per_play", 2024, view_mode="table"))
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    monkeypatch.setattr(cli.StatEngine, "evaluate_all_metrics_for_group", lambda self, plays, only=None: orig(self, plays, only=None))
    assert fast == cli.strip_ansi(cli.render_general_stat_view(engine, PLAYS, "epa_per_play", 2024, view_mode="table"))


def test_default_call_without_only_still_evaluates_everything(engine):
    metrics = engine.evaluate_all_metrics_for_group(PLAYS[:10])
    assert set(engine.stats) <= set(metrics)
