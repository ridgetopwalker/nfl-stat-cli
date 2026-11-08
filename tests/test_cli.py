import importlib.util
from importlib import resources
from pathlib import Path
import subprocess
import sys

import pytest
import nfl_stat_cli as cli


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)


def test_ambiguous_query_needs_no_season_data(engine):
    query = "tell me something unrelated 2024 AFC Chiefs"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off")
    assert parsed["intent"] == "ambiguous"
    assert parsed["query"] == query
    assert parsed["season"] == 2024
    assert parsed["conf"] == "AFC"
    assert parsed["team"] == "KC"
    assert parsed["show_field"] is False
    output = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, []))
    assert "Unsupported or ambiguous query" in output
    assert query in output
    assert "/stats" in output and "/help" in output


@pytest.mark.parametrize("query,intent,stat", [
    ("epa per play", "stat_query", "epa_per_play"),
    ("yards per play", "stat_query", "yards_per_play"),
    ("screen yac", "stat_query", "screen_yards_after_catch"),
    ("passer rating", "stat_query", "passer_rating"),
    ("show Mahomes touchdown play", "specific_play", None),
    ("diagram Goff screen play", "specific_play", None),
    ("qb wins", "qb_wins_report", "qb_impact_score"),
])
def test_recognized_queries(engine, query, intent, stat):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off")
    assert parsed["intent"] == intent
    if stat:
        assert parsed["stat_name"] == stat


@pytest.mark.parametrize("formula,warns", [
    ("passing_yards / pass_attempts", True),
    ("passing_yards / nz(pass_attempts, 1)", False),
    ("ifelse(pass_attempts > 0, passing_yards / pass_attempts, 0)", False),
    ("passing_yards + pass_attempts", False),
])
def test_custom_division_note(engine, tmp_path, formula, warns):
    stat = engine.register_custom_stat("test_ratio", "Test", "qb", formula, "Test", "Explanation")
    note = cli.unguarded_division_warning("a / b")
    assert (note in stat.calculation_explained) is warns
    exported = engine.export_custom_stats_json(tmp_path / "export.json")
    imported = cli.StatEngine(storage_dir=tmp_path / "imported")
    imported.import_custom_stats_json(exported)
    assert imported.stats["test_ratio"].calculation_explained == stat.calculation_explained


def test_package_and_legacy_launcher():
    assert resources.files(cli).joinpath("nflverse_bridge.R").is_file()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("legacy_cli", root / "nfl_stat_cli.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    assert legacy.StatEngine is cli.StatEngine
    assert legacy._safe_div is cli._safe_div
    for args in ([str(root / "nfl_stat_cli.py"), "--help"], ["-m", "nfl_stat_cli", "--help"]):
        result = subprocess.run([sys.executable] + args, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout


def test_custom_stat_example_walkthrough(engine):
    walkthrough = cli.render_custom_stat_example_walkthrough(engine, cli.SAMPLE_PBP_PLAYS, season=2025)
    plain = cli.strip_ansi(walkthrough)
    assert "HOW TO BUILD A CUSTOM STAT" in plain
    assert "MLB-STYLE QB WINS" in plain
    assert "clamp(50 +" in plain
    assert "qb_meaningful_win" in plain
    assert "Meaningful Wins (MW)" in plain


def test_stats_catalog_layout(engine):
    catalog = cli.render_stats_catalog(engine)
    plain = cli.strip_ansi(catalog)
    assert "REGISTERED STATS & ANALYTICS CATALOG" in plain
    assert "Quarterback & Passing Analytics" in plain
    assert "Team & Offensive Efficiency" in plain
    assert "Screen Pass & YAC Analytics" in plain
    assert "epa_per_play" in plain
    assert "passer_rating" in plain
    assert "Formula:" in plain


def test_team_drilldown_view(engine):
    out = cli.render_team_drilldown_view(engine, cli.SAMPLE_PBP_PLAYS, season=2025, team="KC")
    plain = cli.strip_ansi(out)
    assert "TEAM DRILL-DOWN : KANSAS CITY CHIEFS" in plain
    assert "Abbreviation: KC" in plain
    assert "OFFENSIVE EFFICIENCY & PLAY CALLING" in plain
    assert "DEFENSIVE PROFILE" in plain
    assert "PASSING LEADERS:" in plain
    assert "P.Mahomes" in plain
    assert "RECEIVING LEADERS:" in plain
    assert "X.Worthy" in plain

    out_nick = cli.render_team_drilldown_view(engine, cli.SAMPLE_PBP_PLAYS, season=2025, team="Chiefs")
    assert "KANSAS CITY CHIEFS" in cli.strip_ansi(out_nick)


def test_player_drilldown_single_team_auto_select(engine):
    s_plays = cli.plays_for_season(cli.SAMPLE_PBP_PLAYS, 2025)
    teams = cli.get_player_teams(cli.find_player_plays(s_plays, "Mahomes"), "Mahomes")
    assert len(teams) == 1
    assert teams[0] == "KC"

    out = cli.render_player_drilldown_view(engine, cli.SAMPLE_PBP_PLAYS, season=2025, player_name="Mahomes", interactive=False)
    plain = cli.strip_ansi(out)
    assert "PLAYER DRILL-DOWN : P.MAHOMES" in plain
    assert "auto-selected" in plain
    assert "KC (1 team in 2025 — auto-selected)" in plain
    assert "PASSING STATISTICS" in plain
    assert "NFL Passer Rating:" in plain
    assert "SIGNATURE PLAYS FOR P.MAHOMES" in plain


def test_player_drilldown_multi_team(engine):
    synthetic_plays = [
        {"play_id": 901, "season": 2025, "posteam": "KC", "defteam": "BAL", "qb_name": "", "receiver_player_name": "M.Player", "play_type": "pass", "complete_pass": 1, "pass_attempt": 1, "yards_gained": 20.0, "epa": 1.0, "series_success": 1, "desc": "M.Player 20 yd pass"},
        {"play_id": 902, "season": 2025, "posteam": "BUF", "defteam": "MIA", "qb_name": "", "receiver_player_name": "M.Player", "play_type": "pass", "complete_pass": 1, "pass_attempt": 1, "yards_gained": 15.0, "epa": 0.8, "series_success": 1, "desc": "M.Player 15 yd pass"},
    ]
    teams = cli.get_player_teams(synthetic_plays, "M.Player")
    assert len(teams) == 2
    assert "BUF" in teams and "KC" in teams

    out = cli.render_player_drilldown_view(engine, synthetic_plays, season=2025, player_name="M.Player", interactive=False)
    plain = cli.strip_ansi(out)
    assert "Combined All Teams" in plain
    assert "BUF" in plain and "KC" in plain


def test_play_phase_filtering():
    s_plays = cli.plays_for_season(cli.SAMPLE_PBP_PLAYS, 2025)
    offense = cli.filter_plays_by_phase(s_plays, "offense")
    defense = cli.filter_plays_by_phase(s_plays, "defense")
    special_teams = cli.filter_plays_by_phase(s_plays, "special_teams")

    assert len(offense) >= 10
    assert len(defense) >= 2
    assert len(special_teams) >= 2

    ptypes = {p.get("play_type") for p in special_teams}
    assert "field_goal" in ptypes
    assert "punt" in ptypes


def test_cli_subcommands():
    root = Path(__file__).resolve().parents[1]
    res_team = subprocess.run([sys.executable, str(root / "nfl_stat_cli.py"), "team", "KC", "--season", "2025"], capture_output=True, text=True)
    assert res_team.returncode == 0, res_team.stderr
    assert "TEAM DRILL-DOWN : KANSAS CITY CHIEFS" in res_team.stdout

    res_player = subprocess.run([sys.executable, str(root / "nfl_stat_cli.py"), "player", "Mahomes", "--season", "2025"], capture_output=True, text=True)
    assert res_player.returncode == 0, res_player.stderr
    assert "PLAYER DRILL-DOWN : P.MAHOMES" in res_player.stdout
    assert "auto-selected" in res_player.stdout


def test_interactive_tui_and_play_explorer():
    input_text = "\n".join([
        "/team KC",
        "/player Mahomes",
        "/play",
        "1",      # Offense
        "1",      # Play #1
        "1",      # Play Stats
        "3",      # Player Drilldown
        "6",      # Exit Explorer
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "TEAM DRILL-DOWN : KANSAS CITY CHIEFS" in res.stdout
    assert "PLAYER DRILL-DOWN : P.MAHOMES" in res.stdout
    assert "Select Play Phase" in res.stdout
    assert "IN-DEPTH PLAY ANALYTICS" in res.stdout
    assert "auto-selected" in res.stdout
