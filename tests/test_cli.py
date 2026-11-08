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
