"""Issue #21: fantasy.py must score each player only in the role they played (synthetic plays only).

Mirrors normalized rows, where ``player_name`` on a pass play is the receiver.
"""
import pytest

from nfl_stat_cli import fantasy as fa

GID = "2025_01_DDD_OFF"
QB, WR, RB = "Q.Alpha", "W.Bravo", "R.Charlie"


def _play(order, **kw):
    base = {
        "game_id": GID, "season": 2025, "week": 1, "play_id": order, "posteam": "OFF", "defteam": "DDD",
        "play_type": "pass", "pass_attempt": 0, "rush_attempt": 0, "complete_pass": 0, "sack": 0,
        "yards_gained": 0.0, "touchdown": 0, "interception": 0, "fumble_lost": 0,
        "qb_name": "", "passer_player_name": "", "receiver_player_name": "", "rusher_player_name": "",
        "player_name": "", "desc": "fixture",
    }
    base.update(kw)
    return base


@pytest.fixture
def plays():
    return [
        # 30-yard TD completion QB -> WR (player_name is the receiver, as in normalized rows)
        _play(1, qb_name=QB, passer_player_name=QB, receiver_player_name=WR, player_name=WR, pass_attempt=1,
              complete_pass=1, yards_gained=30.0, touchdown=1, pass_touchdown=1, reception=1),
        # intercepted pass intended for the WR
        _play(2, qb_name=QB, passer_player_name=QB, receiver_player_name=WR, player_name=WR, pass_attempt=1,
              interception=1),
        # RB run
        _play(3, play_type="run", rusher_player_name=RB, player_name=RB, rush_attempt=1, yards_gained=12.0),
    ]


def _profile(name, plays):
    return fa.compute_player_fantasy_profile(name, plays)


def _board(plays, fmt="ppr"):
    return {r["player"]: r for r in fa.compute_all_fantasy_leaders(plays, scoring_format=fmt)}


# --- single-player profile -----------------------------------------------------------------

def test_receiver_profile_has_no_passing_production(plays):
    prof = _profile(WR, plays)
    assert prof["pass_yards"] == 0
    assert prof["pass_tds"] == 0
    assert prof["interceptions"] == 0
    assert prof["receptions"] == 1
    assert prof["rec_yards"] == 30.0
    assert prof["rec_tds"] == 1
    # 30*0.1 + 6 = 9.0 standard, +1 reception in PPR (not 12.x with QB points)
    assert prof["points_std"] == pytest.approx(9.0)
    assert prof["points_ppr"] == pytest.approx(10.0)


def test_passer_profile_has_no_receiving_or_rushing_production(plays):
    prof = _profile(QB, plays)
    assert prof["pass_yards"] == 30.0
    assert prof["pass_tds"] == 1
    assert prof["interceptions"] == 1
    assert prof["receptions"] == 0 and prof["rec_yards"] == 0 and prof["rec_tds"] == 0
    assert prof["rush_yards"] == 0
    assert prof["points_ppr"] == pytest.approx(30 * 0.04 + 4 - 2)


def test_rusher_profile_is_rushing_only(plays):
    prof = _profile(RB, plays)
    assert prof["rush_yards"] == 12.0 and prof["rush_attempts"] == 1
    assert prof["pass_yards"] == 0 and prof["receptions"] == 0
    assert prof["points_ppr"] == pytest.approx(1.2)


def test_profile_points_equal_leaderboard_points_for_every_player(plays):
    board = _board(plays)
    for name in (QB, WR, RB):
        assert _profile(name, plays)["points_ppr"] == pytest.approx(board[name]["points_ppr"]), name


# --- plays that only carry player_name -------------------------------------------------------

def test_bare_player_name_gets_exactly_one_role_on_a_completion():
    bare = [_play(1, player_name=WR, pass_attempt=1, complete_pass=1, yards_gained=30.0, touchdown=1, pass_touchdown=1)]
    prof = _profile(WR, bare)
    assert prof["pass_yards"] == 0 and prof["pass_tds"] == 0
    assert prof["rec_yards"] == 30.0
    row = _board(bare)[WR]
    assert row["pass_yards"] == 0 and row["pass_tds"] == 0
    assert row["rec_yards"] == 30.0
    # profile and leaderboard agree on the catch itself (both fall back to complete_pass when reception is absent)
    assert prof["receptions"] == row["receptions"] == 1
    assert prof["points_ppr"] == pytest.approx(row["points_ppr"])


@pytest.mark.parametrize("bad", [None, float("nan"), "", "NA"])
def test_bare_player_name_with_missing_flag_values_does_not_crash(bad):
    bare = [_play(1, player_name=WR, reception=bad, complete_pass=bad, rush_attempt=bad, pass_attempt=1,
                  qb_name=float("nan"), yards_gained=5.0)]
    assert _profile(WR, bare)["pass_yards"] == 5.0  # NaN role fields do not suppress the one-role fallback


def test_bare_player_name_on_an_incompletion_is_the_passer_only():
    bare = [_play(1, player_name=QB, pass_attempt=1, interception=1)]
    prof = _profile(QB, bare)
    assert prof["interceptions"] == 1
    assert prof["targets"] == 0


def test_bare_player_name_on_a_run_is_the_rusher():
    bare = [_play(1, play_type="run", player_name=RB, rush_attempt=1, yards_gained=7.0)]
    assert _profile(RB, bare)["rush_yards"] == 7.0
    assert _board(bare)[RB]["rush_yards"] == 7.0


def test_named_receiver_is_not_treated_as_passer_when_passer_fields_are_blank():
    plays = [_play(1, receiver_player_name=WR, player_name=WR, pass_attempt=1, complete_pass=1,
                   yards_gained=30.0, touchdown=1, reception=1)]
    prof = _profile(WR, plays)
    assert prof["pass_yards"] == 0 and prof["pass_tds"] == 0
    row = _board(plays)[WR]
    assert row["pass_yards"] == 0 and row["pass_tds"] == 0
    assert row["rec_yards"] == 30.0


# --- leaderboard ----------------------------------------------------------------------------

def test_leaderboard_scores_match_roles(plays):
    board = _board(plays)
    assert board[WR]["points_ppr"] == pytest.approx(10.0)
    assert board[WR]["pass_yards"] == 0
    assert board[QB]["points_ppr"] == pytest.approx(3.2)
    assert board[QB]["receptions"] == 0


def test_bare_player_name_still_gets_catch_or_carry_when_only_qb_name_is_filled():
    # the fallback is suppressed per role by that role's own field, not by an unrelated populated field
    catch = [_play(1, qb_name=QB, player_name=WR, pass_attempt=1, complete_pass=1, yards_gained=11.0)]
    run = [_play(2, play_type="run", qb_name=QB, player_name=RB, rush_attempt=1, yards_gained=4.0)]
    assert _profile(WR, catch)["rec_yards"] == 11.0 and _profile(WR, catch)["pass_yards"] == 0
    assert _board(catch)[WR]["rec_yards"] == 11.0
    assert _profile(RB, run)["rush_yards"] == 4.0
    assert _board(run)[RB]["rush_yards"] == 4.0
    # a bare name on an incomplete pass with a QB present is not the passer
    miss = [_play(3, qb_name=QB, player_name=WR, pass_attempt=1)]
    assert _profile(WR, miss)["pass_yards"] == 0 and _profile(WR, miss)["interceptions"] == 0


@pytest.mark.parametrize("bad", [None, float("nan"), "", "NA"])
def test_leaderboard_treats_nan_role_fields_as_blank(bad):
    plays = [_play(1, play_type="run", rusher_player_name=bad, passer_player_name=bad, qb_name=bad,
                   receiver_player_name=bad, player_name=RB, rush_attempt=1, yards_gained=6.0,
                   reception=bad, sack=bad)]
    board = _board(plays)
    assert set(board) == {RB}
    assert board[RB]["rush_yards"] == 6.0
