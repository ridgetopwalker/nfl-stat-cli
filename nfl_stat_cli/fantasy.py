"""
NFL-Stat-CLI Fantasy Football Analytics Engine.
Calculates NFL Standard (non-PPR), Point-Per-Reception (PPR), and Half-PPR scoring
directly from play-by-play events across seasons, weeks, games, and individual players.
Includes interactive browser, weekly box scores, and game log drill-downs.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

# Standard NFL Fantasy Football scoring constants:
# Passing: 1 pt per 25 pass yds (0.04), 4 pts per pass TD, -2 pts per INT, 2 pts per 2-pt conversion
FANTASY_PASS_YARD_PTS = 0.04
FANTASY_PASS_TD_PTS = 4.0
FANTASY_INT_PTS = -2.0
FANTASY_PASS_2PT_PTS = 2.0

# Rushing: 1 pt per 10 rush yds (0.10), 6 pts per rush TD, 2 pts per 2-pt conversion
FANTASY_RUSH_YARD_PTS = 0.10
FANTASY_RUSH_TD_PTS = 6.0
FANTASY_RUSH_2PT_PTS = 2.0

# Receiving: 1 pt per 10 rec yds (0.10), 6 pts per rec TD, 2 pts per 2-pt conversion
FANTASY_REC_YARD_PTS = 0.10
FANTASY_REC_TD_PTS = 6.0
FANTASY_REC_2PT_PTS = 2.0

# Receptions: 0 for Standard, 1.0 for PPR, 0.5 for Half-PPR
FANTASY_REC_PPR_PTS = 1.0
FANTASY_REC_HALF_PPR_PTS = 0.5

# Turnovers: -2 pts per fumble lost
FANTASY_FUMBLE_LOST_PTS = -2.0


def calculate_player_fantasy_points(
    pass_yards: float = 0.0,
    pass_tds: int = 0,
    interceptions: int = 0,
    rush_yards: float = 0.0,
    rush_tds: int = 0,
    receptions: int = 0,
    rec_yards: float = 0.0,
    rec_tds: int = 0,
    fumbles_lost: int = 0,
    two_point_conversions: int = 0,
    format_type: str = "ppr",
) -> float:
    """
    Calculate fantasy points from component metrics across scoring formats:
    - 'standard' (0 PPR)
    - 'ppr' (1.0 PPR)
    - 'half_ppr' / 'half' (0.5 PPR)
    """
    fmt = format_type.strip().lower()
    rec_multiplier = (
        FANTASY_REC_HALF_PPR_PTS if fmt in ("half", "half_ppr", "0.5", "half-ppr")
        else (0.0 if fmt in ("standard", "std", "non-ppr", "0") else FANTASY_REC_PPR_PTS)
    )

    pts = (
        (pass_yards * FANTASY_PASS_YARD_PTS)
        + (pass_tds * FANTASY_PASS_TD_PTS)
        + (interceptions * FANTASY_INT_PTS)
        + (rush_yards * FANTASY_RUSH_YARD_PTS)
        + (rush_tds * FANTASY_RUSH_TD_PTS)
        + (rec_yards * FANTASY_REC_YARD_PTS)
        + (rec_tds * FANTASY_REC_TD_PTS)
        + (receptions * rec_multiplier)
        + (fumbles_lost * FANTASY_FUMBLE_LOST_PTS)
        + (two_point_conversions * 2.0)
    )
    return round(pts, 2)


def compute_player_fantasy_profile(player_name: str, plays: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate all play-by-play events involving a player (as QB, rusher, or receiver)
    and compute standard, PPR, and half-PPR fantasy totals along with weekly game logs.
    """
    p_low = player_name.strip().lower()
    last_name = p_low.split()[-1] if len(p_low.split()) > 1 else ""
    first_initial = p_low[0] if p_low else ""
    abbrev = f"{first_initial}.{last_name}" if last_name else ""

    canonical_name = player_name

    def _match_val(val: Any) -> bool:
        v = str(val or "").strip().lower()
        if not v:
            return False
        if v == p_low or v == canonical_name.lower():
            return True
        if abbrev and v == abbrev:
            return True
        if last_name and len(last_name) > 3 and v == last_name:
            return True
        return False

    def _matches_qb(p: Dict[str, Any]) -> bool:
        return any(_match_val(p.get(k)) for k in ("qb_name", "passer_player_name", "player_name"))

    def _matches_rusher(p: Dict[str, Any]) -> bool:
        return any(_match_val(p.get(k)) for k in ("rusher_player_name", "player_name"))

    def _matches_rec(p: Dict[str, Any]) -> bool:
        return any(_match_val(p.get(k)) for k in ("receiver_player_name", "player_name"))

    # Filter to plays where player was QB, rusher, receiver, or main player
    relevant = [
        p for p in plays
        if _matches_qb(p) or _matches_rusher(p) or _matches_rec(p)
    ]

    team = ""
    for p in relevant:
        for k in ("player_name", "qb_name", "rusher_player_name", "receiver_player_name", "passer_player_name"):
            val = str(p.get(k, "")).strip()
            if val and _match_val(val) and len(val) > len(canonical_name):
                canonical_name = val
        if p.get("posteam"):
            team = str(p.get("posteam"))
        if team and canonical_name != player_name:
            break

    # Group plays by game_id
    games_map: Dict[str, List[Dict[str, Any]]] = {}
    for p in relevant:
        gid = str(p.get("game_id", "game"))
        games_map.setdefault(gid, []).append(p)

    game_logs: List[Dict[str, Any]] = []
    tot_pass_yds = 0.0
    tot_pass_tds = 0
    tot_ints = 0
    tot_rush_yds = 0.0
    tot_rush_tds = 0
    tot_rush_att = 0
    tot_receptions = 0
    tot_rec_yds = 0.0
    tot_rec_tds = 0
    tot_targets = 0
    tot_fumbles_lost = 0
    tot_two_pts = 0

    for gid, gplays in games_map.items():
        sample = gplays[0]
        wk = int(sample.get("week", 1))
        opp = str(sample.get("defteam") if sample.get("posteam") == team else sample.get("posteam", ""))

        g_pass_yds = sum(
            float(p.get("passing_yards") if p.get("passing_yards") is not None else p.get("yards_gained", 0.0))
            for p in gplays
            if _matches_qb(p) and (int(p.get("pass_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "pass") and int(p.get("sack", 0)) == 0
        )
        g_pass_tds = sum(
            int(p.get("pass_touchdown") if p.get("pass_touchdown") is not None else p.get("touchdown", 0))
            for p in gplays
            if _matches_qb(p) and (int(p.get("pass_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "pass") and int(p.get("sack", 0)) == 0
        )
        g_ints = sum(int(p.get("interception", 0)) for p in gplays if _matches_qb(p))

        g_rush_yds = sum(
            float(p.get("rushing_yards") if p.get("rushing_yards") is not None else p.get("yards_gained", 0.0))
            for p in gplays
            if _matches_rusher(p) and (int(p.get("rush_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "run")
        )
        g_rush_tds = sum(
            int(p.get("rush_touchdown") if p.get("rush_touchdown") is not None else p.get("touchdown", 0))
            for p in gplays
            if _matches_rusher(p) and (int(p.get("rush_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "run")
        )
        g_rush_att = sum(
            1 for p in gplays
            if _matches_rusher(p) and (int(p.get("rush_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "run")
        )

        g_rec = sum(
            int(p.get("reception") if p.get("reception") is not None else p.get("complete_pass", 0))
            for p in gplays
            if _matches_rec(p) and int(p.get("complete_pass", 1 if p.get("reception") else 0)) == 1
        )
        g_rec_yds = sum(
            float(p.get("receiving_yards") if p.get("receiving_yards") is not None else p.get("yards_gained", 0.0))
            for p in gplays
            if _matches_rec(p) and int(p.get("complete_pass", 1 if p.get("reception") else 0)) == 1
        )
        g_rec_tds = sum(
            int(p.get("touchdown", 0))
            for p in gplays
            if _matches_rec(p) and int(p.get("complete_pass", 1 if p.get("reception") else 0)) == 1
        )
        g_targets = sum(
            1 for p in gplays
            if _matches_rec(p) and (int(p.get("pass_attempt", 0)) == 1 or str(p.get("play_type", "")).lower() == "pass") and int(p.get("sack", 0)) == 0
        )

        g_fumbles = sum(int(p.get("fumble_lost", 0)) for p in gplays if (
            _matches_rusher(p) or _matches_rec(p) or _matches_qb(p)
        ))
        g_2pt = sum(1 for p in gplays if int(p.get("two_point_conversion", 0)) == 1 and (
            _matches_rusher(p) or _matches_rec(p) or _matches_qb(p)
        ))

        std_pts = calculate_player_fantasy_points(
            pass_yards=g_pass_yds, pass_tds=g_pass_tds, interceptions=g_ints,
            rush_yards=g_rush_yds, rush_tds=g_rush_tds, receptions=g_rec,
            rec_yards=g_rec_yds, rec_tds=g_rec_tds, fumbles_lost=g_fumbles,
            two_point_conversions=g_2pt, format_type="standard"
        )
        ppr_pts = calculate_player_fantasy_points(
            pass_yards=g_pass_yds, pass_tds=g_pass_tds, interceptions=g_ints,
            rush_yards=g_rush_yds, rush_tds=g_rush_tds, receptions=g_rec,
            rec_yards=g_rec_yds, rec_tds=g_rec_tds, fumbles_lost=g_fumbles,
            two_point_conversions=g_2pt, format_type="ppr"
        )
        half_pts = calculate_player_fantasy_points(
            pass_yards=g_pass_yds, pass_tds=g_pass_tds, interceptions=g_ints,
            rush_yards=g_rush_yds, rush_tds=g_rush_tds, receptions=g_rec,
            rec_yards=g_rec_yds, rec_tds=g_rec_tds, fumbles_lost=g_fumbles,
            two_point_conversions=g_2pt, format_type="half_ppr"
        )

        tot_pass_yds += g_pass_yds
        tot_pass_tds += g_pass_tds
        tot_ints += g_ints
        tot_rush_yds += g_rush_yds
        tot_rush_tds += g_rush_tds
        tot_rush_att += g_rush_att
        tot_receptions += g_rec
        tot_rec_yds += g_rec_yds
        tot_rec_tds += g_rec_tds
        tot_targets += g_targets
        tot_fumbles_lost += g_fumbles
        tot_two_pts += g_2pt

        game_logs.append({
            "game_id": gid,
            "week": wk,
            "opponent": opp,
            "pass_yards": g_pass_yds,
            "pass_tds": g_pass_tds,
            "interceptions": g_ints,
            "rush_yards": g_rush_yds,
            "rush_tds": g_rush_tds,
            "rush_attempts": g_rush_att,
            "receptions": g_rec,
            "rec_yards": g_rec_yds,
            "rec_tds": g_rec_tds,
            "targets": g_targets,
            "fumbles_lost": g_fumbles,
            "points_std": std_pts,
            "points_ppr": ppr_pts,
            "points_half_ppr": half_pts,
        })

    game_logs.sort(key=lambda x: x["week"])
    gp = max(1, len(game_logs))

    total_std = calculate_player_fantasy_points(
        pass_yards=tot_pass_yds, pass_tds=tot_pass_tds, interceptions=tot_ints,
        rush_yards=tot_rush_yds, rush_tds=tot_rush_tds, receptions=tot_receptions,
        rec_yards=tot_rec_yds, rec_tds=tot_rec_tds, fumbles_lost=tot_fumbles_lost,
        two_point_conversions=tot_two_pts, format_type="standard"
    )
    total_ppr = calculate_player_fantasy_points(
        pass_yards=tot_pass_yds, pass_tds=tot_pass_tds, interceptions=tot_ints,
        rush_yards=tot_rush_yds, rush_tds=tot_rush_tds, receptions=tot_receptions,
        rec_yards=tot_rec_yds, rec_tds=tot_rec_tds, fumbles_lost=tot_fumbles_lost,
        two_point_conversions=tot_two_pts, format_type="ppr"
    )
    total_half = calculate_player_fantasy_points(
        pass_yards=tot_pass_yds, pass_tds=tot_pass_tds, interceptions=tot_ints,
        rush_yards=tot_rush_yds, rush_tds=tot_rush_tds, receptions=tot_receptions,
        rec_yards=tot_rec_yds, rec_tds=tot_rec_tds, fumbles_lost=tot_fumbles_lost,
        two_point_conversions=tot_two_pts, format_type="half_ppr"
    )

    return {
        "player": canonical_name,
        "team": team,
        "games_played": gp if relevant else 0,
        "pass_yards": tot_pass_yds,
        "pass_tds": tot_pass_tds,
        "interceptions": tot_ints,
        "rush_yards": tot_rush_yds,
        "rush_tds": tot_rush_tds,
        "rush_attempts": tot_rush_att,
        "receptions": tot_receptions,
        "targets": tot_targets,
        "rec_yards": tot_rec_yds,
        "rec_tds": tot_rec_tds,
        "fumbles_lost": tot_fumbles_lost,
        "two_point_conversions": tot_two_pts,
        "points_std": total_std,
        "points_ppr": total_ppr,
        "points_half_ppr": total_half,
        "ppg_std": round(total_std / gp, 2) if relevant else 0.0,
        "ppg_ppr": round(total_ppr / gp, 2) if relevant else 0.0,
        "ppg_half_ppr": round(total_half / gp, 2) if relevant else 0.0,
        "game_logs": game_logs,
    }


def compute_all_fantasy_leaders(
    plays: List[Dict[str, Any]],
    scoring_format: str = "ppr",
    position_filter: Optional[str] = None,
    week: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Extract all players who touched the ball (or threw/caught passes) in plays,
    evaluate their complete fantasy scoring profile in a single O(N) pass,
    and sort by fantasy points.
    """
    target_plays = plays
    if week is not None:
        target_plays = [p for p in target_plays if int(p.get("week", -1)) == int(week)]

    from . import KNOWN_PLAYER_POSITIONS

    # First pass: map abbreviations to full names if present
    canonical_names: Dict[str, str] = {}
    for p in target_plays:
        full_name = str(p.get("player_name") or "").strip()
        if full_name and len(full_name.split()) >= 2:
            for k in ("passer_player_name", "rusher_player_name", "receiver_player_name"):
                abbr = str(p.get(k) or "").strip()
                if abbr and abbr != full_name and abbr.startswith(full_name[0]) and abbr.split(".")[-1] in full_name:
                    canonical_names[abbr] = full_name
                    canonical_names[abbr.lower()] = full_name

    player_data: Dict[str, Dict[str, Any]] = {}
    player_games: Dict[str, Set[str]] = {}
    player_team: Dict[str, str] = {}
    player_pos: Dict[str, str] = {}

    def get_record(raw_name: str) -> Dict[str, Any]:
        c_name = canonical_names.get(raw_name, canonical_names.get(raw_name.lower(), raw_name))
        if c_name not in player_data:
            player_data[c_name] = {
                "player": c_name,
                "pass_yards": 0.0,
                "pass_tds": 0,
                "interceptions": 0,
                "rush_yards": 0.0,
                "rush_tds": 0,
                "rush_attempts": 0,
                "receptions": 0,
                "targets": 0,
                "rec_yards": 0.0,
                "rec_tds": 0,
                "fumbles_lost": 0,
                "two_point_conversions": 0,
            }
            player_games[c_name] = set()
        return player_data[c_name]

    for p in target_plays:
        gid = str(p.get("game_id", ""))
        pt = str(p.get("play_type", "")).lower()
        posteam = str(p.get("posteam", ""))

        # 1. Passing
        qb = str(p.get("passer_player_name") or p.get("qb_name") or p.get("player_name") or "").strip()
        if qb and qb.lower() not in ("unknown qb", "unknown player", "none", ""):
            is_pass = int(p.get("pass_attempt", 0)) == 1 or pt == "pass"
            is_sack = int(p.get("sack", 0)) == 1
            if is_pass and not is_sack:
                rec = get_record(qb)
                c_name = rec["player"]
                player_games[c_name].add(gid)
                if posteam:
                    player_team[c_name] = posteam
                player_pos[c_name] = "QB"
                p_yds = float(p.get("passing_yards") if p.get("passing_yards") is not None else p.get("yards_gained", 0.0))
                rec["pass_yards"] += p_yds
                p_td = int(p.get("pass_touchdown") if p.get("pass_touchdown") is not None else p.get("touchdown", 0))
                rec["pass_tds"] += p_td

            if int(p.get("interception", 0)) == 1:
                rec = get_record(qb)
                c_name = rec["player"]
                player_games[c_name].add(gid)
                player_pos[c_name] = "QB"
                rec["interceptions"] += 1

        # 2. Rushing
        rusher = str(p.get("rusher_player_name") or (p.get("player_name") if pt == "run" else "") or "").strip()
        if rusher and rusher.lower() not in ("unknown player", "unknown rusher", "none", ""):
            is_rush = int(p.get("rush_attempt", 0)) == 1 or pt == "run"
            if is_rush:
                rec = get_record(rusher)
                c_name = rec["player"]
                player_games[c_name].add(gid)
                if posteam:
                    player_team[c_name] = posteam
                if c_name not in player_pos:
                    raw_pos = str(p.get("rusher_position") or p.get("position") or "").upper()
                    player_pos[c_name] = raw_pos if raw_pos in ("QB", "RB", "WR", "TE") else "RB"
                rec["rush_attempts"] += 1
                r_yds = float(p.get("rushing_yards") if p.get("rushing_yards") is not None else p.get("yards_gained", 0.0))
                rec["rush_yards"] += r_yds
                r_td = int(p.get("rush_touchdown") if p.get("rush_touchdown") is not None else p.get("touchdown", 0))
                rec["rush_tds"] += r_td

        # 3. Receiving
        receiver = str(p.get("receiver_player_name") or (p.get("player_name") if int(p.get("reception", 0)) == 1 else "") or "").strip()
        if receiver and receiver.lower() not in ("unknown player", "unknown receiver", "none", ""):
            rec = get_record(receiver)
            c_name = rec["player"]
            player_games[c_name].add(gid)
            if posteam:
                player_team[c_name] = posteam
            if c_name not in player_pos:
                raw_pos = str(p.get("receiver_position") or p.get("position") or "").upper()
                player_pos[c_name] = raw_pos if raw_pos in ("QB", "RB", "WR", "TE") else "WR"
            if (int(p.get("pass_attempt", 0)) == 1 or pt == "pass") and int(p.get("sack", 0)) == 0:
                rec["targets"] += 1
            if int(p.get("reception") if p.get("reception") is not None else p.get("complete_pass", 0)) == 1:
                rec["receptions"] += 1
                rc_yds = float(p.get("receiving_yards") if p.get("receiving_yards") is not None else p.get("yards_gained", 0.0))
                rec["rec_yards"] += rc_yds
                rc_td = int(p.get("touchdown", 0))
                rec["rec_tds"] += rc_td

        # 4. Fumbles lost & 2-point conversions
        if int(p.get("fumble_lost", 0)) == 1:
            fumb_player = rusher or receiver or qb or str(p.get("player_name", "")).strip()
            if fumb_player:
                get_record(fumb_player)["fumbles_lost"] += 1

        if int(p.get("two_point_conversion", 0)) == 1:
            two_pt_player = rusher or receiver or qb or str(p.get("player_name", "")).strip()
            if two_pt_player:
                get_record(two_pt_player)["two_point_conversions"] += 1

    results: List[Dict[str, Any]] = []
    fmt = scoring_format.strip().lower()
    sort_key = "points_ppr" if fmt in ("ppr", "points_ppr") else (
        "points_half_ppr" if fmt in ("half", "half_ppr", "0.5") else "points_std"
    )

    for name, r in player_data.items():
        gp = max(1, len(player_games[name]))
        std_pts = calculate_player_fantasy_points(
            pass_yards=r["pass_yards"], pass_tds=r["pass_tds"], interceptions=r["interceptions"],
            rush_yards=r["rush_yards"], rush_tds=r["rush_tds"], receptions=r["receptions"],
            rec_yards=r["rec_yards"], rec_tds=r["rec_tds"], fumbles_lost=r["fumbles_lost"],
            two_point_conversions=r["two_point_conversions"], format_type="standard"
        )
        ppr_pts = calculate_player_fantasy_points(
            pass_yards=r["pass_yards"], pass_tds=r["pass_tds"], interceptions=r["interceptions"],
            rush_yards=r["rush_yards"], rush_tds=r["rush_tds"], receptions=r["receptions"],
            rec_yards=r["rec_yards"], rec_tds=r["rec_tds"], fumbles_lost=r["fumbles_lost"],
            two_point_conversions=r["two_point_conversions"], format_type="ppr"
        )
        half_pts = calculate_player_fantasy_points(
            pass_yards=r["pass_yards"], pass_tds=r["pass_tds"], interceptions=r["interceptions"],
            rush_yards=r["rush_yards"], rush_tds=r["rush_tds"], receptions=r["receptions"],
            rec_yards=r["rec_yards"], rec_tds=r["rec_tds"], fumbles_lost=r["fumbles_lost"],
            two_point_conversions=r["two_point_conversions"], format_type="half_ppr"
        )

        r["games_played"] = gp
        r["team"] = player_team.get(name, "")
        r["points_std"] = std_pts
        r["points_ppr"] = ppr_pts
        r["points_half_ppr"] = half_pts
        r["ppg_std"] = round(std_pts / gp, 2)
        r["ppg_ppr"] = round(ppr_pts / gp, 2)
        r["ppg_half_ppr"] = round(half_pts / gp, 2)

        # Skip players with 0 contribution
        if r["pass_yards"] == 0 and r["rush_yards"] == 0 and r["rec_yards"] == 0 and r[sort_key] == 0:
            continue

        pos = KNOWN_PLAYER_POSITIONS.get(name.lower(), player_pos.get(name, "WR"))
        r["position"] = pos

        if position_filter:
            pf = position_filter.strip().upper()
            if pf == "FLEX":
                if pos not in ("RB", "WR", "TE"):
                    continue
            elif pos != pf:
                continue

        results.append(r)

    results.sort(key=lambda x: (x.get(sort_key, 0.0), x.get("rush_yards", 0.0) + x.get("rec_yards", 0.0) + x.get("pass_yards", 0.0)), reverse=True)
    return results[:limit] if (limit and limit > 0) else results


def render_fantasy_leaderboard_view(
    plays: List[Dict[str, Any]],
    season: int,
    scoring_format: str = "ppr",
    position: Optional[str] = None,
    week: Optional[int] = None,
    limit: int = 15,
) -> str:
    """Render a colorized ASCII table of top fantasy scorers."""
    from . import C, AsciiArtRenderer

    fmt = scoring_format.strip().lower()
    fmt_title = "PPR (1.0 Pt/Catch)" if fmt == "ppr" else ("Half-PPR (0.5 Pt/Catch)" if fmt in ("half", "half_ppr") else "Standard (0 PPR)")
    score_col = "points_ppr" if fmt == "ppr" else ("points_half_ppr" if fmt in ("half", "half_ppr") else "points_std")
    ppg_col = "ppg_ppr" if fmt == "ppr" else ("ppg_half_ppr" if fmt in ("half", "half_ppr") else "ppg_std")

    leaders = compute_all_fantasy_leaders(plays, scoring_format=scoring_format, position_filter=position, week=week, limit=limit)

    sub_parts = [str(season)]
    if week:
        sub_parts.append(f"Week {week}")
    if position:
        sub_parts.append(f"Pos: {position.upper()}")
    sub_parts.append(fmt_title)
    title_str = f"🏈 Fantasy Football Scoring Leaders ({' • '.join(sub_parts)})"

    headers = ["Rank", "Player", "Pos", "Team", f"Fantasy Pts ({fmt.upper()})", "PPG", "Pass Yds/TD", "Rush Yds/TD", "Rec/Yds/TD", "FUM"]
    rows = []
    for idx, r in enumerate(leaders, 1):
        pass_stat = f"{int(r['pass_yards'])}/{r['pass_tds']}" if r['pass_yards'] > 0 else "-"
        rush_stat = f"{int(r['rush_yards'])}/{r['rush_tds']}" if (r['rush_yards'] > 0 or r['rush_tds'] > 0) else "-"
        rec_stat = f"{r['receptions']}/{int(r['rec_yards'])}/{r['rec_tds']}" if (r['receptions'] > 0 or r['rec_yards'] > 0) else "-"

        rows.append([
            f"#{idx}",
            f"{C.BOLD}{r['player']}{C.RESET}",
            f"{C.CYAN}{r.get('position', '')}{C.RESET}",
            r["team"] or "-",
            f"{C.BOLD}{C.GOLD}{r[score_col]:.2f}{C.RESET}",
            f"{r[ppg_col]:.1f}",
            pass_stat,
            rush_stat,
            rec_stat,
            str(r["fumbles_lost"]) if r["fumbles_lost"] > 0 else "-",
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["right", "left", "center", "center", "right", "right", "center", "center", "center", "center"],
    )
    footer = f"\n  {C.DIM}Scoring Rules: Pass: 0.04/yd, 4/TD, -2/INT │ Rush: 0.1/yd, 6/TD │ Rec: 0.1/yd, 6/TD, {1.0 if fmt=='ppr' else (0.5 if 'half' in fmt else 0.0)}/catch │ -2/Fumble Lost.{C.RESET}"
    return f"\n{tbl}{footer}"


def render_player_fantasy_profile_view(
    player_name: str,
    plays: List[Dict[str, Any]],
    season: int,
) -> str:
    """Render a comprehensive weekly fantasy profile and game log breakdown for a player."""
    from . import C, AsciiArtRenderer

    prof = compute_player_fantasy_profile(player_name, plays)
    if not prof or prof["games_played"] == 0:
        return f"\n{C.YELLOW}⚠ No fantasy game logs found for '{player_name}' in season {season}.{C.RESET}"

    p_name = prof["player"]
    team = prof["team"]
    title_str = f"🏈 Fantasy Profile & Weekly Game Log: {p_name} ({team} • {season})"

    headers = ["Week", "Opp", "Pass Yds", "Pass TD", "INT", "Rush Yds", "Rush TD", "Rec", "Rec Yds", "Rec TD", "Std Pts", "Half-PPR", "PPR Pts"]
    rows = []
    for g in prof["game_logs"]:
        rows.append([
            f"Wk {g['week']}",
            f"vs {g['opponent']}" if g['opponent'] else "-",
            f"{int(g['pass_yards'])}" if g['pass_yards'] > 0 else "-",
            str(g['pass_tds']) if g['pass_tds'] > 0 else "-",
            str(g['interceptions']) if g['interceptions'] > 0 else "-",
            f"{int(g['rush_yards'])}" if g['rush_yards'] != 0 else "-",
            str(g['rush_tds']) if g['rush_tds'] > 0 else "-",
            str(g['receptions']) if g['receptions'] > 0 else "-",
            f"{int(g['rec_yards'])}" if g['rec_yards'] != 0 else "-",
            str(g['rec_tds']) if g['rec_tds'] > 0 else "-",
            f"{g['points_std']:.1f}",
            f"{g['points_half_ppr']:.1f}",
            f"{C.BOLD}{C.GOLD}{g['points_ppr']:.1f}{C.RESET}",
        ])

    # Summary Totals row
    rows.append([
        f"{C.BOLD}TOTAL{C.RESET}",
        f"{prof['games_played']} Gms",
        f"{int(prof['pass_yards'])}",
        f"{prof['pass_tds']}",
        f"{prof['interceptions']}",
        f"{int(prof['rush_yards'])}",
        f"{prof['rush_tds']}",
        f"{prof['receptions']}",
        f"{int(prof['rec_yards'])}",
        f"{prof['rec_tds']}",
        f"{C.BOLD}{prof['points_std']:.1f}{C.RESET}",
        f"{C.BOLD}{prof['points_half_ppr']:.1f}{C.RESET}",
        f"{C.BOLD}{C.GREEN}{prof['points_ppr']:.1f}{C.RESET}",
    ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["center", "center", "right", "center", "center", "right", "center", "center", "right", "center", "right", "right", "right"],
    )

    summary_card = (
        f"\n  {C.BOLD}Season Averages ({prof['games_played']} games):{C.RESET} "
        f"PPR: {C.BOLD}{C.GOLD}{prof['ppg_ppr']:.1f} PPG{C.RESET}  │  "
        f"Half-PPR: {C.BOLD}{prof['ppg_half_ppr']:.1f} PPG{C.RESET}  │  "
        f"Standard: {C.BOLD}{prof['ppg_std']:.1f} PPG{C.RESET}"
    )
    return f"\n{tbl}{summary_card}"


def interactive_fantasy_browser(
    plays: List[Dict[str, Any]],
    active_season: int,
) -> None:
    """Interactive drill-down menu for Fantasy Football leaders, player profiles, and formats."""
    from . import C, prompt_input

    while True:
        print(f"\n{C.BOLD}{C.GOLD}=== 🏈 NFL FANTASY FOOTBALL ANALYTICS CENTER ==={C.RESET}")
        print(f"  Active Season: {C.BOLD}{active_season}{C.RESET}")
        print("  Select Fantasy Browsing Mode:")
        print(f"    [1] {C.BOLD}PPR Scoring Leaders{C.RESET} (1.0 Point per Reception)")
        print(f"    [2] {C.BOLD}Half-PPR Scoring Leaders{C.RESET} (0.5 Point per Reception)")
        print(f"    [3] {C.BOLD}Standard Scoring Leaders{C.RESET} (0.0 Point per Reception)")
        print(f"    [4] {C.BOLD}Filter Leaders by Position{C.RESET} (QB, RB, WR, TE, FLEX)")
        print(f"    [5] {C.BOLD}Player Weekly Fantasy Profile{C.RESET} (Search player game log)")
        print(f"    [q] {C.DIM}Return to main menu{C.RESET}")

        try:
            choice = prompt_input("  Choose mode [1-5, q] (default: 1): ").strip().lower() or "1"
        except (EOFError, KeyboardInterrupt):
            break

        if choice in ("q", "quit", "exit", "back"):
            break

        if choice == "1":
            print(render_fantasy_leaderboard_view(plays, active_season, scoring_format="ppr", limit=20))
        elif choice == "2":
            print(render_fantasy_leaderboard_view(plays, active_season, scoring_format="half_ppr", limit=20))
        elif choice == "3":
            print(render_fantasy_leaderboard_view(plays, active_season, scoring_format="standard", limit=20))
        elif choice == "4":
            try:
                pos = prompt_input("  Enter position [QB/RB/WR/TE/FLEX] (default: RB): ").strip().upper() or "RB"
                fmt = prompt_input("  Scoring format [ppr/half/std] (default: ppr): ").strip().lower() or "ppr"
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_fantasy_leaderboard_view(plays, active_season, scoring_format=fmt, position=pos, limit=15))
        elif choice == "5":
            try:
                p_in = prompt_input("  Enter player name (e.g. Mahomes, Henry, Jefferson, Stroud): ").strip() or "Mahomes"
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_player_fantasy_profile_view(p_in, plays, active_season))
