"""Follow-up to #6 (tracked in #43): ambiguity / unknown-name guard outside the NL handler."""
import sys

import pytest

import nfl_stat_cli as cli

SEASON = 2025


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


@pytest.fixture
def plays(tmp_path):
    return cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline").load_pbp([2024, 2025])


def _ask(engine, plays, query):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off", default_season=SEASON)
    return parsed, cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))


MULTI = [
    {"season": 2026, "game_id": "g1", "posteam": "SF", "defteam": "NYJ", "rusher_player_name": "C.McCaffrey",
     "player_name": "C.McCaffrey", "rush_attempt": 1, "yards_gained": 4.0, "play_id": 1, "desc": "C.McCaffrey 4 yd run"},
    {"season": 2026, "game_id": "g2", "posteam": "WAS", "defteam": "SF", "receiver_player_name": "L.McCaffrey",
     "player_name": "L.McCaffrey", "pass_attempt": 1, "complete_pass": 1, "yards_gained": 9.0, "play_id": 2,
     "desc": "5-J.Daniels pass to 11-L.McCaffrey"},
]


@pytest.mark.parametrize("interactive", [False, True])
def test_render_lists_candidates_instead_of_picking_first(engine, monkeypatch, interactive):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, MULTI, season=2026, player_name="McCaffrey", interactive=interactive))
    assert "I can't answer that" in out
    assert "Christian McCaffrey" in out and "Luke McCaffrey" in out
    assert "PLAYER DRILL-DOWN" not in out


@pytest.mark.parametrize("answer", ["", "0", "9", "abc"])
def test_interactive_blank_or_invalid_choice_is_not_defaulted_to_first(engine, monkeypatch, answer):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: answer)
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, MULTI, season=2026, player_name="McCaffrey", interactive=True))
    assert "I can't answer that" in out and "PLAYER DRILL-DOWN" not in out


def test_interactive_eof_is_not_defaulted_to_first(engine, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def eof(prompt):
        raise EOFError

    monkeypatch.setattr(cli, "prompt_input", eof)
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, MULTI, season=2026, player_name="McCaffrey", interactive=True))
    assert "I can't answer that" in out


def test_explicit_choice_and_full_name_still_work(engine, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "2")
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, MULTI, season=2026, player_name="McCaffrey", interactive=True))
    assert "PLAYER DRILL-DOWN" in out and "WAS" in out
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, MULTI, season=2026, player_name="Christian McCaffrey", interactive=False))
    assert "PLAYER DRILL-DOWN" in out


def test_player_subcommand_lists_candidates(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli.NFLDataBridge, "load_pbp", lambda self, *a, **k: list(MULTI))
    cli.main(["player", "McCaffrey", "--engine", "offline", "--season", "2026", "--no-color"])
    out = cli.strip_ansi(capsys.readouterr().out)
    assert "I can't answer that" in out and "Christian McCaffrey" in out and "Luke McCaffrey" in out
    assert "PLAYER DRILL-DOWN" not in out


def test_unknown_player_in_render_is_cant_answer(engine, plays):
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, plays, season=SEASON, player_name="Zorblax", interactive=False))
    assert "I can't answer that" in out


def test_team_subcommand_does_not_silently_pick_first_of_several(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cli.main(["team", "New York", "--engine", "offline", "--season", "2025", "--no-color"])
    out = cli.strip_ansi(capsys.readouterr().out)
    assert "I can't answer that" in out and "NYG" in out and "NYJ" in out


@pytest.mark.parametrize("query", [
    "Zorblax passing yards",
    "Zorblax epa per play",
    "passing yards for Zorblax",
    "how many passing yards does Zorblax have",
    "Zorblax Smith rushing yards",
    "Josh Zorblax passing yards",
])
def test_unknown_player_in_leaderboard_query_is_cant_answer(engine, plays, query):
    parsed, out = _ask(engine, plays, query)
    assert "I can't answer that" in out, query
    assert "Zorblax" in out
    assert "Passing Yards (Pass Yds)" not in out


@pytest.mark.parametrize("query", [
    "Mahomes passing yards",
    "Top 5 QBs by EPA per play",
    "Which team has the most sacks",
    "Who leads the NFL in passing yards",
    "What is Josh Allen's rushing yards",
    "Tell me about Patrick Mahomes yards per attempt",
    "Passing yards for Lamar Jackson",
    "Compare Chiefs and Bills EPA per play",
    "Jacksonville passing yards",
    "Detroit Lions rushing yards",
    "Highest EPA in the Red Zone",
    "Passing Yards Leaders This Season",
    "passing yards",
])
def test_known_players_teams_and_plain_questions_still_answer(engine, plays, query):
    parsed, out = _ask(engine, plays, query)
    assert "I can't answer that" not in out, query


def test_player_with_no_matching_plays_is_not_answered_from_everyone_else(engine, plays):
    parsed = {"intent": "stat_query", "query": "passing yards", "season": SEASON, "stat_name": "passing_yards",
              "player": "nobodyhere", "team": None, "group_by": None}
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    assert "I can't answer that" in out and "nobodyhere" in out
