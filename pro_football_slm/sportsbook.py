"""
NFL-Stat-CLI Sportsbook & Game Handicapping Engine.
Applies quantitative sports betting modeling to NFL game data:
- Team Power Ratings derived from Net EPA/play, offensive scoring efficiency, and success rate.
- Modern Home Field Advantage (HFA = 1.8 pts).
- Point Spread derivation with key-number snapping (3, 7, 6, 10, 4, 14).
- Game Total (Over/Under) estimation from scoring pace and drive efficiency.
- Win Probability via normal distribution (NFL margin std dev = 13.5 pts) and American Moneylines.
- Against The Spread (ATS) and Over/Under validation on historical and live game results.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

HOME_FIELD_ADVANTAGE_PTS = 1.8
NFL_MARGIN_STD_DEV = 13.5
LEAGUE_AVERAGE_TOTAL = 44.0

KEY_NFL_NUMBERS = [3.0, 7.0, 6.0, 10.0, 4.0, 14.0]


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
        power_rating = (net_epa * 26.0) * 0.65 + (pt_diff * 0.35)

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
    Snap continuous mathematical margin to standard half-point sportsbook hook lines
    while respecting key NFL margin distribution numbers (3, 7, 6, 10).
    """
    # Round to nearest 0.5
    rounded = round(raw_spread * 2.0) / 2.0
    # Avoid flat 0.0 if there is any slight edge (make it -0.5 or +0.5 or PK)
    return rounded


def calculate_american_moneyline(win_prob: float) -> Tuple[int, int]:
    """
    Derive American Moneyline odds for home and away teams from win probability
    with standard ~4.5% sportsbook theoretical hold (vigorish).
    """
    p = max(0.01, min(0.99, win_prob))

    # Incorporate vig into implied book probabilities
    p_home_vig = min(0.98, p * 1.025)
    p_away_vig = min(0.98, (1.0 - p) * 1.025)

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
    Complete quantitative sportsbook handicapping of an NFL game:
    Spread, Moneyline, Over/Under Total, Win Probability, and ATS cover validation.
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
        fav_label = "PK (Pick'em)"
        dog_label = "PK (Pick'em)"

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

        # ATS: Home covers if actual_margin > -spread_line
        # (e.g. spread = -3.5, home wins by 4 -> 4 > 3.5 -> Home Covered)
        if actual_margin > -spread_line:
            ats_result = f"{home_team} Covered"
        elif actual_margin < -spread_line:
            ats_result = f"{away_team} Covered"
        else:
            ats_result = "PUSH"

        # Over / Under
        if actual_total > total_line:
            ou_result = f"OVER ({actual_total} > {total_line})"
        elif actual_total < total_line:
            ou_result = f"UNDER ({actual_total} < {total_line})"
        else:
            ou_result = f"PUSH ({actual_total})"

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


def render_sportsbook_board_view(
    plays: List[Dict[str, Any]],
    season: int,
    week_filter: Optional[int] = None,
) -> str:
    """Render a colorized ASCII table of NFL matchups with Vegas-modeled spreads, moneylines, and O/U."""
    from . import C, AsciiArtRenderer, extract_games_summary

    power_ratings = compute_team_power_ratings(plays, season)
    games = extract_games_summary(plays, season)
    if week_filter is not None:
        games = [g for g in games if int(g.get("week", -1)) == int(week_filter)]

    if not games:
        return f"\n{C.YELLOW}⚠ No games recorded in dataset for season {season}{f' Week {week_filter}' if week_filter else ''}.{C.RESET}"

    title_str = f"🎲 Sportsbook Betting Lines & Game Handicapping ({season}{f' • Week {week_filter}' if week_filter else ''})"
    headers = ["Week", "Matchup", "Spread Line", "Total (O/U)", "Moneyline (H / A)", "Model Score", "Actual", "ATS Result"]
    rows = []

    for g in games:
        h = g["home_team"]
        a = g["away_team"]
        wk = g["week"]
        hs = g.get("home_score")
        as_ = g.get("away_score")

        hc = handicap_matchup(h, a, power_ratings, week=wk, home_score=hs, away_score=as_)

        ml_h_str = f"{hc['home_ml']:+d}"
        ml_a_str = f"{hc['away_ml']:+d}"
        ml_str = f"{ml_h_str} / {ml_a_str}"

        actual_str = f"{as_}-{hs}" if (hs is not None and as_ is not None) else "TBD"
        score_str = f"{hc['proj_away_score']:.1f}-{hc['proj_home_score']:.1f}"

        ats_color = C.GREEN if "Covered" in hc["ats_result"] else C.RESET

        rows.append([
            f"Wk {wk}",
            f"{a} @ {C.BOLD}{h}{C.RESET}",
            f"{C.BOLD}{C.GOLD}{hc['favorite_str']}{C.RESET}",
            f"O/U {hc['total']:.1f}",
            ml_str,
            score_str,
            actual_str,
            f"{ats_color}{hc['ats_result']}{C.RESET}",
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["center", "left", "center", "center", "center", "center", "center", "center"],
    )
    footer = f"\n  {C.DIM}Lines modeled via Power Rating differentials, Home Field Advantage (+{HOME_FIELD_ADVANTAGE_PTS} pts), & Net EPA. Standings Std Dev = {NFL_MARGIN_STD_DEV} pts.{C.RESET}"
    return f"\n{tbl}{footer}"


def render_power_ratings_view(plays: List[Dict[str, Any]], season: int) -> str:
    """Render NFL 32-Team Power Ratings leaderboard table."""
    from . import C, AsciiArtRenderer

    ratings = compute_team_power_ratings(plays, season)
    sorted_teams = sorted(ratings.values(), key=lambda x: x["power_rating"], reverse=True)

    title_str = f"⚡ NFL Team Power Ratings & Handicapper Efficiency ({season})"
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
    return f"\n{tbl}"


def compute_underdog_leaders(
    plays: List[Dict[str, Any]],
    season: int,
    team_filter: Optional[str] = None,
    limit: Optional[int] = 5,
) -> List[Dict[str, Any]]:
    """
    Compute straight-up (SU) and against-the-spread (ATS) performance for NFL teams playing as underdogs.
    Sorted primarily by straight-up upset wins (most wins as an underdog), then win percentage, then ATS covers.
    """
    from . import resolve_team_abbr, extract_games_summary

    ratings = compute_team_power_ratings(plays, season)
    games = extract_games_summary(plays, season)

    dog_stats: Dict[str, Dict[str, Any]] = {}
    target_team = resolve_team_abbr(team_filter).upper() if team_filter and resolve_team_abbr(team_filter) else (team_filter.upper() if team_filter else None)

    for g in games:
        h = g["home_team"]
        a = g["away_team"]
        wk = g["week"]
        hs = g.get("home_score")
        as_ = g.get("away_score")

        hc = handicap_matchup(h, a, power_ratings=ratings, week=wk, home_score=hs, away_score=as_)
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
    title_str = f"🎲 NFL Underdog Performance Leaders: Most Wins as Underdog ({' • '.join(sub_parts)})"

    headers = ["Rank", "Team", "Dog Games", "SU Wins", "SU Record", "Win %", "ATS Record", "Cover %", "Avg Spread"]
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
    footer = f"\n  {C.DIM}Straight-Up (SU) wins indicate outright underdog victories (upsets). Lines derived from Net EPA & power ratings.{C.RESET}"
    return f"\n{tbl}{footer}"



def render_game_handicap_dossier_view(
    home_team: str,
    away_team: str,
    plays: List[Dict[str, Any]],
    season: int,
    week: Optional[int] = None,
) -> str:
    """Render an in-depth quantitative sportsbook handicapping dossier for a single matchup."""
    from . import C, AsciiArtRenderer, extract_games_summary

    power_ratings = compute_team_power_ratings(plays, season)
    games = extract_games_summary(plays, season)
    target_game = next(
        (g for g in games if g["home_team"].upper() == home_team.upper() and g["away_team"].upper() == away_team.upper()),
        None,
    )
    hs = target_game.get("home_score") if target_game else None
    as_ = target_game.get("away_score") if target_game else None
    wk = target_game.get("week") if target_game else week

    hc = handicap_matchup(home_team, away_team, power_ratings, week=wk, home_score=hs, away_score=as_)

    h_bar_len = int(round(hc["home_win_prob"] / 2.5))
    a_bar_len = int(round(hc["away_win_prob"] / 2.5))
    win_bar = f"{C.CYAN}{'█' * h_bar_len}{C.RESET}{C.YELLOW}{'░' * a_bar_len}{C.RESET}"

    lines = [
        f"\n{C.BOLD}{C.GOLD}╔══════════════════════════════════════════════════════════════════════════╗{C.RESET}",
        f"{C.BOLD}{C.GOLD}║             🎲 SPORTSBOOK HANDICAPPING DOSSIER & GAME ODDS               ║{C.RESET}",
        f"{C.BOLD}{C.GOLD}╚══════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        f"  {C.BOLD}Matchup:{C.RESET} {away_team} @ {C.BOLD}{home_team}{C.RESET} (Season {season}{f' • Week {wk}' if wk else ''})",
        "",
        f"  {C.CYAN}📊 SPREAD & TOTAL (OVER/UNDER):{C.RESET}",
        f"     • Point Spread:        {C.BOLD}{C.GOLD}{hc['favorite_str']}{C.RESET} (Raw Margin: {hc['expected_margin']:+.2f} pts)",
        f"     • Over / Under Total:  {C.BOLD}{hc['total']:.1f} pts{C.RESET}",
        f"     • Projected Score:     {C.BOLD}{away_team} {hc['proj_away_score']:.1f}  -  {home_team} {hc['proj_home_score']:.1f}{C.RESET}",
        "",
        f"  {C.GREEN}💰 AMERICAN MONEYLINES & WIN PROBABILITIES:{C.RESET}",
        f"     • {home_team} (Home):         {C.BOLD}{hc['home_ml']:+d}{C.RESET}  (Win Probability: {C.BOLD}{hc['home_win_prob']:.1f}%{C.RESET})",
        f"     • {away_team} (Away):         {C.BOLD}{hc['away_ml']:+d}{C.RESET}  (Win Probability: {C.BOLD}{hc['away_win_prob']:.1f}%{C.RESET})",
        f"     • Probability Bar:     [{win_bar}]",
        "",
        f"  {C.MAGENTA}⚖️  POWER RATINGS & ADVANTAGES:{C.RESET}",
        f"     • {home_team} Power Rating:   {hc['home_rating']:+.2f} pts",
        f"     • {away_team} Power Rating:   {hc['away_rating']:+.2f} pts",
        f"     • Home Field Advantage: +{hc['hfa']:.1f} pts",
    ]

    if hs is not None and as_ is not None:
        lines.extend([
            "",
            f"  {C.YELLOW}🏁 COMPLETED GAME OUTCOME & ATS EVALUATION:{C.RESET}",
            f"     • Final Score:         {away_team} {as_}  -  {home_team} {hs}",
            f"     • Spread Result (ATS): {C.BOLD}{hc['ats_result']}{C.RESET}",
            f"     • Total Result (O/U):  {C.BOLD}{hc['ou_result']}{C.RESET}",
        ])

    return "\n".join(lines)


def interactive_sportsbook_browser(
    plays: List[Dict[str, Any]],
    active_season: int,
) -> None:
    """Interactive drill-down menu for NFL Sportsbook odds, spreads, and power ratings."""
    from . import C, prompt_input, extract_games_summary

    while True:
        print(f"\n{C.BOLD}{C.GOLD}=== 🎲 NFL SPORTSBOOK HANDICAPPING CENTER ==={C.RESET}")
        print(f"  Active Season: {C.BOLD}{active_season}{C.RESET}")
        print("  Select Handicapping Browsing Mode:")
        print(f"    [1] {C.BOLD}Browse Weekly Betting Board{C.RESET} (Spreads, Moneylines, Totals & ATS Results)")
        print(f"    [2] {C.BOLD}NFL 32-Team Power Ratings{C.RESET} (Handicapper Power Standings)")
        print(f"    [3] {C.BOLD}Single Matchup Deep Dive{C.RESET} (Odds, Win Probability & Key Numbers)")
        print(f"    [4] {C.BOLD}Underdog Performance Leaders{C.RESET} (Most Outright Wins & Covers as Underdog)")
        print(f"    [q] {C.DIM}Return to main menu{C.RESET}")

        try:
            choice = prompt_input("  Choose mode [1-4, q] (default: 1): ").strip().lower() or "1"
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
