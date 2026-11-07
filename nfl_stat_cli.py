#!/usr/bin/env python3
"""
nfl-stat-cli: Cross-Platform (*nix & Windows) Colorized Terminal NFL Analytics & Custom Stat Builder
Powered by sportsdataverse-py (Python) & nflverse / nflreadr / nflfastR (R).

Features:
- Colorized ANSI/ASCII Art Terminal Interface (Football Field Visualizer, Play Diagrammer, Tables, Text)
- Dual Data Engine: sportsdataverse-py (Python) + nflverse/nflreadr (R via Rscript bridge) + Offline Dataset
- MLB-Style QB Meaningful Wins (MW), Meaningful Losses (ML), & 0-100 Game Impact Score
- Screen Pass Effectiveness (Yards Gained, YAC, xYAC, EPA) & Conference Play Efficiency Rankings
- Composable Custom Stat Engine: build new stats from traditional stats AND previously created custom stats
- Automatic Descriptions & Calculation Explanations for every traditional and custom stat
- Persistent Stat Page: lookback historical tracking + forward tracking across new weeks/seasons
- JSON Export & Import for sharing custom stats and stat pages
- Zero-Cost Local NL-to-Stat Assistant (no paid APIs required; optional local Ollama or account proxy hook)
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
import textwrap
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

SAMPLE_PBP_PLAYS: List[Dict[str, Any]] = [
    # AFC & NFC representative plays across 2024-2025 seasons for instant offline & unit-test execution
    # KC (AFC) - Patrick Mahomes
    {"season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -2.0, "yards_after_catch": 19.0, "xyac_mean_yardage": 8.4, "yards_gained": 17.0,
     "epa": 1.42, "wpa": 0.065, "cpoe": 8.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 8, "yardline_100": 68, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 4, "desc": "P.Mahomes pass short right to X.Worthy pushed ob at BAL 49 for 17 yards (screen)."},
    {"season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "play_type": "pass", "play_concept": "play_action_deep", "is_screen": 0, "play_action": 1,
     "air_yards": 28.0, "yards_after_catch": 7.0, "xyac_mean_yardage": 4.1, "yards_gained": 35.0,
     "epa": 2.65, "wpa": 0.112, "cpoe": 14.5, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 6, "yardline_100": 35, "series_success": 1, "touchdown": 1, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 4, "desc": "P.Mahomes pass deep middle to X.Worthy for 35 yards, TOUCHDOWN."},
    {"season": 2025, "week": 2, "game_id": "2025_02_CIN_KC", "posteam": "KC", "defteam": "CIN", "conf": "AFC",
     "qb_name": "P.Mahomes", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -1.0, "yards_after_catch": 14.0, "xyac_mean_yardage": 7.2, "yards_gained": 13.0,
     "epa": 0.95, "wpa": 0.048, "cpoe": 6.1, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 55, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 25, "qtr": 4, "desc": "P.Mahomes pass short left to R.Rice to CIN 42 for 13 yards (screen)."},

    # BUF (AFC) - Josh Allen
    {"season": 2025, "week": 1, "game_id": "2025_01_ARI_BUF", "posteam": "BUF", "defteam": "ARI", "conf": "AFC",
     "qb_name": "J.Allen", "play_type": "pass", "play_concept": "play_action_deep", "is_screen": 0, "play_action": 1,
     "air_yards": 22.0, "yards_after_catch": 12.0, "xyac_mean_yardage": 5.0, "yards_gained": 34.0,
     "epa": 2.40, "wpa": 0.095, "cpoe": 12.8, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 7, "yardline_100": 48, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 34, "away_score": 28, "qtr": 3, "desc": "J.Allen pass deep left to K.Shakir to ARI 14 for 34 yards."},
    {"season": 2025, "week": 1, "game_id": "2025_01_ARI_BUF", "posteam": "BUF", "defteam": "ARI", "conf": "AFC",
     "qb_name": "J.Allen", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -3.0, "yards_after_catch": 21.0, "xyac_mean_yardage": 9.1, "yards_gained": 18.0,
     "epa": 1.55, "wpa": 0.072, "cpoe": 9.0, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 10, "yardline_100": 40, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 34, "away_score": 28, "qtr": 4, "desc": "J.Allen pass short middle to J.Cook to ARI 22 for 18 yards (screen)."},
    {"season": 2025, "week": 2, "game_id": "2025_02_BUF_MIA", "posteam": "BUF", "defteam": "MIA", "conf": "AFC",
     "qb_name": "J.Allen", "play_type": "run", "play_concept": "rush_outside", "is_screen": 0, "play_action": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 15.0,
     "epa": 1.18, "wpa": 0.055, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 3, "ydstogo": 3, "yardline_100": 32, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 10, "away_score": 31, "qtr": 2, "desc": "J.Allen scrambles left end to MIA 17 for 15 yards."},

    # BAL (AFC) - Lamar Jackson
    {"season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "L.Jackson", "play_type": "pass", "play_concept": "pass_intermediate", "is_screen": 0, "play_action": 1,
     "air_yards": 14.0, "yards_after_catch": 8.0, "xyac_mean_yardage": 4.8, "yards_gained": 22.0,
     "epa": 1.62, "wpa": 0.068, "cpoe": 9.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 9, "yardline_100": 61, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 3, "desc": "L.Jackson pass short middle to I.Likely to KC 39 for 22 yards."},
    {"season": 2025, "week": 3, "game_id": "2025_03_BAL_DAL", "posteam": "BAL", "defteam": "DAL", "conf": "AFC",
     "qb_name": "L.Jackson", "play_type": "run", "play_concept": "rush_outside", "is_screen": 0, "play_action": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 26.0,
     "epa": 1.95, "wpa": 0.088, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 1, "ydstogo": 10, "yardline_100": 45, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 25, "away_score": 28, "qtr": 2, "desc": "L.Jackson left end to DAL 19 for 26 yards."},

    # HOU (AFC) - C.J. Stroud
    {"season": 2025, "week": 1, "game_id": "2025_01_HOU_IND", "posteam": "HOU", "defteam": "IND", "conf": "AFC",
     "qb_name": "C.Stroud", "play_type": "pass", "play_concept": "play_action_deep", "is_screen": 0, "play_action": 1,
     "air_yards": 25.0, "yards_after_catch": 6.0, "xyac_mean_yardage": 3.5, "yards_gained": 31.0,
     "epa": 2.15, "wpa": 0.089, "cpoe": 11.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 8, "yardline_100": 52, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 29, "qtr": 4, "desc": "C.Stroud pass deep right to N.Collins pushed ob at IND 21 for 31 yards."},

    # CLE (AFC) - Example of QB Meaningful Loss (team lost & negative EPA/WPA impact)
    {"season": 2025, "week": 1, "game_id": "2025_01_DAL_CLE", "posteam": "CLE", "defteam": "DAL", "conf": "AFC",
     "qb_name": "D.Watson", "play_type": "pass", "play_concept": "pass_short", "is_screen": 0, "play_action": 0,
     "air_yards": 6.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 3.2, "yards_gained": 0.0,
     "epa": -1.85, "wpa": -0.095, "cpoe": -14.2, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 7, "yardline_100": 48, "series_success": 0, "touchdown": 0, "interception": 1, "sack": 0,
     "team_win": 0, "home_score": 17, "away_score": 33, "qtr": 3, "desc": "D.Watson pass short right intended for A.Cooper INTERCEPTED."},
    {"season": 2025, "week": 1, "game_id": "2025_01_DAL_CLE", "posteam": "CLE", "defteam": "DAL", "conf": "AFC",
     "qb_name": "D.Watson", "play_type": "pass", "play_concept": "pass_short", "is_screen": 0, "play_action": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": -8.0,
     "epa": -1.45, "wpa": -0.062, "cpoe": -9.0, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 10, "yardline_100": 62, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 1,
     "team_win": 0, "home_score": 17, "away_score": 33, "qtr": 2, "desc": "D.Watson sacked at CLE 30 for -8 yards (M.Parsons)."},

    # PIT (AFC) - Example of Game Manager / Low QB Impact Win (No-Decision in MLB-style QB Win)
    {"season": 2025, "week": 1, "game_id": "2025_01_PIT_ATL", "posteam": "PIT", "defteam": "ATL", "conf": "AFC",
     "qb_name": "J.Fields", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -1.0, "yards_after_catch": 6.0, "xyac_mean_yardage": 5.5, "yards_gained": 5.0,
     "epa": 0.04, "wpa": 0.010, "cpoe": 1.2, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 70, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 10, "away_score": 18, "qtr": 2, "desc": "J.Fields pass short left to N.Harris to PIT 35 for 5 yards (screen)."},

    # DET (NFC) - Jared Goff & Screen Game
    {"season": 2025, "week": 1, "game_id": "2025_01_LA_DET", "posteam": "DET", "defteam": "LA", "conf": "NFC",
     "qb_name": "J.Goff", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -2.0, "yards_after_catch": 24.0, "xyac_mean_yardage": 9.8, "yards_gained": 22.0,
     "epa": 1.78, "wpa": 0.081, "cpoe": 9.5, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 9, "yardline_100": 58, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 20, "qtr": 4, "desc": "J.Goff pass short right to J.Gibbs to LA 36 for 22 yards (screen)."},
    {"season": 2025, "week": 2, "game_id": "2025_02_TB_DET", "posteam": "DET", "defteam": "TB", "conf": "NFC",
     "qb_name": "J.Goff", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -1.0, "yards_after_catch": 16.0, "xyac_mean_yardage": 8.0, "yards_gained": 15.0,
     "epa": 1.12, "wpa": 0.052, "cpoe": 7.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 46, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 16, "away_score": 20, "qtr": 3, "desc": "J.Goff pass short left to A.St. Brown to TB 31 for 15 yards (screen)."},

    # SF (NFC) - Brock Purdy
    {"season": 2025, "week": 1, "game_id": "2025_01_NYJ_SF", "posteam": "SF", "defteam": "NYJ", "conf": "NFC",
     "qb_name": "B.Purdy", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -2.0, "yards_after_catch": 18.0, "xyac_mean_yardage": 8.5, "yards_gained": 16.0,
     "epa": 1.30, "wpa": 0.060, "cpoe": 8.0, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 6, "yardline_100": 44, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 32, "away_score": 19, "qtr": 2, "desc": "B.Purdy pass short left to D.Samuel to NYJ 28 for 16 yards (screen)."},

    # 2024 Historical Lookback plays for Stat Page trend tracking
    {"season": 2024, "week": 1, "game_id": "2024_01_DET_KC", "posteam": "KC", "defteam": "DET", "conf": "AFC",
     "qb_name": "P.Mahomes", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -2.0, "yards_after_catch": 14.0, "xyac_mean_yardage": 7.5, "yards_gained": 12.0,
     "epa": 0.92, "wpa": 0.044, "cpoe": 5.8, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 8, "yardline_100": 60, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 20, "away_score": 21, "qtr": 3, "desc": "P.Mahomes pass short right to J.McKinnon for 12 yards (screen)."},
    {"season": 2024, "week": 2, "game_id": "2024_02_KC_JAX", "posteam": "KC", "defteam": "JAX", "conf": "AFC",
     "qb_name": "P.Mahomes", "play_type": "pass", "play_concept": "play_action_deep", "is_screen": 0, "play_action": 1,
     "air_yards": 24.0, "yards_after_catch": 5.0, "xyac_mean_yardage": 3.8, "yards_gained": 29.0,
     "epa": 2.10, "wpa": 0.088, "cpoe": 11.4, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 6, "yardline_100": 50, "series_success": 1, "touchdown": 1, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 9, "away_score": 27, "qtr": 4, "desc": "P.Mahomes pass deep right to T.Kelce for 29 yards, TOUCHDOWN."},
    {"season": 2024, "week": 2, "game_id": "2024_02_LV_BUF", "posteam": "BUF", "defteam": "LV", "conf": "AFC",
     "qb_name": "J.Allen", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -2.0, "yards_after_catch": 17.0, "xyac_mean_yardage": 8.2, "yards_gained": 15.0,
     "epa": 1.25, "wpa": 0.059, "cpoe": 7.9, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 52, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 38, "away_score": 10, "qtr": 2, "desc": "J.Allen pass short left to J.Cook for 15 yards (screen)."},
    {"season": 2024, "week": 3, "game_id": "2024_03_ATL_DET", "posteam": "DET", "defteam": "ATL", "conf": "NFC",
     "qb_name": "J.Goff", "play_type": "pass", "play_concept": "screen", "is_screen": 1, "play_action": 0,
     "air_yards": -1.0, "yards_after_catch": 19.0, "xyac_mean_yardage": 8.6, "yards_gained": 18.0,
     "epa": 1.40, "wpa": 0.064, "cpoe": 8.3, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 7, "yardline_100": 49, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 20, "away_score": 6, "qtr": 3, "desc": "J.Goff pass short right to J.Gibbs for 18 yards (screen)."},
]

AFC_TEAMS = {"BAL", "BUF", "CIN", "CLE", "DEN", "HOU", "IND", "JAX", "KC", "LV", "LAC", "MIA", "NE", "NYJ", "PIT", "TEN"}
NFC_TEAMS = {"ARI", "ATL", "CAR", "CHI", "DAL", "DET", "GB", "LA", "LAR", "MIN", "NO", "NYG", "PHI", "SEA", "SF", "TB", "WAS"}


# ---------------------------------------------------------------------------
# Dual Data Loader: sportsdataverse-py (Python) & nflverse/nflreadr (R)
# ---------------------------------------------------------------------------

class NFLDataBridge:
    """
    Loads NFL Play-by-Play and Roster/Team data from:
    1. sportsdataverse-py (`sportsdataverse.nfl.load_nfl_pbp`) or `nflreadpy`
    2. nflverse R (`nflreadr::load_pbp`, `nflfastR::calculate_stats`) via Rscript bridge
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
                self.last_source_used = "sportsdataverse-py (Python)"
                return rows

        if self.engine in ("auto", "r", "nflverse"):
            rows = self._try_nflverse_r(seasons)
            if rows:
                self.last_source_used = "nflverse / nflreadr (R)"
                return rows

        # Offline / fallback sample filtered by seasons (or all if none match)
        self.last_source_used = "built-in nflverse/sdv offline dataset"
        filtered = [r for r in SAMPLE_PBP_PLAYS if int(r.get("season", 2025)) in seasons]
        return filtered if filtered else list(SAMPLE_PBP_PLAYS)

    def _try_sportsdataverse_py(self, seasons: List[int]) -> Optional[List[Dict[str, Any]]]:
        """Attempt loading via sportsdataverse-py (`sportsdataverse.nfl.load_nfl_pbp`)."""
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
        """Attempt loading via R `nflverse` / `nflreadr` using Rscript bridge."""
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
                    return [self._normalize_row(r) for r in reader]
        except Exception:
            return None
        return None

    def _normalize_dataframe(self, df: Any) -> List[Dict[str, Any]]:
        records = df.to_dict(orient="records")
        return [self._normalize_row(r) for r in records if r.get("posteam")]

    def _normalize_row(self, r: Dict[str, Any]) -> Dict[str, Any]:
        posteam = str(r.get("posteam") or "")
        conf = r.get("conf") or ("AFC" if posteam in AFC_TEAMS else ("NFC" if posteam in NFC_TEAMS else "NFL"))
        air_yards = float(r.get("air_yards") or 0.0)
        desc = str(r.get("desc") or "")
        is_screen = int(
            r.get("is_screen")
            or ("screen" in desc.lower())
            or (int(r.get("pass_attempt") or 0) == 1 and air_yards <= 0.0 and int(r.get("complete_pass") or 0) == 1)
        )
        play_type = str(r.get("play_type") or "pass")
        play_concept = str(r.get("play_concept") or (
            "screen" if is_screen else (
                "play_action_deep" if air_yards >= 15 else (
                    "pass_short" if play_type == "pass" else "rush_outside"
                )
            )
        ))
        return {
            "season": int(r.get("season") or 2025),
            "week": int(r.get("week") or 1),
            "game_id": str(r.get("game_id") or "2025_01_UNK"),
            "posteam": posteam,
            "defteam": str(r.get("defteam") or ""),
            "conf": conf,
            "qb_name": str(r.get("qb_name") or r.get("passer_player_name") or r.get("rusher_player_name") or "Unknown QB"),
            "play_type": play_type,
            "play_concept": play_concept,
            "is_screen": is_screen,
            "play_action": int(r.get("play_action") or 0),
            "air_yards": air_yards,
            "yards_after_catch": float(r.get("yards_after_catch") or 0.0),
            "xyac_mean_yardage": float(r.get("xyac_mean_yardage") or 0.0),
            "yards_gained": float(r.get("yards_gained") or 0.0),
            "epa": float(r.get("epa") or 0.0),
            "wpa": float(r.get("wpa") or 0.0),
            "cpoe": float(r.get("cpoe") or 0.0),
            "complete_pass": int(r.get("complete_pass") or 0),
            "pass_attempt": int(r.get("pass_attempt") or 0),
            "rush_attempt": int(r.get("rush_attempt") or 0),
            "down": int(r.get("down") or 1),
            "ydstogo": int(r.get("ydstogo") or 10),
            "yardline_100": int(r.get("yardline_100") or 50),
            "series_success": int(r.get("series_success") or 0),
            "touchdown": int(r.get("touchdown") or 0),
            "interception": int(r.get("interception") or 0),
            "sack": int(r.get("sack") or 0),
            "team_win": int(r.get("team_win") if r.get("team_win") is not None else 1),
            "qtr": int(r.get("qtr") or 1),
            "desc": desc,
        }


# ---------------------------------------------------------------------------
# Safe Formula Evaluator & Composable Stat Registry
# ---------------------------------------------------------------------------

ALLOWED_AST_OPS: Dict[Any, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: (a / b) if b != 0 else 0.0,
    ast.Mod: lambda a, b: (a % b) if b != 0 else 0.0,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

ALLOWED_FUNCS: Dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sqrt": lambda x: math.sqrt(max(0.0, float(x))),
    "clamp": lambda x, lo, hi: max(float(lo), min(float(hi), float(x))),
    "ifelse": lambda cond, t_val, f_val: t_val if cond else f_val,
}


def safe_eval_formula(expr: str, context: Dict[str, float]) -> float:
    """Safely evaluate a mathematical stat formula using Python's AST without eval()."""
    tree = ast.parse(expr, mode="eval")

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in context:
                return float(context[node.id])
            raise ValueError(f"Unknown stat variable '{node.id}' in formula '{expr}'")
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_AST_OPS:
            return float(ALLOWED_AST_OPS[type(node.op)](_eval(node.left), _eval(node.right)))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_AST_OPS:
            return float(ALLOWED_AST_OPS[type(node.op)](_eval(node.operand)))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left_v = _eval(node.left)
            right_v = _eval(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Gt):
                return 1.0 if left_v > right_v else 0.0
            if isinstance(op, ast.GtE):
                return 1.0 if left_v >= right_v else 0.0
            if isinstance(op, ast.Lt):
                return 1.0 if left_v < right_v else 0.0
            if isinstance(op, ast.LtE):
                return 1.0 if left_v <= right_v else 0.0
            if isinstance(op, ast.Eq):
                return 1.0 if left_v == right_v else 0.0
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname in ALLOWED_FUNCS:
                args = [_eval(a) for a in node.args]
                return float(ALLOWED_FUNCS[fname](*args))
        raise ValueError(f"Unsupported syntax in formula: {ast.dump(node)}")

    return float(_eval(tree))


def extract_formula_dependencies(expr: str) -> List[str]:
    """Extract all variable identifiers referenced by a custom stat formula."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    deps: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in ALLOWED_FUNCS:
            if node.id not in deps:
                deps.append(node.id)
    return deps


@dataclass
class StatDefinition:
    """Represents either a Traditional Stat or a User-Created Composable Custom Stat."""
    name: str
    title: str
    category: str  # "traditional" | "custom"
    group_by: str  # "qb" | "team" | "play_concept" | "conference"
    formula: str
    description: str
    calculation_explained: str
    unit: str = ""
    filter_expr: str = ""
    dependencies: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


# Built-in Traditional & Foundational Custom Stats (all documented with descriptions + formulas)
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
    # Built-in Custom Stats demonstrating Use Case 1, Use Case 2, and Composable Chaining
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
        dependencies=["epa_per_play", "wpa_per_game", "avg_cpoe", "success_rate", "turnover_rate"],
    ),
    "qb_meaningful_win": StatDefinition(
        name="qb_meaningful_win",
        title="MLB-Style QB Meaningful Win (MW)",
        category="custom",
        group_by="qb",
        formula="ifelse((win_rate >= 0.5) * (qb_impact_score >= 55.0), games_won, 0)",
        description="MLB pitcher-style QB Win credited ONLY when the team wins AND the QB was a meaningful contributor (Impact Score >= 55).",
        calculation_explained=(
            "Evaluates each QB game/season using the custom `qb_impact_score` stat: awards a Meaningful Win (MW) "
            "when the team wins and `qb_impact_score >= 55.0` (or game WPA >= +0.08 with positive EPA). "
            "Wins where the QB plays below the 55.0 impact threshold are scored as a No-Decision (ND)."
        ),
        unit="MW",
        dependencies=["win_rate", "qb_impact_score", "games_won"],
    ),
    "qb_meaningful_loss": StatDefinition(
        name="qb_meaningful_loss",
        title="MLB-Style Inverse QB Meaningful Loss (ML)",
        category="custom",
        group_by="qb",
        formula="ifelse((win_rate < 0.5) * (qb_impact_score <= 42.0), games_lost, 0)",
        description="Inverse loss stat charged to a QB when the team loses AND the QB's Impact Score <= 42.0 materially drove the defeat.",
        calculation_explained=(
            "Builds on `qb_impact_score`: charges a Meaningful Loss (ML) only when the team loses and "
            "`qb_impact_score <= 42.0` (negative EPA/WPA + turnovers/sacks). Losses where a QB played high-impact football "
            "(`qb_impact_score > 42.0`) are recorded as a No-Decision (ND) rather than a QB Loss."
        ),
        unit="ML",
        dependencies=["win_rate", "qb_impact_score", "games_lost"],
    ),
    "screen_effectiveness_index": StatDefinition(
        name="screen_effectiveness_index",
        title="Screen Pass Effectiveness Index (SPEI)",
        category="custom",
        group_by="team",
        formula="(yards_per_play * 3.5) + (screen_yards_after_catch * 2.5) + (yac_over_expected * 4.0) + (epa_per_play * 25.0)",
        description="Composite screen-game rating combining screen yards gained, screen YAC, YAC over expected, and screen EPA.",
        calculation_explained=(
            "Composes three traditional/custom building blocks on screen plays (`is_screen == 1`): "
            "3.5 * `yards_per_play` + 2.5 * `screen_yards_after_catch` + 4.0 * `yac_over_expected` + 25.0 * `epa_per_play`."
        ),
        unit="idx",
        filter_expr="is_screen == 1",
        dependencies=["yards_per_play", "screen_yards_after_catch", "yac_over_expected", "epa_per_play"],
    ),
}


# ---------------------------------------------------------------------------
# Stat Engine: Aggregation, Dependency Resolution, & Stat Page Persistence
# ---------------------------------------------------------------------------

class StatEngine:
    """Manages custom stats, evaluates composable formulas, and tracks the user's Stat Page."""

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
            "lookback_history": {},  # stat_name -> {season_str: summary_dict}
            "last_updated": None,
        }
        self._load_state()

    def _load_state(self) -> None:
        if self.custom_stats_file.exists():
            try:
                data = json.loads(self.custom_stats_file.read_text(encoding="utf-8"))
                for name, item in data.get("stats", {}).items():
                    self.stats[name] = StatDefinition(**item)
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
            "schema_version": "1.0",
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
        pin_to_page: bool = True,
    ) -> StatDefinition:
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())
        deps = extract_formula_dependencies(formula)
        # Validate formula syntax with dummy context
        dummy_ctx = {d: 1.0 for d in deps}
        safe_eval_formula(formula, dummy_ctx)

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
            "schema_version": "1.0",
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
                    dependencies=item.get("dependencies") or extract_formula_dependencies(item["formula"]),
                )
                self.stats[stat_def.name] = stat_def
                if stat_def.name not in self.stat_page["pinned_stats"]:
                    self.stat_page["pinned_stats"].append(stat_def.name)
                imported_names.append(stat_def.name)
        self.save_state()
        return imported_names

    def _apply_filter(self, plays: List[Dict[str, Any]], filter_expr: str, conf: Optional[str] = None) -> List[Dict[str, Any]]:
        result = plays
        if conf:
            result = [p for p in result if str(p.get("conf", "")).upper() == conf.upper()]
        if not filter_expr.strip():
            return result
        filtered: List[Dict[str, Any]] = []
        for p in result:
            ctx = {k: (float(v) if isinstance(v, (int, float)) else 0.0) for k, v in p.items()}
            try:
                if safe_eval_formula(filter_expr, ctx) > 0:
                    filtered.append(p)
            except Exception:
                pass
        return filtered

    def _compute_base_metrics(self, plays: List[Dict[str, Any]]) -> Dict[str, float]:
        n = max(1, len(plays))
        total_yards = sum(float(p.get("yards_gained", 0.0)) for p in plays)
        total_air = sum(float(p.get("air_yards", 0.0)) for p in plays)
        total_yac = sum(float(p.get("yards_after_catch", 0.0)) for p in plays)
        total_xyac = sum(float(p.get("xyac_mean_yardage", 0.0)) for p in plays)
        total_epa = sum(float(p.get("epa", 0.0)) for p in plays)
        total_wpa = sum(float(p.get("wpa", 0.0)) for p in plays)
        completions = sum(int(p.get("complete_pass", 0)) for p in plays)
        pass_attempts = sum(int(p.get("pass_attempt", 0)) for p in plays)
        rush_attempts = sum(int(p.get("rush_attempt", 0)) for p in plays)
        touchdowns = sum(int(p.get("touchdown", 0)) for p in plays)
        interceptions = sum(int(p.get("interception", 0)) for p in plays)
        sacks = sum(int(p.get("sack", 0)) for p in plays)
        success_plays = sum(int(p.get("series_success", 0)) for p in plays)

        # Distinct games and game wins
        games: Dict[str, int] = {}
        for p in plays:
            gid = str(p.get("game_id", "game"))
            games[gid] = int(p.get("team_win", 0))
        games_played = max(1, len(games))
        games_won = sum(1 for w in games.values() if w == 1)
        games_lost = games_played - games_won

        cpoe_vals = [float(p.get("cpoe", 0.0)) for p in plays if int(p.get("pass_attempt", 0)) == 1]
        avg_cpoe = (sum(cpoe_vals) / len(cpoe_vals)) if cpoe_vals else 0.0

        base: Dict[str, float] = {
            "plays": float(len(plays)),
            "games_played": float(games_played),
            "games_won": float(games_won),
            "games_lost": float(games_lost),
            "win_rate": float(games_won) / float(games_played),
            "total_yards": total_yards,
            "yards_per_play": total_yards / n,
            "total_air_yards": total_air,
            "air_yards_per_play": total_air / n,
            "total_yac": total_yac,
            "yac_per_play": total_yac / n,
            "total_xyac": total_xyac,
            "completions": float(max(1, completions)),
            "completion_pct": (float(completions) / float(max(1, pass_attempts))) * 100.0,
            "pass_attempts": float(pass_attempts),
            "rush_attempts": float(rush_attempts),
            "total_epa": total_epa,
            "epa_per_play": total_epa / n,
            "total_wpa": total_wpa,
            "wpa_per_play": total_wpa / n,
            "wpa_per_game": total_wpa / float(games_played),
            "avg_cpoe": avg_cpoe,
            "touchdowns": float(touchdowns),
            "interceptions": float(interceptions),
            "sacks": float(sacks),
            "turnover_rate": float(interceptions) / n,
            "success_rate": float(success_plays) / n,
        }
        return base

    def evaluate_all_metrics_for_group(self, plays: List[Dict[str, Any]]) -> Dict[str, float]:
        """Compute base traditional metrics AND resolve all composable custom stats in dependency order."""
        ctx = self._compute_base_metrics(plays)
        # Multi-pass resolution so custom stats can depend on earlier custom stats
        unresolved = list(self.stats.values())
        for _ in range(len(unresolved) + 2):
            progressed = False
            for sdef in unresolved:
                try:
                    val = safe_eval_formula(sdef.formula, ctx)
                    ctx[sdef.name] = val
                    progressed = True
                except Exception:
                    pass
            if not progressed:
                break
        return ctx

    def evaluate_stat_leaderboard(
        self,
        stat_name: str,
        plays: List[Dict[str, Any]],
        conf: Optional[str] = None,
        group_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate a traditional or custom stat across entities and return a sorted leaderboard."""
        if stat_name not in self.stats:
            raise KeyError(f"Stat '{stat_name}' is not registered.")
        sdef = self.stats[stat_name]
        filtered = self._apply_filter(plays, sdef.filter_expr, conf=conf)
        group_col = group_override or sdef.group_by
        col_map = {
            "qb": "qb_name",
            "team": "posteam",
            "play_concept": "play_concept",
            "conference": "conf",
        }
        key_field = col_map.get(group_col, "posteam")

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in filtered:
            gval = str(p.get(key_field) or "Unknown")
            groups.setdefault(gval, []).append(p)

        rows: List[Dict[str, Any]] = []
        for gval, gplays in groups.items():
            metrics = self.evaluate_all_metrics_for_group(gplays)
            sample_play = max(gplays, key=lambda x: float(x.get("yards_gained", 0.0)))
            rows.append({
                "entity": gval,
                "team": str(gplays[0].get("posteam", "")),
                "conf": str(gplays[0].get("conf", "")),
                "value": round(float(metrics.get(stat_name, 0.0)), 2),
                "plays": int(metrics["plays"]),
                "yards_per_play": round(metrics["yards_per_play"], 2),
                "total_yards": round(metrics["total_yards"], 1),
                "yac_per_play": round(metrics["yac_per_play"], 2),
                "epa_per_play": round(metrics["epa_per_play"], 2),
                "qb_impact_score": round(metrics.get("qb_impact_score", 0.0), 1),
                "qb_meaningful_win": int(round(metrics.get("qb_meaningful_win", 0.0))),
                "qb_meaningful_loss": int(round(metrics.get("qb_meaningful_loss", 0.0))),
                "games_won": int(metrics["games_won"]),
                "games_lost": int(metrics["games_lost"]),
                "no_decisions": max(0, int(metrics["games_played"]) - int(round(metrics.get("qb_meaningful_win", 0.0))) - int(round(metrics.get("qb_meaningful_loss", 0.0)))),
                "best_play": sample_play,
            })

        rows.sort(key=lambda r: (r["value"], r["epa_per_play"]), reverse=True)
        return rows

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
# Colorized ASCII Art Renderer: Banner, Gridiron Field, Play Diagram & Tables
# ---------------------------------------------------------------------------

class AsciiArtRenderer:
    """Renders ANSI-colorized ASCII art banners, football fields, play diagrams, and tables."""

    @staticmethod
    def banner() -> str:
        lines = [
            f"{C.BOLD}{C.GOLD}╔══════════════════════════════════════════════════════════════════════════════════════╗{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.BOLD}{C.GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║{C.RESET}  {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET}  {C.DIM}{C.WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Gridiron TUI{C.RESET}      {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}╚══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        ]
        return "\n".join(lines)

    @staticmethod
    def render_table(title: str, headers: List[str], rows: List[List[Any]], alignments: Optional[List[str]] = None) -> str:
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
    def render_field_and_play(play: Dict[str, Any], title: str = "ASCII ART GRIDIRON & PLAY VISUALIZER") -> str:
        """
        Render a colorized 100-yard NFL field with endzones, yard numbers, hash marks,
        Line of Scrimmage (LOS), First Down marker, Air Yards trajectory, and YAC path.
        """
        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        conf = str(play.get("conf", "NFL"))
        yardline_100 = int(play.get("yardline_100", 60))  # yards from opponent endzone (100 = own GL, 0 = opp GL)
        los_yard = max(1, min(99, 100 - yardline_100))     # 0..100 left-to-right
        yards_gained = float(play.get("yards_gained", 15.0))
        air_yards = float(play.get("air_yards", 0.0))
        yac = float(play.get("yards_after_catch", 0.0))
        ydstogo = int(play.get("ydstogo", 10))
        down = int(play.get("down", 1))
        is_screen = int(play.get("is_screen", 0)) == 1
        play_type = str(play.get("play_type", "pass"))
        concept = str(play.get("play_concept", "pass"))
        qb_name = str(play.get("qb_name", "QB"))

        end_yard = max(0, min(100, int(round(los_yard + yards_gained))))
        catch_yard = max(0, min(100, int(round(los_yard + air_yards)))) if play_type == "pass" else los_yard
        first_down_yard = max(0, min(100, los_yard + ydstogo))

        # 60-character inner field representing 100 yards (1 char = ~1.67 yards)
        field_width = 60
        def y_to_col(y: float) -> int:
            return max(0, min(field_width - 1, int(round((y / 100.0) * (field_width - 1)))))

        los_col = y_to_col(los_yard)
        catch_col = y_to_col(catch_yard)
        end_col = y_to_col(end_yard)
        fd_col = y_to_col(first_down_yard)

        border = f"{C.BOLD}{C.WHITE}+------+{'-' * field_width}+------+{C.RESET}"
        yard_hdr = f"       {C.GRAY}0    10    20    30    40    50    40    30    20    10   100{C.RESET}"

        rows_out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} ({posteam} vs {defteam} • {conf}){C.RESET}",
            yard_hdr,
            border,
        ]

        ez_left = ["  " + posteam[:3].ljust(3) + " ", " OWN  ", " END  ", " ZONE ", "  🏈  ", "      ", "      "]
        ez_right = ["  " + defteam[:3].ljust(3) + " ", " OPP  ", " END  ", " ZONE ", "  TD  ", "      ", "      "]

        for r_idx in range(7):
            row_chars = [" "] * field_width
            # Draw 10-yard vertical lines & hash marks
            for c_idx in range(field_width):
                if c_idx % 6 == 0:
                    row_chars[c_idx] = f"{C.GRAY}⋮{C.RESET}"
                elif r_idx in (2, 4) and c_idx % 2 == 0:
                    row_chars[c_idx] = f"{C.TURF_LIGHT}·{C.RESET}"
                else:
                    row_chars[c_idx] = f"{C.TURF_GREEN}░{C.RESET}"

            # Line of Scrimmage (Blue) & First Down Line (Yellow)
            row_chars[los_col] = f"{C.BOLD}{C.BLUE}┃{C.RESET}"
            if fd_col != los_col:
                row_chars[fd_col] = f"{C.BOLD}{C.YELLOW}┇{C.RESET}"

            # Draw Offensive / Defensive Formation & Play Trajectory on middle rows
            if r_idx == 3:
                qb_col = max(0, los_col - 2)
                row_chars[qb_col] = f"{C.BOLD}{C.CYAN}Q{C.RESET}"
                if play_type == "pass":
                    # Air yards path (Cyan '~' or '-' if behind LOS screen)
                    step = 1 if catch_col >= qb_col else -1
                    for c in range(qb_col + step, catch_col, step):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.CYAN}~{C.RESET}"
                    row_chars[catch_col] = f"{C.BOLD}{C.MAGENTA}◎{C.RESET}"  # Catch point
                    # YAC path (Bright Green '═>')
                    for c in range(min(catch_col, end_col) + 1, max(catch_col, end_col)):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.GREEN}═{C.RESET}"
                else:
                    # Rush path
                    for c in range(min(los_col, end_col) + 1, max(los_col, end_col)):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.GREEN}═{C.RESET}"
                row_chars[end_col] = f"{C.BOLD}{C.GOLD}★{C.RESET}"

            # Screen blockers / route runners on adjacent rows
            if is_screen and r_idx in (2, 4):
                blk_col = min(field_width - 1, max(0, catch_col + 1))
                row_chars[blk_col] = f"{C.BOLD}{C.ORANGE}▓{C.RESET}"
            elif not is_screen and r_idx == 1 and play_type == "pass":
                wr_col = min(field_width - 1, los_col + 4)
                row_chars[wr_col] = f"{C.YELLOW}↗{C.RESET}"

            left_box = f"{C.BOLD}{C.WHITE}|{C.BG_ENDZONE_AFC}{C.WHITE}{ez_left[r_idx]}{C.RESET}{C.BOLD}{C.WHITE}|{C.RESET}"
            right_box = f"{C.BOLD}{C.WHITE}|{C.BG_ENDZONE_NFC}{C.WHITE}{ez_right[r_idx]}{C.RESET}{C.BOLD}{C.WHITE}|{C.RESET}"
            rows_out.append(f"{left_box}{''.join(row_chars)}{right_box}")

        rows_out.append(border)
        legend = (
            f"  {C.BOLD}{C.CYAN}Q{C.RESET}=QB ({qb_name})  "
            f"{C.BOLD}{C.BLUE}┃{C.RESET}=LOS (Own {los_yard})  "
            f"{C.BOLD}{C.YELLOW}┇{C.RESET}=1st Down ({down}&{ydstogo})  "
            f"{C.BOLD}{C.CYAN}~{C.RESET}=Air ({air_yards:+.0f}y)  "
            f"{C.BOLD}{C.MAGENTA}◎{C.RESET}=Catch  "
            f"{C.BOLD}{C.ORANGE}▓{C.RESET}=Screen Blockers  "
            f"{C.BOLD}{C.GREEN}═{C.RESET}=YAC (+{yac:.0f}y)  "
            f"{C.BOLD}{C.GOLD}★{C.RESET}=End (+{yards_gained:.0f}y)"
        )
        summary_box = (
            f"  {C.BOLD}Play Concept:{C.RESET} {C.CYAN}{concept}{C.RESET}  │  "
            f"{C.BOLD}Gain:{C.RESET} {C.GREEN}{yards_gained:+.1f} yds{C.RESET} (Air: {air_yards:+.1f}, YAC: {yac:.1f})  │  "
            f"{C.BOLD}EPA:{C.RESET} {C.GOLD}{float(play.get('epa', 0.0)):+.2f}{C.RESET}  │  "
            f"{C.BOLD}WPA:{C.RESET} {C.MAGENTA}{float(play.get('wpa', 0.0)) * 100:+.1f}%{C.RESET}\n"
            f"  {C.DIM}Play Call: {play.get('desc', '')}{C.RESET}"
        )
        rows_out.extend([legend, summary_box])
        return "\n".join(rows_out)


# ---------------------------------------------------------------------------
# Zero-Cost Local Natural Language Stat Query Parser (No Paid API Required)
# ---------------------------------------------------------------------------

class NaturalLanguageStatAssistant:
    """
    Translates natural-language user questions into stat queries or custom stat definitions
    locally at $0 cost (no paid API or external server required).
    Optionally connects to a local Ollama model or an authenticated cloud proxy server if configured.
    """

    @staticmethod
    def interpret_query(query: str) -> Dict[str, Any]:
        q = query.strip().lower()
        season_match = re.search(r"\b(20\d{2})\b", q)
        season = int(season_match.group(1)) if season_match else 2025
        conf = "AFC" if "afc" in q else ("NFC" if "nfc" in q else None)

        if any(w in q for w in ("qb win", "pitcher", "meaningful", "impact", "loss")):
            return {
                "intent": "qb_wins_report",
                "season": season,
                "conf": conf,
                "explanation": "Evaluated MLB-style QB Meaningful Wins (MW), Meaningful Losses (ML), No-Decisions (ND), and 0-100 QB Game Impact Scores.",
            }
        if "screen" in q:
            metric = "screen_yards_after_catch" if ("yac" in q or "after catch" in q) else "screen_effectiveness_index"
            return {
                "intent": "screen_effectiveness",
                "stat_name": metric,
                "season": season,
                "conf": conf,
                "explanation": f"Analyzed screen pass effectiveness ({metric}) for season {season} across yards gained, YAC, xYAC, and EPA.",
            }
        if any(w in q for w in ("efficient", "offensive play", "yards gained", "afc", "nfc", "concept")):
            return {
                "intent": "play_efficiency",
                "stat_name": "yards_per_play",
                "season": season,
                "conf": conf or "AFC",
                "explanation": f"Ranked offensive play concepts in the {conf or 'AFC'} by average yards gained per play and EPA.",
            }
        return {
            "intent": "stat_leaderboard",
            "stat_name": "qb_impact_score",
            "season": season,
            "conf": conf,
            "explanation": f"Evaluated custom stat leaderboard for season {season}.",
        }


# ---------------------------------------------------------------------------
# High-Level Workflows & CLI Entrypoint
# ---------------------------------------------------------------------------

def render_qb_meaningful_wins_view(engine: StatEngine, plays: List[Dict[str, Any]], season: int, conf: Optional[str], view_mode: str) -> str:
    board = engine.evaluate_stat_leaderboard("qb_impact_score", plays, conf=conf, group_override="qb")
    sdef_win = engine.stats["qb_meaningful_win"]
    sdef_loss = engine.stats["qb_meaningful_loss"]
    sdef_imp = engine.stats["qb_impact_score"]

    out: List[str] = []
    if view_mode in ("table", "all"):
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

    if view_mode in ("text", "table", "all"):
        out.append(
            f"\n{C.BOLD}{C.CYAN}📘 Stat Definitions & How They Are Calculated:{C.RESET}\n"
            f"  • {C.BOLD}{sdef_imp.title} (`{sdef_imp.name}`){C.RESET}: {sdef_imp.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_imp.formula}`\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_imp.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_win.title} (`{sdef_win.name}`){C.RESET}: {sdef_win.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_win.formula}` (Depends on: {', '.join(sdef_win.dependencies)})\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_win.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_loss.title} (`{sdef_loss.name}`){C.RESET}: {sdef_loss.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_loss.formula}` (Depends on: {', '.join(sdef_loss.dependencies)})\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_loss.calculation_explained}"
        )

    if view_mode in ("field", "play", "all") and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"SIGNATURE WIN-IMPACT PLAY: {board[0]['entity']} ({board[0]['team']})",
        ))
    return "\n".join(out)


def render_screen_pass_view(engine: StatEngine, plays: List[Dict[str, Any]], season: int, conf: Optional[str], view_mode: str) -> str:
    screen_plays = [p for p in plays if int(p.get("is_screen", 0)) == 1 and (not conf or p.get("conf") == conf)]
    board = engine.evaluate_stat_leaderboard("screen_effectiveness_index", screen_plays, conf=conf, group_override="team")
    sdef_yac = engine.stats["screen_yards_after_catch"]
    sdef_idx = engine.stats["screen_effectiveness_index"]

    out: List[str] = []
    if view_mode in ("table", "all"):
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

    if view_mode in ("text", "table", "all"):
        out.append(
            f"\n{C.BOLD}{C.CYAN}📘 Screen Pass Stat Explanations:{C.RESET}\n"
            f"  • {C.BOLD}{sdef_yac.title} (`{sdef_yac.name}`){C.RESET}: {sdef_yac.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_yac.formula}` (Filter: `{sdef_yac.filter_expr}`)\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_yac.calculation_explained}\n"
            f"  • {C.BOLD}{sdef_idx.title} (`{sdef_idx.name}`){C.RESET}: {sdef_idx.description}\n"
            f"    {C.DIM}Formula:{C.RESET} `{sdef_idx.formula}`\n"
            f"    {C.DIM}How Calculated:{C.RESET} {sdef_idx.calculation_explained}"
        )

    if view_mode in ("field", "play", "all") and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"TOP SCREEN PASS PLAY DIAGRAM ({board[0]['entity']} • +{board[0]['best_play']['yards_after_catch']:.0f} YAC)",
        ))
    return "\n".join(out)


def render_play_efficiency_view(engine: StatEngine, plays: List[Dict[str, Any]], season: int, conf: str, view_mode: str) -> str:
    board = engine.evaluate_stat_leaderboard("yards_per_play", plays, conf=conf, group_override="play_concept")
    sdef = engine.stats["yards_per_play"]

    out: List[str] = []
    if view_mode in ("table", "all"):
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
            f"Most Efficient Offensive Plays in the {conf} by Yards Gained ({season})",
            headers,
            rows,
            alignments=["right", "left", "right", "right", "right", "right", "right"],
        ))

    if view_mode in ("text", "table", "all") and board:
        top = board[0]
        out.append(
            f"\n{C.BOLD}{C.GREEN}🏆 Most Efficient {conf} Offensive Concept:{C.RESET} "
            f"`{top['entity']}` averaging {C.BOLD}{top['yards_per_play']:.2f} yards gained/play{C.RESET} "
            f"({top['epa_per_play']:+.2f} EPA/play).\n"
            f"  • {C.BOLD}{sdef.title} (`{sdef.name}`){C.RESET}: {sdef.calculation_explained}"
        )

    if view_mode in ("field", "play", "all") and board:
        out.append(AsciiArtRenderer.render_field_and_play(
            board[0]["best_play"],
            title=f"MOST EFFICIENT {conf} OFFENSIVE PLAY ON FIELD: {board[0]['entity'].upper()}",
        ))
    return "\n".join(out)


def render_stat_page(engine: StatEngine, all_plays: List[Dict[str, Any]]) -> str:
    page = engine.update_stat_page_tracking(all_plays)
    headers = ["Stat ID", "Title", "Type", "2024 Lookback Leader", "2025 Current Leader", "YoY Avg Trend", "Formula / Basis"]
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
            sdef.title[:30],
            cat_badge,
            str24,
            str25,
            arrow,
            sdef.formula[:34] + ("…" if len(sdef.formula) > 34 else ""),
        ])

    table_str = AsciiArtRenderer.render_table(
        f"📌 SAVED STAT PAGE — Lookback (2024) & Forward Tracking (2025) • Updated {page.get('last_updated')}",
        headers,
        rows,
        alignments=["left", "left", "center", "left", "left", "right", "left"],
    )
    catalog_lines = [f"\n{C.BOLD}{C.CYAN}📚 Saved Stat Catalog (Descriptions & Calculation Formulas):{C.RESET}"]
    for sname in page.get("pinned_stats", []):
        if sname in engine.stats:
            s = engine.stats[sname]
            deps_str = ", ".join(s.dependencies) if s.dependencies else "base play-by-play columns"
            catalog_lines.append(
                f"  • {C.BOLD}{C.GOLD}{s.name}{C.RESET} ({s.title}) [{s.category.upper()}]\n"
                f"    {C.WHITE}Description:{C.RESET} {s.description}\n"
                f"    {C.WHITE}Calculation:{C.RESET} {s.calculation_explained}\n"
                f"    {C.DIM}Formula: `{s.formula}`  |  Built From: {deps_str}{C.RESET}"
            )
    return table_str + "\n" + "\n".join(catalog_lines)


def interactive_tui(engine: StatEngine, bridge: NFLDataBridge) -> None:
    """Interactive terminal interface loop for *nix and Windows."""
    print(AsciiArtRenderer.banner())
    plays = bridge.load_pbp([2024, 2025])
    print(f"  {C.GREEN}✔ Loaded {len(plays)} play-by-play records via [{bridge.last_source_used}]{C.RESET}")

    menu = f"""
{C.BOLD}{C.CYAN}┌──────────────────────────────────────────────────────────────────────────────┐
│                         NFL-STAT-CLI INTERACTIVE MENU                        │
├──────────────────────────────────────────────────────────────────────────────┤{C.RESET}
  {C.BOLD}[1]{C.RESET} 🏈 {C.GOLD}MLB-Style QB Meaningful Wins (MW), Losses (ML) & 0-100 Impact Score{C.RESET}
  {C.BOLD}[2]{C.RESET} 🎯 {C.CYAN}Screen Pass Effectiveness (Yards Gained, YAC, xYAC & Play Diagram){C.RESET}
  {C.BOLD}[3]{C.RESET} ⚡ {C.GREEN}Most Efficient Offensive Play in the AFC / NFC (Yards Gained + Field){C.RESET}
  {C.BOLD}[4]{C.RESET} 🧪 {C.MAGENTA}Build a New Composable Custom Stat (from Traditional + Custom Stats){C.RESET}
  {C.BOLD}[5]{C.RESET} 📌 {C.WHITE}View Saved Stat Page (Historical Lookback & Forward Tracking){C.RESET}
  {C.BOLD}[6]{C.RESET} 💾 {C.YELLOW}Export / Import Custom Stats JSON{C.RESET}
  {C.BOLD}[7]{C.RESET} 💬 {C.CYAN}Ask a Natural-Language Stat Question (Zero-Cost Local Parser){C.RESET}
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
            p25 = [p for p in plays if int(p.get("season", 2025)) == 2025]
            print(render_qb_meaningful_wins_view(engine, p25, 2025, None, "all"))
        elif choice == "2":
            p25 = [p for p in plays if int(p.get("season", 2025)) == 2025]
            print(render_screen_pass_view(engine, p25, 2025, None, "all"))
        elif choice == "3":
            p25 = [p for p in plays if int(p.get("season", 2025)) == 2025]
            print(render_play_efficiency_view(engine, p25, 2025, "AFC", "all"))
        elif choice == "4":
            print(f"\n{C.BOLD}{C.MAGENTA}=== BUILD A NEW COMPOSABLE CUSTOM STAT ==={C.RESET}")
            print(f"Available building blocks (traditional + existing custom stats):")
            print("  " + ", ".join(sorted(list(engine.stats.keys()) + ["wpa_per_game", "avg_cpoe", "success_rate", "turnover_rate", "completion_pct"])))
            name = input("  Stat identifier (e.g. clutch_qb_value): ").strip() or "clutch_qb_value"
            title = input("  Display Title: ").strip() or "Clutch QB Value Index"
            group_by = input("  Group by [qb/team/play_concept] (default: qb): ").strip() or "qb"
            formula = input("  Formula (e.g. (qb_impact_score * 0.7) + (yards_per_play * 3.0) + (qb_meaningful_win * 10) - (qb_meaningful_loss * 10)): ").strip()
            if not formula:
                formula = "(qb_impact_score * 0.7) + (yards_per_play * 3.0) + (qb_meaningful_win * 10) - (qb_meaningful_loss * 10)"
            desc = input("  Description: ").strip() or "Combines custom qb_impact_score, MW/ML record, and traditional yards_per_play."
            calc = input("  Calculation explanation: ").strip() or f"Weighted composite evaluated via formula: {formula}"
            sdef = engine.register_custom_stat(name, title, group_by, formula, desc, calc, unit="pts")
            print(f"\n  {C.GREEN}✔ Registered & pinned custom stat `{sdef.name}`! Dependencies: {', '.join(sdef.dependencies)}{C.RESET}")
            p25 = [p for p in plays if int(p.get("season", 2025)) == 2025]
            board = engine.evaluate_stat_leaderboard(sdef.name, p25)
            rows = [[f"#{i}", r["entity"], r["team"], f"{r['value']:.2f}", f"{r['qb_impact_score']:.1f}", f"{r['yards_per_play']:.1f}"] for i, r in enumerate(board, 1)]
            print(AsciiArtRenderer.render_table(f"New Custom Stat Preview: {sdef.title}", ["Rank", "Entity", "Team", sdef.name, "qb_impact_score", "Yds/Play"], rows))
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
            q = input("  Ask a stat question (e.g. 'show screen pass effectiveness for 2025 in YAC'): ").strip()
            parsed = NaturalLanguageStatAssistant.interpret_query(q)
            print(f"  {C.DIM}→ {parsed['explanation']}{C.RESET}")
            s_plays = [p for p in plays if int(p.get("season", 2025)) == parsed["season"]]
            if parsed["intent"] == "qb_wins_report":
                print(render_qb_meaningful_wins_view(engine, s_plays, parsed["season"], parsed["conf"], "all"))
            elif parsed["intent"] == "screen_effectiveness":
                print(render_screen_pass_view(engine, s_plays, parsed["season"], parsed["conf"], "all"))
            elif parsed["intent"] == "play_efficiency":
                print(render_play_efficiency_view(engine, s_plays, parsed["season"], parsed["conf"] or "AFC", "all"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nfl-stat-cli",
        description="Cross-platform (*nix & Windows) colorized ASCII art NFL analytics & composable custom stat CLI using nflverse (R) & sportsdataverse-py (Python).",
    )
    parser.add_argument("--engine", choices=["auto", "python", "r", "offline"], default="auto", help="Data backend preference")
    parser.add_argument("--season", type=int, default=2025, help="Season year to analyze (default: 2025)")
    parser.add_argument("--conf", choices=["AFC", "NFC"], default=None, help="Filter by conference (AFC or NFC)")
    parser.add_argument("--view", choices=["table", "field", "play", "text", "all"], default="all", help="Display mode")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color codes")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", help="Launch interactive colorized terminal interface (default)")
    sub.add_parser("qb-wins", help="Run MLB-style QB Meaningful Wins (MW), Losses (ML) & 0-100 Impact Score report")
    sub.add_parser("screen-pass", help="Analyze screen pass effectiveness in yards gained, YAC, xYAC, and EPA")

    eff_p = sub.add_parser("play-efficiency", help="Rank most efficient offensive play concepts by yards gained")
    eff_p.add_argument("--conference", choices=["AFC", "NFC"], default="AFC", help="Conference to rank (default: AFC)")

    create_p = sub.add_parser("create-stat", help="Create & save a new custom stat built from traditional or custom stats")
    create_p.add_argument("--name", required=True, help="Unique stat identifier (e.g. clutch_qb_value)")
    create_p.add_argument("--title", required=True, help="Human-readable title")
    create_p.add_argument("--group-by", choices=["qb", "team", "play_concept", "conference"], default="qb")
    create_p.add_argument("--formula", required=True, help="Math formula referencing traditional or custom stats")
    create_p.add_argument("--description", required=True, help="What the stat measures")
    create_p.add_argument("--explained", required=True, help="How the stat is calculated")
    create_p.add_argument("--filter", default="", help="Optional filter expression (e.g. 'is_screen == 1')")
    create_p.add_argument("--unit", default="", help="Unit label")

    sub.add_parser("stat-page", help="Display saved Stat Page with historical lookback and forward tracking")

    exp_p = sub.add_parser("export-stats", help="Export custom stats (with descriptions & formulas) to JSON")
    exp_p.add_argument("--output", required=True, help="Target JSON file path")
    exp_p.add_argument("--include-traditional", action="store_true", help="Include built-in traditional stats in JSON")

    imp_p = sub.add_parser("import-stats", help="Import custom stats from a JSON file")
    imp_p.add_argument("--input", required=True, help="Source JSON file path")

    ask_p = sub.add_parser("ask", help="Ask a natural-language NFL stat question (zero-cost local parser)")
    ask_p.add_argument("query", help="Natural language question")

    sub.add_parser("demo-all", help="Run full showcase of all views, ASCII field/play diagrams, custom stat chaining, and Stat Page")

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
        interactive_tui(engine, bridge)
        return 0

    print(AsciiArtRenderer.banner())
    print(f"  {C.DIM}Data Source: {bridge.last_source_used}  |  Platform: {platform.system()} ({os.name}){C.RESET}")

    if cmd == "qb-wins":
        print(render_qb_meaningful_wins_view(engine, season_plays, args.season, args.conf, args.view))
    elif cmd == "screen-pass":
        print(render_screen_pass_view(engine, season_plays, args.season, args.conf, args.view))
    elif cmd == "play-efficiency":
        conf = args.conf or getattr(args, "conference", "AFC")
        print(render_play_efficiency_view(engine, season_plays, args.season, conf, args.view))
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
        )
        print(f"\n{C.GREEN}✔ Created & saved custom stat `{sdef.name}` ({sdef.title}){C.RESET}")
        print(f"  {C.BOLD}Description:{C.RESET} {sdef.description}")
        print(f"  {C.BOLD}Calculation:{C.RESET} {sdef.calculation_explained}")
        print(f"  {C.BOLD}Formula:{C.RESET} `{sdef.formula}` (Dependencies: {', '.join(sdef.dependencies)})")
        board = engine.evaluate_stat_leaderboard(sdef.name, season_plays, conf=args.conf)
        rows = [[f"#{i}", r["entity"], r["team"], f"{r['value']:.2f} {sdef.unit}".strip(), r["plays"]] for i, r in enumerate(board, 1)]
        print(AsciiArtRenderer.render_table(f"Leaderboard: {sdef.title} ({args.season})", ["Rank", "Entity", "Team", sdef.title, "Plays"], rows))
    elif cmd == "stat-page":
        print(render_stat_page(engine, all_plays))
    elif cmd == "export-stats":
        out_path = engine.export_custom_stats_json(Path(args.output), include_traditional=args.include_traditional)
        print(f"\n{C.GREEN}✔ Exported custom stats JSON to: {out_path}{C.RESET}")
    elif cmd == "import-stats":
        names = engine.import_custom_stats_json(Path(args.input))
        print(f"\n{C.GREEN}✔ Imported {len(names)} custom stats: {', '.join(names)}{C.RESET}")
    elif cmd == "ask":
        parsed = NaturalLanguageStatAssistant.interpret_query(args.query)
        print(f"\n{C.BOLD}{C.CYAN}🤖 Query Interpretation:{C.RESET} {parsed['explanation']}")
        if parsed["intent"] == "qb_wins_report":
            print(render_qb_meaningful_wins_view(engine, season_plays, parsed["season"], parsed["conf"], args.view))
        elif parsed["intent"] == "screen_effectiveness":
            print(render_screen_pass_view(engine, season_plays, parsed["season"], parsed["conf"], args.view))
        else:
            print(render_play_efficiency_view(engine, season_plays, parsed["season"], parsed["conf"] or "AFC", args.view))
    elif cmd == "demo-all":
        print(render_qb_meaningful_wins_view(engine, season_plays, args.season, None, "all"))
        print(render_screen_pass_view(engine, season_plays, args.season, None, "all"))
        print(render_play_efficiency_view(engine, season_plays, args.season, "AFC", "all"))
        # Demonstrate chaining a second-order custom stat built on top of `qb_impact_score` and `qb_meaningful_win`
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
