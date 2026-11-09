"""Issue #25: modeled totals must fall as a defence gets stronger (lower EPA allowed). Synthetic data only."""
import pytest

from nfl_stat_cli import sportsbook as sb


def _ratings(off, def_allowed):
    return {"power_rating": 0.0, "off_epa": off, "def_epa": def_allowed}


def _total(home_off=0.0, home_def=0.0, away_off=0.0, away_def=0.0):
    pr = {"HHH": _ratings(home_off, home_def), "AAA": _ratings(away_off, away_def)}
    return sb.handicap_matchup("HHH", "AAA", pr)["total"]


def test_stronger_defences_lower_the_total():
    strong = _total(home_def=-0.10, away_def=-0.10)   # both defences allow little EPA
    average = _total()
    weak = _total(home_def=0.10, away_def=0.10)        # both defences allow a lot
    assert strong < average < weak


@pytest.mark.parametrize("side", ["home_def", "away_def"])
def test_each_defence_is_monotonic_on_its_own(side):
    totals = [_total(**{side: d}) for d in (-0.15, -0.05, 0.05, 0.15)]
    assert totals == sorted(totals)
    assert totals[0] < totals[-1]


@pytest.mark.parametrize("side", ["home_off", "away_off"])
def test_better_offences_still_raise_the_total(side):
    totals = [_total(**{side: o}) for o in (-0.10, 0.0, 0.10)]
    assert totals == sorted(totals)
    assert totals[0] < totals[-1]


def test_total_is_symmetric_between_offence_and_opposing_defence_effects():
    # A +0.1 EPA offence and a +0.1 EPA-allowed defence move the total by the same amount
    assert _total(home_off=0.1) == _total(away_def=0.1)


def test_end_to_end_ratings_to_total_respects_defence_strength():
    def play(team, opp, epa, pid, season=2025):
        return {"season": season, "week": 1, "qtr": 1, "play_id": pid, "game_id": f"{season}_01_{opp}_{team}",
                "posteam": team, "defteam": opp, "epa": epa, "series_success": 0,
                "home_score": 0, "away_score": 0}

    # STR's defence allows -0.3 EPA/play to OFF; WEK's allows +0.3. Their own offences are neutral (0.0).
    plays = [
        play("OFF", "STR", -0.3, 1), play("STR", "XXX", 0.0, 2),
        play("OFF", "WEK", 0.3, 3), play("WEK", "XXX", 0.0, 4),
    ]
    ratings = sb.compute_team_power_ratings(plays, 2025)
    assert ratings["STR"]["def_epa"] < ratings["WEK"]["def_epa"]
    vs_strong = sb.handicap_matchup("OFF", "STR", ratings)["total"]
    vs_weak = sb.handicap_matchup("OFF", "WEK", ratings)["total"]
    assert vs_strong < vs_weak
