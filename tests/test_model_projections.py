"""Issue #14: Model Projections wording, disclaimer, explain/formula output, and the season look-ahead fix."""
import ast
import inspect
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import sportsbook as sb

ROOT = Path(__file__).resolve().parent.parent

DISCLAIMER = (
    "Statistical model projections for analysis and entertainment. Not betting advice. "
    "We don't take bets or link to sportsbooks, and we aren't affiliated with the NFL."
)
MARGIN_LABEL = "Includes a modeled 2.5% margin (typical market hold)"

# Words that must not appear in user-facing projection text (the required disclaimer itself is exempt).
BANNED = re.compile(
    r"\b(?:picks?|locks?|edges?|beat the book|winning bets?|handicapp\w*|vegas|sportsbooks?|betting|wagers?|gambl\w*|"
    r"ats|covers?|covered|over/under|bets?)\b",
    re.I,
)


def _clean(text):
    return cli.strip_ansi(text).replace(DISCLAIMER, "")


def _play(season, week, home, away, posteam, epa, home_score, away_score, play_id):
    defteam = away if posteam == home else home
    return {
        "season": season, "week": week, "qtr": 1, "play_id": play_id,
        "game_id": f"{season}_{week:02d}_{away}_{home}",
        "posteam": posteam, "defteam": defteam, "epa": epa, "series_success": 1,
        "home_score": home_score, "away_score": away_score,
    }


@pytest.fixture
def season_plays():
    """Three weeks, four teams, a few plays each (synthetic)."""
    plays = []
    pid = 0

    def add(week, home, away, hs, as_, e_home, e_away):
        nonlocal pid
        for _ in range(3):
            pid += 1
            plays.append(_play(2025, week, home, away, home, e_home, hs, as_, pid))
            pid += 1
            plays.append(_play(2025, week, home, away, away, e_away, hs, as_, pid))

    add(1, "AAA", "BBB", 27, 17, 0.20, -0.10)
    add(1, "CCC", "DDD", 10, 24, -0.15, 0.25)
    add(2, "BBB", "CCC", 20, 23, 0.05, 0.10)
    add(2, "DDD", "AAA", 30, 14, 0.30, -0.20)
    add(3, "AAA", "CCC", 21, 17, 0.10, 0.00)
    add(3, "BBB", "DDD", 13, 31, -0.05, 0.40)
    return plays


# --- exact required text ---------------------------------------------------------------------

def test_disclaimer_constant_is_the_required_text():
    assert sb.PROJECTIONS_DISCLAIMER == DISCLAIMER
    assert sb.PROJECTIONS_TITLE == "Model Projections"


def test_disclaimer_sits_above_the_board_and_every_projection_view(season_plays):
    views = {
        "board": sb.render_sportsbook_board_view(season_plays, 2025),
        "power": sb.render_power_ratings_view(season_plays, 2025),
        "dogs": sb.render_underdog_leaderboard_view(season_plays, 2025),
        "dossier": sb.render_game_handicap_dossier_view("AAA", "BBB", season_plays, 2025),
        "explain": sb.render_model_explanation(),
    }
    for name, text in views.items():
        clean = cli.strip_ansi(text)
        assert DISCLAIMER in clean, name
        first_table_line = min((clean.find(m) for m in ("┌", "╔", "HOW MODEL") if m in clean), default=len(clean))
        assert clean.index(DISCLAIMER) < first_table_line, name


def test_projections_menu_shows_disclaimer_and_explain_option(season_plays, monkeypatch, capsys):
    answers = iter(["5", "q"])
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: next(answers))
    sb.interactive_sportsbook_browser(season_plays, 2025)
    out = cli.strip_ansi(capsys.readouterr().out)
    assert DISCLAIMER in out
    assert out.index(DISCLAIMER) < out.index("Select Browsing Mode")
    assert "HOW MODEL PROJECTIONS ARE COMPUTED" in out
    assert not BANNED.search(out.replace(DISCLAIMER, ""))


# --- wording ---------------------------------------------------------------------------------

def test_user_facing_projection_text_avoids_banned_words(season_plays):
    texts = [
        sb.render_sportsbook_board_view(season_plays, 2025),
        sb.render_sportsbook_board_view(season_plays, 2025, week_filter=2),
        sb.render_power_ratings_view(season_plays, 2025),
        sb.render_underdog_leaderboard_view(season_plays, 2025),
        sb.render_game_handicap_dossier_view("AAA", "BBB", season_plays, 2025),
        sb.render_game_handicap_dossier_view("AAA", "ZZZ", season_plays, 2025),
        sb.render_model_explanation(),
    ]
    for t in texts:
        found = BANNED.findall(_clean(t))
        assert not found, found


def test_every_string_literal_in_the_module_avoids_banned_words():
    """Static guard: no new user-facing literal (outside identifiers and the required disclaimer) uses the old framing."""
    tree = ast.parse((ROOT / "nfl_stat_cli" / "sportsbook.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.replace(DISCLAIMER, "")
            # the disclaimer is assembled from two literals; exempt its two halves
            if text in (DISCLAIMER.split("Not betting advice. ")[0] + "Not betting advice. ",
                        "We don't take bets or link to sportsbooks, and we aren't affiliated with the NFL."):
                continue
            if BANNED.search(text):
                offenders.append(text[:80])
    assert not offenders, offenders


def test_nl_explanations_and_help_use_projection_wording():
    engine = cli.StatEngine(storage_dir=_tmp_storage())
    for q in ("spread for chiefs vs bills", "nfl power ratings", "odds for week 4"):
        parsed = cli.NaturalLanguageStatAssistant.interpret_query(q, engine=engine, slm_model="off")
        assert parsed["intent"] == "sportsbook_report"
        assert not BANNED.search(parsed.get("explanation", "")), parsed["explanation"]
    help_text = cli.strip_ansi(cli.render_slash_help())
    assert "/projections" in help_text and "/explain" in help_text
    assert "/sportsbook" not in help_text
    proj_lines = [l for l in help_text.splitlines() if "/projections" in l or "/explain" in l]
    assert proj_lines and not any(BANNED.search(l) for l in proj_lines)


def _tmp_storage():
    import tempfile
    return Path(tempfile.mkdtemp(prefix="nfl-proj-"))


def test_even_line_is_not_called_pickem():
    ratings = {"H": {"power_rating": 0.0, "off_epa": 0, "def_epa": 0}, "A": {"power_rating": 0.0, "off_epa": 0, "def_epa": 0}}
    old = sb.HOME_FIELD_ADVANTAGE_PTS
    try:
        sb.HOME_FIELD_ADVANTAGE_PTS = 0.0
        hc = sb.handicap_matchup("H", "A", ratings)
    finally:
        sb.HOME_FIELD_ADVANTAGE_PTS = old
    assert hc["favorite_str"] == "EVEN (0.0)"
    assert "pick" not in hc["favorite_str"].lower()


# --- numbers are unchanged (including the modeled margin) -------------------------------------

@pytest.mark.parametrize("p,expected", [(0.5, (-105, -105)), (0.7, (-254, 225)), (0.99, (-4900, 9656)), (0.01, (9656, -4900))])
def test_moneyline_values_are_unchanged(p, expected):
    assert sb.calculate_american_moneyline(p) == expected


def test_matchup_golden_numbers():
    hc = sb.explanation_example()
    assert (hc["spread"], hc["total"], hc["home_ml"], hc["away_ml"], hc["home_win_prob"]) == (-5.0, 46.0, -190, 170, 63.9)
    assert hc["proj_home_score"] == 25.5 and hc["proj_away_score"] == 20.5


def test_margin_label_comes_from_the_constant(season_plays, monkeypatch):
    assert sb.modeled_margin_label() == MARGIN_LABEL
    assert sb.modeled_margin_pct() == 2.5
    monkeypatch.setattr(sb, "MONEYLINE_MARGIN_FACTOR", 1.045)
    label = sb.modeled_margin_label()
    assert label == "Includes a modeled 4.5% margin (typical market hold)"
    for text in (sb.render_sportsbook_board_view(season_plays, 2025),
                 sb.render_game_handicap_dossier_view("AAA", "BBB", season_plays, 2025),
                 sb.render_model_explanation()):
        assert label in cli.strip_ansi(text)
        assert MARGIN_LABEL not in cli.strip_ansi(text)
    # and the numbers really move with the same constant
    assert sb.calculate_american_moneyline(0.5) == (-109, -109)


def test_label_is_shown_wherever_moneylines_are_shown(season_plays):
    for text in (sb.render_sportsbook_board_view(season_plays, 2025),
                 sb.render_game_handicap_dossier_view("AAA", "BBB", season_plays, 2025),
                 sb.render_model_explanation()):
        assert MARGIN_LABEL in cli.strip_ansi(text)


# --- model accuracy framing ------------------------------------------------------------------

def test_backtest_is_presented_as_model_accuracy(season_plays):
    board = cli.strip_ansi(sb.render_sportsbook_board_view(season_plays, 2025))
    assert "Model accuracy vs. actual results (6 completed games)" in board
    assert "Model vs. Actual" in board
    assert re.search(r"projected winner \d+/6", board)
    assert "above projection" in board or "At projection" in board
    hc = sb.handicap_matchup("H", "A", {"H": {"power_rating": 3.0}, "A": {"power_rating": 0.0}}, home_score=30, away_score=10)
    assert hc["ats_result"] == "H above projection"
    assert hc["ou_result"].startswith("Below projected total (40 vs ") or hc["ou_result"].startswith("Above projected total (40 vs ")
    assert sb.summarize_model_accuracy([]) is None
    assert sb.render_accuracy_line(None) == ""


def test_accuracy_summary_math():
    rows = [
        {"actual_margin": 7, "expected_margin": 3.0, "actual_total": 40, "total": 44.0},
        {"actual_margin": -3, "expected_margin": 4.0, "actual_total": 50, "total": 44.0},
        {"actual_margin": None, "expected_margin": 1.0, "actual_total": None, "total": 40.0},
    ]
    s = sb.summarize_model_accuracy(rows)
    assert s["games"] == 2 and s["winner_correct"] == 1 and s["winner_pct"] == 50.0
    assert s["avg_margin_error"] == 5.5 and s["avg_total_error"] == 5.0


# --- season look-ahead (#24-compatible) ------------------------------------------------------

def test_power_ratings_filter_to_the_requested_season_first():
    src = inspect.getsource(sb.compute_team_power_ratings)
    tree = ast.parse(textwrap.dedent(src))
    body = tree.body[0].body
    assert isinstance(body[0], ast.Expr)                      # docstring
    assert isinstance(body[1], ast.ImportFrom) and body[1].names[0].name == "plays_for_season"
    assign = body[2]
    assert isinstance(assign, ast.Assign) and ast.unparse(assign) == "plays = plays_for_season(plays, season)"


def test_mixed_seasons_do_not_leak_into_ratings():
    plays = [
        _play(2024, 1, "HHH", "AAA", "HHH", 0.50, 30, 10, 1),
        _play(2024, 1, "HHH", "AAA", "AAA", -0.50, 30, 10, 2),
        _play(2025, 1, "HHH", "AAA", "HHH", -0.20, 10, 24, 1),
        _play(2025, 1, "HHH", "AAA", "AAA", 0.20, 10, 24, 2),
    ]
    only25 = [p for p in plays if p["season"] == 2025]
    assert sb.compute_team_power_ratings(plays, 2025) == sb.compute_team_power_ratings(only25, 2025)
    assert sb.compute_team_power_ratings(plays, 2023) == {}


def test_a_games_projection_ignores_its_own_and_later_weeks(season_plays):
    base = sb.render_sportsbook_board_view(season_plays, 2025, week_filter=2)
    # Rewrite the results of week 2 itself and of week 3: the week-2 projections must not move.
    altered = []
    for p in season_plays:
        q = dict(p)
        if q["week"] >= 2:
            q["epa"] = q["epa"] + 5.0
            q["home_score"], q["away_score"] = q["away_score"], q["home_score"]
        altered.append(q)
    alt = sb.render_sportsbook_board_view(altered, 2025, week_filter=2)
    cut = lambda t: [l for l in cli.strip_ansi(t).splitlines() if l.startswith("│") and "Wk 2" in l]
    # compare the projected columns (everything before the Actual / result columns)
    proj = lambda rows: ["│".join(r.split("│")[1:7]) for r in rows]
    assert proj(cut(base)) and proj(cut(base)) == proj(cut(alt))
    # and truncating the data after week 1 changes nothing either
    truncated = sb.render_sportsbook_board_view([p for p in season_plays if p["week"] <= 2], 2025, week_filter=2)
    assert proj(cut(truncated)) == proj(cut(base))


def test_week_one_uses_no_prior_games_and_pregame_helper(season_plays):
    pre = sb.PregameRatings(season_plays, 2025)
    assert pre.for_week(1) == {}
    assert set(pre.for_week(2)) == {"AAA", "BBB", "CCC", "DDD"}
    assert pre.for_week(3) == sb.compute_team_power_ratings([p for p in season_plays if p["week"] < 3], 2025)
    assert pre.for_week(None) == sb.compute_team_power_ratings(season_plays, 2025)
    assert sb.plays_before_week(season_plays, 2025, 1) == []
    hc = sb.handicap_matchup("AAA", "BBB", pre.for_week(1))
    assert hc["expected_margin"] == sb.HOME_FIELD_ADVANTAGE_PTS


def test_underdog_leaders_use_pregame_ratings(season_plays, monkeypatch):
    seen = []
    real = sb.handicap_matchup

    def spy(home, away, power_ratings, week=None, **kw):
        seen.append((week, power_ratings))
        return real(home, away, power_ratings, week=week, **kw)

    monkeypatch.setattr(sb, "handicap_matchup", spy)
    sb.compute_underdog_leaders(season_plays, 2025, limit=None)
    assert [w for w, _ in seen] == [1, 1, 2, 2, 3, 3]
    for week, ratings in seen:
        expected = sb.compute_team_power_ratings([p for p in season_plays if p["week"] < week], 2025)
        assert ratings == expected, week
    seen.clear()
    sb.render_sportsbook_board_view(season_plays, 2025)
    sb.render_game_handicap_dossier_view("AAA", "CCC", season_plays, 2025)
    assert [w for w, _ in seen] == [1, 1, 2, 2, 3, 3, 3]
    assert seen[-1][1] == sb.compute_team_power_ratings([p for p in season_plays if p["week"] < 3], 2025)


# --- explain / formula -----------------------------------------------------------------------

def test_explain_mentions_every_formula_with_real_constants():
    text = cli.strip_ansi(sb.render_model_explanation())
    assert DISCLAIMER in text
    for needle in (
        "power rating = 26 x net EPA/play x 0.65 + average point differential x 0.35",
        "home-field advantage (1.8 pts)",
        "rounded to the nearest 0.5 point",
        "Key numbers (3, 7, 6, 10, 4, 14)",
        "NormalCDF(expected home margin / 13.5)",
        "multiplied by 1.025",
        MARGIN_LABEL,
        "total = 44 + 24 x",
        "limited to 37-56",
        "Worked example",
    ):
        assert needle in text, needle


@pytest.mark.parametrize("const,value,present,absent", [
    ("NFL_MARGIN_STD_DEV", 9.0, ["margin / 9)", "9 pts is the assumed standard deviation"], ["13.5"]),
    ("HOME_FIELD_ADVANTAGE_PTS", 2.5, ["home-field advantage (2.5 pts)"], ["(1.8 pts)"]),
    ("LEAGUE_AVERAGE_TOTAL", 40.0, ["total = 40 + 24 x"], ["total = 44"]),
    ("TOTAL_EPA_SCALE", 30.0, ["total = 44 + 30 x"], ["44 + 24 x"]),
    ("TOTAL_MIN", 35.0, ["limited to 35-56"], ["37-56"]),
    ("TOTAL_MAX", 58.0, ["limited to 37-58"], ["37-56"]),
    ("POWER_EPA_SCALE", 20.0, ["power rating = 20 x net EPA/play x 0.65"], ["26 x net"]),
    ("POWER_EPA_WEIGHT", 0.5, ["x net EPA/play x 0.5 +"], ["x 0.65"]),
    ("POWER_DIFF_WEIGHT", 0.5, ["point differential x 0.5"], ["x 0.35"]),
    ("SPREAD_ROUNDING_STEP", 0.25, ["nearest 0.25 point"], ["nearest 0.5 point"]),
    ("MONEYLINE_MARGIN_FACTOR", 1.05, ["multiplied by 1.05,", "modeled 5% margin"], ["2.5%", "1.025"]),
    ("MONEYLINE_IMPLIED_CAP", 0.9, ["capped at 0.9."], ["capped at 0.98"]),
    ("MONEYLINE_PROB_MIN", 0.05, ["limited to 0.05-0.99"], ["0.01-0.99"]),
    ("MONEYLINE_PROB_MAX", 0.95, ["limited to 0.01-0.95"], ["0.01-0.99"]),
    ("KEY_NFL_NUMBERS", [3.0, 7.0], ["Key numbers (3, 7)"], ["(3, 7, 6"]),
])
def test_explanation_follows_the_constants(monkeypatch, const, value, present, absent):
    monkeypatch.setattr(sb, const, value)
    text = cli.strip_ansi(sb.render_model_explanation())
    for s in present:
        assert s in text, (const, s)
    for s in absent:
        assert s not in text, (const, s)


def test_worked_example_follows_the_code(monkeypatch):
    before = cli.strip_ansi(sb.render_model_explanation())
    monkeypatch.setattr(sb, "NFL_MARGIN_STD_DEV", 6.0)
    after = cli.strip_ansi(sb.render_model_explanation())
    ex = sb.explanation_example()
    assert f"P(home wins) = {ex['home_win_prob']:.1f}%" in after
    assert "P(home wins) = 63.9%" in before and "P(home wins) = 63.9%" not in after
    monkeypatch.setattr(sb, "HOME_FIELD_ADVANTAGE_PTS", 0.0)
    ex2 = sb.explanation_example()
    assert ex2["spread"] == -3.0 and f"spread {ex2['spread']:+.1f}" in cli.strip_ansi(sb.render_model_explanation())


def test_behaviour_follows_the_same_constants(monkeypatch):
    """The constants the explanation prints are the ones the calculations use."""
    ratings = {"H": {"power_rating": 4.0, "off_epa": 0.0, "def_epa": 0.0}, "A": {"power_rating": 1.0, "off_epa": 0.0, "def_epa": 0.0}}
    base = sb.handicap_matchup("H", "A", ratings)
    monkeypatch.setattr(sb, "NFL_MARGIN_STD_DEV", 6.0)
    assert sb.handicap_matchup("H", "A", ratings)["home_win_prob"] > base["home_win_prob"]
    monkeypatch.undo()
    monkeypatch.setattr(sb, "HOME_FIELD_ADVANTAGE_PTS", 0.0)
    assert sb.handicap_matchup("H", "A", ratings)["expected_margin"] == 3.0
    monkeypatch.undo()
    monkeypatch.setattr(sb, "SPREAD_ROUNDING_STEP", 0.25)
    assert sb.snap_to_sportsbook_spread(-3.3) == -3.25
    monkeypatch.undo()
    monkeypatch.setattr(sb, "MONEYLINE_MARGIN_FACTOR", 1.0)
    assert sb.calculate_american_moneyline(0.5) == (100, 100) or sb.calculate_american_moneyline(0.5) == (-100, -100)
    monkeypatch.undo()
    monkeypatch.setattr(sb, "POWER_EPA_SCALE", 0.0)
    monkeypatch.setattr(sb, "POWER_DIFF_WEIGHT", 0.0)
    plays = [_play(2025, 1, "H", "A", "H", 0.3, 20, 10, 1), _play(2025, 1, "H", "A", "A", -0.3, 20, 10, 2)]
    assert sb.compute_team_power_ratings(plays, 2025)["H"]["power_rating"] == 0.0


def test_total_constants_match_the_handicap_matchup_literals():
    """TOTAL_* mirror literals inside handicap_matchup (owned by #25); fail loudly if they drift."""
    def total_for(off_home, off_away):
        r = {"H": {"power_rating": 0.0, "off_epa": off_home, "def_epa": 0.0},
             "A": {"power_rating": 0.0, "off_epa": off_away, "def_epa": 0.0}}
        return sb.handicap_matchup("H", "A", r)["total"]

    assert total_for(0.0, 0.0) == sb.LEAGUE_AVERAGE_TOTAL
    step = sb.SPREAD_ROUNDING_STEP
    expect = round(round((sb.LEAGUE_AVERAGE_TOTAL + sb.TOTAL_EPA_SCALE * 0.08) / step) * step, 1)
    assert total_for(0.05, 0.03) == expect
    assert total_for(10.0, 10.0) == sb.TOTAL_MAX
    assert total_for(-10.0, -10.0) == sb.TOTAL_MIN


# --- CLI / TUI wiring ------------------------------------------------------------------------

def _env(home):
    env = dict(os.environ)
    env.update({"HOME": str(home), "USERPROFILE": str(home), "NFL_STAT_SLM_MODEL": "off"})
    return env


def _run(home, *args, stdin=None):
    return subprocess.run([sys.executable, "-m", "nfl_stat_cli", *args], input=stdin, capture_output=True,
                          text=True, env=_env(home), cwd=str(ROOT), timeout=120)


def test_cli_explain_and_formula_flags(tmp_path):
    outs = []
    for flag in ("--explain", "--formula"):
        res = _run(tmp_path, flag)
        assert res.returncode == 0, res.stderr
        outs.append(cli.strip_ansi(res.stdout))
    assert outs[0] == outs[1]
    assert outs[0].strip() == cli.strip_ansi(sb.render_model_explanation()).strip()


def test_cli_formula_option_of_create_stat_is_unaffected():
    parser = cli.build_arg_parser()
    ns = parser.parse_args(["create-stat", "--name", "x", "--title", "X", "--formula", "yards_per_play * 2",
                            "--description", "d", "--explained", "e"])
    assert ns.formula == "yards_per_play * 2" and ns.explain is False
    assert parser.parse_args(["--explain"]).explain is True
    assert parser.parse_args(["--formula"]).explain is True


def test_tui_projection_commands(tmp_path):
    stdin = "\n".join(["/projections", "q", "/sportsbook 1", "/explain", "/formula", "/help", "quit"]) + "\n"
    res = _run(tmp_path, "tui", "--engine", "offline", "--season", "2025", "--no-color", "--slm-model", "off", stdin=stdin)
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert out.count("HOW MODEL PROJECTIONS ARE COMPUTED") == 2
    assert out.count(DISCLAIMER) >= 3
    assert "Model Projections (2025" in out
    assert "/projections" in out and "/explain" in out


def test_slash_completer_offers_projection_commands():
    assert "/projections" in cli.SLASH_COMMAND_OPTIONS and "/explain" in cli.SLASH_COMMAND_OPTIONS
    assert "/sportsbook" not in cli.SLASH_COMMAND_OPTIONS
