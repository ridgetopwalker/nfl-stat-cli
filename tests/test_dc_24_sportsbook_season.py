"""Issue #24: sportsbook ratings must be driven only by the requested season (synthetic plays only)."""
import pytest

import pro_football_slm as cli
from pro_football_slm import sportsbook as sb


def _play(season, week, home, away, posteam, epa, home_score, away_score, play_id):
    defteam = away if posteam == home else home
    return {
        "season": season, "week": week, "qtr": 1, "play_id": play_id,
        "game_id": f"{season}_{week:02d}_{away}_{home}",
        "posteam": posteam, "defteam": defteam, "epa": epa, "series_success": 1,
        "home_score": home_score, "away_score": away_score,
    }


@pytest.fixture
def two_seasons():
    plays = []
    # 2024: HHH dominates (+EPA), AAA is bad
    plays.append(_play(2024, 1, "HHH", "AAA", "HHH", 0.50, 30, 10, 1))
    plays.append(_play(2024, 1, "HHH", "AAA", "AAA", -0.50, 30, 10, 2))
    # 2025: reversed
    plays.append(_play(2025, 1, "HHH", "AAA", "HHH", -0.20, 10, 24, 1))
    plays.append(_play(2025, 1, "HHH", "AAA", "AAA", 0.20, 10, 24, 2))
    return plays


def _only(plays, season):
    return [p for p in plays if p["season"] == season]


def test_power_ratings_use_only_requested_season(two_seasons):
    r25 = sb.compute_team_power_ratings(two_seasons, 2025)
    assert r25["HHH"]["off_epa"] == pytest.approx(-0.20)
    assert r25["AAA"]["off_epa"] == pytest.approx(0.20)
    assert r25["HHH"]["games_played"] == 1
    assert r25["AAA"]["power_rating"] > r25["HHH"]["power_rating"]

    r24 = sb.compute_team_power_ratings(two_seasons, 2024)
    assert r24["HHH"]["off_epa"] == pytest.approx(0.50)
    assert r24["HHH"]["power_rating"] > r24["AAA"]["power_rating"]


def test_mixed_season_input_matches_single_season_input(two_seasons):
    for season in (2024, 2025):
        assert sb.compute_team_power_ratings(two_seasons, season) == sb.compute_team_power_ratings(_only(two_seasons, season), season)


def test_rendered_board_and_power_ratings_ignore_other_seasons(two_seasons):
    for season in (2024, 2025):
        only = _only(two_seasons, season)
        assert cli.strip_ansi(sb.render_sportsbook_board_view(two_seasons, season)) == cli.strip_ansi(sb.render_sportsbook_board_view(only, season))
        assert cli.strip_ansi(sb.render_power_ratings_view(two_seasons, season)) == cli.strip_ansi(sb.render_power_ratings_view(only, season))
        assert cli.strip_ansi(sb.render_underdog_leaderboard_view(two_seasons, season)) == cli.strip_ansi(sb.render_underdog_leaderboard_view(only, season))
        assert cli.strip_ansi(sb.render_game_handicap_dossier_view("HHH", "AAA", two_seasons, season)) == cli.strip_ansi(sb.render_game_handicap_dossier_view("HHH", "AAA", only, season))


def test_season_with_no_plays_yields_no_ratings(two_seasons):
    assert sb.compute_team_power_ratings(two_seasons, 2023) == {}
