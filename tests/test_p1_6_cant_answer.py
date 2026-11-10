"""Golden tests: unsupported/ambiguous questions get an explicit can't-answer; supported ones still answer (issue #6)."""
import pytest

import pro_football_slm as cli

SEASON = 2025


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


@pytest.fixture
def plays(tmp_path):
    return cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline").load_pbp([2024, 2025])


def _ask(engine, plays, query):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query(query, engine, slm_model="off", default_season=SEASON)
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    return parsed, out


# (question, exact reason in the can't-answer response)
UNANSWERABLE = [
    ("Justin Jefferson targets",
     "`targets` is not a stat this engine tracks. Type /stats to see supported stats."),
    ("how many receptions did Kelce have",
     "`receptions` is not a stat this engine tracks. Type /stats to see supported stats."),
    ("Justin Jefferson receiving yards",
     "`receiving yards/touchdowns` is not a stat this engine tracks. Type /stats to see supported stats."),
    ("Henry yards after contact",
     "`yards after contact` is not a stat this engine tracks. Type /stats to see supported stats."),
    ("compare Mahomes and Allen",
     "side-by-side player comparisons are not supported yet; ask about one player or stat at a time."),
    ("Josh Allen vs Patrick Mahomes",
     "side-by-side player comparisons are not supported yet; ask about one player or stat at a time."),
    ("who is the head coach",
     "no team was given for the coaching question; name a team (e.g. 'head coach of the Chiefs')."),
    ("best flurbo",
     "the question did not match any supported stat, play, or action."),
    ("who will win the super bowl",
     "the question did not match any supported stat, play, or action."),
]


@pytest.mark.parametrize("query,reason", UNANSWERABLE)
def test_unanswerable_gets_explicit_cant_answer(engine, plays, query, reason):
    parsed, out = _ask(engine, plays, query)
    assert parsed["intent"] == "ambiguous"
    assert parsed["status"] == "unanswered"
    assert parsed["reason"] == reason
    assert f"I can't answer that: {reason}" in out
    assert "Unsupported or ambiguous query" in out
    # none of the old confident-wrong answers
    for wrong in ("COACHING STAFF", "Passing Yards (Pass Yds)", "Yards / Play", "Dennis Allen"):
        assert wrong not in out


def test_coach_table_does_not_hijack_player_surnames(engine, plays):
    for q in ("Justin Jefferson targets", "compare Mahomes and Allen"):
        parsed, _ = _ask(engine, plays, q)
        assert parsed["intent"] != "coaching_staff"


# Supported questions: (question) -> (intent, stat_name, group_by, team, expected text in the rendered answer)
SUPPORTED = [
    ("passing yards leaders", "stat_query", "passing_yards", "qb", None, "#1 │ P.Mahomes │  KC  │ AFC  │                76.00 yds"),
    ("top 5 qbs by passer rating", "stat_query", "passer_rating", "qb", None, "#1 │ P.Mahomes │  KC  │ AFC  │        158.33 rtg"),
    ("epa per play", "stat_query", "epa_per_play", "qb", None, "#1 │ J.Goff    │ DET  │ NFC  │"),
    ("who is the head coach of the Chiefs", "coaching_staff", None, None, "KC", "Head Coach: Andy Reid"),
    ("head coach of the Bills", "coaching_staff", None, None, "BUF", "Head Coach: Sean McDermott"),
    ("contract of Patrick Mahomes", "contract_report", None, None, None, "Average Per Year (APY):   $45.00M / season"),
]


@pytest.mark.parametrize("query,intent,stat,group,team,expected", SUPPORTED)
def test_supported_questions_still_answer_exactly(engine, plays, query, intent, stat, group, team, expected):
    parsed, out = _ask(engine, plays, query)
    assert parsed["intent"] == intent
    assert parsed.get("stat_name") == stat
    assert parsed.get("group_by") == group
    assert parsed.get("team") == team
    assert "I can't answer that" not in out
    assert expected in out


def test_sportsbook_vs_query_is_not_blocked(engine, plays):
    parsed, out = _ask(engine, plays, "spread for chiefs vs bills")
    assert parsed["intent"] == "sportsbook_report"
    assert "I can't answer that" not in out


def test_coach_surname_still_resolves_in_coaching_context(engine, plays):
    parsed, out = _ask(engine, plays, "which team does coach McDermott lead")
    assert parsed["intent"] == "coaching_staff" and parsed["team"] == "BUF"


def test_unknown_player_play_request_does_not_fall_back_to_mahomes(engine, plays):
    parsed, out = _ask(engine, plays, "show Zorblax touchdown play")
    assert parsed["player"] == "Zorblax"
    assert "No matching play found" in out
    assert "Mahomes" not in out


def test_missing_entities_do_not_default_to_kc_or_mahomes(engine, plays):
    for intent in ("coaching_staff", "team_drilldown", "player_drilldown"):
        parsed = {"intent": intent, "query": "q", "season": SEASON, "team": None, "player": None, "stat_name": None}
        out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
        assert "I can't answer that" in out, intent
        assert "Kansas City" not in out and "COACHING STAFF" not in out and "DRILL-DOWN" not in out
    sb = {"intent": "sportsbook_report", "subquery": "matchup", "query": "q", "season": SEASON, "team": "KC", "stat_name": None}
    assert "I can't answer that" in cli.strip_ansi(cli.handle_nl_query_result(sb, engine, plays))
    ct = {"intent": "contract_report", "subquery": "team", "query": "q", "season": SEASON, "team": None, "stat_name": None}
    assert "I can't answer that" in cli.strip_ansi(cli.handle_nl_query_result(ct, engine, plays))


def test_unknown_stat_does_not_default_to_yards_per_play(engine, plays):
    parsed = {"intent": "stat_query", "query": "q", "season": SEASON, "stat_name": "not_a_real_stat", "group_by": "qb"}
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    assert "I can't answer that" in out and "`not_a_real_stat` is not a registered stat" in out
    parsed["stat_name"] = None
    assert "I can't answer that" in cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))


def test_unknown_team_staff_is_not_kc(engine):
    assert cli.get_team_coaching_staff("ZZZ") == {}
    assert cli.get_team_head_coach("ZZZ") == "Unknown Coach"


def test_ambiguous_player_in_noninteractive_nl_asks_instead_of_picking_first(engine):
    bridge_rows = [
        {"season": 2026, "game_id": "g1", "posteam": "SF", "defteam": "DAL", "qb_name": "B.Purdy",
         "rusher_player_name": "C.McCaffrey", "player_name": "C.McCaffrey", "rush_attempt": 1, "yards_gained": 5.0, "play_id": 1},
        {"season": 2026, "game_id": "g2", "posteam": "WAS", "defteam": "DAL", "qb_name": "J.Daniels",
         "receiver_player_name": "L.McCaffrey", "player_name": "L.McCaffrey", "pass_attempt": 1, "complete_pass": 1, "yards_gained": 9.0, "play_id": 2},
    ]
    parsed = {"intent": "player_drilldown", "query": "mccaffrey", "season": 2026, "player": "McCaffrey", "team": None, "stat_name": None}
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, bridge_rows, interactive=False))
    assert "I can't answer that" in out
    assert "matches several players" in out


def test_compare_guard_uses_word_boundaries(engine, plays):
    # "better" contains "bet" and "between" contains "bet"; neither is a sportsbook term
    for q in ("compare Mahomes and Allen, who is better", "compare Mahomes and Allen between weeks"):
        parsed, out = _ask(engine, plays, q)
        assert parsed["intent"] == "ambiguous" and parsed["status"] == "unanswered", q
        assert "side-by-side player comparisons" in out


def test_player_and_coach_sharing_a_surname_is_not_guessed(engine, plays):
    parsed, out = _ask(engine, plays, "which team does coach Allen lead")
    assert parsed["intent"] == "ambiguous"
    assert "'Allen' is both a player and a coach name" in parsed["reason"]
    assert "COACHING STAFF" not in out


def test_unsupported_terms_do_not_block_supported_neighbours(engine, plays):
    # singular position words / fantasy per-reception scoring are not "receptions" questions
    parsed, out = _ask(engine, plays, "highest paid left tackle")
    assert parsed["intent"] == "contract_report"
    assert "I can't answer that" not in out
    parsed, _ = _ask(engine, plays, "ppr fantasy points per reception leaders")
    assert parsed["intent"] == "fantasy_report"


def test_cant_answer_output_has_no_terminal_escapes(engine, plays):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("best \x1b[31mflurbo\x1b[0m", engine, slm_model="off", default_season=SEASON)
    out = cli.handle_nl_query_result(parsed, engine, plays)
    assert "flurbo" in out
    assert "\x1b[31mflurbo" not in out


def test_reason_text_is_sanitized_when_rendered(engine, plays):
    parsed = {"intent": "player_drilldown", "query": "q", "season": SEASON, "team": None, "stat_name": None,
              "player": "\x1b[31mevil\x1b]0;x\x07"}
    rows = [
        {"season": SEASON, "game_id": "g1", "posteam": "SF", "defteam": "DAL", "qb_name": "B.Purdy",
         "rusher_player_name": "\x1b[31mevil\x1b]0;x\x07 One", "player_name": "x", "rush_attempt": 1, "yards_gained": 5.0, "play_id": 1},
    ]
    out = cli.handle_nl_query_result({**parsed, "intent": "ambiguous", "reason": "bad \x1b[31mred\x1b[0m \x07 name\r\nx"}, engine, rows)
    assert "\x07" not in out and "\r" not in out and "\x1b[31mred" not in out
    assert "bad" in out and "name" in out


def test_unique_player_and_team_still_drill_down_non_interactively(engine, plays):
    parsed, out = _ask(engine, plays, "stats for Mahomes")
    assert parsed["intent"] == "player_drilldown"
    assert "I can't answer that" not in out and "No plays found" not in out
    parsed, out = _ask(engine, plays, "team stats for Chiefs")
    assert parsed["intent"] == "team_drilldown" and parsed["team"] == "KC"
    assert "I can't answer that" not in out


def test_team_city_in_a_play_request_is_not_treated_as_an_unknown_player(engine, plays):
    for q in ("show Dallas touchdown play", "show Chicago touchdown play", "show Kansas touchdown play"):
        parsed, _ = _ask(engine, plays, q)
        assert parsed["intent"] == "specific_play"
        assert parsed["player"] != q.split()[1], q


def test_compare_guard_not_bypassed_by_offensive_line(engine, plays):
    parsed, _ = _ask(engine, plays, "compare Mahomes and Allen behind the offensive line")
    assert parsed["intent"] == "ambiguous" and "side-by-side" in parsed["reason"]
