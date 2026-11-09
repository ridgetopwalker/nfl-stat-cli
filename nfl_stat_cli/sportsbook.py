"""
Model Projections: statistical game projections built from play-by-play data.
- Team power ratings derived from net EPA/play, scoring differential, and success rate.
- Home-field advantage (HFA = 1.8 pts).
- Projected point spread (rounded to the nearest half point).
- Projected game total from scoring pace and drive efficiency.
- Win probability from a normal model (margin standard deviation = 13.5 pts) and moneyline-style
  conversions that include a modeled margin.
- Model accuracy vs. actual results on completed games, using only games played before each game's week.
Use `--explain` / `/explain` for the formulas, generated from the constants in this module.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

PROJECTIONS_TITLE = "Model Projections"
PROJECTIONS_DISCLAIMER = (
    "Statistical model projections for analysis and entertainment. Not betting advice. "
    "We don't take bets or link to sportsbooks, and we aren't affiliated with the NFL."
)

HOME_FIELD_ADVANTAGE_PTS = 1.8
NFL_MARGIN_STD_DEV = 13.5
LEAGUE_AVERAGE_TOTAL = 44.0

KEY_NFL_NUMBERS = [3.0, 7.0, 6.0, 10.0, 4.0, 14.0]

# Spread rounding step (the projected margin is rounded to the nearest half point).
SPREAD_ROUNDING_STEP = 0.5

# Power rating = POWER_EPA_SCALE * net EPA/play * POWER_EPA_WEIGHT + point differential * POWER_DIFF_WEIGHT
POWER_EPA_SCALE = 26.0
POWER_EPA_WEIGHT = 0.65
POWER_DIFF_WEIGHT = 0.35

# Projected total = LEAGUE_AVERAGE_TOTAL + TOTAL_EPA_SCALE * (EPA adjustment), clamped to [TOTAL_MIN, TOTAL_MAX]
# and rounded to the nearest half point. These mirror the literals inside handicap_matchup();
# tests/test_model_projections.py keeps them in sync.
TOTAL_EPA_SCALE = 24.0
TOTAL_MIN = 37.0
TOTAL_MAX = 56.0

# Moneyline conversion: each side's win probability is clamped to [MONEYLINE_PROB_MIN, MONEYLINE_PROB_MAX],
# multiplied by MONEYLINE_MARGIN_FACTOR (the modeled margin), capped at MONEYLINE_IMPLIED_CAP, then converted.
MONEYLINE_PROB_MIN = 0.01
MONEYLINE_PROB_MAX = 0.99
MONEYLINE_MARGIN_FACTOR = 1.025
MONEYLINE_IMPLIED_CAP = 0.98


def modeled_margin_pct() -> float:
    """The modeled margin built into the moneylines, as a percentage (from MONEYLINE_MARGIN_FACTOR)."""
    return round((MONEYLINE_MARGIN_FACTOR - 1.0) * 100.0, 4)


def _fmt_num(x: float) -> str:
    """Compact number text for labels (13.5 -> '13.5', 26.0 -> '26', 2.5000 -> '2.5')."""
    return f"{x:.4f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def modeled_margin_label() -> str:
    """Exact label shown wherever moneylines are displayed."""
    return f"Includes a modeled {_fmt_num(modeled_margin_pct())}% margin (typical market hold)"


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function (error function approximation)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_team_power_ratings(plays: List[Dict[str, Any]], season: int) -> Dict[str, Dict[str, Any]]:
    """
    Compute 32-team quantitative power ratings using season-to-date play-by-play metrics:
    - Offensive EPA/play
    - Defensive EPA/play allowed
    - Net EPA/play
    - Scoring differential per game
    - Success rate
    """
    from . import plays_for_season

    # Honor the requested season: callers (e.g. the TUI) may hold several loaded seasons.
    plays = plays_for_season(plays, season)
    teams = sorted({str(p.get("posteam", "")).strip() for p in plays if p.get("posteam")})

    raw_stats: Dict[str, Dict[str, Any]] = {}
    for t in teams:
        if not t or len(t) > 4:
            continue
        off_plays = [p for p in plays if str(p.get("posteam", "")) == t]
        def_plays = [p for p in plays if str(p.get("defteam", "")) == t]

        n_off = max(1, len(off_plays))
        n_def = max(1, len(def_plays))

        off_epa = sum(float(p.get("epa", 0.0)) for p in off_plays) / n_off
        def_epa = sum(float(p.get("epa", 0.0)) for p in def_plays) / n_def
        net_epa = off_epa - def_epa

        off_success = sum(int(p.get("series_success", 0)) for p in off_plays) / n_off

        # Points scored & points allowed
        games_scored: Dict[str, float] = {}
        games_allowed: Dict[str, float] = {}
        for p in off_plays:
            gid = str(p.get("game_id", ""))
            if gid:
                # Max score recorded in game
                hs = float(p.get("home_score", 0.0))
                as_ = float(p.get("away_score", 0.0))
                if gid.endswith(f"_{t}"):
                    games_scored[gid] = max(games_scored.get(gid, 0.0), hs)
                    games_allowed[gid] = max(games_allowed.get(gid, 0.0), as_)
                else:
                    games_scored[gid] = max(games_scored.get(gid, 0.0), as_)
                    games_allowed[gid] = max(games_allowed.get(gid, 0.0), hs)

        gp = max(1, len(games_scored))
        avg_pts_for = (sum(games_scored.values()) / gp) if games_scored else 22.0
        avg_pts_against = (sum(games_allowed.values()) / gp) if games_allowed else 22.0
        pt_diff = avg_pts_for - avg_pts_against

        # Quantitative power rating scaled to points relative to average NFL team (0.0):
        # Net EPA scaled by ~25.0 points per EPA/play unit, blended with scoring differential
        power_rating = (net_epa * POWER_EPA_SCALE) * POWER_EPA_WEIGHT + (pt_diff * POWER_DIFF_WEIGHT)

        raw_stats[t] = {
            "team": t,
            "off_epa": round(off_epa, 3),
            "def_epa": round(def_epa, 3),
            "net_epa": round(net_epa, 3),
            "success_rate": round(off_success * 100.0, 1),
            "pts_for": round(avg_pts_for, 1),
            "pts_against": round(avg_pts_against, 1),
            "point_diff": round(pt_diff, 1),
            "power_rating": round(power_rating, 2),
            "games_played": gp,
        }

    return raw_stats


def snap_to_sportsbook_spread(raw_spread: float) -> float:
    """
    Round a continuous projected margin to the nearest half point (SPREAD_ROUNDING_STEP).
    KEY_NFL_NUMBERS are listed for context only; rounding does not move a line onto them.
    """
    return round(raw_spread / SPREAD_ROUNDING_STEP) * SPREAD_ROUNDING_STEP


def calculate_american_moneyline(win_prob: float) -> Tuple[int, int]:
    """
    Convert a win probability into American-style moneyline values for home and away.
    Each side's probability is multiplied by MONEYLINE_MARGIN_FACTOR (the modeled margin, see
    modeled_margin_label()) before conversion.
    """
    p = max(MONEYLINE_PROB_MIN, min(MONEYLINE_PROB_MAX, win_prob))

    # Include the modeled margin in the implied probabilities
    p_home_vig = min(MONEYLINE_IMPLIED_CAP, p * MONEYLINE_MARGIN_FACTOR)
    p_away_vig = min(MONEYLINE_IMPLIED_CAP, (1.0 - p) * MONEYLINE_MARGIN_FACTOR)

    def to_american(prob: float) -> int:
        if prob >= 0.50:
            return -int(round((prob / (1.0 - prob)) * 100.0))
        else:
            return int(round(((1.0 - prob) / prob) * 100.0))

    ml_home = to_american(p_home_vig)
    ml_away = to_american(p_away_vig)
    return (ml_home, ml_away)


def handicap_matchup(
    home_team: str,
    away_team: str,
    power_ratings: Dict[str, Dict[str, Any]],
    week: Optional[int] = None,
    home_score: Optional[int] = None,
    away_score: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Complete model projection for an NFL game:
    projected spread, moneyline-style values, projected total, win probability, and, when the
    game has been played, how the model's projection compared with the actual result.
    """
    home_pr = power_ratings.get(home_team, {}).get("power_rating", 0.0)
    away_pr = power_ratings.get(away_team, {}).get("power_rating", 0.0)

    home_off_epa = power_ratings.get(home_team, {}).get("off_epa", 0.0)
    home_def_epa = power_ratings.get(home_team, {}).get("def_epa", 0.0)
    away_off_epa = power_ratings.get(away_team, {}).get("off_epa", 0.0)
    away_def_epa = power_ratings.get(away_team, {}).get("def_epa", 0.0)

    # Projected expected margin from Home perspective:
    # Expected Margin = Home Rating - Away Rating + Home Field Advantage
    raw_home_margin = (home_pr - away_pr) + HOME_FIELD_ADVANTAGE_PTS

    # Traditional spread is expressed from home perspective:
    # If Home is favored by 3.5, spread = -3.5
    raw_spread = -raw_home_margin
    spread_line = snap_to_sportsbook_spread(raw_spread)

    # Favorite display
    if spread_line < 0:
        fav_label = f"{home_team} {spread_line:+.1f}"
        dog_label = f"{away_team} {abs(spread_line):+.1f}"
    elif spread_line > 0:
        fav_label = f"{away_team} {-spread_line:+.1f}"
        dog_label = f"{home_team} {+spread_line:+.1f}"
    else:
        fav_label = "EVEN (0.0)"
        dog_label = "EVEN (0.0)"

    # Total (Over/Under) estimation:
    # Baseline 44.0 + offensive EPA boost - defensive EPA suppression
    epa_scoring_factor = (home_off_epa + away_off_epa - (home_def_epa + away_def_epa)) * 24.0
    raw_total = LEAGUE_AVERAGE_TOTAL + epa_scoring_factor
    total_line = round(round(max(37.0, min(56.0, raw_total)) * 2.0) / 2.0, 1)

    # Win probability via normal CDF
    home_win_prob = normal_cdf(raw_home_margin / NFL_MARGIN_STD_DEV)
    away_win_prob = 1.0 - home_win_prob

    # Moneylines
    home_ml, away_ml = calculate_american_moneyline(home_win_prob)

    # Implied final score projection
    proj_home = round((total_line - spread_line) / 2.0, 1)
    proj_away = round((total_line + spread_line) / 2.0, 1)

    # Against The Spread (ATS) and Over/Under result if game has been played
    ats_result = "-"
    ou_result = "-"
    actual_margin = None
    actual_total = None

    if home_score is not None and away_score is not None:
        actual_margin = home_score - away_score
        actual_total = home_score + away_score

        # Margin vs. projection: the home team finished above the projected margin if
        # actual_margin > -spread_line (e.g. projected -3.5, home wins by 4 -> 4 > 3.5)
        if actual_margin > -spread_line:
            ats_result = f"{home_team} above projection"
        elif actual_margin < -spread_line:
            ats_result = f"{away_team} above projection"
        else:
            ats_result = "At projection"

        # Total vs. projected total
        if actual_total > total_line:
            ou_result = f"Above projected total ({actual_total} vs {total_line})"
        elif actual_total < total_line:
            ou_result = f"Below projected total ({actual_total} vs {total_line})"
        else:
            ou_result = f"At projected total ({actual_total})"

    return {
        "home_team": home_team,
        "away_team": away_team,
        "week": week,
        "home_rating": home_pr,
        "away_rating": away_pr,
        "hfa": HOME_FIELD_ADVANTAGE_PTS,
        "expected_margin": round(raw_home_margin, 2),
        "spread": spread_line,
        "favorite_str": fav_label,
        "underdog_str": dog_label,
        "total": total_line,
        "home_win_prob": round(home_win_prob * 100.0, 1),
        "away_win_prob": round(away_win_prob * 100.0, 1),
        "home_ml": home_ml,
        "away_ml": away_ml,
        "proj_home_score": proj_home,
        "proj_away_score": proj_away,
        "actual_home_score": home_score,
        "actual_away_score": away_score,
        "actual_margin": actual_margin,
        "actual_total": actual_total,
        "ats_result": ats_result,
        "ou_result": ou_result,
    }


def plays_before_week(plays: List[Dict[str, Any]], season: int, week: Optional[int]) -> List[Dict[str, Any]]:
    """Plays from `season` in weeks strictly before `week` (what was known before that week's games)."""
    if week is None:
        return [p for p in plays if int(p.get("season", 0) or 0) == int(season)]
    return [
        p for p in plays
        if int(p.get("season", 0) or 0) == int(season) and int(p.get("week", 0) or 0) < int(week)
    ]


class PregameRatings:
    """Power ratings for a game, built only from games played in earlier weeks of that season.

    Using season-to-date ratings for a game that is already in the data would let the model "see"
    that game (and later ones), which makes accuracy numbers look better than they are.
    """

    def __init__(self, plays: List[Dict[str, Any]], season: int) -> None:
        self._plays = plays
        self._season = season
        self._cache: Dict[Optional[int], Dict[str, Dict[str, Any]]] = {}

    def for_week(self, week: Optional[int]) -> Dict[str, Dict[str, Any]]:
        key = int(week) if week is not None else None
        if key not in self._cache:
            self._cache[key] = compute_team_power_ratings(
                plays_before_week(self._plays, self._season, key), self._season
            )
        return self._cache[key]


def summarize_model_accuracy(results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Summarize how projections compared with actual results over completed games."""
    done = [r for r in results if r.get("actual_margin") is not None]
    if not done:
        return None
    n = len(done)
    winner_ok = 0
    for r in done:
        proj, act = r["expected_margin"], r["actual_margin"]
        if act == 0 or (proj > 0) == (act > 0):
            winner_ok += 1
    margin_err = sum(abs(r["actual_margin"] - r["expected_margin"]) for r in done) / n
    total_err = sum(abs(r["actual_total"] - r["total"]) for r in done) / n
    return {
        "games": n,
        "winner_correct": winner_ok,
        "winner_pct": round(winner_ok / n * 100.0, 1),
        "avg_margin_error": round(margin_err, 1),
        "avg_total_error": round(total_err, 1),
    }


def render_accuracy_line(summary: Optional[Dict[str, Any]]) -> str:
    if not summary:
        return ""
    return (
        f"Model accuracy vs. actual results ({summary['games']} completed games): projected winner "
        f"{summary['winner_correct']}/{summary['games']} ({summary['winner_pct']:.1f}%), "
        f"average margin error {summary['avg_margin_error']:.1f} pts, "
        f"average total error {summary['avg_total_error']:.1f} pts."
    )


def render_disclaimer_block() -> str:
    from . import C

    return f"\n  {C.BOLD}{PROJECTIONS_DISCLAIMER}{C.RESET}"


def render_sportsbook_board_view(
    plays: List[Dict[str, Any]],
    season: int,
    week_filter: Optional[int] = None,
) -> str:
    """Render a colorized ASCII table of NFL matchups with modeled spreads, moneylines, and totals."""
    from . import C, AsciiArtRenderer, extract_games_summary

    pregame = PregameRatings(plays, season)
    games = extract_games_summary(plays, season)
    if week_filter is not None:
        games = [g for g in games if int(g.get("week", -1)) == int(week_filter)]

    if not games:
        return f"\n{C.YELLOW}⚠ No games recorded in dataset for season {season}{f' Week {week_filter}' if week_filter else ''}.{C.RESET}"

    title_str = f"📊 {PROJECTIONS_TITLE} ({season}{f' • Week {week_filter}' if week_filter else ''})"
    headers = ["Week", "Matchup", "Model Spread", "Model Total", "Model Moneyline (H / A)", "Model Score", "Actual", "Model vs. Actual"]
    rows = []
    results: List[Dict[str, Any]] = []

    for g in games:
        h = g["home_team"]
        a = g["away_team"]
        wk = g["week"]
        hs = g.get("home_score")
        as_ = g.get("away_score")

        hc = handicap_matchup(h, a, pregame.for_week(wk), week=wk, home_score=hs, away_score=as_)
        results.append(hc)

        ml_h_str = f"{hc['home_ml']:+d}"
        ml_a_str = f"{hc['away_ml']:+d}"
        ml_str = f"{ml_h_str} / {ml_a_str}"

        actual_str = f"{as_}-{hs}" if (hs is not None and as_ is not None) else "TBD"
        score_str = f"{hc['proj_away_score']:.1f}-{hc['proj_home_score']:.1f}"

        res_color = C.GREEN if "above projection" in hc["ats_result"] else C.RESET

        rows.append([
            f"Wk {wk}",
            f"{a} @ {C.BOLD}{h}{C.RESET}",
            f"{C.BOLD}{C.GOLD}{hc['favorite_str']}{C.RESET}",
            f"{hc['total']:.1f}",
            ml_str,
            score_str,
            actual_str,
            f"{res_color}{hc['ats_result']}{C.RESET}",
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["center", "left", "center", "center", "center", "center", "center", "center"],
    )
    notes = [
        f"Projections use power-rating differences, home-field advantage (+{HOME_FIELD_ADVANTAGE_PTS} pts), and net EPA; "
        f"win probability uses a normal model with a margin standard deviation of {NFL_MARGIN_STD_DEV} pts.",
        modeled_margin_label(),
        "Each game's ratings use only games from earlier weeks, so Week 1 has no prior games (ratings start at 0).",
    ]
    acc = render_accuracy_line(summarize_model_accuracy(results))
    if acc:
        notes.append(acc)
    notes.append("Formulas: run with --explain (or type /explain).")
    footer = "\n" + "\n".join(f"  {C.DIM}{n}{C.RESET}" for n in notes)
    return f"{render_disclaimer_block()}\n{tbl}{footer}"


def render_power_ratings_view(plays: List[Dict[str, Any]], season: int) -> str:
    """Render NFL 32-Team Power Ratings leaderboard table."""
    from . import C, AsciiArtRenderer

    ratings = compute_team_power_ratings(plays, season)
    sorted_teams = sorted(ratings.values(), key=lambda x: x["power_rating"], reverse=True)

    title_str = f"⚡ NFL Team Power Ratings & Efficiency ({season}, season to date)"
    headers = ["Rank", "Team", "Power Rating", "Net EPA/Play", "Off EPA", "Def EPA", "Success %", "Avg Pts For", "Avg Pts Against", "Point Diff"]
    rows = []

    for idx, r in enumerate(sorted_teams, 1):
        pr_color = C.GREEN if r["power_rating"] > 0 else (C.RED if r["power_rating"] < 0 else C.RESET)
        rows.append([
            f"#{idx}",
            f"{C.BOLD}{r['team']}{C.RESET}",
            f"{pr_color}{C.BOLD}{r['power_rating']:+.2f}{C.RESET}",
            f"{r['net_epa']:+.3f}",
            f"{r['off_epa']:+.3f}",
            f"{r['def_epa']:+.3f}",
            f"{r['success_rate']:.1f}%",
            f"{r['pts_for']:.1f}",
            f"{r['pts_against']:.1f}",
            f"{r['point_diff']:+.1f}",
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["right", "center", "right", "right", "right", "right", "right", "right", "right", "right"],
    )
    return f"{render_disclaimer_block()}\n{tbl}"


def compute_underdog_leaders(
    plays: List[Dict[str, Any]],
    season: int,
    team_filter: Optional[str] = None,
    limit: Optional[int] = 5,
) -> List[Dict[str, Any]]:
    """
    Compute straight-up (SU) results and results versus the projected margin for NFL teams that the model
    projects as underdogs. Sorted primarily by outright wins as an underdog, then win percentage, then the
    share of games finished above the projected margin.
    """
    from . import resolve_team_abbr, extract_games_summary

    pregame = PregameRatings(plays, season)
    games = extract_games_summary(plays, season)

    dog_stats: Dict[str, Dict[str, Any]] = {}
    target_team = resolve_team_abbr(team_filter).upper() if team_filter and resolve_team_abbr(team_filter) else (team_filter.upper() if team_filter else None)

    for g in games:
        h = g["home_team"]
        a = g["away_team"]
        wk = g["week"]
        hs = g.get("home_score")
        as_ = g.get("away_score")

        hc = handicap_matchup(h, a, power_ratings=pregame.for_week(wk), week=wk, home_score=hs, away_score=as_)
        spread = hc["spread"]

        if spread < 0:
            # Home favored -> Away is underdog
            dog, fav = a, h
            dog_score, fav_score = as_, hs
            dog_spread = abs(spread)
        elif spread > 0:
            # Away favored -> Home is underdog
            dog, fav = h, a
            dog_score, fav_score = hs, as_
            dog_spread = abs(spread)
        else:
            continue

        if dog not in dog_stats:
            dog_stats[dog] = {
                "team": dog,
                "games": 0,
                "su_wins": 0,
                "su_losses": 0,
                "su_ties": 0,
                "ats_wins": 0,
                "ats_losses": 0,
                "ats_pushes": 0,
                "spreads": [],
            }

        st = dog_stats[dog]
        if dog_score is not None and fav_score is not None:
            st["games"] += 1
            st["spreads"].append(dog_spread)
            if dog_score > fav_score:
                st["su_wins"] += 1
            elif dog_score < fav_score:
                st["su_losses"] += 1
            else:
                st["su_ties"] += 1

            if (dog_score + dog_spread) > fav_score:
                st["ats_wins"] += 1
            elif (dog_score + dog_spread) < fav_score:
                st["ats_losses"] += 1
            else:
                st["ats_pushes"] += 1

    results: List[Dict[str, Any]] = []
    for team, st in dog_stats.items():
        if target_team and team != target_team:
            continue
        gm = st["games"]
        if gm == 0:
            continue
        su_w = st["su_wins"]
        su_l = st["su_losses"]
        su_t = st["su_ties"]
        su_rec = f"{su_w}-{su_l}" if su_t == 0 else f"{su_w}-{su_l}-{su_t}"
        su_pct = round((su_w / gm) * 100.0, 1)

        ats_w = st["ats_wins"]
        ats_l = st["ats_losses"]
        ats_p = st["ats_pushes"]
        ats_rec = f"{ats_w}-{ats_l}" if ats_p == 0 else f"{ats_w}-{ats_l}-{ats_p}"
        ats_decided = ats_w + ats_l
        cover_pct = round((ats_w / ats_decided) * 100.0, 1) if ats_decided > 0 else 0.0

        avg_spd = round(sum(st["spreads"]) / len(st["spreads"]), 1) if st["spreads"] else 0.0

        results.append({
            "team": team,
            "games_as_dog": gm,
            "su_wins": su_w,
            "su_losses": su_l,
            "su_ties": su_t,
            "su_record": su_rec,
            "su_win_pct": su_pct,
            "ats_wins": ats_w,
            "ats_losses": ats_l,
            "ats_pushes": ats_p,
            "ats_record": ats_rec,
            "cover_pct": cover_pct,
            "avg_spread": avg_spd,
        })

    results.sort(key=lambda x: (x["su_wins"], x["su_win_pct"], x["cover_pct"], x["games_as_dog"]), reverse=True)
    return results[:limit] if (limit and limit > 0) else results


def render_underdog_leaderboard_view(
    plays: List[Dict[str, Any]],
    season: int,
    team_filter: Optional[str] = None,
    limit: Optional[int] = 5,
) -> str:
    """Render a colorized ASCII table of NFL teams with the most wins as an underdog."""
    from . import C, AsciiArtRenderer

    leaders = compute_underdog_leaders(plays, season, team_filter=team_filter, limit=limit)
    if not leaders:
        return f"\n{C.YELLOW}⚠ No underdog games recorded for season {season}.{C.RESET}"

    sub_parts = [str(season)]
    if team_filter:
        sub_parts.append(f"Team: {team_filter.upper()}")
    if limit and not team_filter:
        sub_parts.append(f"Top {limit}")
    title_str = f"📊 NFL Underdog Performance Leaders: Most Wins as Underdog ({' • '.join(sub_parts)})"

    headers = ["Rank", "Team", "Dog Games", "SU Wins", "SU Record", "Win %", "Vs Model Margin", "Above Margin %", "Avg Spread"]
    rows = []
    for idx, r in enumerate(leaders, 1):
        su_win_color = C.GREEN if r["su_wins"] > 0 else C.RESET
        rows.append([
            f"#{idx}",
            f"{C.BOLD}{r['team']}{C.RESET}",
            str(r["games_as_dog"]),
            f"{su_win_color}{C.BOLD}{r['su_wins']}{C.RESET}",
            r["su_record"],
            f"{r['su_win_pct']:.1f}%",
            r["ats_record"],
            f"{r['cover_pct']:.1f}%",
            f"+{r['avg_spread']:.1f}",
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["right", "center", "center", "center", "center", "right", "center", "right", "right"],
    )
    footer = (
        f"\n  {C.DIM}Straight-Up (SU) wins are outright underdog victories (upsets). Projections come from Net EPA & power ratings "
        f"using only earlier weeks. 'Vs Model Margin' is wins-losses-ties for finishing above the projected margin.{C.RESET}"
    )
    return f"{render_disclaimer_block()}\n{tbl}{footer}"



def render_game_handicap_dossier_view(
    home_team: str,
    away_team: str,
    plays: List[Dict[str, Any]],
    season: int,
    week: Optional[int] = None,
) -> str:
    """Render an in-depth model projection dossier for a single matchup."""
    from . import C, AsciiArtRenderer, extract_games_summary

    games = extract_games_summary(plays, season)
    target_game = next(
        (g for g in games if g["home_team"].upper() == home_team.upper() and g["away_team"].upper() == away_team.upper()),
        None,
    )
    hs = target_game.get("home_score") if target_game else None
    as_ = target_game.get("away_score") if target_game else None
    wk = target_game.get("week") if target_game else week

    # A game already in the data is projected from earlier weeks only; an unplayed matchup uses season to date.
    power_ratings = PregameRatings(plays, season).for_week(wk if target_game else None)

    hc = handicap_matchup(home_team, away_team, power_ratings, week=wk, home_score=hs, away_score=as_)

    h_bar_len = int(round(hc["home_win_prob"] / 2.5))
    a_bar_len = int(round(hc["away_win_prob"] / 2.5))
    win_bar = f"{C.CYAN}{'█' * h_bar_len}{C.RESET}{C.YELLOW}{'░' * a_bar_len}{C.RESET}"

    lines = [
        render_disclaimer_block(),
        f"\n{C.BOLD}{C.GOLD}╔══════════════════════════════════════════════════════════════════════════╗{C.RESET}",
        f"{C.BOLD}{C.GOLD}║                   📊 MODEL PROJECTION DOSSIER                            ║{C.RESET}",
        f"{C.BOLD}{C.GOLD}╚══════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        f"  {C.BOLD}Matchup:{C.RESET} {away_team} @ {C.BOLD}{home_team}{C.RESET} (Season {season}{f' • Week {wk}' if wk else ''})",
        "",
        f"  {C.CYAN}📊 MODELED SPREAD & TOTAL:{C.RESET}",
        f"     • Point Spread:        {C.BOLD}{C.GOLD}{hc['favorite_str']}{C.RESET} (Raw Margin: {hc['expected_margin']:+.2f} pts)",
        f"     • Projected Total:     {C.BOLD}{hc['total']:.1f} pts{C.RESET}",
        f"     • Projected Score:     {C.BOLD}{away_team} {hc['proj_away_score']:.1f}  -  {home_team} {hc['proj_home_score']:.1f}{C.RESET}",
        "",
        f"  {C.GREEN}📈 MODELED MONEYLINES & WIN PROBABILITIES:{C.RESET}",
        f"     • {home_team} (Home):         {C.BOLD}{hc['home_ml']:+d}{C.RESET}  (Win Probability: {C.BOLD}{hc['home_win_prob']:.1f}%{C.RESET})",
        f"     • {away_team} (Away):         {C.BOLD}{hc['away_ml']:+d}{C.RESET}  (Win Probability: {C.BOLD}{hc['away_win_prob']:.1f}%{C.RESET})",
        f"     • Probability Bar:     [{win_bar}]",
        f"     • {C.DIM}{modeled_margin_label()}{C.RESET}",
        "",
        f"  {C.MAGENTA}⚖️  POWER RATINGS & ADVANTAGES:{C.RESET}",
        f"     • {home_team} Power Rating:   {hc['home_rating']:+.2f} pts",
        f"     • {away_team} Power Rating:   {hc['away_rating']:+.2f} pts",
        f"     • Home Field Advantage: +{hc['hfa']:.1f} pts",
    ]

    if hs is not None and as_ is not None:
        lines.extend([
            "",
            f"  {C.YELLOW}🏁 COMPLETED GAME: MODEL VS. ACTUAL RESULT:{C.RESET}",
            f"     • Final Score:         {away_team} {as_}  -  {home_team} {hs}",
            f"     • Margin vs. Model:    {C.BOLD}{hc['ats_result']}{C.RESET}",
            f"     • Total vs. Model:     {C.BOLD}{hc['ou_result']}{C.RESET}",
        ])

    lines.extend([
        "",
        f"  {C.DIM}Ratings use only games from earlier weeks. Formulas: run with --explain (or type /explain).{C.RESET}",
    ])
    return "\n".join(lines)


def interactive_sportsbook_browser(
    plays: List[Dict[str, Any]],
    active_season: int,
) -> None:
    """Interactive drill-down menu for Model Projections: spreads, totals, win probability, and power ratings."""
    from . import C, prompt_input, extract_games_summary

    while True:
        print(f"\n{C.BOLD}{C.GOLD}=== 📊 {PROJECTIONS_TITLE.upper()} ==={C.RESET}")
        print(f"  {C.BOLD}{PROJECTIONS_DISCLAIMER}{C.RESET}")
        print(f"  Active Season: {C.BOLD}{active_season}{C.RESET}")
        print("  Select Browsing Mode:")
        print(f"    [1] {C.BOLD}Browse Weekly Projections Board{C.RESET} (Spreads, Moneylines, Totals & Model vs. Actual)")
        print(f"    [2] {C.BOLD}NFL 32-Team Power Ratings{C.RESET} (Team Power Standings)")
        print(f"    [3] {C.BOLD}Single Matchup Deep Dive{C.RESET} (Projections, Win Probability & Key Numbers)")
        print(f"    [4] {C.BOLD}Underdog Performance Leaders{C.RESET} (Most Outright Wins as Underdog)")
        print(f"    [5] {C.BOLD}How these projections are computed{C.RESET} (Formulas)")
        print(f"    [q] {C.DIM}Return to main menu{C.RESET}")

        try:
            choice = prompt_input("  Choose mode [1-5, q] (default: 1): ").strip().lower() or "1"
        except (EOFError, KeyboardInterrupt):
            break

        if choice in ("q", "quit", "exit", "back"):
            break

        if choice == "1":
            try:
                wk_in = prompt_input("  Enter Week number (or Enter for all weeks): ").strip()
                wk_val = int(wk_in) if (wk_in.isdigit() and int(wk_in) > 0) else None
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_sportsbook_board_view(plays, active_season, week_filter=wk_val))
        elif choice == "2":
            print(render_power_ratings_view(plays, active_season))
        elif choice == "3":
            all_games = extract_games_summary(plays, active_season)
            if not all_games:
                print(f"  {C.YELLOW}⚠ No games recorded in dataset for season {active_season}.{C.RESET}")
                continue
            print(f"\n  Available matchups ({len(all_games)}):")
            for idx, g in enumerate(all_games, 1):
                print(f"    [{idx}] Wk {g['week']} - {g['away_team']} @ {g['home_team']}")
            try:
                g_sel = prompt_input(f"  Select matchup [1-{len(all_games)}] (default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                continue
            if g_sel.isdigit() and 1 <= int(g_sel) <= len(all_games):
                chosen = all_games[int(g_sel) - 1]
                print(render_game_handicap_dossier_view(chosen["home_team"], chosen["away_team"], plays, active_season, week=chosen["week"]))
        elif choice == "4":
            print(render_underdog_leaderboard_view(plays, active_season, limit=10))
        elif choice == "5":
            print(render_model_explanation())


def explanation_example() -> Dict[str, Any]:
    """A worked example computed by calling the real functions, so it can never drift from the code."""
    ratings = {
        "HOME": {"power_rating": 4.0, "off_epa": 0.05, "def_epa": 0.0},
        "AWAY": {"power_rating": 1.0, "off_epa": 0.03, "def_epa": 0.0},
    }
    hc = handicap_matchup("HOME", "AWAY", ratings)
    hc["inputs"] = ratings
    return hc


def render_model_explanation() -> str:
    """Plain-language formulas behind the projections, generated from this module's constants."""
    from . import C

    n = _fmt_num
    keys = ", ".join(n(k) for k in KEY_NFL_NUMBERS)
    ex = explanation_example()
    z = ex["expected_margin"] / NFL_MARGIN_STD_DEV
    p_cap = n(MONEYLINE_IMPLIED_CAP)
    lines = [
        render_disclaimer_block(),
        "",
        f"{C.BOLD}{C.GOLD}HOW {PROJECTIONS_TITLE.upper()} ARE COMPUTED{C.RESET}",
        f"{C.DIM}Every number below is read from the constants in the code; the worked example calls the real functions.{C.RESET}",
        "",
        f"{C.BOLD}1. Team power rating{C.RESET} (points relative to an average team)",
        "   net EPA/play = offense EPA/play - EPA/play allowed by the defense",
        f"   power rating = {n(POWER_EPA_SCALE)} x net EPA/play x {n(POWER_EPA_WEIGHT)}"
        f" + average point differential x {n(POWER_DIFF_WEIGHT)}",
        "   Ratings for a game use only games played in earlier weeks of that season.",
        "",
        f"{C.BOLD}2. Projected spread and key numbers{C.RESET}",
        f"   expected home margin = home rating - away rating + home-field advantage ({n(HOME_FIELD_ADVANTAGE_PTS)} pts)",
        f"   spread (home view) = -(expected home margin), rounded to the nearest {n(SPREAD_ROUNDING_STEP)} point",
        f"   Key numbers ({keys}) are the most common final margins in NFL games. They are shown for context:"
        " the rounding step above does not move a line onto them.",
        "",
        f"{C.BOLD}3. Win probability (normal model){C.RESET}",
        f"   P(home wins) = NormalCDF(expected home margin / {n(NFL_MARGIN_STD_DEV)}), "
        f"where {n(NFL_MARGIN_STD_DEV)} pts is the assumed standard deviation of NFL final margins",
        "   P(away wins) = 1 - P(home wins)",
        "",
        f"{C.BOLD}4. Moneyline-style values{C.RESET}",
        f"   Each side's win probability is limited to {n(MONEYLINE_PROB_MIN)}-{n(MONEYLINE_PROB_MAX)}, multiplied by "
        f"{n(MONEYLINE_MARGIN_FACTOR)}, and capped at {p_cap}.",
        f"   {modeled_margin_label()}",
        "   If that probability p is 0.5 or more: value = -(p / (1 - p)) x 100; otherwise value = +((1 - p) / p) x 100 (rounded).",
        "",
        f"{C.BOLD}5. Projected total and score{C.RESET}",
        f"   total = {n(LEAGUE_AVERAGE_TOTAL)} + {n(TOTAL_EPA_SCALE)} x (EPA adjustment from both teams' offense and defense EPA/play),"
        f" limited to {n(TOTAL_MIN)}-{n(TOTAL_MAX)} and rounded to the nearest {n(SPREAD_ROUNDING_STEP)}",
        "   projected score: home = (total - spread) / 2, away = (total + spread) / 2",
        "",
        f"{C.BOLD}6. Model accuracy vs. actual results{C.RESET}",
        "   For completed games the board compares each projection with the final score: whether the projected winner won,",
        "   and the average margin and total error. Only earlier weeks feed each game's ratings.",
        "",
        f"{C.BOLD}Worked example{C.RESET} (home rating {ex['inputs']['HOME']['power_rating']:+.1f}, "
        f"away rating {ex['inputs']['AWAY']['power_rating']:+.1f}, offense EPA/play "
        f"{ex['inputs']['HOME']['off_epa']:.2f} and {ex['inputs']['AWAY']['off_epa']:.2f}, defense EPA/play 0.00)",
        f"   expected home margin = {ex['home_rating']:.1f} - {ex['away_rating']:.1f} + {n(HOME_FIELD_ADVANTAGE_PTS)}"
        f" = {ex['expected_margin']:.2f}  ->  spread {ex['spread']:+.1f}",
        f"   z = {ex['expected_margin']:.2f} / {n(NFL_MARGIN_STD_DEV)} = {z:.3f}  ->  P(home wins) = {ex['home_win_prob']:.1f}%",
        f"   moneyline values: home {ex['home_ml']:+d}, away {ex['away_ml']:+d}   ({modeled_margin_label()})",
        f"   projected total {ex['total']:.1f}  ->  projected score home {ex['proj_home_score']:.1f}, away {ex['proj_away_score']:.1f}",
    ]
    return "\n".join(lines)
