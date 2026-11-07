#!/usr/bin/env python3
"""
nfl-stat-cli: Cross-Platform (*nix & Windows) Colorized Terminal NFL Analytics,
Multi-Angle Play Visualizer (Behind Offense, Behind Defense, Sideline), & General Composable Custom Stat Engine.
Powered by sportsdataverse-py (Python), nflverse / nflreadr / nflfastR (R), and Local Small Language Model (SLM via Ollama) + Deterministic Engine.
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import json
import math
import operator
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Cross-Platform (*nix & Windows) ANSI Color Support
# ---------------------------------------------------------------------------

def enable_windows_ansi() -> None:
    """Enable virtual terminal processing on Windows 10/11 consoles."""
    if platform.system().lower() == "windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass


enable_windows_ansi()


class C:
    """ANSI escape codes for colorized ASCII art and terminal tables."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    TURF_GREEN = "\033[38;5;28m"
    TURF_LIGHT = "\033[38;5;34m"
    GOLD = "\033[38;5;220m"
    ORANGE = "\033[38;5;208m"

    # Backgrounds
    BG_TURF = "\033[48;5;22m"
    BG_ENDZONE_AFC = "\033[48;5;52m"
    BG_ENDZONE_NFC = "\033[48;5;17m"
    BG_HEADER = "\033[48;5;236m"

    @classmethod
    def disable(cls) -> None:
        for attr in dir(cls):
            if attr.isupper() and not attr.startswith("_"):
                setattr(cls, attr, "")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", str(text))


def visible_len(text: str) -> int:
    return len(strip_ansi(text))


def pad_ansi(text: str, width: int, align: str = "left") -> str:
    vlen = visible_len(text)
    pad = max(0, width - vlen)
    if align == "right":
        return (" " * pad) + text
    if align == "center":
        left = pad // 2
        right = pad - left
        return (" " * left) + text + (" " * right)
    return text + (" " * pad)


# ---------------------------------------------------------------------------
# Built-in Sample Play-by-Play Dataset (Fallback & Instant Demo Mode)
# Mirrors canonical nflverse / sportsdataverse-py play-by-play schema
# ---------------------------------------------------------------------------

AFC_TEAMS = {"BAL", "BUF", "CIN", "CLE", "DEN", "HOU", "IND", "JAX", "KC", "LV", "LAC", "MIA", "NE", "NYJ", "PIT", "TEN"}
NFC_TEAMS = {"ARI", "ATL", "CAR", "CHI", "DAL", "DET", "GB", "LA", "LAR", "MIN", "NO", "NYG", "PHI", "SEA", "SF", "TB", "WAS"}

TEAM_DIVISIONS: Dict[str, str] = {
    "BAL": "AFC North", "CIN": "AFC North", "CLE": "AFC North", "PIT": "AFC North",
    "BUF": "AFC East", "MIA": "AFC East", "NE": "AFC East", "NYJ": "AFC East",
    "HOU": "AFC South", "IND": "AFC South", "JAX": "AFC South", "TEN": "AFC South",
    "DEN": "AFC West", "KC": "AFC West", "LV": "AFC West", "LAC": "AFC West",
    "DAL": "NFC East", "NYG": "NFC East", "PHI": "NFC East", "WAS": "NFC East",
    "CHI": "NFC North", "DET": "NFC North", "GB": "NFC North", "MIN": "NFC North",
    "ATL": "NFC South", "CAR": "NFC South", "NO": "NFC South", "TB": "NFC South",
    "ARI": "NFC West", "LA": "NFC West", "LAR": "NFC West", "SF": "NFC West", "SEA": "NFC West",
}

SAMPLE_PBP_PLAYS: List[Dict[str, Any]] = [
    # KC (AFC) - Patrick Mahomes
    {"play_id": 101, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "X.Worthy", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "right", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -2.0, "yards_after_catch": 19.0, "xyac_mean_yardage": 8.4, "yards_gained": 17.0,
     "epa": 1.42, "wpa": 0.065, "cpoe": 8.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 8, "yardline_100": 68, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 4,
     "desc": "(11:20 Q4) P.Mahomes pass short right to X.Worthy pushed ob at BAL 49 for 17 yards (screen)."},
    {"play_id": 102, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "X.Worthy", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "play_action_deep", "play_direction": "middle", "is_screen": 0, "play_action": 1, "shotgun": 1,
     "air_yards": 28.0, "yards_after_catch": 7.0, "xyac_mean_yardage": 4.1, "yards_gained": 35.0,
     "epa": 2.65, "wpa": 0.112, "cpoe": 14.5, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 6, "yardline_100": 35, "series_success": 1, "touchdown": 1, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 4,
     "desc": "(06:42 Q4) P.Mahomes play-action pass deep middle to X.Worthy for 35 yards, TOUCHDOWN."},
    {"play_id": 103, "season": 2025, "week": 2, "game_id": "2025_02_CIN_KC", "posteam": "KC", "defteam": "CIN", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "R.Rice", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "left", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -1.0, "yards_after_catch": 14.0, "xyac_mean_yardage": 7.2, "yards_gained": 13.0,
     "epa": 0.95, "wpa": 0.048, "cpoe": 6.1, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 55, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 25, "qtr": 4,
     "desc": "(04:15 Q4) P.Mahomes pass short left to R.Rice to CIN 42 for 13 yards (screen)."},

    # BUF (AFC) - Josh Allen
    {"play_id": 104, "season": 2025, "week": 1, "game_id": "2025_01_ARI_BUF", "posteam": "BUF", "defteam": "ARI", "conf": "AFC",
     "qb_name": "J.Allen", "receiver_player_name": "K.Shakir", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "play_action_deep", "play_direction": "left", "is_screen": 0, "play_action": 1, "shotgun": 1,
     "air_yards": 22.0, "yards_after_catch": 12.0, "xyac_mean_yardage": 5.0, "yards_gained": 34.0,
     "epa": 2.40, "wpa": 0.095, "cpoe": 12.8, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 7, "yardline_100": 48, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 34, "away_score": 28, "qtr": 3,
     "desc": "(08:11 Q3) J.Allen play-action pass deep left to K.Shakir to ARI 14 for 34 yards."},
    {"play_id": 105, "season": 2025, "week": 1, "game_id": "2025_01_ARI_BUF", "posteam": "BUF", "defteam": "ARI", "conf": "AFC",
     "qb_name": "J.Allen", "receiver_player_name": "J.Cook", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "middle", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -3.0, "yards_after_catch": 21.0, "xyac_mean_yardage": 9.1, "yards_gained": 18.0,
     "epa": 1.55, "wpa": 0.072, "cpoe": 9.0, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 10, "yardline_100": 40, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 34, "away_score": 28, "qtr": 4,
     "desc": "(12:05 Q4) J.Allen pass short middle to J.Cook to ARI 22 for 18 yards (screen)."},
    {"play_id": 106, "season": 2025, "week": 2, "game_id": "2025_02_BUF_MIA", "posteam": "BUF", "defteam": "MIA", "conf": "AFC",
     "qb_name": "J.Allen", "receiver_player_name": "", "rusher_player_name": "J.Allen", "play_type": "run",
     "play_concept": "rush_outside", "play_direction": "left", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 15.0,
     "epa": 1.18, "wpa": 0.055, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 3, "ydstogo": 3, "yardline_100": 32, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 10, "away_score": 31, "qtr": 2,
     "desc": "(03:44 Q2) J.Allen scrambles left end to MIA 17 for 15 yards."},

    # BAL (AFC) - Lamar Jackson
    {"play_id": 107, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "L.Jackson", "receiver_player_name": "I.Likely", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "pass_intermediate", "play_direction": "middle", "is_screen": 0, "play_action": 1, "shotgun": 1,
     "air_yards": 14.0, "yards_after_catch": 8.0, "xyac_mean_yardage": 4.8, "yards_gained": 22.0,
     "epa": 1.62, "wpa": 0.068, "cpoe": 9.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 9, "yardline_100": 61, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 3,
     "desc": "(05:19 Q3) L.Jackson pass short middle to I.Likely to KC 39 for 22 yards."},
    {"play_id": 108, "season": 2025, "week": 3, "game_id": "2025_03_BAL_DAL", "posteam": "BAL", "defteam": "DAL", "conf": "AFC",
     "qb_name": "L.Jackson", "receiver_player_name": "", "rusher_player_name": "L.Jackson", "play_type": "run",
     "play_concept": "rush_outside", "play_direction": "left", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 26.0,
     "epa": 1.95, "wpa": 0.088, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 1, "ydstogo": 10, "yardline_100": 45, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 25, "away_score": 28, "qtr": 2,
     "desc": "(09:30 Q2) L.Jackson left end to DAL 19 for 26 yards."},

    # HOU (AFC) - C.J. Stroud
    {"play_id": 109, "season": 2025, "week": 1, "game_id": "2025_01_HOU_IND", "posteam": "HOU", "defteam": "IND", "conf": "AFC",
     "qb_name": "C.Stroud", "receiver_player_name": "N.Collins", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "play_action_deep", "play_direction": "right", "is_screen": 0, "play_action": 1, "shotgun": 0,
     "air_yards": 25.0, "yards_after_catch": 6.0, "xyac_mean_yardage": 3.5, "yards_gained": 31.0,
     "epa": 2.15, "wpa": 0.089, "cpoe": 11.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 8, "yardline_100": 52, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 29, "qtr": 4,
     "desc": "(02:15 Q4) C.Stroud pass deep right to N.Collins pushed ob at IND 21 for 31 yards."},

    # CLE (AFC) - Deshaun Watson (low impact loss)
    {"play_id": 110, "season": 2025, "week": 1, "game_id": "2025_01_DAL_CLE", "posteam": "CLE", "defteam": "DAL", "conf": "AFC",
     "qb_name": "D.Watson", "receiver_player_name": "A.Cooper", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "pass_short", "play_direction": "right", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 6.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 3.2, "yards_gained": 0.0,
     "epa": -1.85, "wpa": -0.095, "cpoe": -14.2, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 7, "yardline_100": 48, "series_success": 0, "touchdown": 0, "interception": 1, "sack": 0,
     "team_win": 0, "home_score": 17, "away_score": 33, "qtr": 3,
     "desc": "(07:02 Q3) D.Watson pass short right intended for A.Cooper INTERCEPTED by T.Diggs."},
    {"play_id": 111, "season": 2025, "week": 1, "game_id": "2025_01_DAL_CLE", "posteam": "CLE", "defteam": "DAL", "conf": "AFC",
     "qb_name": "D.Watson", "receiver_player_name": "", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "pass_short", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": -8.0,
     "epa": -1.45, "wpa": -0.062, "cpoe": -9.0, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 10, "yardline_100": 62, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 1,
     "team_win": 0, "home_score": 17, "away_score": 33, "qtr": 2,
     "desc": "(01:50 Q2) D.Watson sacked at CLE 30 for -8 yards (M.Parsons)."},

    # PIT (AFC) - Justin Fields (low impact win -> No-Decision)
    {"play_id": 112, "season": 2025, "week": 1, "game_id": "2025_01_PIT_ATL", "posteam": "PIT", "defteam": "ATL", "conf": "AFC",
     "qb_name": "J.Fields", "receiver_player_name": "N.Harris", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "left", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -1.0, "yards_after_catch": 6.0, "xyac_mean_yardage": 5.5, "yards_gained": 5.0,
     "epa": 0.04, "wpa": 0.010, "cpoe": 1.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 70, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 10, "away_score": 18, "qtr": 2,
     "desc": "(10:12 Q2) J.Fields pass short left to N.Harris to PIT 35 for 5 yards (screen)."},

    # DET (NFC) - Jared Goff & Screen Game
    {"play_id": 113, "season": 2025, "week": 1, "game_id": "2025_01_LA_DET", "posteam": "DET", "defteam": "LA", "conf": "NFC",
     "qb_name": "J.Goff", "receiver_player_name": "J.Gibbs", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "right", "is_screen": 1, "play_action": 0, "shotgun": 0,
     "air_yards": -2.0, "yards_after_catch": 24.0, "xyac_mean_yardage": 9.8, "yards_gained": 22.0,
     "epa": 1.78, "wpa": 0.081, "cpoe": 9.5, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 9, "yardline_100": 58, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 20, "qtr": 4,
     "desc": "(05:40 Q4) J.Goff pass short right to J.Gibbs to LA 36 for 22 yards (screen)."},
    {"play_id": 114, "season": 2025, "week": 2, "game_id": "2025_02_TB_DET", "posteam": "DET", "defteam": "TB", "conf": "NFC",
     "qb_name": "J.Goff", "receiver_player_name": "A.St. Brown", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "left", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -1.0, "yards_after_catch": 16.0, "xyac_mean_yardage": 8.0, "yards_gained": 15.0,
     "epa": 1.12, "wpa": 0.052, "cpoe": 7.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 46, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 16, "away_score": 20, "qtr": 3,
     "desc": "(09:05 Q3) J.Goff pass short left to A.St. Brown to TB 31 for 15 yards (screen)."},

    # SF (NFC) - Brock Purdy
    {"play_id": 115, "season": 2025, "week": 1, "game_id": "2025_01_NYJ_SF", "posteam": "SF", "defteam": "NYJ", "conf": "NFC",
     "qb_name": "B.Purdy", "receiver_player_name": "D.Samuel", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "left", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -2.0, "yards_after_catch": 18.0, "xyac_mean_yardage": 8.5, "yards_gained": 16.0,
     "epa": 1.30, "wpa": 0.060, "cpoe": 8.0, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 6, "yardline_100": 44, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 32, "away_score": 19, "qtr": 2,
     "desc": "(04:22 Q2) B.Purdy pass short left to D.Samuel to NYJ 28 for 16 yards (screen)."},

    # 2024 Historical Lookback plays for Stat Page trend tracking
    {"play_id": 201, "season": 2024, "week": 1, "game_id": "2024_01_DET_KC", "posteam": "KC", "defteam": "DET", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "J.McKinnon", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "right", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -2.0, "yards_after_catch": 14.0, "xyac_mean_yardage": 7.5, "yards_gained": 12.0,
     "epa": 0.92, "wpa": 0.044, "cpoe": 5.8, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 8, "yardline_100": 60, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 20, "away_score": 21, "qtr": 3,
     "desc": "(06:15 Q3) P.Mahomes pass short right to J.McKinnon for 12 yards (screen)."},
    {"play_id": 202, "season": 2024, "week": 2, "game_id": "2024_02_KC_JAX", "posteam": "KC", "defteam": "JAX", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "T.Kelce", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "play_action_deep", "play_direction": "right", "is_screen": 0, "play_action": 1, "shotgun": 1,
     "air_yards": 24.0, "yards_after_catch": 5.0, "xyac_mean_yardage": 3.8, "yards_gained": 29.0,
     "epa": 2.10, "wpa": 0.088, "cpoe": 11.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 6, "yardline_100": 29, "series_success": 1, "touchdown": 1, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 9, "away_score": 27, "qtr": 4,
     "desc": "(11:02 Q4) P.Mahomes pass deep right to T.Kelce for 29 yards, TOUCHDOWN."},
    {"play_id": 203, "season": 2024, "week": 2, "game_id": "2024_02_LV_BUF", "posteam": "BUF", "defteam": "LV", "conf": "AFC",
     "qb_name": "J.Allen", "receiver_player_name": "J.Cook", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "left", "is_screen": 1, "play_action": 0, "shotgun": 1,
     "air_yards": -2.0, "yards_after_catch": 17.0, "xyac_mean_yardage": 8.2, "yards_gained": 15.0,
     "epa": 1.25, "wpa": 0.059, "cpoe": 7.9, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 52, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 38, "away_score": 10, "qtr": 2,
     "desc": "(07:45 Q2) J.Allen pass short left to J.Cook for 15 yards (screen)."},
    {"play_id": 204, "season": 2024, "week": 3, "game_id": "2024_03_ATL_DET", "posteam": "DET", "defteam": "ATL", "conf": "NFC",
     "qb_name": "J.Goff", "receiver_player_name": "J.Gibbs", "rusher_player_name": "", "play_type": "pass",
     "play_concept": "screen", "play_direction": "right", "is_screen": 1, "play_action": 0, "shotgun": 0,
     "air_yards": -1.0, "yards_after_catch": 19.0, "xyac_mean_yardage": 8.6, "yards_gained": 18.0,
     "epa": 1.40, "wpa": 0.064, "cpoe": 8.3, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 7, "yardline_100": 49, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 20, "away_score": 6, "qtr": 3,
     "desc": "(03:18 Q3) J.Goff pass short right to J.Gibbs for 18 yards (screen)."},
]


# ---------------------------------------------------------------------------
# Dual Data Loader: sportsdataverse-py (Python) & nflverse/nflreadr (R)
# ---------------------------------------------------------------------------

def _infer_play_direction(row: Dict[str, Any], desc: str) -> str:
    raw = str(row.get("play_direction") or row.get("pass_location") or row.get("run_location") or "").lower()
    if raw in ("left", "middle", "right"):
        return raw
    dl = desc.lower()
    if "left" in dl:
        return "left"
    if "right" in dl:
        return "right"
    return "middle"


class NFLDataBridge:
    """
    Loads NFL Play-by-Play and Roster/Team data from:
    1. sportsdataverse-py (`sportsdataverse.nfl.load_nfl_pbp`) or `nflreadpy`
    2. nflverse R (`nflreadr::load_pbp`, `nflfastR`) via Rscript bridge
    3. Local cache / built-in sample dataset for instant offline operation
    """

    def __init__(self, cache_dir: Optional[Path] = None, engine: str = "auto") -> None:
        self.cache_dir = cache_dir or (Path.home() / ".nfl_stat_cli" / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine.lower()
        self.last_source_used = "built-in-nflverse-sample"

    def load_pbp(self, seasons: List[int]) -> List[Dict[str, Any]]:
        """Load play-by-play rows for the requested seasons using the selected engine."""
        if self.engine in ("auto", "python", "sdv"):
            rows = self._try_sportsdataverse_py(seasons)
            if rows:
                self.last_source_used = "sportsdataverse-py / nflreadpy (Python)"
                return rows

        if self.engine in ("auto", "r", "nflverse"):
            rows = self._try_nflverse_r(seasons)
            if rows:
                self.last_source_used = "nflverse / nflreadr (R)"
                return rows

        self.last_source_used = "built-in nflverse/sdv offline dataset"
        norm_sample = [self._normalize_row(r, idx) for idx, r in enumerate(SAMPLE_PBP_PLAYS, 1)]
        filtered = [r for r in norm_sample if int(r.get("season", 2025)) in seasons]
        return filtered if filtered else norm_sample

    def _try_sportsdataverse_py(self, seasons: List[int]) -> Optional[List[Dict[str, Any]]]:
        try:
            import nfl_data_py as nfl_data  # type: ignore[import]
            df = nfl_data.import_pbp_data(seasons)
            return self._normalize_dataframe(df)
        except Exception:
            pass
        try:
            import sportsdataverse.nfl as sdv_nfl  # type: ignore[import]
            df = sdv_nfl.load_nfl_pbp(seasons=seasons, return_as_pandas=True)
            return self._normalize_dataframe(df)
        except Exception:
            pass
        try:
            import nflreadpy as nfl  # type: ignore[import]
            df = nfl.load_pbp(seasons=seasons).to_pandas()
            return self._normalize_dataframe(df)
        except Exception:
            return None

    def _try_nflverse_r(self, seasons: List[int]) -> Optional[List[Dict[str, Any]]]:
        rscript_bin = shutil.which("Rscript")
        if not rscript_bin:
            return None
        bridge_script = Path(__file__).resolve().parent / "nflverse_bridge.R"
        out_csv = self.cache_dir / f"nflverse_pbp_{'_'.join(map(str, seasons))}.csv"
        seasons_arg = ",".join(map(str, seasons))
        try:
            if bridge_script.exists():
                cmd = [rscript_bin, str(bridge_script), "--seasons", seasons_arg, "--output", str(out_csv)]
            else:
                r_code = (
                    f"suppressPackageStartupMessages(library(nflreadr)); "
                    f"pbp <- load_pbp(c({seasons_arg})); "
                    f"write.csv(pbp, '{out_csv.as_posix()}', row.names=FALSE)"
                )
                cmd = [rscript_bin, "-e", r_code]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            if res.returncode == 0 and out_csv.exists():
                with open(out_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    return [self._normalize_row(r, idx) for idx, r in enumerate(reader, 1)]
        except Exception:
            return None
        return None

    def _normalize_dataframe(self, df: Any) -> List[Dict[str, Any]]:
        records = df.to_dict(orient="records")
        return [self._normalize_row(r, idx) for idx, r in enumerate(records, 1) if r.get("posteam")]

    def _normalize_row(self, r: Dict[str, Any], idx: int = 1) -> Dict[str, Any]:
        posteam = str(r.get("posteam") or "")
        conf = str(r.get("conf") or ("AFC" if posteam in AFC_TEAMS else ("NFC" if posteam in NFC_TEAMS else "NFL")))
        division = str(r.get("division") or TEAM_DIVISIONS.get(posteam, f"{conf} Division"))
        air_yards = float(r.get("air_yards") or 0.0)
        desc = str(r.get("desc") or "")
        pass_attempt = int(float(r.get("pass_attempt") or 0))
        rush_attempt = int(float(r.get("rush_attempt") or 0))
        complete_pass = int(float(r.get("complete_pass") or 0))
        is_screen = int(
            r.get("is_screen")
            or ("screen" in desc.lower())
            or (pass_attempt == 1 and air_yards <= 0.0 and complete_pass == 1)
        )
        play_type = str(r.get("play_type") or ("pass" if pass_attempt else "run"))
        play_action = int(float(r.get("play_action") or ("play-action" in desc.lower() or "play action" in desc.lower())))
        play_concept = str(r.get("play_concept") or (
            "screen" if is_screen else (
                "play_action_deep" if (play_action or air_yards >= 18) and play_type == "pass" else (
                    "pass_intermediate" if air_yards >= 10 and play_type == "pass" else (
                        "pass_short" if play_type == "pass" else "rush_outside"
                    )
                )
            )
        ))
        direction = _infer_play_direction(r, desc)
        yards_gained = float(r.get("yards_gained") or 0.0)
        ydstogo = int(float(r.get("ydstogo") or 10))
        touchdown = int(float(r.get("touchdown") or 0))
        yardline_100 = int(float(r.get("yardline_100") or 50))
        first_down = int(float(r.get("first_down") if r.get("first_down") is not None else (1 if (yards_gained >= ydstogo or touchdown == 1) else 0)))
        qb_name = str(r.get("qb_name") or r.get("passer_player_name") or r.get("rusher_player_name") or "Unknown QB")
        receiver_name = str(r.get("receiver_player_name") or "")
        rusher_name = str(r.get("rusher_player_name") or (qb_name if rush_attempt else ""))
        skill_player = receiver_name or rusher_name or qb_name
        home_score = int(float(r.get("home_score") or 0))
        away_score = int(float(r.get("away_score") or 0))
        score_diff = float(r.get("score_differential") if r.get("score_differential") is not None else abs(home_score - away_score))

        return {
            "play_id": int(float(r.get("play_id") or idx)),
            "season": int(float(r.get("season") or 2025)),
            "week": int(float(r.get("week") or 1)),
            "game_id": str(r.get("game_id") or "2025_01_UNK"),
            "posteam": posteam,
            "defteam": str(r.get("defteam") or ""),
            "conf": conf,
            "division": division,
            "qb_name": qb_name,
            "receiver_player_name": receiver_name,
            "rusher_player_name": rusher_name,
            "player_name": skill_player,
            "play_type": play_type,
            "play_concept": play_concept,
            "play_direction": direction,
            "is_screen": is_screen,
            "play_action": play_action,
            "shotgun": int(float(r.get("shotgun") or 0)),
            "no_huddle": int(float(r.get("no_huddle") or 0)),
            "red_zone": 1 if yardline_100 <= 20 else 0,
            "air_yards": air_yards,
            "yards_after_catch": float(r.get("yards_after_catch") or 0.0),
            "xyac_mean_yardage": float(r.get("xyac_mean_yardage") or 0.0),
            "yards_gained": yards_gained,
            "epa": float(r.get("epa") or 0.0),
            "wpa": float(r.get("wpa") or 0.0),
            "cpoe": float(r.get("cpoe") or 0.0),
            "complete_pass": complete_pass,
            "pass_attempt": pass_attempt,
            "rush_attempt": rush_attempt,
            "down": int(float(r.get("down") or 1)),
            "ydstogo": ydstogo,
            "yardline_100": yardline_100,
            "series_success": int(float(r.get("series_success") or 0)),
            "first_down": first_down,
            "explosive_play": 1 if yards_gained >= 20.0 else 0,
            "touchdown": touchdown,
            "interception": int(float(r.get("interception") or 0)),
            "fumble_lost": int(float(r.get("fumble_lost") or 0)),
            "sack": int(float(r.get("sack") or 0)),
            "team_win": int(float(r.get("team_win") if r.get("team_win") is not None else 1)),
            "home_score": home_score,
            "away_score": away_score,
            "score_differential": score_diff,
            "qtr": int(float(r.get("qtr") or 1)),
            "desc": desc,
        }


# ---------------------------------------------------------------------------
# Safe Formula & Filter Evaluator (Supports Numbers, Strings, Booleans, AST)
# ---------------------------------------------------------------------------

ALLOWED_AST_OPS: Dict[Any, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: (float(a) / float(b)) if float(b) != 0.0 else 0.0,
    ast.Mod: lambda a, b: (float(a) % float(b)) if float(b) != 0.0 else 0.0,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.BitAnd: lambda a, b: 1.0 if (bool(a) and bool(b)) else 0.0,
    ast.BitOr: lambda a, b: 1.0 if (bool(a) or bool(b)) else 0.0,
}

ALLOWED_FUNCS: Dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sqrt": lambda x: math.sqrt(max(0.0, float(x))),
    "log": lambda x: math.log(max(1e-9, float(x))),
    "pow": math.pow,
    "clamp": lambda x, lo, hi: max(float(lo), min(float(hi), float(x))),
    "ifelse": lambda cond, t_val, f_val: t_val if bool(cond) else f_val,
    "nz": lambda x, default=1.0: float(x) if float(x) != 0.0 else float(default),
}


def safe_eval_expr(expr: str, context: Dict[str, Any]) -> Any:
    """Safely evaluate a mathematical or boolean filter/stat expression using Python's AST."""
    tree = ast.parse(expr.strip(), mode="eval")

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)):
                return node.value
            raise ValueError(f"Unsupported constant: {node.value}")
        if isinstance(node, ast.Name):
            if node.id in ("True", "true"):
                return 1.0
            if node.id in ("False", "false"):
                return 0.0
            if node.id in context:
                return context[node.id]
            raise ValueError(f"Unknown variable '{node.id}' in expression '{expr}'")
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_AST_OPS:
            return ALLOWED_AST_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return 0.0 if bool(_eval(node.operand)) else 1.0
            if type(node.op) in ALLOWED_AST_OPS:
                return ALLOWED_AST_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return 1.0 if all(bool(_eval(v)) for v in node.values) else 0.0
            if isinstance(node.op, ast.Or):
                return 1.0 if any(bool(_eval(v)) for v in node.values) else 0.0
        if isinstance(node, ast.IfExp):
            return _eval(node.body) if bool(_eval(node.test)) else _eval(node.orelse)
        if isinstance(node, ast.Compare):
            left_v = _eval(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right_v = _eval(comp)
                if isinstance(left_v, str) or isinstance(right_v, str):
                    l_str = str(left_v).strip().lower()
                    r_str = str(right_v).strip().lower()
                    ok = (l_str == r_str) if isinstance(op, ast.Eq) else (
                        (l_str != r_str) if isinstance(op, ast.NotEq) else False
                    )
                else:
                    lf, rf = float(left_v), float(right_v)
                    if isinstance(op, ast.Gt):
                        ok = lf > rf
                    elif isinstance(op, ast.GtE):
                        ok = lf >= rf
                    elif isinstance(op, ast.Lt):
                        ok = lf < rf
                    elif isinstance(op, ast.LtE):
                        ok = lf <= rf
                    elif isinstance(op, ast.Eq):
                        ok = lf == rf
                    elif isinstance(op, ast.NotEq):
                        ok = lf != rf
                    else:
                        ok = False
                if not ok:
                    return 0.0
                left_v = right_v
            return 1.0
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname in ALLOWED_FUNCS:
                args = [_eval(a) for a in node.args]
                return ALLOWED_FUNCS[fname](*args)
        raise ValueError(f"Unsupported syntax in formula: {ast.dump(node)}")

    return _eval(tree)


def safe_eval_formula(expr: str, context: Dict[str, Any]) -> float:
    """Evaluate a formula and return a float value."""
    return float(safe_eval_expr(expr, context))


def extract_formula_dependencies(expr: str) -> List[str]:
    """Extract all variable identifiers referenced by a custom stat formula."""
    if not expr or not expr.strip():
        return []
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    deps: List[str] = []
    reserved = set(ALLOWED_FUNCS.keys()) | {"True", "False", "true", "false"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in reserved:
            if node.id not in deps:
                deps.append(node.id)
    return deps


# ---------------------------------------------------------------------------
# General-Purpose Stat Definition & Multi-Scope Composable Stat Engine
# ---------------------------------------------------------------------------

@dataclass
class StatDefinition:
    """
    Represents either a Traditional Stat or a User-Created Composable Custom Stat.
    Supports:
    - scope: "season" (default aggregate formula), "game" (evaluated per game then aggregated), or "play" (evaluated per play then aggregated)
    - agg: "formula" (default), "sum", "avg", "count_true", "rate", "max", "min"
    - filter_expr: play-level filter (e.g., "is_screen == 1", "down == 3", "qtr == 4", "conf == 'AFC'")
    - group_by: "qb" | "team" | "defteam" | "receiver" | "rusher" | "player" | "play_concept" | "play_type" | "conference" | "division" | "down" | "qtr" | "game"
    """
    name: str
    title: str
    category: str  # "traditional" | "custom"
    group_by: str
    formula: str
    description: str
    calculation_explained: str
    unit: str = ""
    filter_expr: str = ""
    scope: str = "season"     # "season" | "game" | "play"
    agg: str = "formula"      # "formula" | "sum" | "avg" | "count_true" | "rate" | "max" | "min"
    dependencies: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


DEFAULT_STATS: Dict[str, StatDefinition] = {
    # Traditional stats (available as building blocks for any custom stat)
    "yards_per_play": StatDefinition(
        name="yards_per_play",
        title="Yards Per Play (YPP)",
        category="traditional",
        group_by="play_concept",
        formula="total_yards / plays",
        description="Average offensive yards gained per snap across matching plays.",
        calculation_explained="Sum of yards_gained divided by total qualifying offensive plays (pass_attempt + rush_attempt).",
        unit="yds/play",
        dependencies=["total_yards", "plays"],
    ),
    "epa_per_play": StatDefinition(
        name="epa_per_play",
        title="Expected Points Added / Play (EPA/play)",
        category="traditional",
        group_by="qb",
        formula="total_epa / plays",
        description="Expected Points Added per offensive play from the nflfastR Expected Points model.",
        calculation_explained="Sum of play-level EPA (Expected Points after play minus Expected Points before play) divided by total plays.",
        unit="EPA/play",
        dependencies=["total_epa", "plays"],
    ),
    "success_rate_pct": StatDefinition(
        name="success_rate_pct",
        title="Offensive Success Rate (%)",
        category="traditional",
        group_by="team",
        formula="success_rate * 100.0",
        description="Percentage of plays that achieve positive series/down success.",
        calculation_explained="Divides successful plays (series_success == 1 or EPA > 0) by total plays, multiplied by 100.",
        unit="%",
        dependencies=["success_rate"],
    ),
    "passer_rating": StatDefinition(
        name="passer_rating",
        title="NFL Passer Rating",
        category="traditional",
        group_by="qb",
        formula="nfl_passer_rating",
        description="Official NFL Passer Rating (0.0 to 158.3 scale) based on completion %, YPA, TD %, and INT %.",
        calculation_explained="Standard NFL formula combining clamped completion %, yards/attempt, touchdowns/attempt, and interceptions/attempt.",
        unit="rtg",
        dependencies=["nfl_passer_rating"],
    ),
    "any_a": StatDefinition(
        name="any_a",
        title="Adjusted Net Yards / Attempt (ANY/A)",
        category="traditional",
        group_by="qb",
        formula="(passing_yards + 20.0 * touchdowns - 45.0 * interceptions - sack_yards_estimated) / nz(pass_attempts + sacks, 1)",
        description="Passing yards per dropback adjusted for touchdowns (+20 yds), interceptions (-45 yds), and sacks.",
        calculation_explained="(passing_yards + 20*TD - 45*INT - sack_yards) / (pass_attempts + sacks).",
        unit="ANY/A",
        dependencies=["passing_yards", "touchdowns", "interceptions", "sack_yards_estimated", "pass_attempts", "sacks"],
    ),
    "explosive_play_rate": StatDefinition(
        name="explosive_play_rate",
        title="Explosive Play Rate (20+ Yds %)",
        category="traditional",
        group_by="team",
        formula="(explosive_plays / plays) * 100.0",
        description="Percentage of offensive plays gaining 20 or more yards.",
        calculation_explained="Counts plays with yards_gained >= 20 divided by total plays * 100.",
        unit="%",
        dependencies=["explosive_plays", "plays"],
    ),
    "screen_yards_after_catch": StatDefinition(
        name="screen_yards_after_catch",
        title="Screen Pass Yards After Catch (Screen YAC/play)",
        category="traditional",
        group_by="team",
        formula="total_yac / plays",
        description="Average yards gained after the catch on screen pass plays (air_yards <= 0 or charted screen).",
        calculation_explained="Filters play-by-play to screen passes (is_screen == 1) and divides sum(yards_after_catch) by total screen plays.",
        unit="YAC/screen",
        filter_expr="is_screen == 1",
        dependencies=["total_yac", "plays"],
    ),
    "yac_over_expected": StatDefinition(
        name="yac_over_expected",
        title="Yards After Catch Over Expected (YACOE)",
        category="traditional",
        group_by="team",
        formula="(total_yac - total_xyac) / completions",
        description="Average extra yards gained after catch above nflfastR's xYAC model expectation.",
        calculation_explained="Subtracts nflfastR xyac_mean_yardage from actual yards_after_catch and divides by completed passes.",
        unit="yds",
        dependencies=["total_yac", "total_xyac", "completions"],
    ),
    # Composable Custom Stats (built using the exact same engine capabilities available to the user!)
    "qb_impact_score": StatDefinition(
        name="qb_impact_score",
        title="QB Game Impact Score (0-100)",
        category="custom",
        group_by="qb",
        formula="clamp(50 + (epa_per_play * 18.0) + (wpa_per_game * 85.0) + (avg_cpoe * 0.85) + (success_rate * 20.0 - 10.0) - (turnover_rate * 120.0), 0, 100)",
        description="0-to-100 composite score measuring how much a quarterback directly impacted the game outcome.",
        calculation_explained=(
            "Starts at a league-average baseline of 50.0 and adds weighted contributions from "
            "EPA/play (+18x), Win Probability Added per game (+85x), Completion % Over Expected (+0.85x), "
            "series success rate above 50% (+20x), minus turnover rate penalty (-120x), clamped to [0, 100]."
        ),
        unit="pts",
        scope="season",
        agg="formula",
        dependencies=["epa_per_play", "wpa_per_game", "avg_cpoe", "success_rate", "turnover_rate"],
    ),
    "qb_meaningful_win": StatDefinition(
        name="qb_meaningful_win",
        title="MLB-Style QB Meaningful Win (MW)",
        category="custom",
        group_by="qb",
        formula="ifelse((team_win == 1) and (qb_impact_score >= 55.0), 1, 0)",
        description="MLB pitcher-style QB Win credited per game ONLY when the team wins AND the QB was a meaningful contributor (Game Impact Score >= 55).",
        calculation_explained=(
            "Evaluates each individual game (scope='game', agg='sum') using the custom `qb_impact_score` stat: "
            "awards +1 Meaningful Win (MW) for each game where the team wins and game `qb_impact_score >= 55.0`. "
            "Wins where the QB plays below the 55.0 impact threshold are scored as a No-Decision (ND)."
        ),
        unit="MW",
        scope="game",
        agg="sum",
        dependencies=["team_win", "qb_impact_score"],
    ),
    "qb_meaningful_loss": StatDefinition(
        name="qb_meaningful_loss",
        title="MLB-Style Inverse QB Meaningful Loss (ML)",
        category="custom",
        group_by="qb",
        formula="ifelse((team_win == 0) and (qb_impact_score <= 42.0), 1, 0)",
        description="Inverse loss stat charged per game to a QB when the team loses AND the QB's Game Impact Score <= 42.0 materially drove the defeat.",
        calculation_explained=(
            "Evaluates each individual game (scope='game', agg='sum') on top of `qb_impact_score`: "
            "charges +1 Meaningful Loss (ML) only when the team loses and game `qb_impact_score <= 42.0`. "
            "Losses where a QB played high-impact football (`qb_impact_score > 42.0`) are recorded as a No-Decision (ND)."
        ),
        unit="ML",
        scope="game",
        agg="sum",
        dependencies=["team_win", "qb_impact_score"],
    ),
    "screen_effectiveness_index": StatDefinition(
        name="screen_effectiveness_index",
        title="Screen Pass Effectiveness Index (SPEI)",
        category="custom",
        group_by="team",
        formula="(yards_per_play * 3.5) + (screen_yards_after_catch * 2.5) + (yac_over_expected * 4.0) + (epa_per_play * 25.0)",
        description="Composite screen-game rating combining screen yards gained, screen YAC, YAC over expected, and screen EPA.",
        calculation_explained=(
            "Composes traditional/custom building blocks on screen plays (`is_screen == 1`): "
            "3.5 * `yards_per_play` + 2.5 * `screen_yards_after_catch` + 4.0 * `yac_over_expected` + 25.0 * `epa_per_play`."
        ),
        unit="idx",
        filter_expr="is_screen == 1",
        scope="season",
        agg="formula",
        dependencies=["yards_per_play", "screen_yards_after_catch", "yac_over_expected", "epa_per_play"],
    ),
}

# Starter templates for users who want examples when building their own custom stats
CUSTOM_STAT_TEMPLATES: List[Dict[str, str]] = [
    {
        "label": "Game-Conditional Stat (like MLB Pitcher QB Win / Quality Start)",
        "name": "qb_quality_start",
        "title": "QB Quality Start (QS)",
        "group_by": "qb",
        "scope": "game",
        "agg": "sum",
        "filter_expr": "",
        "formula": "ifelse((qb_impact_score >= 60.0) and (turnover_rate == 0), 1, 0)",
        "unit": "QS",
        "description": "Counts games where a QB posts a 60+ Game Impact Score with zero turnovers.",
        "calculation_explained": "Evaluated per game (scope=game, agg=sum): awards 1 QS when game qb_impact_score >= 60 and turnover_rate == 0.",
    },
    {
        "label": "Filtered Play-Concept Stat (like Screen Pass or Deep Play-Action Efficiency)",
        "name": "deep_pa_efficiency",
        "title": "Deep Play-Action Efficiency Index",
        "group_by": "team",
        "scope": "season",
        "agg": "formula",
        "filter_expr": "play_action == 1 and air_yards >= 15",
        "formula": "(yards_per_play * 2.5) + (epa_per_play * 20.0) + (completion_pct * 0.3)",
        "unit": "idx",
        "description": "Measures offensive efficiency on deep play-action passes (15+ air yards).",
        "calculation_explained": "Filters to play_action == 1 and air_yards >= 15, then weights yards_per_play (2.5x), epa_per_play (20x), and completion_pct (0.3x).",
    },
    {
        "label": "Situational Down/Quarter Stat (like 3rd/4th Down Clutch Conversion Rating)",
        "name": "third_down_clutch_rating",
        "title": "3rd Down Clutch Rating",
        "group_by": "qb",
        "scope": "season",
        "agg": "formula",
        "filter_expr": "down == 3",
        "formula": "(first_down_rate * 100.0) + (epa_per_play * 15.0) + (yards_per_play * 2.0)",
        "unit": "pts",
        "description": "Rates QBs on 3rd down by combining first-down conversion rate, EPA/play, and yards/play.",
        "calculation_explained": "Filters to 3rd down plays (down == 3) and sums conversion percentage, 15x EPA/play, and 2x yards/play.",
    },
    {
        "label": "Second-Order Chained Stat (combining multiple existing Custom Stats)",
        "name": "qb_clutch_win_index",
        "title": "QB Clutch Win Value Index",
        "group_by": "qb",
        "scope": "season",
        "agg": "formula",
        "filter_expr": "",
        "formula": "(qb_impact_score * 0.65) + (qb_meaningful_win * 12.0) - (qb_meaningful_loss * 15.0) + (yards_per_play * 1.5)",
        "unit": "idx",
        "description": "Second-order custom stat built on top of custom `qb_impact_score`, `qb_meaningful_win`, `qb_meaningful_loss`, and traditional `yards_per_play`.",
        "calculation_explained": "Multiplies custom `qb_impact_score` by 0.65, adds +12 per Meaningful Win, subtracts 15 per Meaningful Loss, and adds 1.5x `yards_per_play`.",
    },
]


# ---------------------------------------------------------------------------
# Stat Engine: Multi-Scope Aggregation, Dependency Resolution, & Stat Page
# ---------------------------------------------------------------------------

GROUP_BY_COLUMN_MAP: Dict[str, str] = {
    "qb": "qb_name",
    "team": "posteam",
    "defteam": "defteam",
    "receiver": "receiver_player_name",
    "rusher": "rusher_player_name",
    "player": "player_name",
    "play_concept": "play_concept",
    "play_type": "play_type",
    "conference": "conf",
    "division": "division",
    "down": "down",
    "qtr": "qtr",
    "game": "game_id",
}


class StatEngine:
    """Manages custom stats, evaluates multi-scope composable formulas, and tracks the user's Stat Page."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or (Path.home() / ".nfl_stat_cli")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.custom_stats_file = self.storage_dir / "custom_stats.json"
        self.stat_page_file = self.storage_dir / "stat_page.json"
        self.stats: Dict[str, StatDefinition] = dict(DEFAULT_STATS)
        self.stat_page: Dict[str, Any] = {
            "title": "My NFL Analytics Stat Page",
            "pinned_stats": [
                "qb_impact_score",
                "qb_meaningful_win",
                "qb_meaningful_loss",
                "screen_yards_after_catch",
                "screen_effectiveness_index",
                "yards_per_play",
            ],
            "lookback_history": {},
            "last_updated": None,
        }
        self._load_state()

    def _load_state(self) -> None:
        if self.custom_stats_file.exists():
            try:
                data = json.loads(self.custom_stats_file.read_text(encoding="utf-8"))
                for name, item in data.get("stats", {}).items():
                    if name in DEFAULT_STATS:
                        # Keep updated default scope/agg if loading older schema
                        item.setdefault("scope", DEFAULT_STATS[name].scope)
                        item.setdefault("agg", DEFAULT_STATS[name].agg)
                    self.stats[name] = StatDefinition(
                        name=item.get("name", name),
                        title=item.get("title", name),
                        category=item.get("category", "custom"),
                        group_by=item.get("group_by", "qb"),
                        formula=item["formula"],
                        description=item.get("description", ""),
                        calculation_explained=item.get("calculation_explained", ""),
                        unit=item.get("unit", ""),
                        filter_expr=item.get("filter_expr", ""),
                        scope=item.get("scope", "season"),
                        agg=item.get("agg", "formula"),
                        dependencies=item.get("dependencies") or extract_formula_dependencies(item["formula"]),
                        created_at=item.get("created_at", ""),
                    )
                # Ensure core built-in game-scoped stats use their game scope if old state had legacy formula
                for core_game_stat in ("qb_meaningful_win", "qb_meaningful_loss"):
                    if core_game_stat in self.stats and "win_rate" in self.stats[core_game_stat].formula:
                        self.stats[core_game_stat] = DEFAULT_STATS[core_game_stat]
            except Exception:
                pass
        if self.stat_page_file.exists():
            try:
                self.stat_page = json.loads(self.stat_page_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    def save_state(self) -> None:
        custom_only = {k: asdict(v) for k, v in self.stats.items() if v.category == "custom"}
        payload = {
            "schema_version": "2.0",
            "exported_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": custom_only,
        }
        self.custom_stats_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.stat_page_file.write_text(json.dumps(self.stat_page, indent=2), encoding="utf-8")

    def register_custom_stat(
        self,
        name: str,
        title: str,
        group_by: str,
        formula: str,
        description: str,
        calculation_explained: str,
        unit: str = "",
        filter_expr: str = "",
        scope: str = "season",
        agg: str = "formula",
        pin_to_page: bool = True,
    ) -> StatDefinition:
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())
        deps = extract_formula_dependencies(formula)
        dummy_ctx: Dict[str, Any] = {d: 1.0 for d in deps}
        safe_eval_formula(formula, dummy_ctx)

        if scope in ("game", "play") and agg == "formula":
            agg = "sum" if "ifelse" in formula else "avg"

        stat_def = StatDefinition(
            name=clean_name,
            title=title,
            category="custom",
            group_by=group_by,
            formula=formula,
            description=description,
            calculation_explained=calculation_explained,
            unit=unit,
            filter_expr=filter_expr,
            scope=scope,
            agg=agg,
            dependencies=deps,
        )
        self.stats[clean_name] = stat_def
        if pin_to_page and clean_name not in self.stat_page["pinned_stats"]:
            self.stat_page["pinned_stats"].append(clean_name)
        self.save_state()
        return stat_def

    def export_custom_stats_json(self, target_path: Path, include_traditional: bool = False) -> Path:
        exported = {
            k: asdict(v)
            for k, v in self.stats.items()
            if include_traditional or v.category == "custom"
        }
        payload = {
            "package": "nfl-stat-cli",
            "schema_version": "2.0",
            "exported_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stat_count": len(exported),
            "stats": exported,
            "stat_page_pinned": self.stat_page.get("pinned_stats", []),
        }
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target_path

    def import_custom_stats_json(self, source_path: Path) -> List[str]:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        stats_dict = raw.get("stats", raw)
        imported_names: List[str] = []
        for name, item in stats_dict.items():
            if isinstance(item, dict) and "formula" in item:
                stat_def = StatDefinition(
                    name=item.get("name", name),
                    title=item.get("title", name),
                    category=item.get("category", "custom"),
                    group_by=item.get("group_by", "qb"),
                    formula=item["formula"],
                    description=item.get("description", "Imported custom NFL stat."),
                    calculation_explained=item.get("calculation_explained", f"Calculated via formula: {item['formula']}"),
                    unit=item.get("unit", ""),
                    filter_expr=item.get("filter_expr", ""),
                    scope=item.get("scope", "season"),
                    agg=item.get("agg", "formula"),
                    dependencies=item.get("dependencies") or extract_formula_dependencies(item["formula"]),
                )
                self.stats[stat_def.name] = stat_def
                if stat_def.name not in self.stat_page["pinned_stats"]:
                    self.stat_page["pinned_stats"].append(stat_def.name)
                imported_names.append(stat_def.name)
        self.save_state()
        return imported_names

    def apply_filter(
        self,
        plays: List[Dict[str, Any]],
        filter_expr: str = "",
        conf: Optional[str] = None,
        team: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        result = plays
        if conf:
            result = [p for p in result if str(p.get("conf", "")).upper() == conf.upper()]
        if team:
            result = [p for p in result if str(p.get("posteam", "")).upper() == team.upper()]
        if not filter_expr or not filter_expr.strip():
            return result
        filtered: List[Dict[str, Any]] = []
        for p in result:
            try:
                if safe_eval_formula(filter_expr, p) > 0:
                    filtered.append(p)
            except Exception:
                pass
        return filtered

    def _compute_base_metrics(self, plays: List[Dict[str, Any]]) -> Dict[str, float]:
        n = max(1, len(plays))
        total_yards = sum(float(p.get("yards_gained", 0.0)) for p in plays)
        passing_yards = sum(float(p.get("yards_gained", 0.0)) for p in plays if int(p.get("pass_attempt", 0)) == 1 and int(p.get("sack", 0)) == 0)
        rushing_yards = sum(float(p.get("yards_gained", 0.0)) for p in plays if int(p.get("rush_attempt", 0)) == 1)
        total_air = sum(float(p.get("air_yards", 0.0)) for p in plays)
        total_yac = sum(float(p.get("yards_after_catch", 0.0)) for p in plays)
        total_xyac = sum(float(p.get("xyac_mean_yardage", 0.0)) for p in plays)
        total_epa = sum(float(p.get("epa", 0.0)) for p in plays)
        pass_plays = [p for p in plays if int(p.get("pass_attempt", 0)) == 1]
        rush_plays = [p for p in plays if int(p.get("rush_attempt", 0)) == 1]
        pass_epa = sum(float(p.get("epa", 0.0)) for p in pass_plays)
        rush_epa = sum(float(p.get("epa", 0.0)) for p in rush_plays)
        total_wpa = sum(float(p.get("wpa", 0.0)) for p in plays)
        completions = sum(int(p.get("complete_pass", 0)) for p in plays)
        pass_attempts = sum(int(p.get("pass_attempt", 0)) for p in plays)
        rush_attempts = sum(int(p.get("rush_attempt", 0)) for p in plays)
        touchdowns = sum(int(p.get("touchdown", 0)) for p in plays)
        interceptions = sum(int(p.get("interception", 0)) for p in plays)
        fumbles_lost = sum(int(p.get("fumble_lost", 0)) for p in plays)
        turnovers = interceptions + fumbles_lost
        sacks = sum(int(p.get("sack", 0)) for p in plays)
        sack_yards_est = sum(abs(float(p.get("yards_gained", 0.0))) for p in plays if int(p.get("sack", 0)) == 1)
        success_plays = sum(int(p.get("series_success", 0)) for p in plays)
        first_downs = sum(int(p.get("first_down", 0)) for p in plays)
        explosive_plays = sum(1 for p in plays if float(p.get("yards_gained", 0.0)) >= 20.0)
        screen_plays = sum(1 for p in plays if int(p.get("is_screen", 0)) == 1)
        play_action_plays = sum(1 for p in plays if int(p.get("play_action", 0)) == 1)

        games: Dict[str, int] = {}
        for p in plays:
            gid = str(p.get("game_id", "game"))
            games[gid] = int(p.get("team_win", 0))
        games_played = max(1, len(games))
        games_won = sum(1 for w in games.values() if w == 1)
        games_lost = games_played - games_won

        cpoe_vals = [float(p.get("cpoe", 0.0)) for p in pass_plays]
        avg_cpoe = (sum(cpoe_vals) / len(cpoe_vals)) if cpoe_vals else 0.0

        att_nz = float(max(1, pass_attempts))
        comp_nz = float(max(1, completions))
        rush_nz = float(max(1, rush_attempts))

        # Official NFL Passer Rating calculation
        pr_a = max(0.0, min(2.375, ((float(completions) / att_nz) - 0.3) * 5.0))
        pr_b = max(0.0, min(2.375, ((passing_yards / att_nz) - 3.0) * 0.25))
        pr_c = max(0.0, min(2.375, (float(touchdowns) / att_nz) * 20.0))
        pr_d = max(0.0, min(2.375, 2.375 - ((float(interceptions) / att_nz) * 25.0)))
        nfl_passer_rating = ((pr_a + pr_b + pr_c + pr_d) / 6.0) * 100.0 if pass_attempts > 0 else 0.0

        base: Dict[str, float] = {
            "plays": float(len(plays)),
            "games_played": float(games_played),
            "games_won": float(games_won),
            "games_lost": float(games_lost),
            "team_win": 1.0 if games_won >= games_lost and games_won > 0 else 0.0,
            "win_rate": float(games_won) / float(games_played),
            "total_yards": total_yards,
            "yards_per_play": total_yards / n,
            "passing_yards": passing_yards,
            "yards_per_attempt": passing_yards / att_nz,
            "yards_per_completion": passing_yards / comp_nz,
            "rushing_yards": rushing_yards,
            "yards_per_rush": rushing_yards / rush_nz,
            "total_air_yards": total_air,
            "air_yards_per_play": total_air / n,
            "air_yards_per_attempt": total_air / att_nz,
            "total_yac": total_yac,
            "yac_per_play": total_yac / n,
            "yac_per_completion": total_yac / comp_nz,
            "total_xyac": total_xyac,
            "xyac_per_completion": total_xyac / comp_nz,
            "completions": float(completions),
            "incompletions": float(max(0, pass_attempts - completions)),
            "completion_pct": (float(completions) / att_nz) * 100.0,
            "pass_attempts": float(pass_attempts),
            "rush_attempts": float(rush_attempts),
            "screen_plays": float(screen_plays),
            "play_action_plays": float(play_action_plays),
            "total_epa": total_epa,
            "epa_per_play": total_epa / n,
            "pass_epa_per_play": pass_epa / float(max(1, len(pass_plays))),
            "rush_epa_per_play": rush_epa / float(max(1, len(rush_plays))),
            "total_wpa": total_wpa,
            "wpa_per_play": total_wpa / n,
            "wpa_per_game": total_wpa / float(games_played),
            "avg_cpoe": avg_cpoe,
            "touchdowns": float(touchdowns),
            "interceptions": float(interceptions),
            "fumbles_lost": float(fumbles_lost),
            "turnovers": float(turnovers),
            "sacks": float(sacks),
            "sack_yards_estimated": sack_yards_est,
            "first_downs": float(first_downs),
            "first_down_rate": float(first_downs) / n,
            "explosive_plays": float(explosive_plays),
            "explosive_play_rate": (float(explosive_plays) / n) * 100.0,
            "turnover_rate": float(turnovers) / n,
            "sack_rate": float(sacks) / float(max(1, pass_attempts + sacks)),
            "td_rate": float(touchdowns) / n,
            "int_rate": float(interceptions) / att_nz,
            "success_rate": float(success_plays) / n,
            "nfl_passer_rating": nfl_passer_rating,
        }
        return base

    @staticmethod
    def _aggregate_values(vals: List[float], agg: str) -> float:
        if not vals:
            return 0.0
        agg_l = agg.lower()
        if agg_l == "sum":
            return sum(vals)
        if agg_l in ("avg", "mean", "formula"):
            return sum(vals) / len(vals)
        if agg_l == "count_true":
            return float(sum(1 for v in vals if v > 0.0))
        if agg_l == "rate":
            return (float(sum(1 for v in vals if v > 0.0)) / len(vals)) * 100.0
        if agg_l == "max":
            return max(vals)
        if agg_l == "min":
            return min(vals)
        return sum(vals) / len(vals)

    def _resolve_season_formulas(self, ctx: Dict[str, float], stat_defs: List[StatDefinition]) -> None:
        for _ in range(len(stat_defs) + 2):
            progressed = False
            for sdef in stat_defs:
                if sdef.scope == "season":
                    try:
                        val = safe_eval_formula(sdef.formula, ctx)
                        if ctx.get(sdef.name) != val:
                            ctx[sdef.name] = val
                            progressed = True
                    except Exception:
                        pass
            if not progressed:
                break

    def evaluate_all_metrics_for_group(self, plays: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Compute base traditional metrics AND resolve all composable custom stats across:
        1. Play-scoped custom stats (evaluated per play, aggregated via sdef.agg)
        2. Game-scoped custom stats (evaluated per game with full game-level custom stat context, aggregated via sdef.agg)
        3. Season-scoped custom stats (evaluated on the entity's season context in dependency order)
        """
        ctx = self._compute_base_metrics(plays)
        all_defs = list(self.stats.values())

        # 1. Play-scoped custom stats
        play_defs = [s for s in all_defs if s.scope == "play"]
        for sdef in play_defs:
            p_sub = self.apply_filter(plays, sdef.filter_expr) if sdef.filter_expr else plays
            p_vals: List[float] = []
            for p in p_sub:
                try:
                    p_vals.append(safe_eval_formula(sdef.formula, p))
                except Exception:
                    pass
            ctx[sdef.name] = self._aggregate_values(p_vals, sdef.agg)

        # 2. First-pass season formulas so game-scoped stats or season stats have baseline values
        self._resolve_season_formulas(ctx, all_defs)

        # 3. Game-scoped custom stats (evaluated per game_id)
        game_defs = [s for s in all_defs if s.scope == "game"]
        if game_defs:
            games_map: Dict[str, List[Dict[str, Any]]] = {}
            for p in plays:
                gid = str(p.get("game_id", "game"))
                games_map.setdefault(gid, []).append(p)

            game_contexts: List[Dict[str, float]] = []
            for gplays in games_map.values():
                g_ctx = self._compute_base_metrics(gplays)
                self._resolve_season_formulas(g_ctx, all_defs)
                # Resolve game-scoped stats inside each game context in dependency order
                for _ in range(len(game_defs) + 2):
                    for gdef in game_defs:
                        try:
                            g_ctx[gdef.name] = safe_eval_formula(gdef.formula, g_ctx)
                        except Exception:
                            pass
                game_contexts.append(g_ctx)

            for gdef in game_defs:
                g_vals = [gc.get(gdef.name, 0.0) for gc in game_contexts]
                ctx[gdef.name] = self._aggregate_values(g_vals, gdef.agg)

        # 4. Final pass for season-scoped custom stats that depend on game-scoped or play-scoped custom stats
        self._resolve_season_formulas(ctx, all_defs)
        return ctx

    def evaluate_stat_leaderboard(
        self,
        stat_name: str,
        plays: List[Dict[str, Any]],
        conf: Optional[str] = None,
        team: Optional[str] = None,
        group_override: Optional[str] = None,
        extra_filter: str = "",
    ) -> List[Dict[str, Any]]:
        """Evaluate a traditional or custom stat across entities and return a sorted leaderboard."""
        if stat_name not in self.stats:
            raise KeyError(f"Stat '{stat_name}' is not registered.")
        sdef = self.stats[stat_name]
        filtered = self.apply_filter(plays, sdef.filter_expr, conf=conf, team=team)
        if extra_filter:
            filtered = self.apply_filter(filtered, extra_filter)
        group_col = group_override or sdef.group_by
        key_field = GROUP_BY_COLUMN_MAP.get(group_col, "posteam")

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in filtered:
            gval = str(p.get(key_field) or "").strip()
            if not gval:
                continue
            groups.setdefault(gval, []).append(p)

        rows: List[Dict[str, Any]] = []
        for gval, gplays in groups.items():
            metrics = self.evaluate_all_metrics_for_group(gplays)
            sample_play = max(gplays, key=lambda x: float(x.get("yards_gained", 0.0)))
            mw = int(round(metrics.get("qb_meaningful_win", 0.0)))
            ml = int(round(metrics.get("qb_meaningful_loss", 0.0)))
            gp = int(metrics["games_played"])
            rows.append({
                "entity": gval,
                "team": str(gplays[0].get("posteam", "")),
                "conf": str(gplays[0].get("conf", "")),
                "value": round(float(metrics.get(stat_name, 0.0)), 2),
                "plays": int(metrics["plays"]),
                "games_played": gp,
                "yards_per_play": round(metrics["yards_per_play"], 2),
                "total_yards": round(metrics["total_yards"], 1),
                "yac_per_play": round(metrics["yac_per_play"], 2),
                "epa_per_play": round(metrics["epa_per_play"], 2),
                "success_rate_pct": round(metrics["success_rate"] * 100.0, 1),
                "completion_pct": round(metrics["completion_pct"], 1),
                "qb_impact_score": round(metrics.get("qb_impact_score", 0.0), 1),
                "qb_meaningful_win": mw,
                "qb_meaningful_loss": ml,
                "games_won": int(metrics["games_won"]),
                "games_lost": int(metrics["games_lost"]),
                "no_decisions": max(0, gp - mw - ml),
                "best_play": sample_play,
                "metrics": metrics,
            })

        rows.sort(key=lambda r: (r["value"], r["epa_per_play"]), reverse=True)
        return rows

    def query_plays(
        self,
        plays: List[Dict[str, Any]],
        season: Optional[int] = None,
        conf: Optional[str] = None,
        team: Optional[str] = None,
        qb: Optional[str] = None,
        concept: Optional[str] = None,
        play_type: Optional[str] = None,
        filter_expr: str = "",
        sort_by: str = "yards_gained",
        play_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Filter and rank individual plays for play-level inspection and ASCII field visualization."""
        res = list(plays)
        if play_id is not None:
            exact = [p for p in res if int(p.get("play_id", -1)) == int(play_id)]
            if exact:
                return exact
        if season is not None:
            s_match = [p for p in res if int(p.get("season", 2025)) == int(season)]
            if s_match:
                res = s_match
        if conf:
            res = [p for p in res if str(p.get("conf", "")).upper() == conf.upper()]
        if team:
            res = [p for p in res if team.upper() in (str(p.get("posteam", "")).upper(), str(p.get("defteam", "")).upper())]
        if qb:
            q_low = qb.lower()
            res = [p for p in res if q_low in str(p.get("qb_name", "")).lower() or q_low in str(p.get("player_name", "")).lower() or q_low in str(p.get("desc", "")).lower()]
        if concept:
            c_low = concept.lower()
            res = [p for p in res if c_low in str(p.get("play_concept", "")).lower() or (c_low == "screen" and int(p.get("is_screen", 0)) == 1)]
        if play_type:
            pt_low = play_type.lower()
            res = [p for p in res if str(p.get("play_type", "")).lower() == pt_low]
        if filter_expr:
            res = self.apply_filter(res, filter_expr)

        sort_map = {
            "yards": "yards_gained",
            "yards_gained": "yards_gained",
            "epa": "epa",
            "wpa": "wpa",
            "yac": "yards_after_catch",
            "yards_after_catch": "yards_after_catch",
            "air_yards": "air_yards",
        }
        s_col = sort_map.get(sort_by.lower(), "yards_gained")
        res.sort(key=lambda p: (float(p.get(s_col, 0.0)), float(p.get("epa", 0.0))), reverse=True)
        return res

    def update_stat_page_tracking(self, all_plays: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update lookback & forward season snapshots for all pinned stats on the Stat Page."""
        seasons = sorted({int(p.get("season", 2025)) for p in all_plays})
        history = self.stat_page.setdefault("lookback_history", {})

        for stat_name in self.stat_page.get("pinned_stats", []):
            if stat_name not in self.stats:
                continue
            stat_hist = history.setdefault(stat_name, {})
            for s in seasons:
                s_plays = [p for p in all_plays if int(p.get("season", 2025)) == s]
                board = self.evaluate_stat_leaderboard(stat_name, s_plays)
                if board:
                    leader = board[0]
                    avg_val = round(sum(r["value"] for r in board) / len(board), 2)
                    stat_hist[str(s)] = {
                        "season": s,
                        "leader": leader["entity"],
                        "leader_team": leader["team"],
                        "leader_value": leader["value"],
                        "league_avg": avg_val,
                        "qualified_entities": len(board),
                    }
        self.stat_page["last_updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save_state()
        return self.stat_page


# ---------------------------------------------------------------------------
# Colorized ASCII Art Renderer:
# Supports Behind-the-Offense, Behind-the-Defense, and Sideline Play Views
# ---------------------------------------------------------------------------

class AsciiArtRenderer:
    """Renders ANSI-colorized ASCII art banners, multi-angle football play diagrams, and tables."""

    @staticmethod
    def banner() -> str:
        lines = [
            f"{C.BOLD}{C.GOLD}╔══════════════════════════════════════════════════════════════════════════════════════╗{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.DIM}{C.WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Play Visualizer{C.RESET}   {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}╚══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        ]
        return "\n".join(lines)

    @staticmethod
    def render_table(title: str, headers: List[str], rows: List[List[Any]], alignments: Optional[List[str]] = None) -> str:
        if not rows:
            return f"\n{C.BOLD}{C.GOLD}▶ {title}{C.RESET}\n  {C.DIM}(No matching records found){C.RESET}"
        if not alignments:
            alignments = ["left"] + ["right"] * (len(headers) - 1)
        str_rows = [[str(cell) for cell in r] for r in rows]
        widths = [max([visible_len(h)] + [visible_len(r[i]) for r in str_rows]) for i, h in enumerate(headers)]

        top = "┌─" + "─┬─".join("─" * w for w in widths) + "─┐"
        sep = "├─" + "─┼─".join("─" * w for w in widths) + "─┤"
        bot = "└─" + "─┴─".join("─" * w for w in widths) + "─┘"

        header_cells = [f"{C.BOLD}{C.CYAN}{pad_ansi(h, widths[i], alignments[i])}{C.RESET}" for i, h in enumerate(headers)]
        header_line = "│ " + " │ ".join(header_cells) + " │"

        out = [f"\n{C.BOLD}{C.GOLD}▶ {title}{C.RESET}", top, header_line, sep]
        for r in str_rows:
            cells = [pad_ansi(r[i], widths[i], alignments[i]) for i in range(len(headers))]
            out.append("│ " + " │ ".join(cells) + " │")
        out.append(bot)
        return "\n".join(out)

    @staticmethod
    def _place_token(row_chars: List[str], col: int, token: str, color: str) -> None:
        width = len(row_chars)
        start = max(0, min(width - len(token), col - len(token) // 2))
        for i, ch in enumerate(token):
            if 0 <= start + i < width:
                row_chars[start + i] = f"{color}{ch}{C.RESET}"

    @classmethod
    def render_field_and_play(
        cls,
        play: Dict[str, Any],
        title: str = "PLAY VISUALIZER",
        camera: str = "behind-offense",
    ) -> str:
        """
        Render a specific play on the ASCII football field from the chosen camera perspective:
        - 'behind-offense' (or 'offense'): All-22 view behind QB/Offense looking upfield toward Defense
        - 'behind-defense' (or 'defense'): All-22 view behind Defense/Safeties looking toward Offense
        - 'sideline' (or 'side'): 100-yard left-to-right broadcast view
        - 'all': renders behind-offense and behind-defense
        """
        cam = camera.strip().lower().replace("_", "-")
        if cam in ("offense", "behind-offense", "qb", "all22-offense"):
            return cls.render_behind_offense(play, title=title)
        if cam in ("defense", "behind-defense", "def", "all22-defense"):
            return cls.render_behind_defense(play, title=title)
        if cam in ("all", "both", "all-angles"):
            return (
                cls.render_behind_offense(play, title=f"{title} [BEHIND OFFENSE]")
                + "\n"
                + cls.render_behind_defense(play, title=f"{title} [BEHIND DEFENSE]")
                + "\n"
                + cls.render_sideline(play, title=f"{title} [SIDELINE VIEW]")
            )
        return cls.render_sideline(play, title=title)

    @classmethod
    def render_behind_offense(cls, play: Dict[str, Any], title: str = "BEHIND THE OFFENSE PLAY VIEW") -> str:
        """
        All-22 Behind-the-Offense View:
        Viewer is behind the QB looking UPFIELD (▲) toward the Defense and Opponent End Zone.
        Left of screen = Offense Left; Right of screen = Offense Right.
        """
        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        conf = str(play.get("conf", "NFL"))
        qb_name = str(play.get("qb_name", "QB"))
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        yardline_100 = int(play.get("yardline_100", 50))
        los_yard = max(1, min(99, 100 - yardline_100))
        yards_gained = float(play.get("yards_gained", 0.0))
        air_yards = float(play.get("air_yards", 0.0))
        yac = float(play.get("yards_after_catch", 0.0))
        ydstogo = int(play.get("ydstogo", 10))
        down = int(play.get("down", 1))
        qtr = int(play.get("qtr", 1))
        is_screen = int(play.get("is_screen", 0)) == 1
        play_type = str(play.get("play_type", "pass"))
        concept = str(play.get("play_concept", "pass"))
        direction = _infer_play_direction(play, str(play.get("desc", "")))
        is_td = int(play.get("touchdown", 0)) == 1
        is_int = int(play.get("interception", 0)) == 1
        is_sack = int(play.get("sack", 0)) == 1

        width = 56
        total_rows = 15
        los_row = 11  # Row 11 is Line of Scrimmage; Rows 0..10 are upfield (+33y down to +3y); Rows 12..14 are backfield

        def depth_to_row(rel_yards: float) -> int:
            # Each row above LOS is ~3 yards
            r = int(round(los_row - (rel_yards / 3.0)))
            return max(0, min(total_rows - 1, r))

        dir_col_map = {"left": 12, "middle": 28, "right": 44}
        target_col = dir_col_map.get(direction, 28)
        qb_row, qb_col = 13, 28
        catch_row = depth_to_row(air_yards) if play_type == "pass" else los_row
        end_row = 0 if is_td else depth_to_row(yards_gained)
        fd_row = depth_to_row(float(ydstogo))

        ez_banner = f"{C.BOLD}{C.WHITE}╔══════╦{'═' * width}╦══════╗{C.RESET}"
        ez_title = pad_ansi(f"▲ OPPONENT END ZONE ({defteam}) • OFFENSE DRIVING UPFIELD ▲", width, "center")
        ez_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE}  TD  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.BOLD}{C.GOLD}{ez_title}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE}  TD  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        mid_sep = f"{C.BOLD}{C.WHITE}╠══════╬{'═' * width}╬══════╣{C.RESET}"
        bot_border = f"{C.BOLD}{C.WHITE}╚══════╩{'═' * width}╩══════╝{C.RESET}"
        side_hdr = f"        {C.DIM}◀ OFFENSE LEFT            HASH :     : HASH           OFFENSE RIGHT ▶{C.RESET}"

        out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} — [CAMERA: BEHIND THE OFFENSE]{C.RESET}",
            f"  {C.BOLD}{posteam}{C.RESET} vs {C.BOLD}{defteam}{C.RESET} ({conf}) │ Q{qtr} • {down}&{ydstogo} at Own {los_yard} │ Direction: {C.CYAN}{direction.upper()}{C.RESET}",
            side_hdr,
            ez_banner,
            ez_row,
            mid_sep,
        ]

        # Precompute trajectory points
        air_points: Dict[Tuple[int, int], str] = {}
        yac_points: Dict[Tuple[int, int], str] = {}

        if is_sack:
            end_row, target_col = qb_row, qb_col
        elif play_type == "pass":
            # Line from (qb_row, qb_col) to (catch_row, target_col)
            steps = max(1, max(abs(catch_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (catch_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                ch = "╱" if target_col > qb_col + 3 else ("╲" if target_col < qb_col - 3 else "⋮")
                air_points[(r_p, c_p)] = ch
            # YAC from (catch_row, target_col) to (end_row, target_col)
            if not is_int and end_row != catch_row:
                step_r = -1 if end_row < catch_row else 1
                for r_p in range(catch_row + step_r, end_row, step_r):
                    yac_points[(r_p, target_col)] = "║"
        else:
            # Rush path from (qb_row, qb_col) to (end_row, target_col)
            steps = max(1, max(abs(end_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (end_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                yac_points[(r_p, c_p)] = "║"

        for r_idx in range(total_rows):
            rel_yds = (los_row - r_idx) * 3
            row_chars = [f"{C.TURF_GREEN}░{C.RESET}"] * width
            # Hash marks at cols 20 and 35, numbers at cols 6 and 49
            row_chars[20] = f"{C.GRAY}:{C.RESET}"
            row_chars[35] = f"{C.GRAY}:{C.RESET}"
            if r_idx % 2 == 0:
                row_chars[5] = f"{C.TURF_LIGHT}·{C.RESET}"
                row_chars[50] = f"{C.TURF_LIGHT}·{C.RESET}"

            # Line of Scrimmage (Blue) & First Down Line (Yellow)
            if r_idx == los_row:
                row_chars = [f"{C.BOLD}{C.BLUE}━{C.RESET}"] * width
            elif r_idx == fd_row:
                row_chars = [f"{C.BOLD}{C.YELLOW}┄{C.RESET}"] * width

            # Draw Defense Formation (Red) above LOS
            if r_idx == max(1, los_row - 7):
                cls._place_token(row_chars, 18, "FS", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 38, "SS", f"{C.BOLD}{C.RED}")
            elif r_idx == max(2, los_row - 4):
                cls._place_token(row_chars, 7, "CB", f"{C.RED}")
                cls._place_token(row_chars, 22, "LB", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 34, "LB", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 49, "CB", f"{C.RED}")
            elif r_idx == los_row - 1:
                for dl_col, dl_lbl in [(21, "DE"), (25, "DT"), (31, "DT"), (35, "DE")]:
                    cls._place_token(row_chars, dl_col, dl_lbl, f"{C.RED}")

            # Draw Offense Formation (Cyan/White) on & behind LOS
            if r_idx == los_row:
                cls._place_token(row_chars, 6, "WR", f"{C.BOLD}{C.CYAN}")
                for ol_col, ol_lbl in [(22, "LT"), (25, "LG"), (28, "C"), (31, "RG"), (34, "RT")]:
                    cls._place_token(row_chars, ol_col, ol_lbl, f"{C.BOLD}{C.WHITE}")
                cls._place_token(row_chars, 38, "TE", f"{C.BOLD}{C.CYAN}")
                cls._place_token(row_chars, 50, "WR", f"{C.BOLD}{C.CYAN}")
            elif r_idx == qb_row:
                cls._place_token(row_chars, qb_col, "QB", f"{C.BOLD}{C.CYAN}")
                cls._place_token(row_chars, qb_col + 5, "RB", f"{C.CYAN}")

            # Screen blockers
            if is_screen and r_idx == max(0, catch_row - 1):
                for blk_c in (target_col - 2, target_col, target_col + 2):
                    if 0 <= blk_c < width:
                        row_chars[blk_c] = f"{C.BOLD}{C.ORANGE}▓{C.RESET}"

            # Overlay Air Path & YAC Path
            for (pr, pc), ch in air_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.CYAN}{ch}{C.RESET}"
            for (pr, pc), ch in yac_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.GREEN}{ch}{C.RESET}"

            # Catch Point & End Spot
            if play_type == "pass" and r_idx == catch_row and not is_sack:
                marker = f"{C.BOLD}{C.RED}✖{C.RESET}" if is_int else f"{C.BOLD}{C.MAGENTA}◎{C.RESET}"
                row_chars[target_col] = marker
            if r_idx == end_row:
                end_marker = f"{C.BOLD}{C.RED}⚡{C.RESET}" if (is_sack or is_int) else f"{C.BOLD}{C.GOLD}★{C.RESET}"
                row_chars[target_col] = end_marker

            if r_idx == los_row:
                lbl = f"{C.BOLD}{C.BLUE}  LOS {C.RESET}"
            elif r_idx == fd_row:
                lbl = f"{C.BOLD}{C.YELLOW}  1ST {C.RESET}"
            else:
                lbl = f"{C.GRAY}{rel_yds:+4d}y {C.RESET}"

            out.append(f"{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}{''.join(row_chars)}{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}")

        out.append(bot_border)
        out.append(cls._play_legend_and_summary(play, qb_name, target_name, los_yard, down, ydstogo, air_yards, yac, yards_gained, concept, "BEHIND OFFENSE (Looking ▲ Upfield)"))
        return "\n".join(out)

    @classmethod
    def render_behind_defense(cls, play: Dict[str, Any], title: str = "BEHIND THE DEFENSE PLAY VIEW") -> str:
        """
        All-22 Behind-the-Defense View:
        Viewer is behind the Defensive Secondary (Safeties) looking at the Offense driving DOWNWARD (▼) toward the Defense.
        Perspective is mirrored laterally: Left of screen = Offense Right / Defense Left; Right of screen = Offense Left / Defense Right.
        """
        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        conf = str(play.get("conf", "NFL"))
        qb_name = str(play.get("qb_name", "QB"))
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        yardline_100 = int(play.get("yardline_100", 50))
        los_yard = max(1, min(99, 100 - yardline_100))
        yards_gained = float(play.get("yards_gained", 0.0))
        air_yards = float(play.get("air_yards", 0.0))
        yac = float(play.get("yards_after_catch", 0.0))
        ydstogo = int(play.get("ydstogo", 10))
        down = int(play.get("down", 1))
        qtr = int(play.get("qtr", 1))
        is_screen = int(play.get("is_screen", 0)) == 1
        play_type = str(play.get("play_type", "pass"))
        concept = str(play.get("play_concept", "pass"))
        direction = _infer_play_direction(play, str(play.get("desc", "")))
        is_td = int(play.get("touchdown", 0)) == 1
        is_int = int(play.get("interception", 0)) == 1
        is_sack = int(play.get("sack", 0)) == 1

        width = 56
        total_rows = 15
        los_row = 3  # Offense is at top (rows 0..3); Play drives DOWNWARD (rows 4..14) toward Defense!

        def depth_to_row(rel_yards: float) -> int:
            r = int(round(los_row + (rel_yards / 3.0)))
            return max(0, min(total_rows - 1, r))

        # Mirror lateral column: from Defense POV facing Offense, Offense's Right is on viewer's Left (col 12)
        dir_col_map_mirrored = {"right": 12, "middle": 28, "left": 44}
        target_col = dir_col_map_mirrored.get(direction, 28)
        qb_row, qb_col = 1, 28
        catch_row = depth_to_row(air_yards) if play_type == "pass" else los_row
        end_row = total_rows - 1 if is_td else depth_to_row(yards_gained)
        fd_row = depth_to_row(float(ydstogo))

        top_banner = f"{C.BOLD}{C.WHITE}╔══════╦{'═' * width}╦══════╗{C.RESET}"
        off_hdr = pad_ansi(f"▼ OFFENSE BACKFIELD ({posteam}) DRIVING DOWNWARD TOWARD DEFENSE ▼", width, "center")
        off_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.WHITE} OFF  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.BOLD}{C.CYAN}{off_hdr}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.WHITE} OFF  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        mid_sep = f"{C.BOLD}{C.WHITE}╠══════╬{'═' * width}╬══════╣{C.RESET}"
        def_hdr = pad_ansi(f"🛡 DEFENSE SECONDARY VIEW ({defteam} END ZONE BEHIND VIEWER) 🛡", width, "center")
        def_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE} DEF  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.BOLD}{C.GOLD}{def_hdr}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE} DEF  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        bot_border = f"{C.BOLD}{C.WHITE}╚══════╩{'═' * width}╩══════╝{C.RESET}"
        side_hdr = f"        {C.DIM}◀ DEF LEFT (OFF RIGHT)   HASH :     : HASH   DEF RIGHT (OFF LEFT) ▶{C.RESET}"

        out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} — [CAMERA: BEHIND THE DEFENSE]{C.RESET}",
            f"  {C.BOLD}{defteam} Defense POV{C.RESET} vs {C.BOLD}{posteam} Offense{C.RESET} ({conf}) │ Q{qtr} • {down}&{ydstogo} │ Off Direction: {C.CYAN}{direction.upper()}{C.RESET}",
            side_hdr,
            top_banner,
            off_row,
            mid_sep,
        ]

        air_points: Dict[Tuple[int, int], str] = {}
        yac_points: Dict[Tuple[int, int], str] = {}

        if is_sack:
            end_row, target_col = qb_row, qb_col
        elif play_type == "pass":
            steps = max(1, max(abs(catch_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (catch_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                ch = "╲" if target_col > qb_col + 3 else ("╱" if target_col < qb_col - 3 else "⋮")
                air_points[(r_p, c_p)] = ch
            if not is_int and end_row != catch_row:
                step_r = 1 if end_row > catch_row else -1
                for r_p in range(catch_row + step_r, end_row, step_r):
                    yac_points[(r_p, target_col)] = "║"
        else:
            steps = max(1, max(abs(end_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (end_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                yac_points[(r_p, c_p)] = "║"

        for r_idx in range(total_rows):
            rel_yds = (r_idx - los_row) * 3
            row_chars = [f"{C.TURF_GREEN}░{C.RESET}"] * width
            row_chars[20] = f"{C.GRAY}:{C.RESET}"
            row_chars[35] = f"{C.GRAY}:{C.RESET}"
            if r_idx % 2 == 0:
                row_chars[5] = f"{C.TURF_LIGHT}·{C.RESET}"
                row_chars[50] = f"{C.TURF_LIGHT}·{C.RESET}"

            if r_idx == los_row:
                row_chars = [f"{C.BOLD}{C.BLUE}━{C.RESET}"] * width
            elif r_idx == fd_row:
                row_chars = [f"{C.BOLD}{C.YELLOW}┄{C.RESET}"] * width

            # Offense at top (mirrored left-to-right from Defense viewpoint)
            if r_idx == qb_row:
                cls._place_token(row_chars, qb_col - 5, "RB", f"{C.CYAN}")
                cls._place_token(row_chars, qb_col, "QB", f"{C.BOLD}{C.CYAN}")
            elif r_idx == los_row:
                cls._place_token(row_chars, 6, "WR", f"{C.BOLD}{C.CYAN}")
                cls._place_token(row_chars, 18, "TE", f"{C.BOLD}{C.CYAN}")
                for ol_col, ol_lbl in [(22, "RT"), (25, "RG"), (28, "C"), (31, "LG"), (34, "LT")]:
                    cls._place_token(row_chars, ol_col, ol_lbl, f"{C.BOLD}{C.WHITE}")
                cls._place_token(row_chars, 50, "WR", f"{C.BOLD}{C.CYAN}")

            # Defense in foreground (below LOS)
            if r_idx == los_row + 1:
                for dl_col, dl_lbl in [(21, "DE"), (25, "DT"), (31, "DT"), (35, "DE")]:
                    cls._place_token(row_chars, dl_col, dl_lbl, f"{C.RED}")
            elif r_idx == min(total_rows - 2, los_row + 4):
                cls._place_token(row_chars, 7, "CB", f"{C.RED}")
                cls._place_token(row_chars, 22, "LB", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 34, "LB", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 49, "CB", f"{C.RED}")
            elif r_idx == min(total_rows - 1, los_row + 7):
                cls._place_token(row_chars, 18, "SS", f"{C.BOLD}{C.RED}")
                cls._place_token(row_chars, 38, "FS", f"{C.BOLD}{C.RED}")

            if is_screen and r_idx == min(total_rows - 1, catch_row + 1):
                for blk_c in (target_col - 2, target_col, target_col + 2):
                    if 0 <= blk_c < width:
                        row_chars[blk_c] = f"{C.BOLD}{C.ORANGE}▓{C.RESET}"

            for (pr, pc), ch in air_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.CYAN}{ch}{C.RESET}"
            for (pr, pc), ch in yac_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.GREEN}{ch}{C.RESET}"

            if play_type == "pass" and r_idx == catch_row and not is_sack:
                marker = f"{C.BOLD}{C.RED}✖{C.RESET}" if is_int else f"{C.BOLD}{C.MAGENTA}◎{C.RESET}"
                row_chars[target_col] = marker
            if r_idx == end_row:
                end_marker = f"{C.BOLD}{C.RED}⚡{C.RESET}" if (is_sack or is_int) else f"{C.BOLD}{C.GOLD}★{C.RESET}"
                row_chars[target_col] = end_marker

            if r_idx == los_row:
                lbl = f"{C.BOLD}{C.BLUE}  LOS {C.RESET}"
            elif r_idx == fd_row:
                lbl = f"{C.BOLD}{C.YELLOW}  1ST {C.RESET}"
            else:
                lbl = f"{C.GRAY}{rel_yds:+4d}y {C.RESET}"

            out.append(f"{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}{''.join(row_chars)}{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}")

        out.extend([mid_sep, def_row, bot_border])
        out.append(cls._play_legend_and_summary(play, qb_name, target_name, los_yard, down, ydstogo, air_yards, yac, yards_gained, concept, "BEHIND DEFENSE (Offense Driving ▼ Toward Viewer)"))
        return "\n".join(out)

    @classmethod
    def render_sideline(cls, play: Dict[str, Any], title: str = "SIDELINE BROADCAST PLAY VIEW") -> str:
        """Render a colorized 100-yard sideline view (left-to-right) with lateral direction awareness."""
        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        conf = str(play.get("conf", "NFL"))
        yardline_100 = int(play.get("yardline_100", 60))
        los_yard = max(1, min(99, 100 - yardline_100))
        yards_gained = float(play.get("yards_gained", 15.0))
        air_yards = float(play.get("air_yards", 0.0))
        yac = float(play.get("yards_after_catch", 0.0))
        ydstogo = int(play.get("ydstogo", 10))
        down = int(play.get("down", 1))
        is_screen = int(play.get("is_screen", 0)) == 1
        play_type = str(play.get("play_type", "pass"))
        concept = str(play.get("play_concept", "pass"))
        qb_name = str(play.get("qb_name", "QB"))
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        direction = _infer_play_direction(play, str(play.get("desc", "")))

        end_yard = max(0, min(100, int(round(los_yard + yards_gained))))
        catch_yard = max(0, min(100, int(round(los_yard + air_yards)))) if play_type == "pass" else los_yard
        first_down_yard = max(0, min(100, los_yard + ydstogo))

        field_width = 60
        def y_to_col(y: float) -> int:
            return max(0, min(field_width - 1, int(round((y / 100.0) * (field_width - 1)))))

        los_col = y_to_col(los_yard)
        catch_col = y_to_col(catch_yard)
        end_col = y_to_col(end_yard)
        fd_col = y_to_col(first_down_yard)
        target_row = 1 if direction == "left" else (5 if direction == "right" else 3)

        border = f"{C.BOLD}{C.WHITE}+------+{'-' * field_width}+------+{C.RESET}"
        yard_hdr = f"       {C.GRAY}0    10    20    30    40    50    40    30    20    10   100{C.RESET}"

        rows_out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} — [CAMERA: SIDELINE BROADCAST] ({posteam} vs {defteam} • {conf}){C.RESET}",
            yard_hdr,
            border,
        ]

        ez_left = ["  " + posteam[:3].ljust(3) + " ", " OWN  ", " END  ", " ZONE ", "  🏈  ", "      ", "      "]
        ez_right = ["  " + defteam[:3].ljust(3) + " ", " OPP  ", " END  ", " ZONE ", "  TD  ", "      ", "      "]

        for r_idx in range(7):
            row_chars = [" "] * field_width
            for c_idx in range(field_width):
                if c_idx % 6 == 0:
                    row_chars[c_idx] = f"{C.GRAY}⋮{C.RESET}"
                elif r_idx in (2, 4) and c_idx % 2 == 0:
                    row_chars[c_idx] = f"{C.TURF_LIGHT}·{C.RESET}"
                else:
                    row_chars[c_idx] = f"{C.TURF_GREEN}░{C.RESET}"

            row_chars[los_col] = f"{C.BOLD}{C.BLUE}┃{C.RESET}"
            if fd_col != los_col:
                row_chars[fd_col] = f"{C.BOLD}{C.YELLOW}┇{C.RESET}"

            qb_col = max(0, los_col - 2)
            if r_idx == 3:
                row_chars[qb_col] = f"{C.BOLD}{C.CYAN}Q{C.RESET}"

            if r_idx == target_row:
                if play_type == "pass":
                    step = 1 if catch_col >= qb_col else -1
                    for c in range(qb_col + step, catch_col, step):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.CYAN}~{C.RESET}"
                    row_chars[catch_col] = f"{C.BOLD}{C.MAGENTA}◎{C.RESET}"
                    for c in range(min(catch_col, end_col) + 1, max(catch_col, end_col)):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.GREEN}═{C.RESET}"
                else:
                    for c in range(min(los_col, end_col) + 1, max(los_col, end_col)):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.GREEN}═{C.RESET}"
                row_chars[end_col] = f"{C.BOLD}{C.GOLD}★{C.RESET}"

            if is_screen and abs(r_idx - target_row) == 1:
                blk_col = min(field_width - 1, max(0, catch_col + 1))
                row_chars[blk_col] = f"{C.BOLD}{C.ORANGE}▓{C.RESET}"

            left_box = f"{C.BOLD}{C.WHITE}|{C.BG_ENDZONE_AFC}{C.WHITE}{ez_left[r_idx]}{C.RESET}{C.BOLD}{C.WHITE}|{C.RESET}"
            right_box = f"{C.BOLD}{C.WHITE}|{C.BG_ENDZONE_NFC}{C.WHITE}{ez_right[r_idx]}{C.RESET}{C.BOLD}{C.WHITE}|{C.RESET}"
            rows_out.append(f"{left_box}{''.join(row_chars)}{right_box}")

        rows_out.append(border)
        rows_out.append(cls._play_legend_and_summary(play, qb_name, target_name, los_yard, down, ydstogo, air_yards, yac, yards_gained, concept, "SIDELINE (Left ▶ Right)"))
        return "\n".join(rows_out)

    @staticmethod
    def _play_legend_and_summary(
        play: Dict[str, Any],
        qb_name: str,
        target_name: str,
        los_yard: int,
        down: int,
        ydstogo: int,
        air_yards: float,
        yac: float,
        yards_gained: float,
        concept: str,
        cam_label: str,
    ) -> str:
        tgt_str = f" → {target_name}" if target_name and target_name != qb_name else ""
        legend = (
            f"  {C.BOLD}{C.CYAN}QB{C.RESET}={qb_name}{tgt_str}  "
            f"{C.BOLD}{C.BLUE}━/┃{C.RESET}=LOS (Own {los_yard})  "
            f"{C.BOLD}{C.YELLOW}┄/┇{C.RESET}=1st Down ({down}&{ydstogo})  "
            f"{C.BOLD}{C.CYAN}⋮/╱/╲{C.RESET}=Air ({air_yards:+.0f}y)  "
            f"{C.BOLD}{C.MAGENTA}◎{C.RESET}=Catch  "
            f"{C.BOLD}{C.ORANGE}▓{C.RESET}=Blockers  "
            f"{C.BOLD}{C.GREEN}║/═{C.RESET}=YAC (+{yac:.0f}y)  "
            f"{C.BOLD}{C.GOLD}★{C.RESET}=End ({yards_gained:+.0f}y)"
        )
        summary_box = (
            f"  {C.BOLD}Camera:{C.RESET} {C.WHITE}{cam_label}{C.RESET}  │  "
            f"{C.BOLD}Concept:{C.RESET} {C.CYAN}{concept}{C.RESET}  │  "
            f"{C.BOLD}Gain:{C.RESET} {C.GREEN}{yards_gained:+.1f} yds{C.RESET} (Air: {air_yards:+.1f}, YAC: {yac:.1f})  │  "
            f"{C.BOLD}EPA:{C.RESET} {C.GOLD}{float(play.get('epa', 0.0)):+.2f}{C.RESET}  │  "
            f"{C.BOLD}WPA:{C.RESET} {C.MAGENTA}{float(play.get('wpa', 0.0)) * 100:+.1f}%{C.RESET}\n"
            f"  {C.DIM}Play #{play.get('play_id', 1)} ({play.get('game_id', '')}): {play.get('desc', '')}{C.RESET}"
        )
        return legend + "\n" + summary_box


# ---------------------------------------------------------------------------
# Hybrid Local Small Language Model (SLM) + Deterministic NL-to-Stat Engine
# ---------------------------------------------------------------------------

class NaturalLanguageStatAssistant:
    """
    Translates natural-language user questions or custom-stat requests into structured
    stat queries, custom stat definitions, or specific play visualizations.

    Supports:
    1. Local Small Language Model (SLM) via Ollama (`http://localhost:11434`) or OpenAI-compatible local server
       (e.g., `qwen2.5:1.5b`, `qwen2.5-coder:1.5b`, `llama3.2:1b`, `llama3.2:3b`, `phi3:mini`).
    2. Zero-dependency deterministic parser fallback so it works 100% offline with zero setup.
    """

    PREFERRED_SLM_MODELS = [
        "qwen2.5-coder:1.5b",
        "qwen2.5:1.5b",
        "llama3.2:1b",
        "llama3.2:3b",
        "qwen2.5:3b",
        "phi3:mini",
    ]

    @classmethod
    def detect_ollama_model(cls, requested_model: Optional[str] = None) -> Optional[str]:
        if requested_model and requested_model.lower() not in ("auto", "none", "off"):
            return requested_model
        env_model = os.environ.get("NFL_STAT_SLM_MODEL")
        if env_model:
            return env_model
        base_url = os.environ.get("NFL_STAT_OLLAMA_URL", "http://127.0.0.1:11434")
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = [m.get("name", "") for m in data.get("models", [])]
                if not installed:
                    return None
                for pref in cls.PREFERRED_SLM_MODELS:
                    for inst in installed:
                        if inst == pref or inst.startswith(pref.split(":")[0]):
                            return inst
                return installed[0]
        except Exception:
            return None

    @classmethod
    def query_local_slm(cls, query: str, engine: StatEngine, model_name: str) -> Optional[Dict[str, Any]]:
        """Call local Ollama SLM to parse natural language into structured JSON intent."""
        base_url = os.environ.get("NFL_STAT_OLLAMA_URL", "http://127.0.0.1:11434")
        available_stats = list(engine.stats.keys())
        system_prompt = (
            "You are the NFL-Stat-CLI Local Small Language Model parser. "
            "Respond ONLY with a valid JSON object matching one of these intents:\n"
            "1. 'stat_query': when the user asks for a season average, leaderboard, ranking, or aggregate stat across the year. "
            "Set 'show_field': false.\n"
            "2. 'specific_play': ONLY when the user asks to see, diagram, or find a specific single play (e.g. longest play, touchdown play, specific QB/team play, or behind offense/defense view). "
            "Set 'show_field': true and 'camera': 'behind-offense' | 'behind-defense' | 'sideline'.\n"
            "3. 'create_stat': when the user wants to define/create/make a new custom stat.\n"
            f"Available stats: {', '.join(available_stats)}.\n"
            "JSON keys: {\"intent\": \"stat_query|specific_play|create_stat\", \"stat_name\": \"...\", "
            "\"group_by\": \"qb|team|play_concept|conference|receiver|rusher|game\", \"filter_expr\": \"...\", "
            "\"season\": 2025, \"conf\": null, \"team\": null, \"qb\": null, \"concept\": null, "
            "\"sort_by\": \"yards_gained|epa|wpa|yac\", \"camera\": \"behind-offense|behind-defense|sideline\", "
            "\"show_field\": false, \"formula\": \"\", \"title\": \"\", \"scope\": \"season|game|play\", \"agg\": \"formula|sum|avg\", \"explanation\": \"...\"}"
        )
        payload = json.dumps({
            "model": model_name,
            "prompt": query,
            "system": system_prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 256},
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(body.get("response", "{}"))
                if isinstance(parsed, dict) and "intent" in parsed:
                    parsed["slm_model_used"] = model_name
                    return parsed
        except Exception:
            return None
        return None

    @classmethod
    def interpret_query(
        cls,
        query: str,
        engine: Optional[StatEngine] = None,
        slm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Interpret a user's natural language question using a local SLM (if available)
        or the deterministic rule/AST parser.
        Never forces an ASCII field when the user is asking for an average or leaderboard across the year!
        """
        if engine is not None and (slm_model or "off").lower() not in ("none", "off", "disable"):
            detected = cls.detect_ollama_model(slm_model)
            if detected:
                slm_res = cls.query_local_slm(query, engine, detected)
                if slm_res:
                    return slm_res

        q = query.strip()
        ql = q.lower()

        season_match = re.search(r"\b(20\d{2})\b", ql)
        season = int(season_match.group(1)) if season_match else 2025
        conf = "AFC" if re.search(r"\bafc\b", ql) else ("NFC" if re.search(r"\bnfc\b", ql) else None)

        # Detect camera perspective
        camera = "behind-offense"
        if any(p in ql for p in ("behind the defense", "behind defense", "defense view", "defensive view", "from defense")):
            camera = "behind-defense"
        elif any(p in ql for p in ("behind the offense", "behind offense", "offense view", "offensive view", "behind qb")):
            camera = "behind-offense"
        elif any(p in ql for p in ("sideline", "broadcast view", "side view")):
            camera = "sideline"

        # Detect team or QB filters
        team_filter: Optional[str] = None
        for t_abbr in AFC_TEAMS | NFC_TEAMS:
            if re.search(rf"\b{t_abbr.lower()}\b", ql):
                team_filter = t_abbr
                break
        team_Aliases = {
            "chiefs": "KC", "bills": "BUF", "ravens": "BAL", "texans": "HOU",
            "browns": "CLE", "steelers": "PIT", "lions": "DET", "49ers": "SF", "niners": "SF",
        }
        for alias, abbr in team_Aliases.items():
            if alias in ql:
                team_filter = abbr
                break

        qb_filter: Optional[str] = None
        for qb_key in ("mahomes", "allen", "jackson", "stroud", "watson", "fields", "goff", "purdy", "worthy", "kelce", "gibbs", "cook"):
            if qb_key in ql:
                qb_filter = qb_key
                break

        # 1. Check if user is asking to CREATE a custom stat
        if any(ql.startswith(prefix) for prefix in ("create stat", "create a stat", "make a stat", "make stat", "define stat", "build stat")):
            name_m = re.search(r"(?:called|named)\s+([a-zA-Z0-9_]+)", ql)
            formula_m = re.search(r"formula\s+(.+?)(?:\s+where|\s+by|$)", q, flags=re.IGNORECASE)
            where_m = re.search(r"where\s+(.+?)(?:\s+by|$)", q, flags=re.IGNORECASE)
            by_m = re.search(r"\bby\s+(qb|team|play_concept|conference|receiver|rusher|game)\b", ql)
            s_name = name_m.group(1) if name_m else "custom_user_stat"
            s_formula = formula_m.group(1).strip() if formula_m else "yards_per_play + (epa_per_play * 10)"
            s_filter = where_m.group(1).strip() if where_m else ""
            s_group = by_m.group(1) if by_m else "qb"
            return {
                "intent": "create_stat",
                "stat_name": s_name,
                "title": s_name.replace("_", " ").title(),
                "group_by": s_group,
                "formula": s_formula,
                "filter_expr": s_filter,
                "scope": "game" if "game" in ql and "win" in ql else "season",
                "agg": "sum" if "ifelse" in s_formula else "formula",
                "season": season,
                "conf": conf,
                "show_field": False,
                "explanation": f"Created custom stat `{s_name}` grouped by `{s_group}` using formula `{s_formula}`.",
            }

        # 2. Check if user is asking about a SPECIFIC PLAY vs an AVERAGE/LEADERBOARD across the year
        is_aggregate_request = any(w in ql for w in (
            "average", "avg", "across the year", "across the season", "leaderboard",
            "rankings", "rank teams", "rank qbs", "by team", "by qb", "by concept",
            "effectiveness", "meaningful win", "meaningful loss", "impact score",
        ))
        is_specific_play_request = (
            any(p in ql for p in (
                "specific play", "single play", "show play", "show a play", "show the play",
                "diagram", "on the field", "ascii field", "behind the offense", "behind offense",
                "behind the defense", "behind defense", "longest play", "best play", "top play",
                "touchdown play", "interception play", "sack play",
            ))
            or ("play" in ql and not is_aggregate_request and any(w in ql for w in ("show", "diagram", "longest", "best", "most efficient", "touchdown", "mahomes", "allen", "jackson", "goff", "stroud", "purdy")))
        )

        if is_specific_play_request and not ("average" in ql or "across the year" in ql):
            concept_filter = "screen" if "screen" in ql else ("play_action_deep" if ("deep" in ql or "play action" in ql) else None)
            extra_filter = "touchdown == 1" if "touchdown" in ql else ("interception == 1" if "interception" in ql else ("sack == 1" if "sack" in ql else ""))
            sort_by = "epa" if ("epa" in ql or "efficient" in ql) else ("wpa" if "wpa" in ql else ("yac" if "yac" in ql else "yards_gained"))
            return {
                "intent": "specific_play",
                "season": season,
                "conf": conf,
                "team": team_filter,
                "qb": qb_filter,
                "concept": concept_filter,
                "filter_expr": extra_filter,
                "sort_by": sort_by,
                "camera": camera,
                "show_field": True,
                "explanation": f"Selected specific matching play for {season} (sorted by {sort_by}, camera={camera}).",
            }

        # 3. General Stat / Average / Leaderboard Query across the season (show_field = False!)
        # Match any registered custom or traditional stat first
        matched_stat: Optional[str] = None
        if engine:
            for sname, sdef in engine.stats.items():
                if sname in ql or sdef.title.lower() in ql:
                    matched_stat = sname
                    break

        if not matched_stat:
            if any(w in ql for w in ("meaningful win", "qb win", "pitcher", "meaningful loss", "impact score")):
                matched_stat = "qb_impact_score"
                return {
                    "intent": "qb_wins_report",
                    "stat_name": "qb_impact_score",
                    "season": season,
                    "conf": conf,
                    "team": team_filter,
                    "show_field": False,
                    "explanation": f"Evaluated per-game MLB-style QB Meaningful Wins (MW), Losses (ML), No-Decisions (ND), and 0-100 Impact Scores for {season}.",
                }
            elif "screen" in ql:
                matched_stat = "screen_yards_after_catch" if ("yac" in ql or "after catch" in ql) else "screen_effectiveness_index"
            elif "passer rating" in ql:
                matched_stat = "passer_rating"
            elif "any/a" in ql or "adjusted net yards" in ql:
                matched_stat = "any_a"
            elif "explosive" in ql:
                matched_stat = "explosive_play_rate"
            elif "success rate" in ql:
                matched_stat = "success_rate_pct"
            elif "yac" in ql or "after catch" in ql:
                matched_stat = "yac_over_expected" if "expected" in ql else "screen_yards_after_catch"
            elif "epa" in ql:
                matched_stat = "epa_per_play"
            else:
                matched_stat = "yards_per_play"

        # Determine group_by override from query
        group_override: Optional[str] = None
        if "by qb" in ql or "quarterback" in ql:
            group_override = "qb"
        elif "by team" in ql or "teams" in ql:
            group_override = "team"
        elif "by receiver" in ql or "wide receiver" in ql:
            group_override = "receiver"
        elif "by concept" in ql or "play concept" in ql or "offensive play" in ql:
            group_override = "play_concept"
        elif "by conference" in ql:
            group_override = "conference"

        filter_parts: List[str] = []
        if "3rd down" in ql or "third down" in ql:
            filter_parts.append("down == 3")
        if "4th quarter" in ql or "fourth quarter" in ql:
            filter_parts.append("qtr == 4")
        if "red zone" in ql:
            filter_parts.append("red_zone == 1")
        if "play action" in ql:
            filter_parts.append("play_action == 1")
        if "screen" in ql and matched_stat not in ("screen_yards_after_catch", "screen_effectiveness_index"):
            filter_parts.append("is_screen == 1")

        return {
            "intent": "stat_query",
            "stat_name": matched_stat,
            "group_by": group_override,
            "filter_expr": " and ".join(filter_parts),
            "season": season,
            "conf": conf,
            "team": team_filter,
            "show_field": False,
            "camera": camera,
            "explanation": f"Evaluated `{matched_stat}` across {season} (season aggregate/leaderboard — no ASCII field needed).",
        }


# ---------------------------------------------------------------------------
# Context-Aware View Renderers & Interactive Workflows
# (Season averages/leaderboards show tables only; specific play queries show the ASCII field)
# ---------------------------------------------------------------------------

def _should_show_table(view_mode: str, is_play_query: bool = False) -> bool:
    vm = view_mode.lower()
    if vm == "auto":
        return not is_play_query
    return vm in ("table", "all")


def _should_show_field(view_mode: str, is_play_query: bool = False) -> bool:
    vm = view_mode.lower()
    if vm == "auto":
        return is_play_query
    return vm in ("field", "play", "all")


def _should_show_text(view_mode: str, is_play_query: bool = False) -> bool:
    vm = view_mode.lower()
    if vm == "auto":
        return not is_play_query
    return vm in ("text", "table", "all")


def render_general_stat_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    stat_name: str,
    season: int,
    conf: Optional[str] = None,
    team: Optional[str] = None,
    group_override: Optional[str] = None,
    extra_filter: str = "",
    view_mode: str = "auto",
    camera: str = "behind-offense",
) -> str:
    if stat_name not in engine.stats:
        raise KeyError(f"Unknown stat '{stat_name}'. Run `list-stats` to see available stats.")
    sdef = engine.stats[stat_name]
    group_col = group_override or sdef.group_by
    board = engine.evaluate_stat_leaderboard(
        stat_name, plays, conf=conf, team=team, group_override=group_col, extra_filter=extra_filter
    )

    out: List[str] = []
    if _should_show_table(view_mode, is_play_query=False):
        unit_sfx = f" {sdef.unit}" if sdef.unit else ""
        headers = ["Rank", group_col.upper(), "Team", "Conf", f"{sdef.title}", "Plays", "Avg Yds/Play", "EPA/Play", "Success %"]
        rows = []
        for idx, r in enumerate(board, 1):
            rows.append([
                f"#{idx}",
                f"{C.BOLD}{r['entity']}{C.RESET}",
                r["team"],
                r["conf"],
                f"{C.BOLD}{C.GREEN}{r['value']:.2f}{unit_sfx}{C.RESET}",
                r["plays"],
                f"{r['yards_per_play']:.2f}",
                f"{r['epa_per_play']:+.2f}",
                f"{r['success_rate_pct']:.1f}%",
            ])
        filter_desc = f" • Filter: {extra_filter or sdef.filter_expr}" if (extra_filter or sdef.filter_expr) else ""
        conf_desc = f" • {conf}" if conf else ""
        out.append(AsciiArtRenderer.render_table(
            f"{sdef.title} ({season}{conf_desc}{filter_desc})",
            headers,
            rows,
            alignments=["right", "left", "center", "center", "right", "right", "right", "right", "right"],
        ))
        if board:
            overall_avg = sum(r["value"] for r in board) / len(board)
            out.append(
                f"  {C.BOLD}Season Average Across Qualified {group_col.upper()}s:{C.RESET} "
                f"{C.GOLD}{overall_avg:.2f}{unit_sfx}{C.RESET}  │  "
                f"{C.BOLD}Leader:{C.RESET} {C.CYAN}{board[0]['entity']}{C.RESET} ({board[0]['value']:.2f}{unit_sfx})"
            )

    if _should_show_text(view_mode, is_play_query=False):
        deps_str = ", ".join(sdef.dependencies) if sdef.dependencies else "base play-by-play metrics"
        out.append(
            f"\n{C.BOLD}{C.CYAN}📘 Stat Definition & Calculation:{C.RESET}\n"
            f"  • {C.BOLD}{sdef.title} (`{sdef.name}`){C.RESET} [Scope: {sdef.scope.upper()}, Agg: {sdef.agg.upper()}]: {sdef.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef.formula}` (Dependencies: {deps_str})\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef.calculation_explained}"
        )

    if _should_show_field(view_mode, is_play_query=False) and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"SAMPLE PLAY FOR {board[0]['entity']} ({sdef.title})",
            camera=camera,
        ))
    return "\n".join(out)


def render_specific_play_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: Optional[int] = None,
    conf: Optional[str] = None,
    team: Optional[str] = None,
    qb: Optional[str] = None,
    concept: Optional[str] = None,
    play_type: Optional[str] = None,
    filter_expr: str = "",
    sort_by: str = "yards_gained",
    play_id: Optional[int] = None,
    camera: str = "behind-offense",
) -> str:
    matched = engine.query_plays(
        plays,
        season=season,
        conf=conf,
        team=team,
        qb=qb,
        concept=concept,
        play_type=play_type,
        filter_expr=filter_expr,
        sort_by=sort_by,
        play_id=play_id,
    )
    if not matched:
        return f"\n{C.RED}No matching play found for the given criteria.{C.RESET}"
    chosen = matched[0]
    title = f"SPECIFIC PLAY DIAGRAM — {chosen.get('qb_name', 'QB')} ({chosen.get('posteam', '')} vs {chosen.get('defteam', '')})"
    return AsciiArtRenderer.render_field_and_play(chosen, title=title, camera=camera)


def render_qb_meaningful_wins_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: Optional[str],
    view_mode: str = "auto",
    camera: str = "behind-offense",
) -> str:
    board = engine.evaluate_stat_leaderboard("qb_impact_score", plays, conf=conf, group_override="qb")
    sdef_win = engine.stats["qb_meaningful_win"]
    sdef_loss = engine.stats["qb_meaningful_loss"]
    sdef_imp = engine.stats["qb_impact_score"]

    out: List[str] = []
    if _should_show_table(view_mode, is_play_query=False):
        headers = ["Rank", "Quarterback", "Team", "Conf", "Team W-L", "QB MW-ML-ND", "Impact (0-100)", "EPA/Play", "Yds/Play"]
        rows = []
        for idx, r in enumerate(board, 1):
            imp = r["qb_impact_score"]
            imp_color = C.GREEN if imp >= 55.0 else (C.RED if imp <= 42.0 else C.YELLOW)
            bar_fill = int(round(imp / 10.0))
            bar = f"{imp_color}{'█' * bar_fill}{C.GRAY}{'░' * (10 - bar_fill)}{C.RESET} {imp:5.1f}"
            rows.append([
                f"#{idx}",
                f"{C.BOLD}{r['entity']}{C.RESET}",
                r["team"],
                r["conf"],
                f"{r['games_won']}-{r['games_lost']}",
                f"{C.GREEN}{r['qb_meaningful_win']}W{C.RESET}-{C.RED}{r['qb_meaningful_loss']}L{C.RESET}-{C.GRAY}{r['no_decisions']}ND{C.RESET}",
                bar,
                f"{r['epa_per_play']:+.2f}",
                f"{r['yards_per_play']:.1f}",
            ])
        out.append(AsciiArtRenderer.render_table(
            f"MLB-Style QB Meaningful Wins (MW), Inverse Losses (ML) & 0-100 Impact Score ({season})",
            headers,
            rows,
            alignments=["right", "left", "center", "center", "center", "center", "left", "right", "right"],
        ))

    if _should_show_text(view_mode, is_play_query=False):
        out.append(
            f"\n{C.BOLD}{C.CYAN}📘 Stat Definitions & How They Are Calculated:{C.RESET}\n"
            f"  • {C.BOLD}{sdef_imp.title} (`{sdef_imp.name}`){C.RESET}: {sdef_imp.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_imp.formula}`\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_imp.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_win.title} (`{sdef_win.name}`){C.RESET} [Scope: {sdef_win.scope.upper()}, Agg: {sdef_win.agg.upper()}]: {sdef_win.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_win.formula}` (Depends on: {', '.join(sdef_win.dependencies)})\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_win.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_loss.title} (`{sdef_loss.name}`){C.RESET} [Scope: {sdef_loss.scope.upper()}, Agg: {sdef_loss.agg.upper()}]: {sdef_loss.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_loss.formula}` (Depends on: {', '.join(sdef_loss.dependencies)})\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_loss.calculation_explained}"
        )

    if _should_show_field(view_mode, is_play_query=False) and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"SIGNATURE WIN-IMPACT PLAY: {board[0]['entity']} ({board[0]['team']})",
            camera=camera,
        ))
    return "\n".join(out)


def render_screen_pass_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: Optional[str],
    view_mode: str = "auto",
    camera: str = "behind-offense",
) -> str:
    screen_plays = [p for p in plays if int(p.get("is_screen", 0)) == 1 and (not conf or p.get("conf") == conf)]
    board = engine.evaluate_stat_leaderboard("screen_effectiveness_index", screen_plays, conf=conf, group_override="team")
    sdef_yac = engine.stats["screen_yards_after_catch"]
    sdef_idx = engine.stats["screen_effectiveness_index"]

    out: List[str] = []
    if _should_show_table(view_mode, is_play_query=False):
        headers = ["Rank", "Team", "Conf", "Screens", "Avg Yds Gained", "Screen YAC/Play", "EPA/Screen", "Screen Eff. Index"]
        rows = []
        for idx, r in enumerate(board, 1):
            rows.append([
                f"#{idx}",
                f"{C.BOLD}{r['entity']}{C.RESET}",
                r["conf"],
                r["plays"],
                f"{C.GREEN}{r['yards_per_play']:.1f} yds{C.RESET}",
                f"{C.CYAN}{r['yac_per_play']:.1f} YAC{C.RESET}",
                f"{r['epa_per_play']:+.2f}",
                f"{C.GOLD}{r['value']:.1f}{C.RESET}",
            ])
        out.append(AsciiArtRenderer.render_table(
            f"Screen Pass Effectiveness: Yards Gained & Yards After Catch ({season})",
            headers,
            rows,
            alignments=["right", "center", "center", "right", "right", "right", "right", "right"],
        ))

    if _should_show_text(view_mode, is_play_query=False):
        out.append(
            f"\n{C.BOLD}{C.CYAN}📘 Screen Pass Stat Explanations:{C.RESET}\n"
            f"  • {C.BOLD}{sdef_yac.title} (`{sdef_yac.name}`){C.RESET}: {sdef_yac.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_yac.formula}` (Filter: `{sdef_yac.filter_expr}`)\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_yac.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_idx.title} (`{sdef_idx.name}`){C.RESET}: {sdef_idx.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_idx.formula}`\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_idx.calculation_explained}"
        )

    if _should_show_field(view_mode, is_play_query=False) and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"TOP SCREEN PASS PLAY DIAGRAM ({board[0]['entity']} • +{board[0]['best_play']['yards_after_catch']:.0f} YAC)",
            camera=camera,
        ))
    return "\n".join(out)


def render_play_efficiency_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: str,
    view_mode: str = "auto",
    camera: str = "behind-offense",
) -> str:
    board = engine.evaluate_stat_leaderboard("yards_per_play", plays, conf=conf, group_override="play_concept")
    sdef = engine.stats["yards_per_play"]

    out: List[str] = []
    if _should_show_table(view_mode, is_play_query=False):
        headers = ["Rank", f"{conf} Play Concept", "Plays", "Avg Yards Gained", "Total Yards", "Avg YAC", "EPA/Play"]
        rows = []
        for idx, r in enumerate(board, 1):
            rows.append([
                f"#{idx}",
                f"{C.BOLD}{C.CYAN}{r['entity']}{C.RESET}",
                r["plays"],
                f"{C.BOLD}{C.GREEN}{r['yards_per_play']:.2f} yds{C.RESET}",
                f"{r['total_yards']:.0f} yds",
                f"{r['yac_per_play']:.1f} yds",
                f"{r['epa_per_play']:+.2f}",
            ])
        out.append(AsciiArtRenderer.render_table(
            f"Most Efficient Offensive Play Concepts in the {conf} by Yards Gained ({season})",
            headers,
            rows,
            alignments=["right", "left", "right", "right", "right", "right", "right"],
        ))

    if _should_show_text(view_mode, is_play_query=False) and board:
        top = board[0]
        out.append(
            f"\n{C.BOLD}{C.GREEN}🏆 Most Efficient {conf} Offensive Concept:{C.RESET} "
            f"`{top['entity']}` averaging {C.BOLD}{top['yards_per_play']:.2f} yards gained/play{C.RESET} "
            f"({top['epa_per_play']:+.2f} EPA/play).\n"
            f"  • {C.BOLD}{sdef.title} (`{sdef.name}`){C.RESET}: {sdef.calculation_explained}"
        )

    if _should_show_field(view_mode, is_play_query=False) and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"MOST EFFICIENT {conf} OFFENSIVE PLAY ON FIELD: {board[0]['entity'].upper()}",
            camera=camera,
        ))
    return "\n".join(out)


def render_stat_page(engine: StatEngine, all_plays: List[Dict[str, Any]]) -> str:
    page = engine.update_stat_page_tracking(all_plays)
    headers = ["Stat ID", "Title", "Type", "Scope", "2024 Lookback Leader", "2025 Current Leader", "YoY Avg Trend", "Formula / Basis"]
    rows = []
    for sname in page.get("pinned_stats", []):
        if sname not in engine.stats:
            continue
        sdef = engine.stats[sname]
        hist = page.get("lookback_history", {}).get(sname, {})
        h24 = hist.get("2024")
        h25 = hist.get("2025")
        str24 = f"{h24['leader']} ({h24['leader_value']})" if h24 else "—"
        str25 = f"{C.BOLD}{h25['leader']}{C.RESET} ({C.GREEN}{h25['leader_value']}{C.RESET})" if h25 else "—"
        if h24 and h25:
            delta = round(h25["league_avg"] - h24["league_avg"], 2)
            arrow = f"{C.GREEN}▲ +{delta}{C.RESET}" if delta >= 0 else f"{C.RED}▼ {delta}{C.RESET}"
        else:
            arrow = f"{C.GRAY}NEW{C.RESET}"
        cat_badge = f"{C.MAGENTA}CUSTOM{C.RESET}" if sdef.category == "custom" else f"{C.BLUE}TRAD{C.RESET}"
        rows.append([
            sname,
            sdef.title[:28],
            cat_badge,
            sdef.scope.upper(),
            str24,
            str25,
            arrow,
            sdef.formula[:32] + ("…" if len(sdef.formula) > 32 else ""),
        ])

    table_str = AsciiArtRenderer.render_table(
        f"📌 SAVED STAT PAGE — Lookback (2024) & Forward Tracking (2025) • Updated {page.get('last_updated')}",
        headers,
        rows,
        alignments=["left", "left", "center", "center", "left", "left", "right", "left"],
    )
    catalog_lines = [f"\n{C.BOLD}{C.CYAN}📚 Saved Stat Catalog (Descriptions & Calculation Formulas):{C.RESET}"]
    for sname in page.get("pinned_stats", []):
        if sname in engine.stats:
            s = engine.stats[sname]
            deps_str = ", ".join(s.dependencies) if s.dependencies else "base play-by-play columns"
            catalog_lines.append(
                f"  • {C.BOLD}{C.GOLD}{s.name}{C.RESET} ({s.title}) [{s.category.upper()} • Scope: {s.scope}/{s.agg}]\n"
                f"    {C.WHITE}Description:{C.RESET} {s.description}\n"
                f"    {C.WHITE}Calculation:{C.RESET} {s.calculation_explained}\n"
                f"    {C.DIM}Formula: `{s.formula}`  |  Filter: `{s.filter_expr or 'None'}`  |  Built From: {deps_str}{C.RESET}"
            )
    return table_str + "\n" + "\n".join(catalog_lines)


def handle_nl_query_result(
    parsed: Dict[str, Any],
    engine: StatEngine,
    all_plays: List[Dict[str, Any]],
    view_override: str = "auto",
    camera_override: Optional[str] = None,
) -> str:
    season = int(parsed.get("season") or 2025)
    s_plays = [p for p in all_plays if int(p.get("season", 2025)) == season] or all_plays
    conf = parsed.get("conf")
    team = parsed.get("team")
    camera = camera_override or parsed.get("camera") or "behind-offense"
    slm_tag = f" [SLM: {parsed['slm_model_used']}]" if parsed.get("slm_model_used") else " [Local Rule/AST Parser]"
    header = f"\n{C.BOLD}{C.CYAN}🤖 Query Interpretation{slm_tag}:{C.RESET} {parsed.get('explanation', '')}"

    intent = parsed.get("intent", "stat_query")
    if intent == "create_stat":
        sdef = engine.register_custom_stat(
            name=parsed.get("stat_name", "custom_stat"),
            title=parsed.get("title", "Custom Stat"),
            group_by=parsed.get("group_by") or "qb",
            formula=parsed.get("formula", "yards_per_play"),
            description=parsed.get("explanation", "User-created custom stat."),
            calculation_explained=f"Evaluated via formula `{parsed.get('formula')}` (scope={parsed.get('scope', 'season')}).",
            filter_expr=parsed.get("filter_expr", ""),
            scope=parsed.get("scope", "season"),
            agg=parsed.get("agg", "formula"),
        )
        return header + "\n" + render_general_stat_view(engine, s_plays, sdef.name, season, conf=conf, team=team, view_mode="table")

    if intent == "specific_play" or parsed.get("show_field") is True:
        return header + "\n" + render_specific_play_view(
            engine,
            s_plays,
            season=season,
            conf=conf,
            team=team,
            qb=parsed.get("qb"),
            concept=parsed.get("concept"),
            filter_expr=parsed.get("filter_expr", ""),
            sort_by=parsed.get("sort_by", "yards_gained"),
            camera=camera,
        )

    if intent == "qb_wins_report":
        return header + "\n" + render_qb_meaningful_wins_view(engine, s_plays, season, conf, view_mode=view_override, camera=camera)

    stat_name = parsed.get("stat_name") or "yards_per_play"
    if stat_name not in engine.stats:
        stat_name = "yards_per_play"
    return header + "\n" + render_general_stat_view(
        engine,
        s_plays,
        stat_name=stat_name,
        season=season,
        conf=conf,
        team=team,
        group_override=parsed.get("group_by"),
        extra_filter=parsed.get("filter_expr", ""),
        view_mode=view_override,
        camera=camera,
    )


def interactive_custom_stat_wizard(engine: StatEngine, plays: List[Dict[str, Any]]) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}=== 🧪 COMPOSABLE CUSTOM STAT BUILDER ==={C.RESET}")
    print(f"  {C.BOLD}[1]{C.RESET} Build a custom stat from scratch (Season, Game-by-Game, or Play-by-Play scope)")
    print(f"  {C.BOLD}[2]{C.RESET} Start from a customizable template (e.g. Game-Conditional QB Stat, Filtered Concept Stat, 3rd Down Clutch, Chained Stat)")
    mode = input("  Select mode [1/2] (default: 1): ").strip() or "1"

    preset: Dict[str, str] = {}
    if mode == "2":
        print(f"\n  {C.BOLD}{C.CYAN}Available Customizable Templates:{C.RESET}")
        for idx, tmpl in enumerate(CUSTOM_STAT_TEMPLATES, 1):
            print(f"    [{idx}] {C.BOLD}{tmpl['label']}{C.RESET}")
            print(f"        Formula: `{tmpl['formula']}` | Scope: {tmpl['scope']} ({tmpl['agg']}) | Filter: `{tmpl['filter_expr'] or 'None'}`")
        t_idx = input(f"  Pick a template [1-{len(CUSTOM_STAT_TEMPLATES)}] (default: 1): ").strip() or "1"
        try:
            preset = dict(CUSTOM_STAT_TEMPLATES[max(0, min(len(CUSTOM_STAT_TEMPLATES) - 1, int(t_idx) - 1))])
        except ValueError:
            preset = dict(CUSTOM_STAT_TEMPLATES[0])

    print(f"\n  {C.CYAN}Available Building Blocks (Traditional + Existing Custom Stats):{C.RESET}")
    building_blocks = sorted(list(engine.stats.keys()) + [
        "total_yards", "passing_yards", "rushing_yards", "yards_per_attempt", "yards_per_rush",
        "total_yac", "yac_per_play", "yac_per_completion", "total_xyac", "completion_pct",
        "total_epa", "pass_epa_per_play", "rush_epa_per_play", "wpa_per_game", "avg_cpoe",
        "success_rate", "first_down_rate", "turnover_rate", "sack_rate", "td_rate",
        "touchdowns", "interceptions", "sacks", "games_played", "games_won", "games_lost", "team_win", "win_rate",
    ])
    print("  " + ", ".join(building_blocks))

    default_name = preset.get("name", "custom_efficiency_score")
    name = input(f"  Stat ID (default: {default_name}): ").strip() or default_name
    default_title = preset.get("title", name.replace("_", " ").title())
    title = input(f"  Display Title (default: {default_title}): ").strip() or default_title
    default_group = preset.get("group_by", "qb")
    group_by = input(f"  Group by [qb/team/receiver/rusher/play_concept/conference/game] (default: {default_group}): ").strip() or default_group
    default_scope = preset.get("scope", "season")
    scope = input(f"  Evaluation Scope [season / game / play] (default: {default_scope}): ").strip().lower() or default_scope
    default_agg = preset.get("agg", "sum" if scope == "game" else "formula")
    agg = default_agg
    if scope in ("game", "play"):
        agg = input(f"  Aggregation across {scope}s [sum / avg / count_true / rate / max / min] (default: {default_agg}): ").strip().lower() or default_agg

    default_filter = preset.get("filter_expr", "")
    filter_expr = input(f"  Optional Play Filter (e.g. `is_screen == 1` or `down == 3` or `conf == 'AFC'`) [{default_filter or 'None'}]: ").strip() or default_filter
    default_formula = preset.get("formula", "(yards_per_play * 2.5) + (epa_per_play * 20.0)")
    formula = input(f"  Formula (default: {default_formula}): ").strip() or default_formula
    default_unit = preset.get("unit", "pts")
    unit = input(f"  Unit label (default: {default_unit}): ").strip() or default_unit
    default_desc = preset.get("description", f"Custom {scope}-scoped stat grouped by {group_by}.")
    desc = input(f"  Description (default: {default_desc}): ").strip() or default_desc
    default_calc = preset.get("calculation_explained", f"Evaluated at {scope} scope ({agg}) with filter `{filter_expr or 'all plays'}` via `{formula}`.")
    calc = input(f"  Calculation explanation (default: {default_calc}): ").strip() or default_calc

    try:
        sdef = engine.register_custom_stat(
            name=name,
            title=title,
            group_by=group_by,
            formula=formula,
            description=desc,
            calculation_explained=calc,
            unit=unit,
            filter_expr=filter_expr,
            scope=scope,
            agg=agg,
        )
        print(f"\n  {C.GREEN}✔ Registered & pinned custom stat `{sdef.name}` (Scope: {sdef.scope}, Agg: {sdef.agg})!{C.RESET}")
        p25 = [p for p in plays if int(p.get("season", 2025)) == 2025] or plays
        print(render_general_stat_view(engine, p25, sdef.name, 2025, view_mode="table"))
    except Exception as exc:
        print(f"\n  {C.RED}✖ Error creating stat: {exc}{C.RESET}")


def interactive_tui(engine: StatEngine, bridge: NFLDataBridge, slm_model: Optional[str] = None) -> None:
    """Interactive terminal interface loop for *nix and Windows."""
    print(AsciiArtRenderer.banner())
    plays = bridge.load_pbp([2024, 2025])
    detected_slm = NaturalLanguageStatAssistant.detect_ollama_model(slm_model)
    slm_status = f"Ollama SLM ({detected_slm})" if detected_slm else "Built-in Deterministic AST Parser (Offline)"
    print(f"  {C.GREEN}✔ Loaded {len(plays)} play-by-play records via [{bridge.last_source_used}]{C.RESET}")
    print(f"  {C.CYAN}✔ Natural Language Engine: [{slm_status}]{C.RESET}")

    menu = f"""
{C.BOLD}{C.CYAN}┌──────────────────────────────────────────────────────────────────────────────┐
│                         NFL-STAT-CLI INTERACTIVE MENU                        │
├──────────────────────────────────────────────────────────────────────────────┤{C.RESET}
  {C.BOLD}[1]{C.RESET} 📊 {C.GOLD}Evaluate Any Stat Leaderboard / Yearly Average (Table Only — No Field){C.RESET}
  {C.BOLD}[2]{C.RESET} 🧪 {C.MAGENTA}Create or Customize a Stat (Season, Game-by-Game, or Play-by-Play Scope){C.RESET}
  {C.BOLD}[3]{C.RESET} 🏈 {C.GREEN}Diagram a Specific Play on ASCII Field (Behind Offense / Behind Defense / Sideline){C.RESET}
  {C.BOLD}[4]{C.RESET} 🔎 {C.CYAN}Ad-Hoc Season Query (Filter by Down/Concept/Conf & Group by QB/Team/Concept){C.RESET}
  {C.BOLD}[5]{C.RESET} 📌 {C.WHITE}View Saved Stat Page (Historical Lookback & Forward Season Tracking){C.RESET}
  {C.BOLD}[6]{C.RESET} 💾 {C.YELLOW}Export / Import Custom Stats JSON{C.RESET}
  {C.BOLD}[7]{C.RESET} 💬 {C.CYAN}Ask a Natural-Language Question (Smart Output: Table for Averages, Field for Plays){C.RESET}
  {C.BOLD}[q]{C.RESET} ❌ Quit
{C.BOLD}{C.CYAN}└──────────────────────────────────────────────────────────────────────────────┘{C.RESET}"""

    while True:
        print(menu)
        try:
            choice = input(f"{C.BOLD}{C.GOLD}nfl-stat-cli ❯ {C.RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting nfl-stat-cli.")
            break

        if choice in ("q", "quit", "exit"):
            break
        elif choice == "1":
            stat_names = list(engine.stats.keys())
            print(f"\n  {C.BOLD}{C.CYAN}Available Traditional & Custom Stats:{C.RESET}")
            for i, sname in enumerate(stat_names, 1):
                s = engine.stats[sname]
                print(f"    [{i:2d}] {C.BOLD}{s.name:<28}{C.RESET} — {s.title} [{s.category.upper()} • by {s.group_by}]")
            sel = input("  Pick stat number or name (default: 1): ").strip() or "1"
            chosen_stat = stat_names[0]
            if sel.isdigit() and 1 <= int(sel) <= len(stat_names):
                chosen_stat = stat_names[int(sel) - 1]
            elif sel in engine.stats:
                chosen_stat = sel
            season_str = input("  Season [2024/2025] (default: 2025): ").strip() or "2025"
            season_val = int(season_str) if season_str.isdigit() else 2025
            conf_val = input("  Conference filter [AFC/NFC/all] (default: all): ").strip().upper()
            conf_arg = conf_val if conf_val in ("AFC", "NFC") else None
            group_val = input(f"  Group by override [qb/team/play_concept/conference/receiver/game] (Enter for default `{engine.stats[chosen_stat].group_by}`): ").strip() or None
            s_plays = [p for p in plays if int(p.get("season", 2025)) == season_val] or plays
            if chosen_stat in ("qb_meaningful_win", "qb_meaningful_loss", "qb_impact_score") and not group_val:
                print(render_qb_meaningful_wins_view(engine, s_plays, season_val, conf_arg, view_mode="table"))
            else:
                print(render_general_stat_view(engine, s_plays, chosen_stat, season_val, conf=conf_arg, group_override=group_val, view_mode="table"))
        elif choice == "2":
            interactive_custom_stat_wizard(engine, plays)
        elif choice == "3":
            print(f"\n{C.BOLD}{C.GREEN}=== 🏈 SPECIFIC PLAY EXPLORER & MULTI-ANGLE DIAGRAMMER ==={C.RESET}")
            qb_q = input("  Filter by QB/Player name (e.g. Mahomes, Allen, Goff, or Enter for any): ").strip() or None
            team_q = input("  Filter by Team (e.g. KC, BUF, DET, BAL, or Enter for any): ").strip() or None
            concept_q = input("  Filter by Concept (e.g. screen, play_action_deep, rush_outside, or Enter for any): ").strip() or None
            sort_q = input("  Pick top play by [yards_gained / epa / wpa / yac] (default: yards_gained): ").strip() or "yards_gained"
            cam_q = input("  Camera View [behind-offense / behind-defense / sideline / all] (default: behind-offense): ").strip() or "behind-offense"
            print(render_specific_play_view(
                engine, plays, season=2025, team=team_q, qb=qb_q, concept=concept_q, sort_by=sort_q, camera=cam_q
            ))
        elif choice == "4":
            print(f"\n{C.BOLD}{C.CYAN}=== 🔎 AD-HOC SEASON FILTER & GROUP QUERY ==={C.RESET}")
            stat_q = input("  Metric to evaluate (e.g. yards_per_play, epa_per_play, screen_yards_after_catch, passer_rating): ").strip() or "yards_per_play"
            if stat_q not in engine.stats:
                stat_q = "yards_per_play"
            grp_q = input("  Group by [qb / team / play_concept / conference / division / down / qtr / game] (default: play_concept): ").strip() or "play_concept"
            flt_q = input("  Filter expression (e.g. `conf == 'AFC'`, `is_screen == 1`, `down == 3`, or Enter for none): ").strip()
            p25 = [p for p in plays if int(p.get("season", 2025)) == 2025] or plays
            print(render_general_stat_view(engine, p25, stat_q, 2025, group_override=grp_q, extra_filter=flt_q, view_mode="table"))
        elif choice == "5":
            print(render_stat_page(engine, plays))
        elif choice == "6":
            sub = input("  [e]xport to JSON or [i]mport from JSON? (e/i): ").strip().lower()
            if sub == "i":
                path_str = input("  Path to JSON file to import: ").strip()
                if path_str and Path(path_str).exists():
                    names = engine.import_custom_stats_json(Path(path_str))
                    print(f"  {C.GREEN}✔ Imported {len(names)} custom stats: {', '.join(names)}{C.RESET}")
            else:
                path_str = input("  Export filename (default: custom_stats_export.json): ").strip() or "custom_stats_export.json"
                out_p = engine.export_custom_stats_json(Path(path_str))
                print(f"  {C.GREEN}✔ Exported custom stats to {out_p.resolve()}{C.RESET}")
        elif choice == "7":
            q = input("  Ask a stat or play question (e.g. 'average screen YAC by team in 2025' or 'show Mahomes touchdown play behind the defense'): ").strip()
            if q:
                parsed = NaturalLanguageStatAssistant.interpret_query(q, engine=engine, slm_model=slm_model)
                print(handle_nl_query_result(parsed, engine, plays))


def build_arg_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--engine", choices=["auto", "python", "r", "offline"], default=argparse.SUPPRESS, help="Data backend preference")
    common.add_argument("--season", type=int, default=argparse.SUPPRESS, help="Season year to analyze (default: 2025)")
    common.add_argument("--conf", choices=["AFC", "NFC"], default=argparse.SUPPRESS, help="Filter by conference (AFC or NFC)")
    common.add_argument("--team", default=argparse.SUPPRESS, help="Filter by team abbreviation (e.g. KC, BUF, DET)")
    common.add_argument(
        "--view",
        choices=["auto", "table", "field", "play", "text", "all"],
        default=argparse.SUPPRESS,
        help="Display mode ('auto' shows tables for season averages/leaderboards and ASCII fields only for specific play queries)",
    )
    common.add_argument(
        "--camera",
        choices=["behind-offense", "behind-defense", "sideline", "offense", "defense", "side", "all"],
        default=argparse.SUPPRESS,
        help="Camera perspective when rendering a play on the ASCII field (default: behind-offense)",
    )
    common.add_argument("--slm-model", default=argparse.SUPPRESS, help="Optional local Ollama SLM model name (e.g. qwen2.5:1.5b, llama3.2:1b) for NL queries")
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="Disable ANSI color codes")

    parser = argparse.ArgumentParser(
        prog="nfl-stat-cli",
        parents=[common],
        description="Cross-platform (*nix & Windows) colorized ASCII art NFL analytics, multi-angle play diagrammer, & composable custom stat CLI.",
    )
    parser.set_defaults(
        engine="auto",
        season=2025,
        conf=None,
        team=None,
        view="auto",
        camera="behind-offense",
        slm_model=None,
        no_color=False,
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", parents=[common], help="Launch interactive colorized terminal interface (default)")

    stat_p = sub.add_parser("stat", parents=[common], help="Evaluate any traditional or custom stat leaderboard / season average (table view by default)")
    stat_p.add_argument("stat_name", nargs="?", default="yards_per_play", help="Stat ID to evaluate (e.g. qb_impact_score, yards_per_play, screen_yards_after_catch)")
    stat_p.add_argument("--group-by", choices=list(GROUP_BY_COLUMN_MAP.keys()), default=None, help="Override grouping dimension")
    stat_p.add_argument("--filter", default="", help="Additional play filter expression (e.g. 'down == 3' or 'is_screen == 1')")

    play_p = sub.add_parser("play", parents=[common], help="Find and diagram a specific play on the ASCII gridiron (supports behind-offense, behind-defense, sideline)")
    play_p.add_argument("--play-id", type=int, default=None, help="Specific play_id to render")
    play_p.add_argument("--qb", default=None, help="Filter by QB or player name (e.g. Mahomes, Allen, Goff)")
    play_p.add_argument("--concept", default=None, help="Filter by play concept (e.g. screen, play_action_deep, rush_outside)")
    play_p.add_argument("--play-type", choices=["pass", "run"], default=None, help="Filter by pass or run")
    play_p.add_argument("--filter", default="", help="Custom play filter expression (e.g. 'touchdown == 1')")
    play_p.add_argument("--sort-by", choices=["yards_gained", "epa", "wpa", "yac", "air_yards"], default="yards_gained", help="Criterion to pick top matching play")
    play_p.add_argument("--perspective", choices=["behind-offense", "behind-defense", "sideline", "offense", "defense", "side", "all"], default=None, help="Camera angle override")

    sub.add_parser("list-stats", parents=[common], help="List all registered traditional and custom stats with their formulas and scopes")

    create_p = sub.add_parser("create-stat", parents=[common], help="Create & save a new custom stat built from traditional or custom stats")
    create_p.add_argument("--name", required=True, help="Unique stat identifier (e.g. clutch_qb_value)")
    create_p.add_argument("--title", required=True, help="Human-readable title")
    create_p.add_argument("--group-by", choices=list(GROUP_BY_COLUMN_MAP.keys()), default="qb")
    create_p.add_argument("--scope", choices=["season", "game", "play"], default="season", help="Evaluation scope: season aggregate, per-game, or per-play")
    create_p.add_argument("--agg", choices=["formula", "sum", "avg", "count_true", "rate", "max", "min"], default="formula", help="Aggregation method for game/play scope")
    create_p.add_argument("--formula", required=True, help="Math/conditional formula referencing traditional or custom stats")
    create_p.add_argument("--description", required=True, help="What the stat measures")
    create_p.add_argument("--explained", required=True, help="How the stat is calculated")
    create_p.add_argument("--filter", default="", help="Optional filter expression (e.g. 'is_screen == 1')")
    create_p.add_argument("--unit", default="", help="Unit label")

    sub.add_parser("stat-page", parents=[common], help="Display saved Stat Page with historical lookback and forward tracking")

    exp_p = sub.add_parser("export-stats", parents=[common], help="Export custom stats (with descriptions & formulas) to JSON")
    exp_p.add_argument("--output", required=True, help="Target JSON file path")
    exp_p.add_argument("--include-traditional", action="store_true", help="Include built-in traditional stats in JSON")

    imp_p = sub.add_parser("import-stats", parents=[common], help="Import custom stats from a JSON file")
    imp_p.add_argument("--input", required=True, help="Source JSON file path")

    ask_p = sub.add_parser("ask", parents=[common], help="Ask a natural-language NFL stat or play question (Local SLM + deterministic parser)")
    ask_p.add_argument("query", help="Natural language question")

    # Backwards-compatible aliases for example workflows
    sub.add_parser("qb-wins", parents=[common], help="Run MLB-style QB Meaningful Wins (MW), Losses (ML) & 0-100 Impact Score report")
    sub.add_parser("screen-pass", parents=[common], help="Analyze screen pass effectiveness in yards gained, YAC, xYAC, and EPA")
    eff_p = sub.add_parser("play-efficiency", parents=[common], help="Rank most efficient offensive play concepts by yards gained")
    eff_p.add_argument("--conference", choices=["AFC", "NFC"], default="AFC", help="Conference to rank (default: AFC)")
    sub.add_parser("demo-all", parents=[common], help="Run full showcase of custom stat engine, multi-angle play diagrams, and Stat Page")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.no_color:
        C.disable()

    bridge = NFLDataBridge(engine=args.engine)
    engine = StatEngine()
    all_plays = bridge.load_pbp([2024, args.season])
    season_plays = [p for p in all_plays if int(p.get("season", args.season)) == args.season] or all_plays

    cmd = args.command or "tui"
    if cmd == "tui":
        interactive_tui(engine, bridge, slm_model=args.slm_model)
        return 0

    print(AsciiArtRenderer.banner())
    print(f"  {C.DIM}Data Source: {bridge.last_source_used}  |  Platform: {platform.system()} ({os.name}){C.RESET}")

    if cmd == "stat":
        print(render_general_stat_view(
            engine,
            season_plays,
            stat_name=args.stat_name,
            season=args.season,
            conf=args.conf,
            team=args.team,
            group_override=args.group_by,
            extra_filter=args.filter,
            view_mode=args.view,
            camera=args.camera,
        ))
    elif cmd == "play":
        cam = getattr(args, "perspective", None) or args.camera
        print(render_specific_play_view(
            engine,
            season_plays,
            season=args.season,
            conf=args.conf,
            team=args.team,
            qb=args.qb,
            concept=args.concept,
            play_type=args.play_type,
            filter_expr=args.filter,
            sort_by=args.sort_by,
            play_id=args.play_id,
            camera=cam,
        ))
    elif cmd == "list-stats":
        rows = []
        for s in engine.stats.values():
            rows.append([s.name, s.title, s.category.upper(), s.group_by, f"{s.scope}/{s.agg}", s.filter_expr or "—", s.formula[:42]])
        print(AsciiArtRenderer.render_table(
            "Registered Traditional & Custom Stats Catalog",
            ["Stat ID", "Title", "Type", "Group By", "Scope/Agg", "Filter", "Formula"],
            rows,
            alignments=["left", "left", "center", "center", "center", "left", "left"],
        ))
    elif cmd == "qb-wins":
        print(render_qb_meaningful_wins_view(engine, season_plays, args.season, args.conf, args.view, camera=args.camera))
    elif cmd == "screen-pass":
        print(render_screen_pass_view(engine, season_plays, args.season, args.conf, args.view, camera=args.camera))
    elif cmd == "play-efficiency":
        conf = args.conf or getattr(args, "conference", "AFC")
        print(render_play_efficiency_view(engine, season_plays, args.season, conf, args.view, camera=args.camera))
    elif cmd == "create-stat":
        sdef = engine.register_custom_stat(
            name=args.name,
            title=args.title,
            group_by=args.group_by,
            formula=args.formula,
            description=args.description,
            calculation_explained=args.explained,
            unit=args.unit,
            filter_expr=args.filter,
            scope=args.scope,
            agg=args.agg,
        )
        print(f"\n{C.GREEN}✔ Created & saved custom stat `{sdef.name}` ({sdef.title}) [Scope: {sdef.scope}/{sdef.agg}]{C.RESET}")
        print(render_general_stat_view(engine, season_plays, sdef.name, args.season, conf=args.conf, team=args.team, view_mode=args.view, camera=args.camera))
    elif cmd == "stat-page":
        print(render_stat_page(engine, all_plays))
    elif cmd == "export-stats":
        out_path = engine.export_custom_stats_json(Path(args.output), include_traditional=args.include_traditional)
        print(f"\n{C.GREEN}✔ Exported custom stats JSON to: {out_path}{C.RESET}")
    elif cmd == "import-stats":
        names = engine.import_custom_stats_json(Path(args.input))
        print(f"\n{C.GREEN}✔ Imported {len(names)} custom stats: {', '.join(names)}{C.RESET}")
    elif cmd == "ask":
        parsed = NaturalLanguageStatAssistant.interpret_query(args.query, engine=engine, slm_model=args.slm_model)
        print(handle_nl_query_result(parsed, engine, all_plays, view_override=args.view, camera_override=args.camera if args.camera != "behind-offense" else None))
    elif cmd == "demo-all":
        print(render_qb_meaningful_wins_view(engine, season_plays, args.season, None, "table"))
        print(render_screen_pass_view(engine, season_plays, args.season, None, "table"))
        print(render_play_efficiency_view(engine, season_plays, args.season, "AFC", "table"))
        print(render_specific_play_view(engine, season_plays, season=args.season, qb="Mahomes", camera="behind-offense"))
        print(render_specific_play_view(engine, season_plays, season=args.season, qb="Goff", concept="screen", camera="behind-defense"))
        engine.register_custom_stat(
            name="qb_clutch_win_index",
            title="QB Clutch Win Value Index",
            group_by="qb",
            formula="(qb_impact_score * 0.65) + (qb_meaningful_win * 12.0) - (qb_meaningful_loss * 15.0) + (yards_per_play * 1.5)",
            description="Second-order custom stat built on top of custom `qb_impact_score`, `qb_meaningful_win`, `qb_meaningful_loss`, and traditional `yards_per_play`.",
            calculation_explained="Multiplies custom `qb_impact_score` by 0.65, adds +12 per Meaningful Win (`qb_meaningful_win`), subtracts 15 per Meaningful Loss (`qb_meaningful_loss`), and adds 1.5x `yards_per_play`.",
            unit="idx",
        )
        print(render_stat_page(engine, all_plays))
    return 0


if __name__ == "__main__":
    sys.exit(main())
