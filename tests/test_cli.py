import importlib.util
from importlib import resources
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import pro_football_slm as cli


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
    ("screen yac", "stat_query", "yards_after_catch"),
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
    spec = importlib.util.spec_from_file_location("legacy_cli", root / "pro_football_slm.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    assert legacy.StatEngine is cli.StatEngine
    assert legacy._safe_div is cli._safe_div
    for args in ([str(root / "pro_football_slm.py"), "--help"], ["-m", "pro_football_slm", "--help"]):
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
    assert "Rushing & Ground Game Analytics" in plain
    assert "Receiving & Yards After Catch (YAC) Analytics" in plain
    assert "Team Offense, Scoring & Drive Efficiency" in plain
    assert "Penalties, Discipline & Situational Operations" in plain
    assert "epa_per_play" in plain
    assert "passer_rating" in plain
    assert "passing_yards" in plain
    assert "rushing_yards" in plain
    assert "penalties" in plain
    assert "timeouts" in plain
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
    res_team = subprocess.run([sys.executable, str(root / "pro_football_slm.py"), "team", "KC", "--season", "2025"], capture_output=True, text=True)
    assert res_team.returncode == 0, res_team.stderr
    assert "TEAM DRILL-DOWN : KANSAS CITY CHIEFS" in res_team.stdout

    res_player = subprocess.run([sys.executable, str(root / "pro_football_slm.py"), "player", "Mahomes", "--season", "2025"], capture_output=True, text=True)
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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
        [sys.executable, "-m", "pro_football_slm", "games", "--season", "2025", "--game-id", "2025_01_LA_DET", "--play-id", "120"],
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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "Last Natural Language Query Parsed Intent:" in res.stdout
    why_block = cli.strip_ansi(res.stdout.split("Last Natural Language Query Parsed Intent:")[1].split("pro-football-slm>")[0])
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
        [sys.executable, str(root / "pro_football_slm.py"), "play", "--player", "Worthy", "--season", "2025"],
        capture_output=True,
        text=True,
    )
    assert res_player.returncode == 0, res_player.stderr
    assert "SPECIFIC PLAY DIAGRAM" in res_player.stdout
    assert "Worthy" in res_player.stdout or "X.Worthy" in res_player.stdout

    # Test backward compatibility with --qb flag
    res_qb = subprocess.run(
        [sys.executable, str(root / "pro_football_slm.py"), "play", "--qb", "Mahomes", "--season", "2025"],
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
    assert "Ready! Launching Pro Football SLM..." in out


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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
    catalog = cli.render_stats_catalog(fresh_engine)
    plain_cat = cli.strip_ansi(catalog)
    assert "User-Created & Imported Custom Stats" not in plain_cat


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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
        [sys.executable, "-m", "pro_football_slm", "import-stats", "--input", str(export_json)],
        capture_output=True,
        text=True,
    )
    assert res_imp.returncode == 0, res_imp.stderr
    assert "Imported 1 custom stats" in res_imp.stdout

    res_del = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "delete-stat", "cli_del_stat"],
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
        [sys.executable, "-m", "pro_football_slm", "tui", "--season", "2025"],
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
    assert "Ready! Launching Pro Football SLM..." in out


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
        [sys.executable, "-m", "pro_football_slm", "stat", "passing_yards", "--limit", "2", "--season", "2025"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "Top 2" in out
    rows = [l for l in out.splitlines() if l.strip().startswith("│") and "#" in l]
    assert len(rows) == 2


def test_penalties_data_and_nlp_queries():
    engine = cli.StatEngine()
    bridge = cli.NFLDataBridge()
    plays = [bridge._normalize_row(r, idx) for idx, r in enumerate(cli.SAMPLE_PBP_PLAYS, 1)]

    # 1. Verify penalties stats exist in engine
    assert "penalties" in engine.stats
    assert "penalty_yards" in engine.stats
    assert "penalties_drawn" in engine.stats
    assert "penalty_yards_drawn" in engine.stats

    # 2. Check leaderboard calculation
    board_pen = engine.evaluate_stat_leaderboard("penalties", plays, group_override="team")
    assert len(board_pen) > 0
    kc_entry = next((item for item in board_pen if item["entity"] == "KC"), None)
    assert kc_entry is not None
    assert kc_entry["value"] >= 1.0
    assert kc_entry["metrics"]["penalties"] >= 1.0

    # 3. Check penalties drawn / in favor
    board_drawn = engine.evaluate_stat_leaderboard("penalties_drawn", plays, group_override="team")
    assert len(board_drawn) > 0
    bal_entry = next((item for item in board_drawn if item["entity"] == "BAL"), None)
    assert bal_entry is not None
    assert bal_entry["value"] >= 2.0

    # 4. NLP Query: "who had the most penalties this year?"
    q1 = cli.NaturalLanguageStatAssistant.interpret_query("who had the most penalties this year?", engine, slm_model="off")
    assert q1["intent"] == "stat_query"
    assert q1["stat_name"] == "penalties"
    assert q1["limit"] == 5
    out1 = cli.strip_ansi(cli.handle_nl_query_result(q1, engine, plays))
    assert "Total Penalties" in out1

    # 5. NLP Query: "which team as had the most penalties in their favor?" (handling colloquialism/typo)
    q_fav = cli.NaturalLanguageStatAssistant.interpret_query("which team as had the most penalties in their favor?", engine, slm_model="off")
    assert q_fav["intent"] == "stat_query"
    assert q_fav["stat_name"] == "penalties_drawn"
    assert q_fav["group_by"] == "team"
    assert q_fav["limit"] == 5
    out_fav = cli.strip_ansi(cli.handle_nl_query_result(q_fav, engine, plays))
    assert "Penalties in Favor" in out_fav
    assert "BAL" in out_fav

    # 6. NLP Query: "who benefited the most from penalties?"
    q_ben = cli.NaturalLanguageStatAssistant.interpret_query("who benefited the most from penalties?", engine, slm_model="off")
    assert q_ben["intent"] == "stat_query"
    assert q_ben["stat_name"] == "penalties_drawn"
    assert q_ben["group_by"] == "team"

    # 7. NLP Query: "which team has the most penalty yards?" and "teams with the most total yards in penalties?"
    q2 = cli.NaturalLanguageStatAssistant.interpret_query("which team has the most penalty yards?", engine, slm_model="off")
    assert q2["intent"] == "stat_query"
    assert q2["stat_name"] == "penalty_yards"
    assert q2["group_by"] == "team"
    assert q2["limit"] == 5
    out2 = cli.strip_ansi(cli.handle_nl_query_result(q2, engine, plays))
    assert "Penalty Yards" in out2

    q_total_yds = cli.NaturalLanguageStatAssistant.interpret_query("teams with the most total yards in penalties?", engine, slm_model="off")
    assert q_total_yds["intent"] == "stat_query"
    assert q_total_yds["stat_name"] == "penalty_yards"
    assert q_total_yds["group_by"] == "team"
    assert q_total_yds["limit"] == 5
    out_total_yds = cli.strip_ansi(cli.handle_nl_query_result(q_total_yds, engine, plays))
    assert "Penalty Yards" in out_total_yds

    q_fav_yds = cli.NaturalLanguageStatAssistant.interpret_query("which team has had the most penalty yards in their favor?", engine, slm_model="off")
    assert q_fav_yds["intent"] == "stat_query"
    assert q_fav_yds["stat_name"] == "penalty_yards_drawn"
    assert q_fav_yds["group_by"] == "team"
    assert q_fav_yds["limit"] == 5

    # 8. Individual Player Penalty Attribution
    q_player = cli.NaturalLanguageStatAssistant.interpret_query("which player committed the most penalties?", engine, slm_model="off")
    assert q_player["intent"] == "stat_query"
    assert q_player["stat_name"] == "penalties"
    assert q_player["group_by"] == "player"
    assert q_player["limit"] == 5
    out_player = cli.strip_ansi(cli.handle_nl_query_result(q_player, engine, plays))
    assert "T.McDuffie" in out_player or "J.Taylor" in out_player

    # 9. Test play normalization extracts player name from desc or leaves empty for team penalty
    p_player = bridge._normalize_row({
        "desc": "PENALTY on SF-71-T.Williams, False Start, 5 yards.",
        "penalty": 1,
        "posteam": "SF",
        "defteam": "NYJ",
    })
    assert p_player["penalty_player_name"] == "T.Williams"

    p_team_only = bridge._normalize_row({
        "desc": "PENALTY on BAL, Delay of Game, 5 yards.",
        "penalty": 1,
        "posteam": "BAL",
        "defteam": "KC",
    })
    assert p_team_only["penalty_player_name"] == ""
    assert p_team_only["penalty_team"] == "BAL"


def test_timeouts_data_and_nlp_queries():
    engine = cli.StatEngine()
    bridge = cli.NFLDataBridge()
    plays = [bridge._normalize_row(r, idx) for idx, r in enumerate(cli.SAMPLE_PBP_PLAYS, 1)]

    # 1. Verify timeouts stat exists in engine
    assert "timeouts" in engine.stats

    # 2. Leaderboard by coach
    board_to_coach = engine.evaluate_stat_leaderboard("timeouts", plays, group_override="coach")
    assert len(board_to_coach) > 0
    reid_entry = next((item for item in board_to_coach if item["entity"] == "Andy Reid"), None)
    assert reid_entry is not None
    assert reid_entry["value"] >= 1.0

    harbaugh_entry = next((item for item in board_to_coach if item["entity"] == "John Harbaugh"), None)
    assert harbaugh_entry is not None
    assert harbaugh_entry["value"] >= 1.0

    # 3. Leaderboard by team
    board_to_team = engine.evaluate_stat_leaderboard("timeouts", plays, group_override="team")
    assert len(board_to_team) > 0
    kc_to = next((item for item in board_to_team if item["entity"] == "KC"), None)
    assert kc_to is not None
    assert kc_to["value"] >= 1.0

    # 4. NLP Query: "which coach has used the most timeouts?"
    p_to = cli.NaturalLanguageStatAssistant.interpret_query("which coach has used the most timeouts?", engine, slm_model="off")
    assert p_to["intent"] == "stat_query"
    assert p_to["stat_name"] == "timeouts"
    assert p_to["group_by"] == "coach"
    assert p_to["limit"] == 5
    out_to = cli.strip_ansi(cli.handle_nl_query_result(p_to, engine, plays))
    assert "Timeouts Used" in out_to
    assert "Andy Reid" in out_to

    # 5. NLP Query: "which team has called the most timeouts?"
    p_to_team = cli.NaturalLanguageStatAssistant.interpret_query("which team has called the most timeouts?", engine, slm_model="off")
    assert p_to_team["intent"] == "stat_query"
    assert p_to_team["stat_name"] == "timeouts"
    assert p_to_team["group_by"] == "team"
    assert p_to_team["limit"] == 5

    # 6. NLP Query with quarter abbreviation typo: "which coach has called the most timeouts in the 4th qrt"
    p_qtr = cli.NaturalLanguageStatAssistant.interpret_query("which coach has called the most timeouts in the 4th qrt", engine, slm_model="off")
    assert p_qtr["intent"] == "stat_query"
    assert p_qtr["stat_name"] == "timeouts"
    assert p_qtr["group_by"] == "coach"
    assert p_qtr["qtr"] == 4
    assert p_qtr["limit"] == 5
    out_qtr = cli.strip_ansi(cli.handle_nl_query_result(p_qtr, engine, plays))
    assert "Q4" in out_qtr


def test_coaching_staff_data_and_nlp_queries():
    engine = cli.StatEngine()

    # 1. Verify 32 NFL teams have full coaching staffs
    for t_abbr in cli.AFC_TEAMS | cli.NFC_TEAMS:
        staff = cli.get_team_coaching_staff(t_abbr)
        assert "hc" in staff, f"Missing HC for {t_abbr}"
        assert "oc" in staff, f"Missing OC for {t_abbr}"
        assert "dc" in staff, f"Missing DC for {t_abbr}"

    # 2. Specific lookups
    kc_staff = cli.get_team_coaching_staff("KC")
    assert kc_staff["hc"] == "Andy Reid"
    assert kc_staff["oc"] == "Matt Nagy"
    assert kc_staff["dc"] == "Steve Spagnuolo"

    det_staff = cli.get_team_coaching_staff("DET")
    assert det_staff["hc"] == "Dan Campbell"
    assert det_staff["oc"] == "Ben Johnson"

    # 3. Coach name lookup
    found_reid = cli.find_coach_team("Andy Reid")
    assert found_reid is not None
    assert found_reid[0] == "KC"
    assert found_reid[2] == "hc"

    found_ben = cli.find_coach_team("Ben Johnson")
    assert found_ben is not None
    assert found_ben[0] == "DET"
    assert found_ben[2] == "oc"

    # 4. NLP Query: "who is the coach of the chiefs?"
    p_hc = cli.NaturalLanguageStatAssistant.interpret_query("who is the coach of the chiefs?", engine, slm_model="off")
    assert p_hc["intent"] == "coaching_staff"
    assert p_hc["team"] == "KC"
    assert p_hc["role"] == "hc"

    # 5. NLP Query: "who is the offensive coordinator for the lions?"
    p_oc = cli.NaturalLanguageStatAssistant.interpret_query("who is the offensive coordinator for the lions?", engine, slm_model="off")
    assert p_oc["intent"] == "coaching_staff"
    assert p_oc["team"] == "DET"
    assert p_oc["role"] == "oc"

    # 6. NLP Query: "who is Andy Reid?"
    p_name = cli.NaturalLanguageStatAssistant.interpret_query("who is Andy Reid?", engine, slm_model="off")
    assert p_name["intent"] == "coaching_staff"
    assert p_name["team"] == "KC"
    assert p_name["role"] == "hc"

    # 7. Rendering coaching staff view
    view_kc = cli.strip_ansi(cli.render_coaching_staff_view("KC"))
    assert "KANSAS CITY CHIEFS" in view_kc
    assert "Andy Reid" in view_kc
    assert "Steve Spagnuolo" in view_kc


def test_coach_grouping_and_stat_query():
    engine = cli.StatEngine()
    bridge = cli.NFLDataBridge()
    plays = [bridge._normalize_row(r, idx) for idx, r in enumerate(cli.SAMPLE_PBP_PLAYS, 1)]

    # 1. NLP Query: "rank coaches by epa per play"
    p = cli.NaturalLanguageStatAssistant.interpret_query("rank coaches by epa per play", engine, slm_model="off")
    assert p["intent"] == "stat_query"
    assert p["stat_name"] == "epa_per_play"
    assert p["group_by"] == "coach"

    # 2. Rendering evaluation
    out = cli.strip_ansi(cli.handle_nl_query_result(p, engine, plays))
    assert "Expected Points Added / Play" in out
    assert "Andy Reid" in out
    assert "Dan Campbell" in out


def test_coaches_cli_and_subcommand():
    # 1. Full coaching staff
    res = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "coaches", "KC"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert "Andy Reid" in out
    assert "Steve Spagnuolo" in out

    # 2. Filter by role
    res_oc = subprocess.run(
        [sys.executable, "-m", "pro_football_slm", "coaches", "DET", "--role", "oc"],
        capture_output=True,
        text=True,
    )
    assert res_oc.returncode == 0, res_oc.stderr
    out_oc = cli.strip_ansi(res_oc.stdout)
    assert "Ben Johnson" in out_oc


def test_general_yac_stat_and_down_filter():
    engine = cli.StatEngine()
    bridge = cli.NFLDataBridge()
    plays = [bridge._normalize_row(r, idx) for idx, r in enumerate(cli.SAMPLE_PBP_PLAYS, 1)]

    # 1. yards_after_catch is in traditional stats
    assert "yards_after_catch" in engine.stats
    sdef = engine.stats["yards_after_catch"]
    assert sdef.filter_expr == "complete_pass == 1"

    # 2. Query "which player has the most yac on 1st down?" evaluates general YAC, not screen passes only
    p = cli.NaturalLanguageStatAssistant.interpret_query(
        "which player has the most yac on 1st down?", engine, slm_model="off"
    )
    assert p["intent"] == "stat_query"
    assert p["stat_name"] == "yards_after_catch"
    assert p["group_by"] == "player"
    assert p["position"] is None, "Generic player queries must not default position to WR"
    assert p["filter_expr"] == "down == 1"
    assert p["limit"] == 5

    out = cli.strip_ansi(cli.handle_nl_query_result(p, engine, plays))
    assert "Yards After Catch (YAC)" in out
    assert "Screen Pass" not in out
    assert "A.St. Brown" in out


def test_position_filtering_on_receiving_and_general_stats():
    engine = cli.StatEngine()
    bridge = cli.NFLDataBridge()
    plays = [bridge._normalize_row(r, idx) for idx, r in enumerate(cli.SAMPLE_PBP_PLAYS, 1)]

    # 1. WR positional query on 1st down YAC
    p_wr = cli.NaturalLanguageStatAssistant.interpret_query(
        "which wr has the most yac on 1st down?", engine, slm_model="off"
    )
    assert p_wr["position"] == "WR"
    assert p_wr["group_by"] == "receiver"
    out_wr = cli.strip_ansi(cli.handle_nl_query_result(p_wr, engine, plays))
    assert "Pos: WR" in out_wr
    assert "A.St. Brown" in out_wr
    assert "R.Rice" in out_wr
    assert "N.Harris" not in out_wr

    # 2. RB positional query on 1st down YAC (must group by receiver, not rusher, and filter to RBs)
    p_rb = cli.NaturalLanguageStatAssistant.interpret_query(
        "which rb has the most yac on 1st down?", engine, slm_model="off"
    )
    assert p_rb["position"] == "RB"
    assert p_rb["group_by"] == "receiver"
    out_rb = cli.strip_ansi(cli.handle_nl_query_result(p_rb, engine, plays))
    assert "Pos: RB" in out_rb
    assert "N.Harris" in out_rb
    assert "A.St. Brown" not in out_rb
    assert "R.Rice" not in out_rb

    # 3. TE positional query on YAC
    p_te = cli.NaturalLanguageStatAssistant.interpret_query(
        "which te has the most yac?", engine, slm_model="off"
    )
    assert p_te["position"] == "TE"
    assert p_te["group_by"] == "receiver"
    out_te = cli.strip_ansi(cli.handle_nl_query_result(p_te, engine, plays))
    assert "Pos: TE" in out_te
    assert "T.Kelce" in out_te
    assert "I.Likely" in out_te
    assert "A.St. Brown" not in out_te
    assert "N.Harris" not in out_te

    # 4. evaluate_stat_leaderboard position parameter filtering
    board_te = engine.evaluate_stat_leaderboard("yards_after_catch", plays, position="TE")
    for r in board_te:
        assert r["position"] == "TE"
        assert r["entity"] in ("T.Kelce", "I.Likely")

    board_rb = engine.evaluate_stat_leaderboard("yards_after_catch", plays, position="RB")
    for r in board_rb:
        assert r["position"] == "RB"
        assert r["entity"] in ("J.Gibbs", "J.Cook", "N.Harris", "J.McKinnon")

    # 3. Special screen stats removed; screen is an attribute filter (is_screen == 1)
    assert "screen_yards_after_catch" not in engine.stats
    assert "screen_effectiveness_index" not in engine.stats

    p_screen = cli.NaturalLanguageStatAssistant.interpret_query("screen yac", engine, slm_model="off")
    assert p_screen["stat_name"] == "yards_after_catch"
    assert p_screen["filter_expr"] == "is_screen == 1"

    # 4. Any stat can be filtered by screen as a standard play concept
    p_epa_screen = cli.NaturalLanguageStatAssistant.interpret_query("epa per play on screen passes", engine, slm_model="off")
    assert p_epa_screen["stat_name"] == "epa_per_play"
    assert p_epa_screen["filter_expr"] == "is_screen == 1"

    # 5. Play volume / counts on screens
    p_vol = cli.NaturalLanguageStatAssistant.interpret_query("which team has the most screen passes?", engine, slm_model="off")
    assert p_vol["stat_name"] == "plays"
    assert p_vol["filter_expr"] == "is_screen == 1"
    assert p_vol["group_by"] == "team"
    assert p_vol["limit"] == 5


def test_play_concept_average_yards_nl_query():
    engine = cli.StatEngine()
    plays = cli.SAMPLE_PBP_PLAYS

    # 1. Parsing 'which play has produces the most yards on average?' and variants
    parsed_main = cli.NaturalLanguageStatAssistant.interpret_query(
        "which play has produces the most yards on average?",
        engine,
        slm_model="off",
    )
    assert parsed_main["intent"] == "stat_query"
    assert parsed_main["stat_name"] == "yards_per_play"
    assert parsed_main["group_by"] == "play_concept"
    assert parsed_main["limit"] == 5
    assert parsed_main["show_field"] is False

    variants = [
        "which play produces the most yards on average?",
        "which play averages the most yards?",
        "which offensive play averages the most yards?",
        "what play concept produces the most yards?",
        "play concept efficiency",
    ]
    for q in variants:
        p = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")
        assert p["intent"] == "stat_query", f"Failed intent for: {q}"
        assert p["stat_name"] == "yards_per_play", f"Failed stat_name for: {q}"
        assert p["group_by"] == "play_concept", f"Failed group_by for: {q}"

    # 2. Verify single play diagram queries are NOT broken
    p_single = cli.NaturalLanguageStatAssistant.interpret_query(
        "show Mahomes touchdown play",
        engine,
        slm_model="off",
    )
    assert p_single["intent"] == "specific_play"
    assert p_single["show_field"] is True

    # 3. Execution and Leaderboard output formatting
    res_str = cli.handle_nl_query_result(parsed_main, engine, plays)
    assert "PLAY CONCEPT" in res_str
    assert "play_action_deep" in res_str
    assert "Season Average Across Qualified Play Concepts:" in res_str
    # Verify non-offensive scrimmage events like punt or field goal are excluded
    assert "field_goal" not in res_str
    assert "punt" not in res_str


def test_ipc_error_reporting_and_resolution():
    ipc_dir = cli.get_ipc_dir()
    assert (ipc_dir / "pending").exists()
    assert (ipc_dir / "resolved").exists()
    assert (ipc_dir / "history").exists()

    engine = cli.StatEngine()
    q = "which coach has called the most timeouts in the 4th qrt"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")

    # 1. Test create_error_report
    rep = cli.create_error_report(
        query_raw=q,
        parsed_nl=parsed,
        user_explanation="Missed 4th qrt filter",
        season=2026,
    )
    rep_id = rep["id"]
    assert rep["query"] == q
    assert rep["user_explanation"] == "Missed 4th qrt filter"
    assert rep["status"] == "pending"

    # Verify files created on disk
    pending_file = ipc_dir / "pending" / f"{rep_id}.json"
    latest_file = ipc_dir / "pending" / "latest.json"
    assert pending_file.exists()
    assert latest_file.exists()

    # 2. Test write_resolution signal
    res = cli.write_resolution(
        report_id=rep_id,
        summary="Added 4th quarter filter mapping to coach timeout leaderboard",
        commit="test_commit_hash",
        status="resolved",
    )
    assert res["id"] == rep_id
    assert res["status"] == "resolved"
    assert res["commit"] == "test_commit_hash"

    # Verify resolution files created and pending file archived
    res_file = ipc_dir / "resolved" / f"{rep_id}.json"
    res_latest = ipc_dir / "resolved" / "latest.json"
    hist_file = ipc_dir / "history" / f"{rep_id}.json"
    assert res_file.exists()
    assert res_latest.exists()
    assert hist_file.exists()
    assert not pending_file.exists()
    assert not (ipc_dir / "pending" / "latest.json").exists()

    # 3. Verify /help contains /error and /reload
    help_text = cli.render_slash_help()
    assert "/error" in help_text
    assert "/reload" in help_text


def test_player_top_plays_latest_game_nl_query():
    engine = cli.StatEngine()
    q = "what is bo nix's top 5 plays in terms of yards gained in his latest game?"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")

    assert parsed["intent"] == "specific_play"
    assert parsed["player"] == "bo nix"
    assert parsed["limit"] == 5
    assert parsed["sort_by"] == "yards_gained"
    assert parsed["latest_game"] is True
    assert parsed["show_field"] is True
    assert "Top 5 matching plays for bo nix" in parsed["explanation"]


def test_clean_successful_plays_query_not_penalties():
    engine = cli.StatEngine()
    q = "which play has been the most successful (points made or yards gain) with the least amout of penalties and turnovers?"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")
    assert parsed["stat_name"] == "clean_play_score"
    assert parsed["group_by"] == "play_concept"
    assert "clean_play_score" in engine.stats and engine.stats["clean_play_score"].category == "traditional"
    board = engine.evaluate_stat_leaderboard("clean_play_score", cli.SAMPLE_PBP_PLAYS, group_override="play_concept")
    names = [r["entity"] for r in board]
    assert names[0] == "play_action_deep"
    # concepts with a turnover/penalty are discounted below their raw yards-per-play
    pass_short = next((r for r in board if r["entity"] == "pass_short"), None)
    if pass_short:
        assert pass_short["value"] < pass_short["yards_per_play"]


def test_register_custom_stat_persist_flag(tmp_path):
    engine = cli.StatEngine(storage_dir=tmp_path)

    # 1. Ephemeral stat (persist=False)
    s_ephem = engine.register_custom_stat(
        name="ephem_rate",
        title="Ephemeral Rate",
        group_by="qb",
        formula="yards_per_play * 1.5",
        description="Session-only stat",
        calculation_explained="Test",
        persist=False,
    )
    assert s_ephem.name == "ephem_rate"
    assert "ephem_rate" in engine.stats
    assert "ephem_rate" in engine.ephemeral_stats
    assert "ephem_rate" not in engine.stat_page.get("pinned_stats", [])

    # Ensure custom_stats.json does NOT contain ephem_rate
    if engine.custom_stats_file.exists():
        disk_data = json.loads(engine.custom_stats_file.read_text(encoding="utf-8"))
        assert "ephem_rate" not in disk_data.get("stats", {})

    # Trigger explicit save_state and ensure still excluded
    engine.save_state()
    disk_data = json.loads(engine.custom_stats_file.read_text(encoding="utf-8"))
    assert "ephem_rate" not in disk_data.get("stats", {})

    # 2. Persistent stat (persist=True)
    s_perm = engine.register_custom_stat(
        name="perm_rate",
        title="Permanent Rate",
        group_by="qb",
        formula="yards_per_play * 2.0",
        description="Permanent stat",
        calculation_explained="Test",
        persist=True,
    )
    assert s_perm.name == "perm_rate"
    assert "perm_rate" in engine.stats
    assert "perm_rate" not in engine.ephemeral_stats
    disk_data = json.loads(engine.custom_stats_file.read_text(encoding="utf-8"))
    assert "perm_rate" in disk_data.get("stats", {})
    assert "ephem_rate" not in disk_data.get("stats", {})


def test_nl_query_create_stat_interactive_prompt_yes(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "y")
    engine = cli.StatEngine(storage_dir=tmp_path)

    parsed = {
        "intent": "create_stat",
        "stat_name": "prompt_yes_stat",
        "title": "Prompt Yes Stat",
        "group_by": "qb",
        "formula": "yards_per_play + 1",
        "explanation": "Custom stat created via query",
        "season": 2026,
    }
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS, interactive=True))
    assert "Saved 'prompt_yes_stat' permanently to custom_stats.json" in out
    assert "prompt_yes_stat" in engine.stats
    assert "prompt_yes_stat" not in engine.ephemeral_stats

    disk_data = json.loads(engine.custom_stats_file.read_text(encoding="utf-8"))
    assert "prompt_yes_stat" in disk_data.get("stats", {})


def test_nl_query_create_stat_interactive_prompt_no(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "n")
    engine = cli.StatEngine(storage_dir=tmp_path)

    parsed = {
        "intent": "create_stat",
        "stat_name": "prompt_no_stat",
        "title": "Prompt No Stat",
        "group_by": "qb",
        "formula": "yards_per_play + 2",
        "explanation": "Custom stat created via query",
        "season": 2026,
    }
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS, interactive=True))
    assert "Evaluated 'prompt_no_stat' for this session only" in out
    assert "prompt_no_stat" in engine.stats
    assert "prompt_no_stat" in engine.ephemeral_stats

    if engine.custom_stats_file.exists():
        disk_data = json.loads(engine.custom_stats_file.read_text(encoding="utf-8"))
        assert "prompt_no_stat" not in disk_data.get("stats", {})


def test_defense_turnovers_and_takeaways_nl_query():
    engine = cli.StatEngine()

    # 1. Reported query: "which team's defense has produces the most turnovers?"
    q = "which team's defense has produces the most turnovers?"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine, slm_model="off")
    assert parsed["intent"] == "stat_query"
    assert parsed["stat_name"] == "takeaways"
    assert parsed["group_by"] == "defteam"
    assert parsed["is_leader"] is True
    assert parsed["show_field"] is False

    # Execute leaderboard view
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS))
    assert "Takeaways (Turnovers Forced)" in out
    assert "DEFENSE" in out
    assert "DAL" in out

    # 2. Test variations
    p_def = cli.NaturalLanguageStatAssistant.interpret_query("which defense has the most takeaways?", engine, slm_model="off")
    assert p_def["stat_name"] == "takeaways"
    assert p_def["group_by"] == "defteam"

    p_off = cli.NaturalLanguageStatAssistant.interpret_query("which team has the most turnovers?", engine, slm_model="off")
    assert p_off["stat_name"] == "turnovers"
    assert p_off["group_by"] == "team"


def test_fantasy_scoring_calculations_and_leaderboards():
    from pro_football_slm.fantasy import (
        calculate_player_fantasy_points,
        compute_player_fantasy_profile,
        compute_all_fantasy_leaders,
        render_fantasy_leaderboard_view,
        render_player_fantasy_profile_view,
    )

    # 1. Custom mock play with 300 passing yds, 3 pass TDs, 1 INT, 40 rushing yds, 1 rush TD, 5 rec, 60 rec yds, 1 rec TD, 1 fumble lost
    mock_plays = [
        # Pass play
        {
            "season": 2024, "week": 1, "game_id": "2024_01_KC_BAL",
            "posteam": "KC", "defteam": "BAL", "home_team": "BAL", "away_team": "KC",
            "passer_player_name": "P.Mahomes", "player_name": "Patrick Mahomes",
            "receiver_player_name": "R.Rice",
            "play_type": "pass", "passing_yards": 250, "pass_touchdown": 2, "interception": 1,
            "epa": 2.5, "wpa": 0.08, "down": 1, "ydstogo": 10,
        },
        # Rush play
        {
            "season": 2024, "week": 1, "game_id": "2024_01_KC_BAL",
            "posteam": "KC", "defteam": "BAL", "home_team": "BAL", "away_team": "KC",
            "rusher_player_name": "P.Mahomes", "player_name": "Patrick Mahomes",
            "play_type": "run", "rushing_yards": 30, "rush_touchdown": 1, "fumble_lost": 0,
            "epa": 1.2, "wpa": 0.04, "down": 2, "ydstogo": 4,
        },
        # Receiver play for Rashee Rice: 6 catches, 80 yards, 1 TD
        {
            "season": 2024, "week": 1, "game_id": "2024_01_KC_BAL",
            "posteam": "KC", "defteam": "BAL", "home_team": "BAL", "away_team": "KC",
            "receiver_player_name": "R.Rice", "player_name": "Rashee Rice",
            "play_type": "pass", "receiving_yards": 80, "reception": 6, "touchdown": 1,
            "epa": 1.5, "wpa": 0.05, "down": 3, "ydstogo": 7,
        },
    ]

    # Mahomes scoring check:
    # Passing: 250 * 0.04 = 10.0 pts, 2 TDs * 4 = 8.0 pts, 1 INT = -2.0 pts -> 16.0 pts
    # Rushing: 30 * 0.10 = 3.0 pts, 1 TD * 6 = 6.0 pts -> 9.0 pts
    # Total = 25.0 pts (Standard, Half, PPR all equal for non-pass-catchers)
    m_std = calculate_player_fantasy_points(pass_yards=250, pass_tds=2, interceptions=1, rush_yards=30, rush_tds=1, format_type="standard")
    m_half = calculate_player_fantasy_points(pass_yards=250, pass_tds=2, interceptions=1, rush_yards=30, rush_tds=1, format_type="half_ppr")
    m_ppr = calculate_player_fantasy_points(pass_yards=250, pass_tds=2, interceptions=1, rush_yards=30, rush_tds=1, format_type="ppr")
    assert round(m_std, 1) == 25.0
    assert round(m_half, 1) == 25.0
    assert round(m_ppr, 1) == 25.0

    # Rashee Rice scoring check:
    # Receiving: 80 * 0.10 = 8.0 pts, 1 TD * 6 = 6.0 pts -> 14.0 pts standard
    # 6 catches: Standard = 14.0, Half-PPR = 14.0 + 3.0 = 17.0, PPR = 14.0 + 6.0 = 20.0
    r_std = calculate_player_fantasy_points(rec_yards=80, receptions=6, rec_tds=1, format_type="standard")
    r_half = calculate_player_fantasy_points(rec_yards=80, receptions=6, rec_tds=1, format_type="half_ppr")
    r_ppr = calculate_player_fantasy_points(rec_yards=80, receptions=6, rec_tds=1, format_type="ppr")
    assert round(r_std, 1) == 14.0
    assert round(r_half, 1) == 17.0
    assert round(r_ppr, 1) == 20.0

    # Profile generation
    prof = compute_player_fantasy_profile("Patrick Mahomes", mock_plays)
    assert prof["player"] == "Patrick Mahomes"
    assert prof["team"] == "KC"
    assert len(prof["game_logs"]) == 1
    assert round(prof["points_ppr"], 1) == 25.0

    # Leaderboard view rendering
    board_view = render_fantasy_leaderboard_view(mock_plays, season=2024, scoring_format="ppr")
    clean_board = cli.strip_ansi(board_view)
    assert "Fantasy Football Scoring Leaders" in clean_board
    assert "Patrick Mahomes" in clean_board
    assert "Rashee Rice" in clean_board

    # Player profile view rendering
    prof_view = render_player_fantasy_profile_view("Patrick Mahomes", mock_plays, season=2024)
    clean_prof = cli.strip_ansi(prof_view)
    assert "Fantasy Profile & Weekly Game Log: Patrick Mahomes" in clean_prof
    assert "Pass Yds" in clean_prof
    assert "Rush Yds" in clean_prof


def test_sportsbook_handicapping_and_power_ratings():
    from pro_football_slm.sportsbook import (
        compute_team_power_ratings,
        handicap_matchup,
        render_sportsbook_board_view,
        render_power_ratings_view,
        render_game_handicap_dossier_view,
    )

    plays = cli.SAMPLE_PBP_PLAYS
    ratings = compute_team_power_ratings(plays, season=2024)
    assert isinstance(ratings, dict)
    assert len(ratings) > 0
    # Every rating record should contain required fields
    for team, r in ratings.items():
        assert "power_rating" in r
        assert "net_epa" in r
        assert "games_played" in r

    # Handicap a matchup between KC and BUF
    dossier = handicap_matchup("KC", "BUF", ratings)
    assert dossier["home_team"] == "KC"
    assert dossier["away_team"] == "BUF"
    assert "spread" in dossier
    assert "total" in dossier
    assert "home_ml" in dossier
    assert "away_ml" in dossier
    assert dossier["home_win_prob"] + dossier["away_win_prob"] == 100.0

    # View renderers
    board = cli.strip_ansi(render_sportsbook_board_view(plays, season=2024))
    assert "Sportsbook Betting Lines & Game Handicapping" in board

    pow_view = cli.strip_ansi(render_power_ratings_view(plays, season=2024))
    assert "NFL Team Power Ratings" in pow_view

    dossier_view = cli.strip_ansi(render_game_handicap_dossier_view("KC", "BUF", plays, season=2024))
    assert "SPORTSBOOK HANDICAPPING DOSSIER" in dossier_view
    assert "Point Spread" in dossier_view
    assert "MONEYLINES" in dossier_view


def test_contracts_dataset_and_views():
    from pro_football_slm.contracts import (
        NFL_CONTRACTS,
        find_contract_by_name,
        get_contracts_by_team,
        get_contracts_by_position,
        get_all_coach_contracts,
        calculate_contract_performance_efficiency,
        render_contracts_leaderboard_view,
        render_player_contract_view,
        render_team_payroll_view,
    )

    # 1. Dataset checks
    assert len(NFL_CONTRACTS) >= 50
    mahomes_c = find_contract_by_name("Patrick Mahomes")
    assert mahomes_c is not None
    assert mahomes_c.apy_m >= 45.0
    assert mahomes_c.team == "KC"
    assert mahomes_c.position == "QB"

    # Coach contract check
    reid_c = find_contract_by_name("Andy Reid")
    assert reid_c is not None
    assert reid_c.contract_type == "coach"
    assert reid_c.team == "KC"

    # Position and team filters
    qbs = get_contracts_by_position("QB")
    assert len(qbs) >= 10
    kc_contracts = get_contracts_by_team("KC")
    assert len(kc_contracts) >= 3

    coaches = get_all_coach_contracts()
    assert len(coaches) >= 10

    # Contract efficiency
    eff = calculate_contract_performance_efficiency(mahomes_c, plays=cli.SAMPLE_PBP_PLAYS, season=2024)
    assert eff["apy_m"] == mahomes_c.apy_m
    assert "cost_per_epa_k" in eff
    assert "cost_per_fpoint_k" in eff

    # View renderers
    c_board = cli.strip_ansi(render_contracts_leaderboard_view(contract_type="player", limit=15))
    assert "Contract & Salary Leaderboard" in c_board
    assert "Patrick Mahomes" in c_board

    coach_board = cli.strip_ansi(render_contracts_leaderboard_view(contract_type="coach", limit=10))
    assert "Contract & Salary Leaderboard" in coach_board
    assert "Andy Reid" in coach_board

    p_view = cli.strip_ansi(render_player_contract_view("Patrick Mahomes", plays=cli.SAMPLE_PBP_PLAYS, season=2024))
    assert "OFFICIAL CONTRACT" in p_view
    assert "Patrick Mahomes" in p_view
    assert "PERFORMANCE ROI & CAP EFFICIENCY" in p_view

    t_view = cli.strip_ansi(render_team_payroll_view("KC"))
    assert "Team Contract Payroll" in t_view
    assert "Patrick Mahomes" in t_view


def test_nl_query_parsing_for_fantasy_sportsbook_and_contracts():
    engine = cli.StatEngine()

    # Fantasy queries
    q_f1 = "who has the most fantasy points"
    p_f1 = cli.NaturalLanguageStatAssistant.interpret_query(q_f1, engine=engine, slm_model="off")
    assert p_f1["intent"] == "fantasy_report"
    assert p_f1["subquery"] == "leaderboard"

    q_f2 = "ppr fantasy leaders"
    p_f2 = cli.NaturalLanguageStatAssistant.interpret_query(q_f2, engine=engine, slm_model="off")
    assert p_f2["intent"] == "fantasy_report"
    assert p_f2["scoring_format"] == "ppr"

    q_f3 = "half-ppr fantasy points for Derrick Henry"
    p_f3 = cli.NaturalLanguageStatAssistant.interpret_query(q_f3, engine=engine, slm_model="off")
    assert p_f3["intent"] == "fantasy_report"
    assert p_f3["subquery"] == "player"
    assert "henry" in p_f3["player"].lower()

    # Sportsbook queries
    q_s1 = "spread for chiefs vs bills"
    p_s1 = cli.NaturalLanguageStatAssistant.interpret_query(q_s1, engine=engine, slm_model="off")
    assert p_s1["intent"] == "sportsbook_report"
    assert p_s1["subquery"] == "matchup"
    assert p_s1["home_team"] == "KC"
    assert p_s1["away_team"] == "BUF"

    q_s2 = "nfl power ratings"
    p_s2 = cli.NaturalLanguageStatAssistant.interpret_query(q_s2, engine=engine, slm_model="off")
    assert p_s2["intent"] == "sportsbook_report"
    assert p_s2["subquery"] == "power_ratings"

    q_s3 = "sportsbook odds for week 4"
    p_s3 = cli.NaturalLanguageStatAssistant.interpret_query(q_s3, engine=engine, slm_model="off")
    assert p_s3["intent"] == "sportsbook_report"
    assert p_s3["week"] == 4

    # Contract queries
    q_c1 = "how much does Patrick Mahomes make"
    p_c1 = cli.NaturalLanguageStatAssistant.interpret_query(q_c1, engine=engine, slm_model="off")
    assert p_c1["intent"] == "contract_report"
    assert p_c1["subquery"] == "player"
    assert "mahomes" in p_c1["player"].lower()

    q_c2 = "Andy Reid contract"
    p_c2 = cli.NaturalLanguageStatAssistant.interpret_query(q_c2, engine=engine, slm_model="off")
    assert p_c2["intent"] == "contract_report"
    assert p_c2["subquery"] == "player"
    assert "reid" in p_c2["player"].lower()

    q_c3 = "highest paid head coaches"
    p_c3 = cli.NaturalLanguageStatAssistant.interpret_query(q_c3, engine=engine, slm_model="off")
    assert p_c3["intent"] == "contract_report"
    assert p_c3["subquery"] == "coaches"

    q_c4 = "Chiefs payroll"
    p_c4 = cli.NaturalLanguageStatAssistant.interpret_query(q_c4, engine=engine, slm_model="off")
    assert p_c4["intent"] == "contract_report"
    assert p_c4["subquery"] == "team"
    assert p_c4["team"] == "KC"


def test_slash_help_includes_new_commands():
    help_text = cli.strip_ansi(cli.render_slash_help())
    assert "/fantasy" in help_text
    assert "/sportsbook" in help_text
    assert "/contract" in help_text


def test_fantasy_points_this_week_error_regression():
    engine = cli.StatEngine()

    # Reported query: "which player had the most fantasy points this week"
    q = "which player had the most fantasy points this week"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine=engine, slm_model="off")
    assert parsed["intent"] == "fantasy_report"
    assert parsed["subquery"] == "leaderboard"
    assert parsed["latest_week"] is True
    assert parsed["scoring_format"] == "ppr"

    # Execution must resolve latest week and complete in milliseconds without hanging
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS))
    assert "Fantasy Football Scoring Leaders" in out
    assert "Week 3" in out
    assert "L.Jackson" in out


def test_fantasy_dst_team_defense_scoring_and_error_regression():
    from pro_football_slm.fantasy import (
        calculate_dst_points_allowed_score,
        compute_team_dst_fantasy_leaders,
        compute_team_dst_fantasy_profile,
        render_fantasy_leaderboard_view,
        render_team_dst_fantasy_profile_view,
    )

    # 1. Points Allowed scoring brackets
    assert calculate_dst_points_allowed_score(0) == 10.0
    assert calculate_dst_points_allowed_score(3) == 7.0
    assert calculate_dst_points_allowed_score(10) == 4.0
    assert calculate_dst_points_allowed_score(17) == 1.0
    assert calculate_dst_points_allowed_score(24) == 0.0
    assert calculate_dst_points_allowed_score(30) == -1.0
    assert calculate_dst_points_allowed_score(42) == -4.0

    # 2. Mock plays with sacks, takeaways, defensive TDs, and points allowed
    mock_plays = [
        {
            "game_id": "2024_01_KC_BAL", "season": 2024, "week": 1,
            "posteam": "KC", "defteam": "BAL", "home_score": 27, "away_score": 20,
            "sack": 1, "interception": 0, "fumble_lost": 0, "safety": 0, "blocked_kick": 0, "touchdown": 0,
            "pass_attempt": 1, "desc": "P.Mahomes sacked by BAL defense",
        },
        {
            "game_id": "2024_01_KC_BAL", "season": 2024, "week": 1,
            "posteam": "KC", "defteam": "BAL", "home_score": 27, "away_score": 20,
            "sack": 0, "interception": 1, "fumble_lost": 0, "safety": 0, "blocked_kick": 0, "touchdown": 1,
            "pass_attempt": 1, "desc": "P.Mahomes pass INTERCEPTED by BAL and returned for TOUCHDOWN",
        },
        {
            "game_id": "2024_01_KC_BAL", "season": 2024, "week": 1,
            "posteam": "BAL", "defteam": "KC", "home_score": 27, "away_score": 20,
            "sack": 0, "interception": 0, "fumble_lost": 1, "safety": 0, "blocked_kick": 0, "touchdown": 0,
            "rush_attempt": 1, "desc": "D.Henry fumble lost, recovered by KC",
        },
    ]

    # In game 2024_01_KC_BAL: KC is away (20), BAL is home (27)
    # BAL (home defense) allowed KC's 20 pts (bracket 14-20 = +1.0) -> 1 sack (+1) + 1 INT (+2) + 1 TD (+6) + 1 PA = 10.0 pts
    # KC (away defense) allowed BAL's 27 pts (bracket 21-27 = 0.0) -> 1 FR (+2) + 0 PA = 2.0 pts
    dst_leaders = compute_team_dst_fantasy_leaders(mock_plays, week=1)
    assert len(dst_leaders) == 2
    bal = next(r for r in dst_leaders if r["team"] == "BAL")
    kc = next(r for r in dst_leaders if r["team"] == "KC")

    assert bal["sacks"] == 1
    assert bal["interceptions"] == 1
    assert bal["defensive_tds"] == 1
    assert bal["points_allowed"] == 20
    assert bal["points_ppr"] == 10.00

    assert kc["fumbles_recovered"] == 1
    assert kc["takeaways"] == 1
    assert kc["points_allowed"] == 27
    assert kc["points_ppr"] == 2.00

    # 3. Leaderboard rendering
    board = cli.strip_ansi(render_fantasy_leaderboard_view(mock_plays, season=2024, position="DEF", week=1))
    assert "Team D/ST Scoring" in board
    assert "BAL Defense" in board
    assert "KC Defense" in board
    assert "10.00" in board

    # 4. Profile rendering
    prof = cli.strip_ansi(render_team_dst_fantasy_profile_view("BAL", mock_plays, season=2024))
    assert "BAL Defense" in prof
    assert "Wk 1" in prof
    assert "10.00" in prof

    # 5. Regression for filed WSL error err_20261108_194628:
    # "which defense has produced the most fantasy points last week?"
    engine = cli.StatEngine()
    err_q = "which defense has produced the most fantasy points last week?"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(err_q, engine=engine, slm_model="off")
    assert parsed["intent"] == "fantasy_report"
    assert parsed["subquery"] == "leaderboard"
    assert parsed["position"] == "DEF"
    assert parsed["latest_week"] is True

    # Output on SAMPLE_PBP_PLAYS must return D/ST leaderboard with teams, NOT empty "(No matching records found)"
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS))
    assert "Team D/ST Scoring" in out
    assert "Defense" in out
    assert "BAL Defense" in out
    assert "DAL Defense" in out
    assert "(No matching records found)" not in out


def test_reload_pro_football_slm_purges_submodules():
    import sys
    # Verify reload_pro_football_slm reloads all submodules cleanly
    reloaded = cli.reload_pro_football_slm(pull_git=False)
    assert hasattr(reloaded, "calculate_dst_points_allowed_score")
    assert hasattr(reloaded, "compute_team_dst_fantasy_leaders")
    assert hasattr(reloaded, "render_team_dst_fantasy_profile_view")
    assert "pro_football_slm.fantasy" in sys.modules


def test_sportsbook_underdog_leaders_and_error_regression():
    from pro_football_slm.sportsbook import (
        compute_underdog_leaders,
        render_underdog_leaderboard_view,
    )

    # 1. Underdog leaders on SAMPLE_PBP_PLAYS
    leaders = compute_underdog_leaders(cli.SAMPLE_PBP_PLAYS, season=2025, limit=5)
    assert len(leaders) <= 5
    assert len(leaders) > 0
    # TB won as underdog
    tb = next((r for r in leaders if r["team"] == "TB"), None)
    assert tb is not None
    assert tb["su_wins"] == 1
    assert tb["games_as_dog"] == 1
    assert tb["su_win_pct"] == 100.0

    # 2. Rendering view
    board = cli.strip_ansi(render_underdog_leaderboard_view(cli.SAMPLE_PBP_PLAYS, season=2025, limit=5))
    assert "NFL Underdog Performance Leaders: Most Wins as Underdog" in board
    assert "Top 5" in board
    assert "Dog Games" in board
    assert "SU Wins" in board
    assert "TB" in board

    # 3. Regression test for err_20261108_201030:
    # "which team won the most games as an underdog this season?"
    engine = cli.StatEngine()
    err_q = "which team won the most games as an underdog this season?"
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(err_q, engine=engine, slm_model="off")
    assert parsed["intent"] == "sportsbook_report"
    assert parsed["subquery"] == "underdogs"
    assert parsed["limit"] == 5

    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS))
    assert "NFL Underdog Performance Leaders" in out
    assert "Top 5" in out
    assert "SU Wins" in out
    assert "#1" in out
    # Must NOT return full game betting board with Matchup and Total (O/U)
    assert "Total (O/U)" not in out


def test_custom_stat_formula_with_contracts_and_results_for_money_regression(tmp_path):
    """
    Regression test for err_20261108_201746:
    'which player has the best results for the money (yards per game / yearly salary against cap)'
    - Verifies find_contract_by_name handles initial + last name abbreviations (e.g. J.Taylor, A.St. Brown).
    - Verifies BASE_METRIC_KEYS includes cap_hit, yearly_salary_against_cap, yards_per_game.
    - Verifies query parses to intent='create_stat' with group_by='player' and normalized formula.
    - Verifies StatEngine leaderboard evaluation ranks players accurately.
    """
    # 1. Verify contract lookup abbreviation & player preference
    jt = cli.find_contract_by_name("J.Taylor")
    assert jt is not None
    assert jt.name == "Jonathan Taylor"
    assert jt.contract_type == "player"

    asb = cli.find_contract_by_name("A.St. Brown")
    assert asb is not None
    assert asb.name == "Amon-Ra St. Brown"
    assert asb.contract_type == "player"

    # 2. Verify BASE_METRIC_KEYS
    for metric in ("yards_per_game", "yearly_salary_against_cap", "cap_hit", "salary"):
        assert metric in cli.BASE_METRIC_KEYS

    # 3. Query parsing regression test
    query = "which player has the best results for the money (yards per game / yearly salary against cap)"
    engine = cli.StatEngine()
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine=engine, slm_model="off")
    assert parsed["intent"] == "create_stat"
    assert parsed["stat_name"] == "results_for_the_money"
    assert parsed["group_by"] == "player"
    assert parsed["formula"] == "yards_per_game / yearly_salary_against_cap"

    # 4. Stat registration and evaluation
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS, interactive=False))
    assert "Results For The Money" in out
    assert "PLAYER" in out
    assert "Plays" in out
    assert "#1" in out
    assert "X.Worthy" in out


def test_export_last_result_csv_and_json(tmp_path):
    """
    Test export of last query/stat result data to CSV and JSON formats,
    including default extension behavior and error handling when no data exists.
    """
    engine = cli.StatEngine()

    # 1. Evaluate a query that produces a leaderboard table
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("who has the most pass yards", engine=engine, slm_model="off")
    out = cli.handle_nl_query_result(parsed, engine, cli.SAMPLE_PBP_PLAYS)
    assert "Passing Yards" in out

    # 2. Export to CSV
    csv_file = tmp_path / "last_results.csv"
    ok, msg = cli.export_last_result(csv_file)
    assert ok is True
    assert "Exported" in msg
    assert csv_file.exists()
    csv_content = csv_file.read_text(encoding="utf-8")
    assert "Rank" in csv_content
    assert "P.Mahomes" in csv_content

    # 3. Export to JSON
    json_file = tmp_path / "last_results.json"
    ok_json, msg_json = cli.export_last_result(json_file)
    assert ok_json is True
    assert json_file.exists()
    payload = json.loads(json_file.read_text(encoding="utf-8"))
    assert "records" in payload
    assert payload["count"] > 0
    assert payload["records"][0]["QB"] == "P.Mahomes"

    # 4. Export without extension defaults to .csv
    no_ext_file = tmp_path / "query_data_dump"
    ok_no_ext, msg_no_ext = cli.export_last_result(no_ext_file)
    assert ok_no_ext is True
    assert (tmp_path / "query_data_dump.csv").exists()


def test_cli_autocomplete_case_insensitive_and_options(tmp_path):
    """
    Test CLICompleter case-insensitive tab autocompletion:
    - /stat metric names (e.g. 'epa' -> 'epa_per_play', 'PASS' -> 'passing_yards')
    - /team names ('kc' -> 'KC', 'chie' -> 'Chiefs')
    - /player names ('mah' -> 'Mahomes')
    - /export & /export-stats file matching
    - Slash commands ('/ex' -> '/example', '/export', '/export-stats')
    """
    engine = cli.StatEngine()
    completer = cli.CLICompleter(engine=engine)

    # 1. /stat case-insensitive completion
    epa_matches = [c for c in completer.get_candidates("/stat epa", 6, "epa") if c.lower().startswith("epa")]
    assert "epa_per_play" in epa_matches

    pass_matches = [c for c in completer.get_candidates("/stat PASS", 6, "PASS") if c.lower().startswith("pass")]
    assert "passer_rating" in pass_matches
    assert "passing_yards" in pass_matches

    # 2. /team case-insensitive completion
    kc_matches = [c for c in completer.get_candidates("/team kc", 6, "kc") if c.lower().startswith("kc")]
    assert "KC" in kc_matches

    chiefs_matches = [c for c in completer.get_candidates("/team chie", 6, "chie") if c.lower().startswith("chie")]
    assert "Chiefs" in chiefs_matches

    # 3. /player case-insensitive completion
    mah_matches = [c for c in completer.get_candidates("/player mah", 8, "mah") if c.lower().startswith("mah")]
    assert any("Mahomes" in m for m in mah_matches)

    # 4. Slash command matching
    ex_matches = [c for c in completer.get_candidates("/ex", 0, "/ex") if c.lower().startswith("/ex")]
    assert "/export" in ex_matches
    assert "/export-stats" in ex_matches
    assert "/example" in ex_matches

    # 5. File matching for /export
    test_file = tmp_path / "custom_test_export.json"
    test_file.write_text("{}", encoding="utf-8")
    cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        file_matches = completer.get_file_options("custom")
        assert any("custom_test_export.json" in f for f in file_matches)
    finally:
        os.chdir(cwd)

    # 6. Context override for sub-prompts
    completer.set_context("stat")
    ctx_matches = completer.get_candidates("", 0, "epa")
    assert "epa_per_play" in ctx_matches
    completer.set_context(None)


def test_player_drilldown_name_matching_regression():
    """
    Regression test for /player command:
    - Verifies 'Patrick Mahomes' does NOT match unrelated players named 'Patrick' (e.g. Patrick Taylor, Patrick Queen).
    - Verifies get_player_teams does not treat opponents who sacked/intercepted the player as teams played for.
    - Verifies exactly 1 team ('KC') is detected for Patrick Mahomes, auto-selecting without prompting.
    """
    mixed_plays = list(cli.SAMPLE_PBP_PLAYS) + [
        {"season": 2024, "rusher_player_name": "P.Taylor", "posteam": "CHI", "defteam": "GB", "desc": "P.Taylor right guard for 4 yards"},
        {"season": 2024, "player_name": "Patrick Taylor", "posteam": "CHI", "defteam": "GB", "desc": "Patrick Taylor up the middle for 2 yards"},
        {"season": 2024, "player_name": "Patrick Queen", "posteam": "CLE", "defteam": "PIT", "desc": "Patrick Queen tackles N.Harris"},
        {"season": 2024, "player_name": "Lucas Patrick", "posteam": "MIA", "defteam": "BUF", "desc": "Lucas Patrick false start"},
        {"season": 2024, "qb_name": "P.Mahomes", "posteam": "KC", "defteam": "LV", "desc": "P.Mahomes sacked by M.Crosby for -5 yards"},
        {"season": 2024, "qb_name": "P.Mahomes", "posteam": "KC", "defteam": "DEN", "desc": "P.Mahomes pass intercepted by P.Surtain"},
    ]

    # 1. Matching plays must only include Patrick Mahomes, not other Patricks
    m_plays = cli.find_player_plays(mixed_plays, "Patrick Mahomes", season=2024)
    for p in m_plays:
        assert p.get("rusher_player_name") != "P.Taylor"
        assert p.get("player_name") not in ("Patrick Taylor", "Patrick Queen", "Lucas Patrick")

    # 2. Teams played for must be strictly ['KC'], NOT opponent teams (LV, DEN, CHI, CLE, MIA)
    teams = cli.get_player_teams(m_plays, "Patrick Mahomes")
    assert teams == ["KC"]

    # 3. Drilldown view should auto-select KC without prompting
    engine = cli.StatEngine()
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, mixed_plays, season=2024, player_name="Patrick Mahomes", interactive=True))
    assert "PLAYER DRILL-DOWN" in out
    assert "KC (1 team in 2024 — auto-selected)" in out
    assert "CHI" not in out.split("Team:")[1].split("\n")[0]


def test_player_team_associations_all_players_regression(engine):
    """
    Regression test ensuring team associations are properly resolved across ALL players:
    1. Christian McCaffrey (SF) is not conflated with Luke McCaffrey (WAS) or opponent punters/kickers (LA).
    2. Luke McCaffrey (WAS) is attributed to WAS, not LA when returning punts.
    3. Aaron Jones (MIN) is not conflated with Chris Jones (KC).
    4. Traded players (e.g. Davante Adams across LV and NYJ) properly retain all genuine teams.
    5. Stray noise (1 edge-case play out of many) is filtered out.
    """
    comprehensive_plays = [
        # Christian McCaffrey on SF
        {"season": 2026, "posteam": "SF", "defteam": "NYJ", "rusher_player_name": "C.McCaffrey", "desc": "(14:22) 23-C.McCaffrey up the middle for 4 yards"},
        {"season": 2026, "posteam": "SF", "defteam": "ARI", "receiver_player_name": "C.McCaffrey", "desc": "(10:15) 13-B.Purdy pass short to 23-C.McCaffrey for 13 yards"},
        # Luke McCaffrey on WAS
        {"season": 2026, "posteam": "SF", "defteam": "WAS", "desc": "18-E.Pineiro kicks 62 yards to WAS 3. 11-L.McCaffrey to WAS 28 for 25 yards"},
        {"season": 2026, "posteam": "WAS", "defteam": "SF", "receiver_player_name": "L.McCaffrey", "desc": "5-J.Daniels pass incomplete to 11-L.McCaffrey"},
        {"season": 2026, "posteam": "LA", "defteam": "WAS", "desc": "42-E.Evans punts 52 yards. 11-L.McCaffrey to WAS 24 for 9 yards"},
        # Aaron Jones on MIN
        {"season": 2026, "posteam": "MIN", "defteam": "GB", "rusher_player_name": "A.Jones", "desc": "33-A.Jones right tackle for 8 yards"},
        {"season": 2026, "posteam": "MIN", "defteam": "CHI", "receiver_player_name": "A.Jones", "desc": "14-S.Darnold pass short middle to 33-A.Jones for 12 yards"},
        # Chris Jones on KC
        {"season": 2026, "posteam": "LV", "defteam": "KC", "sack_player_name": "C.Jones", "desc": "G.Minshew sacked by 95-C.Jones for -8 yards"},
        {"season": 2026, "posteam": "KC", "defteam": "DEN", "penalty_player_name": "C.Jones", "penalty_team": "KC", "desc": "PENALTY on KC-95-C.Jones, Roughing Passer"},
        # Traded player (Davante Adams: LV and NYJ)
        {"season": 2026, "posteam": "LV", "defteam": "LAC", "receiver_player_name": "D.Adams", "desc": "17-D.Adams 15 yd catch"},
        {"season": 2026, "posteam": "LV", "defteam": "BAL", "receiver_player_name": "D.Adams", "desc": "17-D.Adams 25 yd catch"},
        {"season": 2026, "posteam": "NYJ", "defteam": "NE", "receiver_player_name": "D.Adams", "desc": "17-D.Adams 12 yd catch"},
        {"season": 2026, "posteam": "NYJ", "defteam": "HOU", "receiver_player_name": "D.Adams", "desc": "17-D.Adams 18 yd catch"},
    ]

    # 1. Christian McCaffrey -> Strictly ['SF']
    cmc_plays = cli.find_player_plays(comprehensive_plays, "Christian McCaffrey", season=2026)
    cmc_teams = cli.get_player_teams(cmc_plays, "Christian McCaffrey")
    assert cmc_teams == ["SF"], f"Expected ['SF'], got {cmc_teams}"

    # 2. Luke McCaffrey -> Strictly ['WAS'] (punt return from LA goes to WAS defteam)
    luke_plays = cli.find_player_plays(comprehensive_plays, "Luke McCaffrey", season=2026)
    luke_teams = cli.get_player_teams(luke_plays, "Luke McCaffrey")
    assert luke_teams == ["WAS"], f"Expected ['WAS'], got {luke_teams}"

    # 3. Aaron Jones -> Strictly ['MIN'], NOT KC
    aj_plays = cli.find_player_plays(comprehensive_plays, "Aaron Jones", season=2026)
    aj_teams = cli.get_player_teams(aj_plays, "Aaron Jones")
    assert aj_teams == ["MIN"], f"Expected ['MIN'], got {aj_teams}"

    # 4. Chris Jones -> Strictly ['KC'], NOT MIN or LV
    cj_plays = cli.find_player_plays(comprehensive_plays, "Chris Jones", season=2026)
    cj_teams = cli.get_player_teams(cj_plays, "Chris Jones")
    assert cj_teams == ["KC"], f"Expected ['KC'], got {cj_teams}"

    # 5. Traded player (Davante Adams) -> Both ['LV', 'NYJ']
    adams_plays = cli.find_player_plays(comprehensive_plays, "Davante Adams", season=2026)
    adams_teams = cli.get_player_teams(adams_plays, "Davante Adams")
    assert adams_teams == ["LV", "NYJ"], f"Expected ['LV', 'NYJ'], got {adams_teams}"

    # 6. Spurious noise filter test: 20 genuine plays for SF and 1 stray description play on SEA
    noise_plays = [
        {"season": 2026, "posteam": "SF", "defteam": "ARI", "rusher_player_name": "C.McCaffrey", "desc": "C.McCaffrey rush"}
        for _ in range(20)
    ] + [
        {"season": 2026, "posteam": "SEA", "defteam": "LAR", "desc": "Review play involving McCaffrey on sideline"}
    ]
    sf_plays = cli.find_player_plays(noise_plays, "Christian McCaffrey", season=2026)
    sf_teams = cli.get_player_teams(sf_plays, "Christian McCaffrey")
    assert sf_teams == ["SF"], f"Stray 1-play noise should be filtered out, got {sf_teams}"


def test_generic_team_disambiguation(monkeypatch, engine):
    """
    Test generic team disambiguation for cities with multiple teams (New York, Los Angeles).
    """
    # 1. Multiple matching teams for 'New York' (NYG and NYJ)
    ny_matches = cli.resolve_team_matches("New York")
    assert "NYG" in ny_matches and "NYJ" in ny_matches
    assert len(ny_matches) == 2

    # 2. Multiple matching teams for 'Los Angeles' (LA and LAC)
    la_matches = cli.resolve_team_matches("Los Angeles")
    assert "LA" in la_matches and "LAC" in la_matches
    assert len(la_matches) == 2

    # 3. Exact single team match (Chiefs -> KC, Giants -> NYG, Jets -> NYJ)
    assert cli.resolve_team_matches("Chiefs") == ["KC"]
    assert cli.resolve_team_matches("Giants") == ["NYG"]
    assert cli.resolve_team_matches("Jets") == ["NYJ"]

    # 4. Interactive selection prompts user: simulate choosing option 2 (NYJ)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "2")
    selected = cli.resolve_team_interactive("New York", interactive=True)
    assert selected == "NYJ"

    # Simulate choosing option 1 (NYG)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "1")
    selected_1 = cli.resolve_team_interactive("New York", interactive=True)
    assert selected_1 == "NYG"

    # Non-interactive defaults to first match without prompting
    non_int = cli.resolve_team_interactive("New York", interactive=False)
    assert non_int in ("NYG", "NYJ")


def test_generic_player_disambiguation(monkeypatch, engine):
    """
    Test generic player candidate discovery and interactive disambiguation when surname matches multiple players.
    """
    multi_player_plays = [
        {"season": 2026, "posteam": "SF", "defteam": "NYJ", "rusher_player_name": "C.McCaffrey", "desc": "C.McCaffrey 4 yd run"},
        {"season": 2026, "posteam": "SF", "defteam": "ARI", "receiver_player_name": "C.McCaffrey", "desc": "C.McCaffrey 13 yd catch"},
        {"season": 2026, "posteam": "WAS", "defteam": "SF", "receiver_player_name": "L.McCaffrey", "desc": "5-J.Daniels pass to 11-L.McCaffrey"},
        {"season": 2026, "posteam": "LA", "defteam": "WAS", "desc": "42-E.Evans punts. 11-L.McCaffrey to WAS 24 for 9 yards"},
    ]

    # 1. find_matching_player_candidates discovers both McCaffreys
    cands = cli.find_matching_player_candidates(multi_player_plays, "McCaffrey", season=2026)
    assert len(cands) == 2
    names = [c["name"] for c in cands]
    assert "Christian McCaffrey" in names
    assert any("L.McCaffrey" in n or "Luke" in n for n in names)

    # 2. When query is already specific (e.g. 'Christian McCaffrey'), no candidates returned
    assert cli.find_matching_player_candidates(multi_player_plays, "Christian McCaffrey", season=2026) == []

    # 3. When single candidate exists in dataset (e.g. 'Mahomes')
    single_cands = cli.find_matching_player_candidates(cli.SAMPLE_PBP_PLAYS, "Mahomes", season=2025)
    assert len(single_cands) == 1
    assert "Mahomes" in single_cands[0]["name"]

    # 4. Interactive disambiguation in render_player_drilldown_view
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    # Simulate user picking candidate 1 (Christian McCaffrey)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "1")
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, multi_player_plays, season=2026, player_name="McCaffrey", interactive=True))
    assert "PLAYER DRILL-DOWN" in out
    assert "SF" in out

    # Non-interactive defaults cleanly to top candidate
    out_non_int = cli.strip_ansi(cli.render_player_drilldown_view(engine, multi_player_plays, season=2026, player_name="McCaffrey", interactive=False))
    assert "PLAYER DRILL-DOWN" in out_non_int














