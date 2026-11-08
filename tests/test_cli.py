import importlib.util
from importlib import resources
import json
from pathlib import Path
import subprocess
import sys

import pytest
import nfl_stat_cli as cli


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)


@pytest.fixture
def sample_plays():
    bridge = cli.NFLDataBridge(engine="offline")
    return bridge.load_pbp([2024, 2025])


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
        "1",      # Pass
        "1",      # Quick Game & Slant
        "1",      # Browse by Team
        "1",      # Select Team #1 (KC)
        "1",      # Select Matchup #1 (BAL @ KC)
        "a",      # All Quarters in game
        "1",      # Select Play #1
        "1",      # Play Stats
        "3",      # Player Drilldown
        "10",     # Exit Explorer
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
    assert "PLAYBOOK CHALKBOARD" in res.stdout
    assert "GAME SITUATION & SNAP CONTEXT" in res.stdout
    assert "GAME CLOCK:" in res.stdout
    assert "FIELD LOCATION:" in res.stdout
    assert "DOWN & DISTANCE:" in res.stdout
    assert "IN-DEPTH PLAY ANALYTICS" in res.stdout
    assert "auto-selected" in res.stdout


def test_play_explorer_drilldown_by_team_and_game_crosslink():
    input_text = "\n".join([
        "/play",
        "1",      # Offense
        "2",      # Run
        "1",      # Inside Zone & Dive
        "1",      # Browse by Team
        "1",      # Select Team #1 (BAL or DET)
        "1",      # Select Matchup #1
        "a",      # All Quarters in game
        "1",      # Select Play #1
        "4",      # Go to Game View (cross-link to /games)
        "x",      # Exit Game View
        "10",     # Exit Explorer
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "PLAYBOOK CHALKBOARD" in res.stdout
    assert "Inside Zone & Dive" in res.stdout
    assert "GAME SITUATION & SNAP CONTEXT" in res.stdout
    assert "GAME CENTER:" in res.stdout
    assert "GAME VIEW: PLAY #" in res.stdout


def test_games_command_by_team_and_overtime_navigation():
    input_text = "\n".join([
        "/games",
        "1",      # Browse by Team
        "DET",    # Select Detroit Lions
        "1",      # Select Week 1: LA @ DET (Overtime)
        "5",      # Quarter 5: Overtime (OT)
        "1",      # Select Play #1 (#120 D.Montgomery TD run)
        "P",      # Step to Previous Play (#113 in Q4)
        "N",      # Step to Next Play (#120 in OT)
        "C",      # View Concept Chalkboard schematic
        "X",      # Exit Game View
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "GAME CENTER: LA @ DET" in res.stdout
    assert "Overtime" in res.stdout
    assert "D.Montgomery" in res.stdout
    assert "Stepping to Previous Play #113" in res.stdout
    assert "Stepping to Next Play #120" in res.stdout
    assert "PLAYBOOK CHALKBOARD" in res.stdout


def test_games_command_by_week_and_cli_subcommand():
    # Test CLI games subcommand with --game-id and --play-id
    res_cli = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "games", "--season", "2025", "--game-id", "2025_01_LA_DET", "--play-id", "120"],
        input="X\n",
        capture_output=True,
        text=True,
    )
    assert res_cli.returncode == 0, res_cli.stderr
    assert "GAME CENTER: LA @ DET" in res_cli.stdout
    assert "GAME VIEW: PLAY #120" in res_cli.stdout
    assert "D.Montgomery" in res_cli.stdout


def test_why_command_lists_player_not_qb():
    input_text = "\n".join([
        "show Worthy touchdown play",
        "/why",
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "Last Natural Language Query Parsed Intent:" in res.stdout
    why_block = cli.strip_ansi(res.stdout.split("Last Natural Language Query Parsed Intent:")[1].split("nfl-stat>")[0])
    json_start = why_block.find("{")
    json_end = why_block.rfind("}") + 1
    parsed_json = json.loads(why_block[json_start:json_end])
    assert "player" in parsed_json
    assert "qb" not in parsed_json
    assert parsed_json["player"] == "worthy"
    assert parsed_json["intent"] == "specific_play"


@pytest.mark.parametrize("query,expected_player,expected_intent", [
    ("show Worthy touchdown play", "worthy", "specific_play"),
    ("show Mahomes touchdown play", "mahomes", "specific_play"),
    ("diagram Gibbs 40 yard run", "gibbs", "specific_play"),
    ("diagram Parsons sack play", "parsons", "specific_play"),
    ("drill down into Xavier Worthy", "worthy", "player_drilldown"),
    ("stats for Jahmyr Gibbs", "gibbs", "player_drilldown"),
    ("stats for Justin Tucker", "tucker", "player_drilldown"),
    ("epa per play", None, "stat_query"),
    ("tell me something unrelated", None, "ambiguous"),
])
def test_multi_position_player_recognition_and_no_qb_key(engine, query, expected_player, expected_intent):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off")
    assert "qb" not in parsed, f"'qb' field must not be present in parsed intent for query: {query}"
    assert "player" in parsed, f"'player' field must be present in parsed intent for query: {query}"
    assert parsed["player"] == expected_player
    assert parsed["intent"] == expected_intent


def test_cli_play_subcommand_player_flag():
    root = Path(__file__).resolve().parents[1]
    res_player = subprocess.run(
        [sys.executable, str(root / "nfl_stat_cli.py"), "play", "--player", "Worthy", "--season", "2025"],
        capture_output=True,
        text=True,
    )
    assert res_player.returncode == 0, res_player.stderr
    assert "SPECIFIC PLAY DIAGRAM" in res_player.stdout
    assert "Worthy" in res_player.stdout or "X.Worthy" in res_player.stdout

    # Test backward compatibility with --qb flag
    res_qb = subprocess.run(
        [sys.executable, str(root / "nfl_stat_cli.py"), "play", "--qb", "Mahomes", "--season", "2025"],
        capture_output=True,
        text=True,
    )
    assert res_qb.returncode == 0, res_qb.stderr
    assert "SPECIFIC PLAY DIAGRAM" in res_qb.stdout
    assert "Mahomes" in res_qb.stdout or "P.Mahomes" in res_qb.stdout


def test_show_startup_loading(capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.os, "system", lambda cmd: None)
    cli.show_startup_loading(is_interactive=True)
    out = capsys.readouterr().out
    assert "Loading..." in out
    assert "100%" in out
    assert "Ready! Launching NFL-STAT-CLI..." in out


def test_stat_page_loading_and_render(engine, capsys):
    out_table = cli.render_stat_page(engine, cli.SAMPLE_PBP_PLAYS, show_progress=True)
    captured = capsys.readouterr().out
    assert "Loading..." in captured
    assert "Evaluating Saved Stat Page tracking" in captured
    assert "SAVED STAT PAGE" in out_table
    assert "Saved Stat Catalog" in out_table


def test_tui_page_command():
    input_text = "\n".join([
        "/page",
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "Loading..." in res.stdout
    assert "SAVED STAT PAGE" in res.stdout
    assert "Saved Stat Catalog" in res.stdout


def test_nl_query_stat_page(engine):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("show stat page", engine, slm_model="off")
    assert parsed["intent"] == "stat_page"
    parsed_plain = cli.NaturalLanguageStatAssistant.interpret_query("stat page", engine, slm_model="off")
    assert parsed_plain["intent"] == "stat_page"


def test_fresh_install_has_zero_custom_stats(tmp_path):
    fresh_engine = cli.StatEngine(storage_dir=tmp_path / "fresh")
    custom_stats = [k for k, v in fresh_engine.stats.items() if v.category == "custom"]
    assert len(custom_stats) == 0, f"Expected 0 custom stats on fresh install, got: {custom_stats}"
    trad_stats = [k for k, v in fresh_engine.stats.items() if v.category == "traditional"]
    assert len(trad_stats) >= 16
    assert "yards_per_play" in trad_stats
    assert "completion_pct" in trad_stats
    assert "yards_per_attempt" in trad_stats
    assert "yards_per_rush" in trad_stats


def test_delete_custom_stat_success_and_cleanup(tmp_path):
    test_engine = cli.StatEngine(storage_dir=tmp_path / "del_test")
    test_engine.register_custom_stat(
        name="test_del_stat",
        title="Test Delete Stat",
        group_by="qb",
        formula="yards_per_play * 2.0",
        description="To be deleted",
        calculation_explained="YPP times 2",
    )
    assert "test_del_stat" in test_engine.stats
    assert "test_del_stat" in test_engine.stat_page["pinned_stats"]

    deleted = test_engine.delete_custom_stat("test_del_stat")
    assert deleted.name == "test_del_stat"
    assert "test_del_stat" not in test_engine.stats
    assert "test_del_stat" not in test_engine.stat_page["pinned_stats"]

    reloaded_engine = cli.StatEngine(storage_dir=tmp_path / "del_test")
    assert "test_del_stat" not in reloaded_engine.stats


def test_cannot_delete_traditional_stat(engine):
    with pytest.raises(ValueError, match="Cannot delete built-in traditional stat"):
        engine.delete_custom_stat("yards_per_play")


def test_cannot_delete_stat_with_dependents(tmp_path):
    test_engine = cli.StatEngine(storage_dir=tmp_path / "dep_test")
    test_engine.register_custom_stat(
        name="base_custom",
        title="Base Custom",
        group_by="qb",
        formula="yards_per_play * 2.0",
        description="Base stat",
        calculation_explained="Base",
    )
    test_engine.register_custom_stat(
        name="chained_custom",
        title="Chained Custom",
        group_by="qb",
        formula="base_custom + 10.0",
        description="Chained stat",
        calculation_explained="Chained",
    )
    with pytest.raises(ValueError, match="other custom stats depend on it"):
        test_engine.delete_custom_stat("base_custom")

    test_engine.delete_custom_stat("chained_custom")
    deleted_base = test_engine.delete_custom_stat("base_custom")
    assert deleted_base.name == "base_custom"


def test_interactive_tui_delete_stat(tmp_path):
    input_text = "\n".join([
        "/create",
        "1",                    # Scratch
        "tui_del_stat",         # Identifier
        "TUI Delete Stat",      # Title
        "qb",                   # Group by
        "season",               # Scope
        "",                     # Filter (none)
        "yards_per_play * 3.0", # Formula
        "pts",                  # Unit
        "TUI test description", # Description
        "TUI explanation",      # Explained
        "/delete tui_del_stat", # Delete command
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "TUI Delete Stat" in res.stdout
    assert "Successfully deleted custom stat `tui_del_stat`" in res.stdout


def test_cli_delete_stat_subcommand(tmp_path):
    export_json = tmp_path / "import_stat.json"
    export_json.write_text(json.dumps({
        "stats": {
            "cli_del_stat": {
                "name": "cli_del_stat",
                "title": "CLI Delete Stat",
                "group_by": "qb",
                "formula": "yards_per_play + 1",
                "description": "desc",
                "calculation_explained": "expl",
                "unit": "yds",
                "filter_expr": "",
                "scope": "season",
                "agg": "formula",
            }
        }
    }), encoding="utf-8")
    res_imp = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "import-stats", "--input", str(export_json)],
        capture_output=True,
        text=True,
    )
    assert res_imp.returncode == 0, res_imp.stderr
    assert "Imported 1 custom stats" in res_imp.stdout

    res_del = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "delete-stat", "cli_del_stat"],
        capture_output=True,
        text=True,
    )
    assert res_del.returncode == 0, res_del.stderr
    assert "Successfully deleted custom stat `cli_del_stat`" in res_del.stdout


def test_nl_query_delete_stat(engine):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("delete custom stat my_stat", engine, slm_model="off")
    assert parsed["intent"] == "delete_stat"
    assert parsed["stat_name"] == "my_stat"

    parsed2 = cli.NaturalLanguageStatAssistant.interpret_query("remove stat test_stat", engine, slm_model="off")
    assert parsed2["intent"] == "delete_stat"
    assert parsed2["stat_name"] == "test_stat"


def test_nl_dataset_info_queries(engine, sample_plays):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("what is the last game you have data from?", engine, slm_model="off")
    assert parsed["intent"] == "dataset_info"
    assert parsed["subquery"] == "last_game"
    assert parsed["show_field"] is False
    assert "player" in parsed
    assert "qb" not in parsed

    output = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, sample_plays))
    assert "LATEST LOADED GAME IN DATASET" in output
    assert "2025_03_BAL_DAL" in output
    assert "BAL @ DAL" in output
    assert "BAL 28" in output

    parsed_all = cli.NaturalLanguageStatAssistant.interpret_query("what games do you have data from?", engine, slm_model="off")
    assert parsed_all["intent"] == "dataset_info"
    assert parsed_all["subquery"] == "all_games"
    out_all = cli.strip_ansi(cli.handle_nl_query_result(parsed_all, engine, sample_plays))
    assert "NFL Loaded Games" in out_all


def test_nl_passing_yard_leaders_queries(engine, sample_plays):
    for q in ("who had the most passing yard this season", "who had the most passing yards"):
        parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")
        assert parsed["intent"] == "stat_query"
        assert parsed["stat_name"] == "passing_yards"
        assert parsed["group_by"] == "qb"
        assert parsed["show_field"] is False
        assert "player" in parsed
        assert "qb" not in parsed

        out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, sample_plays))
        assert "Passing Yards (Pass Yds)" in out
        assert "P.Mahomes" in out
        assert "76.00 yds" in out
        assert "Leader: P.Mahomes" in out


def test_nl_divisions_weeks_quarters_situations_and_positions(engine, sample_plays):
    p_div = cli.NaturalLanguageStatAssistant.interpret_query("who led the afc north in passing yards", engine, slm_model="off")
    assert p_div["intent"] == "stat_query"
    assert p_div["stat_name"] == "passing_yards"
    assert p_div["division"] == "AFC North"
    assert p_div["conf"] == "AFC"
    out_div = cli.strip_ansi(cli.handle_nl_query_result(p_div, engine, sample_plays))
    assert "AFC North" in out_div
    assert "L.Jackson" in out_div
    assert "P.Mahomes" not in out_div  # KC is AFC West

    p_wk = cli.NaturalLanguageStatAssistant.interpret_query("passing yards in week 1", engine, slm_model="off")
    assert p_wk["week"] == 1
    assert p_wk["stat_name"] == "passing_yards"
    out_wk = cli.strip_ansi(cli.handle_nl_query_result(p_wk, engine, sample_plays))
    assert "Week 1" in out_wk

    p_qtr = cli.NaturalLanguageStatAssistant.interpret_query("passing yards in 4th quarter", engine, slm_model="off")
    assert p_qtr["qtr"] == 4
    assert p_qtr["stat_name"] == "passing_yards"
    out_qtr = cli.strip_ansi(cli.handle_nl_query_result(p_qtr, engine, sample_plays))
    assert "Q4" in out_qtr

    p_rush = cli.NaturalLanguageStatAssistant.interpret_query("who had the most rushing yards", engine, slm_model="off")
    assert p_rush["stat_name"] == "rushing_yards"
    assert p_rush["group_by"] == "rusher"
    assert p_rush["position"] == "RB"
    out_rush = cli.strip_ansi(cli.handle_nl_query_result(p_rush, engine, sample_plays))
    assert "Rushing Yards (Rush Yds)" in out_rush

    p_td = cli.NaturalLanguageStatAssistant.interpret_query("who had the most touchdowns", engine, slm_model="off")
    assert p_td["stat_name"] == "touchdowns"
    assert p_td["group_by"] == "player"
    out_td = cli.strip_ansi(cli.handle_nl_query_result(p_td, engine, sample_plays))
    assert "Total Touchdowns (TD)" in out_td

    p_sit = cli.NaturalLanguageStatAssistant.interpret_query("3rd and short conversion rate", engine, slm_model="off")
    assert "down == 3 and ydstogo <= 2" in p_sit["filter_expr"]

    p_rz = cli.NaturalLanguageStatAssistant.interpret_query("red zone efficiency", engine, slm_model="off")
    assert "yardline_100 <= 20" in p_rz["filter_expr"]


def test_interactive_tui_nl_dataset_and_passing_yards_with_why():
    input_text = "\n".join([
        "what is the last game you have data from?",
        "/why",
        "who had the most passing yard this season",
        "/why",
        "quit",
    ]) + "\n"
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "LATEST LOADED GAME IN DATASET" in out
    assert "2025_03_BAL_DAL" in out
    assert "Passing Yards (Pass Yds)" in out
    assert "P.Mahomes" in out

    # Verify both /why outputs contain valid JSON with 'player' and without 'qb'
    why_sections = out.split("Last Natural Language Query Parsed Intent:")
    assert len(why_sections) >= 3  # Header + 2 queries
    for sec in why_sections[1:]:
        j_start = sec.find("{")
        j_end = sec.find("}") + 1
        parsed = json.loads(sec[j_start:j_end])
        assert "player" in parsed
        assert "qb" not in parsed


def test_downcast_dataframe_floats():
    class DummyDF:
        def __init__(self):
            self.dtypes = {"epa": "float64", "wpa": "float64", "yards": "int64"}
        def select_dtypes(self, include):
            class ColIdx:
                def __init__(self, cols):
                    self.columns = cols
            return ColIdx(["epa", "wpa"])
        def __setitem__(self, key, val):
            self.set_cols = key
            self.val = val

    df = DummyDF()
    res = cli._downcast_dataframe_floats(df)
    assert res is df
    # Non-dataframe object should not throw
    assert cli._downcast_dataframe_floats(None) is None
    assert cli._downcast_dataframe_floats("string") == "string"


def test_console_spinner_lifecycle(capsys):
    with cli.ConsoleSpinner("Context test", enabled=False) as sp:
        sp.update("Updated context test")

    sp2 = cli.ConsoleSpinner("Manual test", enabled=True)
    sp2.enabled = True
    sp2.start()
    sp2.update("Updated manual")
    sp2.stop(final_message="✔ Done manual", clear=True)
    out = capsys.readouterr().out
    assert "✔ Done manual" in out


def test_show_startup_loading_includes_years_and_downcast(capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.os, "system", lambda cmd: None)
    cli.show_startup_loading(is_interactive=True, seasons=[2024, 2025])
    out = capsys.readouterr().out
    assert "Loading..." in out
    assert "2024, 2025" in out
    assert "Downcasting floats" in out
    assert "Ready! Launching NFL-STAT-CLI..." in out


def test_nl_most_yards_queries_and_top_5_limit(engine, sample_plays):
    # 1. "who had the most yards this year?"
    p1 = cli.NaturalLanguageStatAssistant.interpret_query("who had the most yards this year?", engine, slm_model="off")
    assert p1["intent"] == "stat_query"
    assert p1["stat_name"] == "passing_yards"
    assert p1["player"] is None
    assert p1["limit"] == 5
    out1 = cli.strip_ansi(cli.handle_nl_query_result(p1, engine, sample_plays))
    assert "Top 5" in out1
    rows1 = [l for l in out1.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows1) <= 5

    # 2. "which player has the most yards this year?"
    p2 = cli.NaturalLanguageStatAssistant.interpret_query("which player has the most yards this year?", engine, slm_model="off")
    assert p2["intent"] == "stat_query"
    assert p2["stat_name"] == "passing_yards"
    assert p2["player"] is None  # Must NOT mistakenly extract "has the" or "which player"
    assert p2["limit"] == 5
    out2 = cli.strip_ansi(cli.handle_nl_query_result(p2, engine, sample_plays))
    assert "Top 5" in out2
    rows2 = [l for l in out2.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows2) <= 5

    # 3. "who is leading in the most passing yards"
    p3 = cli.NaturalLanguageStatAssistant.interpret_query("who is leading in the most passing yards", engine, slm_model="off")
    assert p3["intent"] == "stat_query"
    assert p3["stat_name"] == "passing_yards"
    assert p3["limit"] == 5
    out3 = cli.strip_ansi(cli.handle_nl_query_result(p3, engine, sample_plays))
    assert "Top 5" in out3
    rows3 = [l for l in out3.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows3) <= 5

    # 4. "top 3 passing yards"
    p4 = cli.NaturalLanguageStatAssistant.interpret_query("top 3 passing yards", engine, slm_model="off")
    assert p4["intent"] == "stat_query"
    assert p4["stat_name"] == "passing_yards"
    assert p4["limit"] == 3
    out4 = cli.strip_ansi(cli.handle_nl_query_result(p4, engine, sample_plays))
    assert "Top 3" in out4
    rows4 = [l for l in out4.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows4) == 3


def test_cli_stat_subcommand_limit_flag():
    res = subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", "stat", "passing_yards", "--limit", "2", "--season", "2025"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "Top 2" in out
    rows = [l for l in out.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows) == 2







