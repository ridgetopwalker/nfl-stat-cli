"""Issue #22: D/ST touchdowns come from defensive/special-teams events only, and profile == leaderboard.

Synthetic plays only. Game id format is season_week_AWAY_HOME.
"""
import pytest

from nfl_stat_cli import fantasy as fa

GID = "2025_01_OFF_DDD"


def _play(order, **kw):
    base = {
        "game_id": GID, "season": 2025, "week": 1, "play_id": order, "posteam": "OFF", "defteam": "DDD",
        "home_score": 0, "away_score": 0, "sack": 0, "interception": 0, "fumble_lost": 0, "safety": 0,
        "blocked_kick": 0, "touchdown": 0, "pass_touchdown": 0, "rush_touchdown": 0, "desc": "",
    }
    base.update(kw)
    return base


def _interception(order):
    return _play(order, interception=1, pass_attempt=1, desc="pass intercepted by DDD at the 40")


def _offensive_pass_td(order):
    return _play(order, touchdown=1, pass_touchdown=1, pass_attempt=1, desc="pass to a receiver for 20 yards, TOUCHDOWN")


def _offensive_rush_td(order):
    return _play(order, touchdown=1, rush_touchdown=1, rush_attempt=1, desc="run for 3 yards, TOUCHDOWN")


def _both(plays):
    profile = fa.compute_team_dst_fantasy_profile("DDD", plays)
    # OFF / DDD are fake abbreviations: the profile resolver passes unknown abbreviations through unchanged
    board = next((r for r in fa.compute_team_dst_fantasy_leaders(plays) if r["team"] == "DDD"), None)
    assert board is not None, "DDD missing from the leaderboard"
    return profile, board


@pytest.mark.parametrize("later_offensive_tds", [0, 1, 2, 3])
def test_later_offensive_tds_never_become_defensive_tds(later_offensive_tds):
    plays = [_interception(1)]
    for i in range(later_offensive_tds):
        plays.append(_offensive_pass_td(10 + 2 * i) if i % 2 == 0 else _offensive_rush_td(10 + 2 * i))
    profile, board = _both(plays)
    assert profile["interceptions"] == 1
    assert profile["defensive_tds"] == 0
    assert board["defensive_tds"] == 0


@pytest.mark.parametrize("early_event", [
    {"fumble_lost": 1, "desc": "fumble lost, recovered by defense"},
    {"blocked_kick": 1, "desc": "punt blocked by DDD"},
    {"interception": 1, "desc": "pass intercepted by DDD"},
])
def test_any_earlier_takeaway_or_block_does_not_taint_later_offensive_tds(early_event):
    plays = [_play(1, **early_event), _offensive_pass_td(2), _offensive_rush_td(3)]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 0
    assert board["defensive_tds"] == 0


def test_real_defensive_touchdowns_are_still_counted_by_both_paths():
    plays = [
        _play(1, interception=1, touchdown=1, desc="pass intercepted by DDD, returned for TOUCHDOWN"),
        _play(2, fumble_lost=1, touchdown=1, desc="fumble recovered by defense, TOUCHDOWN"),
        _play(3, blocked_kick=1, touchdown=1, desc="punt blocked by DDD, returned for TOUCHDOWN"),
        _offensive_pass_td(4),
    ]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 3
    assert board["defensive_tds"] == 3


def test_profile_and_leaderboard_agree_on_every_total():
    plays = [
        _play(1, sack=1, desc="QB sacked"),
        _interception(2),
        _offensive_pass_td(3),
        _play(4, interception=1, touchdown=1, desc="pass intercepted, returned for TOUCHDOWN"),
        _offensive_rush_td(5),
        _play(6, safety=1, desc="safety"),
    ]
    for p in plays:
        p["home_score"], p["away_score"] = 10, 14
    profile, board = _both(plays)
    for key in ("sacks", "interceptions", "fumbles_recovered", "safeties", "blocked_kicks", "defensive_tds", "points_allowed"):
        assert profile[key] == board[key], key
    assert profile["fantasy_points"] == pytest.approx(board["points_ppr"])
    assert profile["defensive_tds"] == 1


def test_touchdown_credited_to_the_other_team_is_not_a_defensive_td():
    plays = [_play(1, interception=1, touchdown=1, td_team="OFF", desc="pass intercepted by DDD")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 0
    assert board["defensive_tds"] == 0


def test_td_team_equal_to_the_defence_still_counts():
    plays = [_play(1, interception=1, touchdown=1, td_team="DDD", desc="pass intercepted, TOUCHDOWN")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 1 and board["defensive_tds"] == 1


def test_punt_or_kick_return_touchdown_counts_with_and_without_td_team():
    for extra in ({}, {"td_team": "DDD"}):
        plays = [_play(1, play_type="punt", touchdown=1, desc="punt returned for TOUCHDOWN", **extra)]
        profile, board = _both(plays)
        assert profile["defensive_tds"] == 1 and board["defensive_tds"] == 1, extra


def test_offensive_td_with_td_team_set_never_counts_even_without_takeaway_flags():
    plays = [_play(1, touchdown=1, pass_touchdown=1, td_team="OFF", desc="TOUCHDOWN")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 0 and board["defensive_tds"] == 0


def test_td_team_in_a_different_abbreviation_does_not_zero_a_real_defensive_td():
    # td_team spelled differently from defteam (alias) must not suppress a pick-six: only td_team == posteam is "offence scored"
    plays = [_play(1, interception=1, touchdown=1, td_team="DDX", desc="pass intercepted, TOUCHDOWN")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 1 and board["defensive_tds"] == 1


@pytest.mark.parametrize("bad", [None, float("nan"), "", "NA"])
def test_missing_flag_values_do_not_crash_the_classifier(bad):
    # non-zero scores keep the (separate, unchanged) points-allowed fallback from reading the touchdown column
    plays = [_play(1, sack=bad, interception=bad, fumble_lost=bad, safety=bad, touchdown=bad, home_score=7,
                   away_score=7, desc="plain play")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 0 and board["defensive_tds"] == 0


@pytest.mark.parametrize("missing", [None, float("nan"), "", "NA"])
def test_missing_team_fields_do_not_suppress_a_real_defensive_td(missing):
    # td_team and posteam both absent must not compare equal and read as "the offence scored"
    plays = [_play(1, interception=1, touchdown=1, td_team=missing, posteam=missing,
                   desc="pass intercepted, returned for TOUCHDOWN")]
    profile, board = _both(plays)
    assert profile["defensive_tds"] == 1 and board["defensive_tds"] == 1


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 2, 1, 0), (1, 3, 0, 2), (2, 0, 3, 1)])
def test_totals_do_not_depend_on_play_order(order):
    # one pick-six plus offensive TDs: the result must be identical however the plays are ordered
    pool = [
        _play(1, interception=1, touchdown=1, td_team="DDD", desc="pass intercepted, returned for TOUCHDOWN"),
        _offensive_pass_td(2), _offensive_rush_td(3), _offensive_pass_td(4),
    ]
    for p in pool:
        p["home_score"], p["away_score"] = 10, 14
    profile, board = _both([pool[i] for i in order])
    assert profile["defensive_tds"] == board["defensive_tds"] == 1
    assert profile["fantasy_points"] == pytest.approx(board["points_ppr"])
