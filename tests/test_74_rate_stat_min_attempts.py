"""Regression tests for #74: rate-stat player leaderboards apply a minimum-attempts qualifier before ranking.

"Top 5 QBs by passer rating" must not rank a 2-attempt backup or a 1-play trick pass above the starters.
Hermetic: synthetic plays only, no network, no files outside tmp_path.
"""
import pytest

import pro_football_slm as cli

SEASON = 2024


def _bridge(tmp_path):
    return cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline")


def _pass(n, game, week, team, opp, qb, complete=True, yards=8, td=0, intc=0):
    return {
        "play_id": n, "game_id": game, "season": SEASON, "week": week, "posteam": team, "defteam": opp,
        "play_type": "pass", "pass_attempt": 1, "rush_attempt": 0, "complete_pass": 1 if complete else 0,
        "yards_gained": yards if complete else 0, "passer_player_name": qb, "receiver_player_name": "R.Catcher",
        "pass_touchdown": td, "touchdown": td, "interception": intc, "epa": 0.2 if complete else -0.4,
        "desc": f"{qb} pass to R.Catcher for {yards if complete else 0} yards",
    }


def _rush(n, game, week, team, opp, rusher, yards=4):
    return {
        "play_id": n, "game_id": game, "season": SEASON, "week": week, "posteam": team, "defteam": opp,
        "play_type": "run", "pass_attempt": 0, "rush_attempt": 1, "complete_pass": 0, "yards_gained": yards,
        "rusher_player_name": rusher, "epa": 0.05, "desc": f"{rusher} up the middle for {yards} yards",
    }


def _season(tmp_path, games=17, starter_att=30, backup_att=2, carries=15):
    """KC and BUF play `games` games each; starters throw `starter_att` passes per game (2 of 3 complete)."""
    raw = []
    n = 0
    for week in range(1, games + 1):
        for team, opp, qb, rb in (("KC", "DEN", "S.Starter", "R.Back"), ("BUF", "MIA", "O.Other", "B.Runner")):
            game = f"{SEASON}_{week:02d}_{team}_{opp}"
            for i in range(starter_att):
                n += 1
                raw.append(_pass(n, game, week, team, opp, qb, complete=(i % 3 != 0), yards=9, td=1 if i == 0 else 0))
            for _ in range(carries):
                n += 1
                raw.append(_rush(n, game, week, team, opp, rb, yards=4))
    # KC backup: perfect passes in garbage time; BUF trick play: one 60-yard WR touchdown pass and one WR carry
    for i in range(backup_att):
        n += 1
        raw.append(_pass(n, f"{SEASON}_01_KC_DEN", 1, "KC", "DEN", "B.Backup", complete=True, yards=25, td=1))
    n += 1
    raw.append(_pass(n, f"{SEASON}_02_BUF_MIA", 2, "BUF", "MIA", "T.Trick", complete=True, yards=60, td=1))
    n += 1
    raw.append(_rush(n, f"{SEASON}_02_BUF_MIA", 2, "BUF", "MIA", "G.Gadget", yards=60))
    bridge = _bridge(tmp_path)
    return [bridge._normalize_row(r, i) for i, r in enumerate(raw, 1)]


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


@pytest.fixture
def plays(tmp_path):
    return _season(tmp_path)


def _names(board):
    return [r["entity"] for r in board]


def test_default_qualifier_values_scale_with_team_games():
    assert cli.default_min_attempts(14.0, 17) == 238   # NFL passer-rating qualifier over 17 games
    assert cli.default_min_attempts(6.25, 16) == 100   # NFL rushing qualifier over 16 games
    assert cli.default_min_attempts(14.0, 4) == 56
    assert cli.default_min_attempts(14.0, 1) == 14
    assert cli.default_min_attempts(6.25, 1) == 10      # small-window floor
    assert cli.default_min_attempts(1.875, 2) == 10
    assert cli.default_min_attempts(14.0, 0) == 10


def test_qualifier_spec_only_for_player_rate_stats():
    assert cli.rate_stat_qualifier_spec("passer_rating", "qb") == ("pass_attempts", 14.0)
    assert cli.rate_stat_qualifier_spec("yards_per_rush", "rusher") == ("rush_attempts", 6.25)
    assert cli.rate_stat_qualifier_spec("epa_per_play", "receiver") == ("plays", 1.875)
    assert cli.rate_stat_qualifier_spec("passer_rating", "team") is None
    assert cli.rate_stat_qualifier_spec("passer_rating", "defteam") is None
    assert cli.rate_stat_qualifier_spec("passing_yards", "qb") is None
    assert cli.rate_stat_qualifier_spec("takeaways", "player") is None


def test_backup_and_one_play_passer_no_longer_lead_passer_rating(engine, plays):
    unqualified = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", min_attempts=0)
    assert _names(unqualified)[:2] in (["B.Backup", "T.Trick"], ["T.Trick", "B.Backup"])  # the #74 bug
    board = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb")
    assert set(_names(board)) == {"S.Starter", "O.Other"}
    q = engine.last_leaderboard_qualifier
    assert q["metric"] == "pass_attempts" and q["min_attempts"] == 238 and q["team_games"] == 17
    assert q["source"] == "default" and q["per_game"] == 14.0 and q["excluded"] == 2


@pytest.mark.parametrize("stat", ["completion_pct", "yards_per_attempt", "any_a", "touchdown_rate", "epa_per_play"])
def test_other_rate_stats_are_qualified_too(engine, plays, stat):
    board = engine.evaluate_stat_leaderboard(stat, plays, group_override="qb")
    assert "B.Backup" not in _names(board) and "T.Trick" not in _names(board)
    assert engine.last_leaderboard_qualifier is not None


def test_rushers_use_carries_per_game(engine, plays):
    board = engine.evaluate_stat_leaderboard("yards_per_rush", plays, group_override="rusher")
    assert "G.Gadget" not in _names(board) and set(_names(board)) == {"R.Back", "B.Runner"}
    q = engine.last_leaderboard_qualifier
    assert q["metric"] == "rush_attempts" and q["min_attempts"] == 107  # ceil(6.25 * 17)


def test_four_game_window_scales_the_qualifier(engine, tmp_path):
    plays = _season(tmp_path, games=4, starter_att=30, backup_att=20)
    board = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb")
    assert engine.last_leaderboard_qualifier["min_attempts"] == 56 and engine.last_leaderboard_qualifier["team_games"] == 4
    assert "B.Backup" not in _names(board)  # 20 attempts < 56
    plays = _season(tmp_path, games=4, starter_att=30, backup_att=60)
    board = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb")
    assert _names(board)[0] == "B.Backup"  # 60 perfect attempts qualify and lead


def test_week_filter_scales_to_one_game(engine, plays):
    board = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", week=1)
    assert engine.last_leaderboard_qualifier["team_games"] == 1
    assert engine.last_leaderboard_qualifier["min_attempts"] == 14
    assert "B.Backup" not in _names(board) and "S.Starter" in _names(board)


def test_sparse_window_still_shows_its_busiest_passers(engine, tmp_path):
    # 4 games x 10 attempts = 40 < 56: the default never empties a board, it caps at half the leader's volume
    plays = _season(tmp_path, games=4, starter_att=10, backup_att=2)
    board = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb")
    assert set(_names(board)) == {"S.Starter", "O.Other"}
    assert engine.last_leaderboard_qualifier["min_attempts"] == 20


def test_override_up_down_and_zero(engine, plays):
    low = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", min_attempts=2)
    assert _names(low)[0] == "B.Backup" and "T.Trick" not in _names(low)
    assert engine.last_leaderboard_qualifier["source"] == "override"
    assert engine.last_leaderboard_qualifier["min_attempts"] == 2
    high = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", min_attempts=1000)
    assert high == []
    off = engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", min_attempts=0)
    assert len(off) == 4 and engine.last_leaderboard_qualifier is None


@pytest.mark.parametrize("bad", [-1, 1.5, "10", True])
def test_invalid_min_attempts_is_rejected(engine, plays, bad):
    with pytest.raises(ValueError):
        engine.evaluate_stat_leaderboard("passer_rating", plays, group_override="qb", min_attempts=bad)


@pytest.mark.parametrize("stat,group", [("passing_yards", "qb"), ("pass_touchdowns", "qb"), ("rushing_yards", "rusher"),
                                        ("takeaways", "defteam"), ("passer_rating", "team")])
def test_count_stats_and_team_groupings_are_unaffected(engine, plays, stat, group):
    default = engine.evaluate_stat_leaderboard(stat, plays, group_override=group)
    assert engine.last_leaderboard_qualifier is None
    assert default == engine.evaluate_stat_leaderboard(stat, plays, group_override=group, min_attempts=0)


def test_named_player_query_is_not_hidden(engine, plays):
    parsed = {"intent": "stat_query", "query": "passer rating", "stat_name": "passer_rating", "group_by": "qb",
              "season": SEASON, "player": "B.Backup"}
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    assert "B.Backup" in out and "Qualifier:" not in out


def test_qualifier_is_shown_in_the_table(engine, plays):
    out = cli.strip_ansi(cli.render_general_stat_view(engine, plays, "passer_rating", SEASON, group_override="qb",
                                                      view_mode="table"))
    assert "Qualifier: min 238 pass attempts (14 per team game); 2 below the minimum not ranked" in out
    assert "B.Backup" not in out
    out = cli.strip_ansi(cli.render_general_stat_view(engine, plays, "passing_yards", SEASON, group_override="qb",
                                                      view_mode="table"))
    assert "Qualifier:" not in out


@pytest.mark.parametrize("query,expected", [
    ("top 5 qbs by passer rating 2024 min 100 attempts", 100),
    ("best yards per rush 2024 at least 50 carries", 50),
    ("top 5 qbs by passer rating 2024 minimum 0 attempts", 0),
    ("top 5 qbs by passer rating 2024", None),
])
def test_nl_min_attempts_phrase(engine, query, expected):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off", default_season=SEASON)
    assert parsed["intent"] == "stat_query"
    assert parsed.get("min_attempts") == expected


@pytest.mark.parametrize("argv,expected", [
    (["--min-attempts", "0"], 0),
    (["--min-attempts", "150"], 150),
    ([], None),
])
def test_stat_command_min_attempts_flag(monkeypatch, capsys, argv, expected):
    seen = []
    orig = cli.StatEngine.evaluate_stat_leaderboard

    def spy(self, *a, **k):
        seen.append(k.get("min_attempts"))
        return orig(self, *a, **k)

    monkeypatch.setattr(cli.StatEngine, "evaluate_stat_leaderboard", spy)
    cli.main(["stat", "passer_rating", "--season", "2025", "--seasons", "2025", "--engine", "offline", "--no-color", *argv])
    assert seen and seen[0] == expected
    capsys.readouterr()
