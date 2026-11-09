#!/usr/bin/env python3
"""
nfl-stat-cli: Cross-Platform (*nix & Windows) Colorized Terminal NFL Analytics,
Multi-Angle Play Visualizer (Behind Offense, Behind Defense, Sideline), & General Composable Custom Stat Engine.
Powered by sportsdataverse-py (Python), nflverse / nflreadr / nflfastR (R), and Local Small Language Model (SLM via Ollama) + Deterministic Engine.
"""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import datetime as dt
import difflib
import functools
import json
import math
import operator
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import nullcontext
from importlib import resources
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from .fantasy import (
    calculate_player_fantasy_points,
    compute_player_fantasy_profile,
    compute_all_fantasy_leaders,
    render_fantasy_leaderboard_view,
    render_player_fantasy_profile_view,
    interactive_fantasy_browser,
)
from .sportsbook import (
    compute_team_power_ratings,
    handicap_matchup,
    render_sportsbook_board_view,
    render_power_ratings_view,
    render_game_handicap_dossier_view,
    interactive_sportsbook_browser,
)
from .contracts import (
    ContractRecord,
    NFL_CONTRACTS,
    find_contract_by_name,
    get_contracts_by_team,
    get_contracts_by_position,
    get_all_coach_contracts,
    calculate_contract_performance_efficiency,
    render_contracts_leaderboard_view,
    render_player_contract_view,
    render_team_payroll_view,
    interactive_contracts_browser,
)

__version__ = "2.0.0"
__author__ = "Sean McClain"
__license__ = "MIT"


def current_nfl_season(today: Optional[dt.date] = None) -> int:
    """NFL seasons kick off in September; Jan–Aug belong to the previous year's season."""
    d = today or dt.date.today()
    return d.year if d.month >= 9 else d.year - 1


CURRENT_SEASON = current_nfl_season()

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


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
    C.disable()

try:
    import readline as _readline  # type: ignore[import]
    _HAS_READLINE = True
    _IS_LIBEDIT = "libedit" in ((_readline.__doc__ or "").lower())
except ImportError:
    _readline = None
    _HAS_READLINE = False
    _IS_LIBEDIT = False


def strip_ansi(text: str) -> str:
    return _CTRL_RE.sub("", _ANSI_RE.sub("", str(text)))


def prompt_input(prompt_text: str) -> str:
    """
    Read a line of user input with readline multi-line wrap support.
    Wraps non-printing ANSI escape sequences in \\x01...\\x02 so GNU readline
    calculates exact visible prompt width and allows backspacing across line wraps.
    """
    if prompt_text.startswith("\n"):
        print()
        prompt_text = prompt_text.lstrip("\n")
    if not sys.stdin.isatty() or _IS_LIBEDIT:
        return input(strip_ansi(prompt_text))
    if _HAS_READLINE:
        rl_prompt = _ANSI_RE.sub(lambda m: f"\x01{m.group(0)}\x02", prompt_text)
        return input(rl_prompt)
    return input(prompt_text)


def _char_display_width(ch: str) -> int:
    cp = ord(ch)
    if cp < 32 or (0x7F <= cp < 0xA0):
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or cp >= 0x1F300:
        return 2
    return 1


def visible_len(text: str) -> int:
    s = strip_ansi(text)
    return sum(_char_display_width(ch) for ch in s)


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

TEAM_FULL_NAMES: Dict[str, str] = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers", "LA": "Los Angeles Rams", "LAR": "Los Angeles Rams",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SF": "San Francisco 49ers", "SEA": "Seattle Seahawks", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

TEAM_NICKNAMES_TO_ABBR: Dict[str, str] = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
    "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
    "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
    "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
    "raiders": "LV", "chargers": "LAC", "rams": "LA", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
    "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "49ers": "SF",
    "niners": "SF", "seahawks": "SEA", "buccaneers": "TB", "bucs": "TB",
    "titans": "TEN", "commanders": "WAS",
}


def resolve_team_abbr(team_str: Optional[str]) -> Optional[str]:
    """Resolve team abbreviation, city, nickname, or full name to a canonical 2-3 letter NFL team abbreviation."""
    if not team_str:
        return None
    raw = team_str.strip()
    up = raw.upper()
    if up in TEAM_DIVISIONS or up in AFC_TEAMS or up in NFC_TEAMS:
        return "LA" if up == "LAR" else up
    low = raw.lower()
    if low in TEAM_NICKNAMES_TO_ABBR:
        return TEAM_NICKNAMES_TO_ABBR[low]
    for abbr, name in TEAM_FULL_NAMES.items():
        if low == name.lower() or low in name.lower():
            return "LA" if abbr == "LAR" else abbr
    all_teams = sorted((AFC_TEAMS | NFC_TEAMS) - {"LAR"})
    matches = difflib.get_close_matches(up, all_teams, n=1, cutoff=0.7)
    if matches:
        return matches[0]
    return None


NFL_COACHING_STAFFS: Dict[str, Dict[str, Any]] = {
    "ARI": {
        "hc": "Jonathan Gannon", "oc": "Drew Petzing", "dc": "Nick Rallis",
        "qb_coach": "Israel Woolfork", "ol_coach": "Klayton Adams", "wr_coach": "Drew Terrell",
        "rb_coach": "Autry Denson", "dl_coach": "Derrick LeBlanc", "lb_coach": "Sam Siefkes",
    },
    "ATL": {
        "hc": "Raheem Morris", "oc": "Zac Robinson", "dc": "Jimmy Lake",
        "qb_coach": "T.J. Yates", "ol_coach": "Dwayne Ledford", "wr_coach": "Ike Hilliard",
        "rb_coach": "Michael Pitre", "dl_coach": "Jay Rodgers", "lb_coach": "Barrett Ruud",
    },
    "BAL": {
        "hc": "John Harbaugh", "oc": "Todd Monken", "dc": "Zach Orr",
        "qb_coach": "Tee Martin", "ol_coach": "George Warhop", "wr_coach": "Greg Lewis",
        "rb_coach": "Willie Taggart", "dl_coach": "Dennis Johnson", "lb_coach": "Mark DeLeone",
    },
    "BUF": {
        "hc": "Sean McDermott", "oc": "Joe Brady", "dc": "Bobby Babich",
        "qb_coach": "Ronald Curry", "ol_coach": "Aaron Kromer", "wr_coach": "Adam Henry",
        "rb_coach": "Kelly Skipper", "dl_coach": "Marcus West", "lb_coach": "Al Holcomb",
    },
    "CAR": {
        "hc": "Dave Canales", "oc": "Brad Idzik", "dc": "Ejiro Evero",
        "qb_coach": "Will Harriger", "ol_coach": "Joe Gilbert", "wr_coach": "Rob Moore",
        "rb_coach": "Bernie Parmalee", "dl_coach": "Todd Wash", "lb_coach": "Peter Hansen",
    },
    "CHI": {
        "hc": "Matt Eberflus", "oc": "Shane Waldron", "dc": "Eric Washington",
        "qb_coach": "Kerry Joseph", "ol_coach": "Chris Morgan", "wr_coach": "Chad Hall",
        "rb_coach": "David Walker", "dl_coach": "Travis Smith", "lb_coach": "Dave Borgonzi",
    },
    "CIN": {
        "hc": "Zac Taylor", "oc": "Dan Pitcher", "dc": "Lou Anarumo",
        "qb_coach": "Brad Kragthorpe", "ol_coach": "Frank Pollack", "wr_coach": "Troy Walters",
        "rb_coach": "Justin Hill", "dl_coach": "Marion Hobby", "lb_coach": "James Bettcher",
    },
    "CLE": {
        "hc": "Kevin Stefanski", "oc": "Ken Dorsey", "dc": "Jim Schwartz",
        "qb_coach": "Bill Musgrave", "ol_coach": "Andy Dickerson", "wr_coach": "Chad O'Shea",
        "rb_coach": "Duce Staley", "dl_coach": "Jacques Cesaire", "lb_coach": "Jason Tarver",
    },
    "DAL": {
        "hc": "Mike McCarthy", "oc": "Brian Schottenheimer", "dc": "Mike Zimmer",
        "qb_coach": "Scott Tolzien", "ol_coach": "Mike Solari", "wr_coach": "Robert Prince",
        "rb_coach": "Jeff Blasko", "dl_coach": "Aaron Whitecotton", "lb_coach": "Scott McCurley",
    },
    "DEN": {
        "hc": "Sean Payton", "oc": "Joe Lombardi", "dc": "Vance Joseph",
        "qb_coach": "Davis Webb", "ol_coach": "Zach Strief", "wr_coach": "Keary Colbert",
        "rb_coach": "Lou Ayeni", "dl_coach": "Jamar Cain", "lb_coach": "Greg Manusky",
    },
    "DET": {
        "hc": "Dan Campbell", "oc": "Ben Johnson", "dc": "Aaron Glenn",
        "qb_coach": "Mark Brunell", "ol_coach": "Hank Fraley", "wr_coach": "Antwaan Randle El",
        "rb_coach": "Scottie Montgomery", "dl_coach": "Terrell Williams", "lb_coach": "Kelvin Sheppard",
    },
    "GB": {
        "hc": "Matt LaFleur", "oc": "Adam Stenavich", "dc": "Jeff Hafley",
        "qb_coach": "Tom Clements", "ol_coach": "Luke Butkus", "wr_coach": "Jason Vrable",
        "rb_coach": "Ben Sirmans", "dl_coach": "Jason Rebrovich", "lb_coach": "Anthony Campanile",
    },
    "HOU": {
        "hc": "DeMeco Ryans", "oc": "Bobby Slowik", "dc": "Matt Burke",
        "qb_coach": "Jerrod Johnson", "ol_coach": "Chris Strausser", "wr_coach": "Ben McDaniels",
        "rb_coach": "Danny Barrett", "dl_coach": "Rod Wright", "lb_coach": "Bill Davis",
    },
    "IND": {
        "hc": "Shane Steichen", "oc": "Jim Bob Cooter", "dc": "Gus Bradley",
        "qb_coach": "Cam Turner", "ol_coach": "Tony Sparano Jr.", "wr_coach": "Reggie Wayne",
        "rb_coach": "DeAndre Smith", "dl_coach": "Charlie Partridge", "lb_coach": "Richard Smith",
    },
    "JAX": {
        "hc": "Doug Pederson", "oc": "Press Taylor", "dc": "Ryan Nielsen",
        "qb_coach": "Mike McCoy", "ol_coach": "Phil Rauscher", "wr_coach": "Chad Hall",
        "rb_coach": "Jerry Mack", "dl_coach": "Matt House", "lb_coach": "Tony Gilbert",
    },
    "KC": {
        "hc": "Andy Reid", "oc": "Matt Nagy", "dc": "Steve Spagnuolo", "st": "Dave Toub",
        "qb_coach": "David Girardi", "ol_coach": "Andy Heck", "wr_coach": "Connor Embree",
        "rb_coach": "Todd Pinkston", "dl_coach": "Joe Cullen", "lb_coach": "Brendan Daly",
    },
    "LV": {
        "hc": "Antonio Pierce", "oc": "Luke Getsy", "dc": "Patrick Graham",
        "qb_coach": "Rich Scangarello", "ol_coach": "James Cregg", "wr_coach": "Edgar Bennett",
        "rb_coach": "Carnell Lake", "dl_coach": "Rob Leonard", "lb_coach": "Mike Caldwell",
    },
    "LAC": {
        "hc": "Jim Harbaugh", "oc": "Greg Roman", "dc": "Jesse Minter",
        "qb_coach": "Shane Day", "ol_coach": "Mike Devlin", "wr_coach": "Sanjay Lal",
        "rb_coach": "Kiel McDonald", "dl_coach": "Mike Elston", "lb_coach": "NaVorro Bowman",
    },
    "LA": {
        "hc": "Sean McVay", "oc": "Mike LaFleur", "dc": "Chris Shula",
        "qb_coach": "Dave Ragone", "ol_coach": "Ryan Wendell", "wr_coach": "Eric Yarber",
        "rb_coach": "Ron Gould", "dl_coach": "Giff Smith", "lb_coach": "Chris Beake",
    },
    "LAR": {
        "hc": "Sean McVay", "oc": "Mike LaFleur", "dc": "Chris Shula",
        "qb_coach": "Dave Ragone", "ol_coach": "Ryan Wendell", "wr_coach": "Eric Yarber",
        "rb_coach": "Ron Gould", "dl_coach": "Giff Smith", "lb_coach": "Chris Beake",
    },
    "MIA": {
        "hc": "Mike McDaniel", "oc": "Frank Smith", "dc": "Anthony Weaver",
        "qb_coach": "Darrell Bevell", "ol_coach": "Butch Barry", "wr_coach": "Wes Welker",
        "rb_coach": "Eric Studesville", "dl_coach": "Derrick LeBlanc", "lb_coach": "Joe Barry",
    },
    "MIN": {
        "hc": "Kevin O'Connell", "oc": "Wes Phillips", "dc": "Brian Flores",
        "qb_coach": "Josh McCown", "ol_coach": "Chris Kuper", "wr_coach": "Keenan McCardell",
        "rb_coach": "Curtis Modkins", "dl_coach": "Marcus Dixon", "lb_coach": "Mike Siravo",
    },
    "NE": {
        "hc": "Jerod Mayo", "oc": "Alex Van Pelt", "dc": "DeMarcus Covington",
        "qb_coach": "T.C. McCartney", "ol_coach": "Scott Peters", "wr_coach": "Tyler Hughes",
        "rb_coach": "Taylor Embree", "dl_coach": "Jerry Montgomery", "lb_coach": "Dont'a Hightower",
    },
    "NO": {
        "hc": "Dennis Allen", "oc": "Klint Kubiak", "dc": "Joe Woods",
        "qb_coach": "Andrew Janocko", "ol_coach": "John Benton", "wr_coach": "Keith Williams",
        "rb_coach": "Joel Thomas", "dl_coach": "Todd Grantham", "lb_coach": "Michael Hodges",
    },
    "NYG": {
        "hc": "Brian Daboll", "oc": "Mike Kafka", "dc": "Shane Bowen",
        "qb_coach": "Shea Tierney", "ol_coach": "Carmen Bricillo", "wr_coach": "Mike Groh",
        "rb_coach": "Joel Thomas", "dl_coach": "Andre Patterson", "lb_coach": "John Egorugwu",
    },
    "NYJ": {
        "hc": "Robert Saleh", "oc": "Nathaniel Hackett", "dc": "Jeff Ulbrich",
        "qb_coach": "Charles London", "ol_coach": "Keith Carter", "wr_coach": "Shawn Jefferson",
        "rb_coach": "Tony Dews", "dl_coach": "Aaron Whitecotton", "lb_coach": "Mike Rutenberg",
    },
    "PHI": {
        "hc": "Nick Sirianni", "oc": "Kellen Moore", "dc": "Vic Fangio",
        "qb_coach": "Doug Nussmeier", "ol_coach": "Jeff Stoutland", "wr_coach": "Aaron Moorehead",
        "rb_coach": "Jemal Singleton", "dl_coach": "Clint Hurtt", "lb_coach": "Bobby King",
    },
    "PIT": {
        "hc": "Mike Tomlin", "oc": "Arthur Smith", "dc": "Teryl Austin",
        "qb_coach": "Mike Sullivan", "ol_coach": "Pat Meyer", "wr_coach": "Zach Azzanni",
        "rb_coach": "Eddie Faulkner", "dl_coach": "Karl Dunbar", "lb_coach": "Aaron Curry",
    },
    "SF": {
        "hc": "Kyle Shanahan", "oc": "Kyle Shanahan", "dc": "Nick Sorensen",
        "qb_coach": "Brian Griese", "ol_coach": "Chris Foerster", "wr_coach": "Leonard Hankerson",
        "rb_coach": "Bobby Turner", "dl_coach": "Kris Kocurek", "lb_coach": "Johnny Holland",
    },
    "SEA": {
        "hc": "Mike Macdonald", "oc": "Ryan Grubb", "dc": "Aden Durde",
        "qb_coach": "Charles London", "ol_coach": "Scott Huff", "wr_coach": "Frisman Jackson",
        "rb_coach": "Kennedy Polamalu", "dl_coach": "Justin Hinds", "lb_coach": "Jay Harbaugh",
    },
    "TB": {
        "hc": "Todd Bowles", "oc": "Liam Coen", "dc": "Kacy Rodgers",
        "qb_coach": "Thad Lewis", "ol_coach": "Kevin Carberry", "wr_coach": "Bryan McClendon",
        "rb_coach": "Skip Peete", "dl_coach": "Larry Foote", "lb_coach": "Mike Caldwell",
    },
    "TEN": {
        "hc": "Brian Callahan", "oc": "Nick Holz", "dc": "Dennard Wilson",
        "qb_coach": "Bo Hardegree", "ol_coach": "Bill Callahan", "wr_coach": "Tyke Tolbert",
        "rb_coach": "Randy Jordan", "dl_coach": "Tracy Rocker", "lb_coach": "Frank Bush",
    },
    "WAS": {
        "hc": "Dan Quinn", "oc": "Kliff Kingsbury", "dc": "Joe Whitt Jr.",
        "qb_coach": "Tavita Pritchard", "ol_coach": "Bobby Johnson", "wr_coach": "Bobby Engram",
        "rb_coach": "Anthony Lynn", "dl_coach": "Darryl Tapp", "lb_coach": "Ken Norton Jr.",
    },
}


def get_team_coaching_staff(team_abbr: str, season: Optional[int] = None) -> Dict[str, Any]:
    """Retrieve full coaching staff dictionary (HC, OC, DC, position coaches) for a given team."""
    resolved = resolve_team_abbr(team_abbr) or team_abbr.upper()
    return NFL_COACHING_STAFFS.get(resolved, NFL_COACHING_STAFFS.get("KC", {}))


def get_team_head_coach(team_abbr: str, season: Optional[int] = None) -> str:
    """Retrieve the Head Coach name for a given team."""
    return str(get_team_coaching_staff(team_abbr, season).get("hc", "Unknown Coach"))


def find_coach_team(coach_name: str) -> Optional[Tuple[str, str, str]]:
    """
    Search for a coach across all NFL teams.
    Matches exact full name, or exact last name (if >= 4 chars and not a common stop word).
    Returns (team_abbr, coach_canonical_name, role) if found, otherwise None.
    """
    c_low = coach_name.strip().lower()
    if len(c_low) < 3:
        return None
    stop_words = {
        "the", "for", "and", "who", "what", "which", "with", "from", "team", "play", "rank",
        "best", "stat", "stats", "coach", "coaches", "coaching", "head", "lead", "leader",
        "rate", "down", "game", "pass", "rush", "year", "week", "more", "most", "each",
    }
    if c_low in stop_words:
        return None

    for team, staff in NFL_COACHING_STAFFS.items():
        if team == "LAR":
            continue
        for role, name in staff.items():
            if not isinstance(name, str):
                continue
            n_low = name.lower()
            if c_low == n_low:
                return (team, name, role)
            parts = n_low.split()
            last_name = parts[-1] if parts else ""
            if len(last_name) >= 4 and c_low == last_name:
                return (team, name, role)
    return None


# ---------------------------------------------------------------------------
# Canonical Player Position Registry & Position Resolver
# ---------------------------------------------------------------------------

KNOWN_PLAYER_POSITIONS: Dict[str, str] = {
    # Quarterbacks
    "mahomes": "QB", "p.mahomes": "QB", "patrick mahomes": "QB",
    "allen": "QB", "j.allen": "QB", "josh allen": "QB",
    "jackson": "QB", "l.jackson": "QB", "lamar jackson": "QB",
    "stroud": "QB", "c.stroud": "QB", "c.j. stroud": "QB",
    "watson": "QB", "d.watson": "QB", "deshaun watson": "QB",
    "fields": "QB", "j.fields": "QB", "justin fields": "QB",
    "goff": "QB", "j.goff": "QB", "jared goff": "QB",
    "purdy": "QB", "b.purdy": "QB", "brock purdy": "QB",
    "burrow": "QB", "j.burrow": "QB", "joe burrow": "QB",
    "hurts": "QB", "j.hurts": "QB", "jalen hurts": "QB",
    "herbert": "QB", "j.herbert": "QB", "justin herbert": "QB",
    "love": "QB", "j.love": "QB", "jordan love": "QB",
    "prescott": "QB", "d.prescott": "QB", "dak prescott": "QB",
    "stafford": "QB", "m.stafford": "QB", "matthew stafford": "QB",
    "tagovailoa": "QB", "t.tagovailoa": "QB", "tua tagovailoa": "QB",
    "daniels": "QB", "j.daniels": "QB", "jayden daniels": "QB",
    "caleb williams": "QB", "c.williams": "QB",
    "maye": "QB", "d.maye": "QB", "drake maye": "QB",
    "nix": "QB", "b.nix": "QB", "bo nix": "QB",
    "rodgers": "QB", "a.rodgers": "QB", "aaron rodgers": "QB",
    "cousins": "QB", "k.cousins": "QB", "kirk cousins": "QB",
    "murray": "QB", "k.murray": "QB", "kyler murray": "QB",
    "lawrence": "QB", "t.lawrence": "QB", "trevor lawrence": "QB",
    "levis": "QB", "w.levis": "QB", "will levis": "QB",
    "young": "QB", "b.young": "QB", "bryce young": "QB",
    "minshew": "QB", "g.minshew": "QB", "gardner minshew": "QB",
    "brissett": "QB", "j.brissett": "QB",
    "darnold": "QB", "s.darnold": "QB", "sam darnold": "QB",
    "carr": "QB", "d.carr": "QB", "derek carr": "QB",
    "o'connell": "QB", "devito": "QB", "ridder": "QB", "lance": "QB", "dalton": "QB",
    "tannehill": "QB", "flacco": "QB", "j.flacco": "QB",
    "russell wilson": "QB", "r.wilson": "QB",
    "pickett": "QB", "trubisky": "QB", "winston": "QB", "lock": "QB", "rush": "QB",
    "browning": "QB", "heinicke": "QB",

    # Running backs
    "warren": "RB", "j.warren": "RB", "jaylen warren": "RB",
    "gibbs": "RB", "j.gibbs": "RB", "jahmyr gibbs": "RB",
    "jeanty": "RB", "a.jeanty": "RB", "ashton jeanty": "RB",
    "tuten": "RB", "b.tuten": "RB", "bhayshul tuten": "RB",
    "cook": "RB", "j.cook": "RB", "james cook": "RB", "d.cook": "RB", "dalvin cook": "RB",
    "henry": "RB", "d.henry": "RB", "derrick henry": "RB",
    "barkley": "RB", "s.barkley": "RB", "saquon barkley": "RB",
    "mccaffrey": "RB", "c.mccaffrey": "RB", "christian mccaffrey": "RB",
    "taylor": "RB", "j.taylor": "RB", "jonathan taylor": "RB",
    "kamara": "RB", "a.kamara": "RB", "alvin kamara": "RB",
    "jacobs": "RB", "j.jacobs": "RB", "josh jacobs": "RB",
    "hall": "RB", "b.hall": "RB", "breece hall": "RB",
    "mixon": "RB", "j.mixon": "RB", "joe mixon": "RB",
    "walker": "RB", "k.walker": "RB", "kenneth walker": "RB",
    "pollard": "RB", "t.pollard": "RB", "tony pollard": "RB",
    "bijan": "RB", "bijan robinson": "RB", "b.robinson": "RB",
    "montgomery": "RB", "d.montgomery": "RB", "david montgomery": "RB",
    "achane": "RB", "d.achane": "RB", "devon achane": "RB",
    "kyren": "RB", "kyren williams": "RB", "k.williams": "RB",
    "swift": "RB", "d.swift": "RB", "d'andre swift": "RB",
    "conner": "RB", "j.conner": "RB", "james conner": "RB",
    "mostert": "RB", "r.mostert": "RB", "raheem mostert": "RB",
    "etienne": "RB", "t.etienne": "RB", "travis etienne": "RB",
    "harris": "RB", "n.harris": "RB", "najee harris": "RB",
    "stevenson": "RB", "r.stevenson": "RB", "rhamondre stevenson": "RB",
    "charbonnet": "RB", "z.charbonnet": "RB", "zach charbonnet": "RB",
    "dowdle": "RB", "r.dowdle": "RB", "rico dowdle": "RB",
    "hubbard": "RB", "c.hubbard": "RB", "chuba hubbard": "RB",
    "ford": "RB", "j.ford": "RB", "jerome ford": "RB",
    "singletary": "RB", "d.singletary": "RB", "devin singletary": "RB",
    "benson": "RB", "t.benson": "RB", "trey benson": "RB",
    "corum": "RB", "b.corum": "RB", "blake corum": "RB",
    "vidal": "RB", "k.vidal": "RB", "kimani vidal": "RB",
    "guerendo": "RB", "i.guerendo": "RB", "isaac guerendo": "RB",
    "mason": "RB", "j.mason": "RB", "jordan mason": "RB",
    "ray davis": "RB", "r.davis": "RB",
    "chubb": "RB", "n.chubb": "RB", "nick chubb": "RB",
    "hunt": "RB", "k.hunt": "RB", "kareem hunt": "RB",
    "mckinnon": "RB", "j.mckinnon": "RB", "jerick mckinnon": "RB",
    "allgeier": "RB", "t.allgeier": "RB", "edwards-helaire": "RB",

    # Tight ends
    "fannin": "TE", "h.fannin": "TE", "harold fannin": "TE",
    "kelce": "TE", "t.kelce": "TE", "travis kelce": "TE",
    "kittle": "TE", "g.kittle": "TE", "george kittle": "TE",
    "laporta": "TE", "s.laporta": "TE", "sam laporta": "TE",
    "andrews": "TE", "m.andrews": "TE", "mark andrews": "TE",
    "bowers": "TE", "b.bowers": "TE", "brock bowers": "TE",
    "hockenson": "TE", "t.hockenson": "TE", "t.j. hockenson": "TE",
    "goedert": "TE", "d.goedert": "TE", "dallas goedert": "TE",
    "ferguson": "TE", "j.ferguson": "TE", "jake ferguson": "TE",
    "njoku": "TE", "d.njoku": "TE", "david njoku": "TE",
    "pitts": "TE", "k.pitts": "TE", "kyle pitts": "TE",
    "kmet": "TE", "c.kmet": "TE", "cole kmet": "TE",
    "kraft": "TE", "t.kraft": "TE", "tucker kraft": "TE",
    "likely": "TE", "i.likely": "TE", "isaiah likely": "TE",
    "otton": "TE", "c.otton": "TE", "cade otton": "TE",
    "schultz": "TE", "d.schultz": "TE", "dalton schultz": "TE",
    "engram": "TE", "e.engram": "TE", "evan engram": "TE",
    "freiermuth": "TE", "p.freiermuth": "TE", "pat freiermuth": "TE",
    "fant": "TE", "n.fant": "TE", "noah fant": "TE",
    "gesicki": "TE", "m.gesicki": "TE", "mike gesicki": "TE",
    "conklin": "TE", "t.conklin": "TE", "tyler conklin": "TE",
    "mcbride": "TE", "t.mcbride": "TE", "trey mcbride": "TE",
    "mayer": "TE", "m.mayer": "TE", "michael mayer": "TE",
    "hunter henry": "TE", "h.henry": "TE",
    "knox": "TE", "d.knox": "TE", "musgrave": "TE", "l.musgrave": "TE",
    "dulcich": "TE", "sinnott": "TE", "sanders": "TE", "j.sanders": "TE",

    # Wide receivers
    "worthy": "WR", "x.worthy": "WR", "xavier worthy": "WR",
    "jefferson": "WR", "j.jefferson": "WR", "justin jefferson": "WR",
    "chase": "WR", "j.chase": "WR", "ja'marr chase": "WR",
    "lamb": "WR", "c.lamb": "WR", "ceedee lamb": "WR",
    "hill": "WR", "t.hill": "WR", "tyreek hill": "WR",
    "st brown": "WR", "st. brown": "WR", "a.st brown": "WR", "a.st. brown": "WR", "amon-ra st. brown": "WR",
    "adams": "WR", "d.adams": "WR", "davante adams": "WR",
    "aiyuk": "WR", "b.aiyuk": "WR", "brandon aiyuk": "WR",
    "samuel": "WR", "d.samuel": "WR", "deebo samuel": "WR", "c.samuel": "WR", "curtis samuel": "WR",
    "diggs": "WR", "s.diggs": "WR", "stefon diggs": "WR",
    "evans": "WR", "m.evans": "WR", "mike evans": "WR",
    "collins": "WR", "n.collins": "WR", "nico collins": "WR",
    "nacua": "WR", "p.nacua": "WR", "puka nacua": "WR",
    "kupp": "WR", "c.kupp": "WR", "cooper kupp": "WR",
    "moore": "WR", "d.moore": "WR", "dj moore": "WR",
    "pickens": "WR", "g.pickens": "WR", "george pickens": "WR",
    "metcalf": "WR", "d.metcalf": "WR", "dk metcalf": "WR",
    "devonta smith": "WR", "d.smith": "WR",
    "higgins": "WR", "t.higgins": "WR", "tee higgins": "WR",
    "flowers": "WR", "z.flowers": "WR", "zay flowers": "WR",
    "olave": "WR", "c.olave": "WR", "chris olave": "WR",
    "london": "WR", "d.london": "WR", "drake london": "WR",
    "reed": "WR", "j.reed": "WR", "jayden reed": "WR",
    "rice": "WR", "r.rice": "WR", "rashee rice": "WR",
    "tank dell": "WR", "t.dell": "WR",
    "waddle": "WR", "j.waddle": "WR", "jaylen waddle": "WR",
    "hopkins": "WR", "d.hopkins": "WR", "deandre hopkins": "WR",
    "mclaurin": "WR", "t.mclaurin": "WR", "terry mclaurin": "WR",
    "godwin": "WR", "c.godwin": "WR", "chris godwin": "WR",
    "sutton": "WR", "c.sutton": "WR", "courtland sutton": "WR",
    "ridley": "WR", "c.ridley": "WR", "calvin ridley": "WR",
    "lockett": "WR", "t.lockett": "WR", "tyler lockett": "WR",
    "shakir": "WR", "k.shakir": "WR", "khalil shakir": "WR",
    "jeudy": "WR", "j.jeudy": "WR", "jerry jeudy": "WR",
    "legette": "WR", "x.legette": "WR", "xavier legette": "WR",
    "thomas": "WR", "b.thomas": "WR", "brian thomas": "WR",
    "nabers": "WR", "m.nabers": "WR", "malik nabers": "WR",
    "odunze": "WR", "r.odunze": "WR", "rome odunze": "WR",
    "harrison": "WR", "m.harrison": "WR", "marvin harrison": "WR",
    "downs": "WR", "j.downs": "WR", "josh downs": "WR",
    "thielen": "WR", "a.thielen": "WR", "adam thielen": "WR",
    "douglas": "WR", "d.douglas": "WR",
    "meyers": "WR", "j.meyers": "WR", "jakobi meyers": "WR",
    "palmer": "WR", "j.palmer": "WR", "joshua palmer": "WR",
    "cooper": "WR", "a.cooper": "WR", "amari cooper": "WR",
    "mcconkey": "WR", "l.mcconkey": "WR", "ladd mcconkey": "WR",
    "lazard": "WR", "a.lazard": "WR", "allen lazard": "WR",
    "slayton": "WR", "d.slayton": "WR", "darius slayton": "WR",
    "washington": "WR", "p.washington": "WR", "parker washington": "WR",
    "wester": "WR", "l.wester": "WR", "lajohntay wester": "WR",
    "mitchell": "WR", "a.mitchell": "WR",
    "coleman": "WR", "k.coleman": "WR",
    "garrett wilson": "WR", "g.wilson": "WR",
    "gabe davis": "WR", "g.davis": "WR",
    "bateman": "WR", "r.bateman": "WR", "mooney": "WR", "kirk": "WR", "pittman": "WR",

    # Specialists (K/P)
    "butker": "K", "h.butker": "K", "tucker": "K", "j.tucker": "K",
    "boswell": "K", "c.boswell": "K", "moody": "K", "j.moody": "K",
    "bass": "K", "t.bass": "K", "mcpherson": "K", "e.mcpherson": "K",
    "dicker": "K", "c.dicker": "K", "aubrey": "K", "b.aubrey": "K",
    "koo": "K", "folk": "K", "prater": "K", "fairbairn": "K", "gay": "K", "santoso": "K",
    "townsend": "P", "t.townsend": "P", "stonehouse": "P", "r.stonehouse": "P",
    "cole": "P", "a.cole": "P", "bojorquez": "P", "dixon": "P", "gillikin": "P", "fox": "P", "wishnowsky": "P",

    # Defensive players
    "parsons": "DEF", "m.parsons": "DEF", "watt": "DEF", "t.watt": "DEF",
    "bosa": "DEF", "n.bosa": "DEF", "j.bosa": "DEF",
    "garrett": "DEF", "m.garrett": "DEF", "crosby": "DEF", "m.crosby": "DEF",
    "hutchinson": "DEF", "a.hutchinson": "DEF", "surtain": "DEF", "p.surtain": "DEF",
    "gardner": "DEF", "s.gardner": "DEF", "hamilton": "DEF", "k.hamilton": "DEF",
    "warner": "DEF", "f.warner": "DEF", "hunter": "DEF", "sweat": "DEF",
    "chris jones": "DEF", "c.jones": "DEF", "donald": "DEF", "mack": "DEF", "queen": "DEF",
    "winfield": "DEF", "kerby": "DEF", "branch": "DEF", "bland": "DEF",
    "roquan": "DEF", "sneed": "DEF", "bowman": "DEF", "burns": "DEF", "thibodeaux": "DEF",
}


def get_player_position(player_name: str, plays: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """
    Resolve a player's official football position (QB, RB, WR, TE, K, P, DEF).
    Looks up in the canonical registry, matches play-by-play row position attributes,
    or falls back to action-based inference.
    """
    if not player_name:
        return None
    raw = str(player_name).strip()
    p_low = raw.lower()

    # 1. Exact match in canonical registry
    if p_low in KNOWN_PLAYER_POSITIONS:
        return KNOWN_PLAYER_POSITIONS[p_low]

    # Clean leading initials/periods (e.g. "J.Warren" -> "warren", "X. Worthy" -> "worthy")
    cleaned = re.sub(r"^[a-z]\.\s*", "", p_low)
    if cleaned in KNOWN_PLAYER_POSITIONS:
        return KNOWN_PLAYER_POSITIONS[cleaned]

    parts = p_low.replace(".", " ").split()
    if len(parts) > 1 and parts[-1] in KNOWN_PLAYER_POSITIONS:
        return KNOWN_PLAYER_POSITIONS[parts[-1]]

    # 2. Check play rows if plays are provided
    if plays:
        for p in plays:
            if raw == p.get("receiver_player_name") or p_low in str(p.get("receiver_player_name", "")).lower():
                pos = str(p.get("receiver_position") or p.get("position") or p.get("player_position") or "").strip().upper()
                if pos:
                    return pos
            if raw == p.get("rusher_player_name") or p_low in str(p.get("rusher_player_name", "")).lower():
                pos = str(p.get("rusher_position") or p.get("position") or p.get("player_position") or "").strip().upper()
                if pos:
                    return pos
            if raw == p.get("qb_name") or p_low in str(p.get("qb_name", "")).lower():
                return "QB"

        # 3. Usage-based heuristic from play volume
        rec_count = sum(1 for p in plays if raw == p.get("receiver_player_name"))
        rush_count = sum(1 for p in plays if raw == p.get("rusher_player_name"))
        pass_count = sum(1 for p in plays if raw == p.get("qb_name") or raw == p.get("passer_player_name"))
        if pass_count > 0:
            return "QB"
        if rush_count > rec_count:
            return "RB"
        if rec_count > 0:
            return "WR"

    return None

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

    # Special Teams Plays (2025)
    {"play_id": 116, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "", "receiver_player_name": "", "rusher_player_name": "", "kicker_player_name": "H.Butker", "player_name": "H.Butker",
     "play_type": "field_goal", "play_concept": "field_goal", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 51.0,
     "epa": 1.82, "wpa": 0.075, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 0,
     "down": 4, "ydstogo": 5, "yardline_100": 33, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 2,
     "desc": "(00:03 Q2) H.Butker 51 yard field goal is GOOD, Center-J.Winchester, Holder-M.Araiza."},
    {"play_id": 117, "season": 2025, "week": 1, "game_id": "2025_01_LA_DET", "posteam": "DET", "defteam": "LA", "conf": "NFC",
     "qb_name": "", "receiver_player_name": "", "rusher_player_name": "", "punter_player_name": "J.Fox", "player_name": "J.Fox",
     "play_type": "punt", "play_concept": "punt", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 62.0,
     "epa": 0.85, "wpa": 0.032, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 0,
     "down": 4, "ydstogo": 12, "yardline_100": 70, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 20, "qtr": 3,
     "desc": "(07:15 Q3) J.Fox punts 62 yards to LA 8, fair catch by K.Fair."},

    # Additional Defensive Highlights (2025)
    {"play_id": 118, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "L.Jackson", "receiver_player_name": "", "rusher_player_name": "", "player_name": "C.Jones",
     "play_type": "pass", "play_concept": "pass_short", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": -7.0,
     "epa": -1.72, "wpa": -0.065, "cpoe": -5.0, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 8, "yardline_100": 42, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 1,
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 4,
     "desc": "(01:50 Q4) L.Jackson sacked at BAL 49 for -7 yards (C.Jones)."},
    {"play_id": 119, "season": 2025, "week": 1, "game_id": "2025_01_ARI_BUF", "posteam": "ARI", "defteam": "BUF", "conf": "NFC",
     "qb_name": "K.Murray", "receiver_player_name": "", "rusher_player_name": "", "player_name": "G.Rousseau",
     "play_type": "pass", "play_concept": "pass_short", "play_direction": "right", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": -9.0,
     "epa": -2.15, "wpa": -0.088, "cpoe": -8.0, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 9, "yardline_100": 38, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 1,
     "team_win": 0, "home_score": 34, "away_score": 28, "qtr": 4,
     "desc": "(03:10 Q4) K.Murray sacked at ARI 29 for -9 yards (G.Rousseau), fumble RECOVERED by BUF-D.Williams."},
    # Overtime & Goal Line Run (2025 Week 1 LA @ DET)
    {"play_id": 120, "season": 2025, "week": 1, "game_id": "2025_01_LA_DET", "posteam": "DET", "defteam": "LA", "conf": "NFC",
     "qb_name": "J.Goff", "receiver_player_name": "", "rusher_player_name": "D.Montgomery", "player_name": "D.Montgomery",
     "play_type": "run", "play_concept": "rush_inside", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 1.0,
     "epa": 3.82, "wpa": 0.350, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 1, "ydstogo": 1, "yardline_100": 1, "series_success": 1, "touchdown": 1, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 26, "away_score": 20, "qtr": 5,
     "desc": "(05:24 OT) D.Montgomery up the middle for 1 yard, TOUCHDOWN (Game Winner in Overtime)."},
    # Quick Slant / Timing Pass (2025 Week 1 BAL @ KC)
    {"play_id": 121, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "T.Kelce", "rusher_player_name": "", "player_name": "T.Kelce",
     "play_type": "pass", "play_concept": "quick_slant", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 6.0, "yards_after_catch": 5.0, "xyac_mean_yardage": 4.0, "yards_gained": 11.0,
     "epa": 1.15, "wpa": 0.045, "cpoe": 7.5, "complete_pass": 1, "pass_attempt": 1, "rush_attempt": 0,
     "down": 2, "ydstogo": 4, "yardline_100": 45, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 2,
     "desc": "(04:30 Q2) P.Mahomes pass short middle to T.Kelce to BAL 34 for 11 yards (quick slant)."},
    # Inside Zone Run (2025 Week 1 BAL @ KC)
    {"play_id": 122, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "L.Jackson", "receiver_player_name": "", "rusher_player_name": "D.Henry", "player_name": "D.Henry",
     "play_type": "run", "play_concept": "rush_inside", "play_direction": "middle", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 13.0,
     "epa": 1.28, "wpa": 0.052, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 1,
     "down": 1, "ydstogo": 10, "yardline_100": 65, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 2,
     "desc": "(08:15 Q2) D.Henry up the middle to KC 52 for 13 yards (inside zone)."},
    # Penalty Plays (2025 Week 1 BAL @ KC)
    {"play_id": 123, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "P.Mahomes", "receiver_player_name": "", "rusher_player_name": "", "player_name": "J.Taylor",
     "play_type": "no_play", "play_concept": "penalty", "play_direction": "", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": -10.0,
     "epa": -1.25, "wpa": -0.045, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 0,
     "down": 1, "ydstogo": 10, "yardline_100": 50, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 0,
     "penalty": 1, "penalty_type": "Offensive Holding", "penalty_yards": 10.0, "penalty_team": "KC", "penalty_player_name": "J.Taylor",
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 2,
     "desc": "(10:12 Q2) PENALTY on KC-J.Taylor, Offensive Holding, 10 yards, enforced at KC 50 - No Play."},
    {"play_id": 124, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "L.Jackson", "receiver_player_name": "Z.Flowers", "rusher_player_name": "", "player_name": "M.Humphrey",
     "play_type": "pass", "play_concept": "pass_deep", "play_direction": "left", "is_screen": 0, "play_action": 0, "shotgun": 1,
     "air_yards": 25.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 25.0,
     "epa": 2.10, "wpa": 0.082, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 1, "rush_attempt": 0,
     "down": 3, "ydstogo": 7, "yardline_100": 60, "series_success": 1, "touchdown": 0, "interception": 0, "sack": 0,
     "penalty": 1, "penalty_type": "Defensive Pass Interference", "penalty_yards": 25.0, "penalty_team": "KC", "penalty_player_name": "T.McDuffie",
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 3,
     "desc": "(03:40 Q3) L.Jackson pass incomplete deep left to Z.Flowers. PENALTY on KC-T.McDuffie, Defensive Pass Interference, 25 yards, enforced at KC 35."},
    # Timeout Plays (2025 Week 1 BAL @ KC)
    {"play_id": 125, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "KC", "defteam": "BAL", "conf": "AFC",
     "qb_name": "", "receiver_player_name": "", "rusher_player_name": "", "player_name": "",
     "play_type": "no_play", "play_concept": "timeout", "play_direction": "", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 0.0,
     "epa": 0.0, "wpa": 0.0, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 0,
     "down": 4, "ydstogo": 1, "yardline_100": 34, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 0,
     "timeout": 1, "timeout_team": "KC", "timeout_coach": "Andy Reid",
     "posteam_timeouts_remaining": 2, "defteam_timeouts_remaining": 3,
     "team_win": 1, "home_score": 27, "away_score": 20, "qtr": 4,
     "desc": "(02:15 Q4) Timeout #1 by KC at 02:15."},
    {"play_id": 126, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC", "posteam": "BAL", "defteam": "KC", "conf": "AFC",
     "qb_name": "", "receiver_player_name": "", "rusher_player_name": "", "player_name": "",
     "play_type": "no_play", "play_concept": "timeout", "play_direction": "", "is_screen": 0, "play_action": 0, "shotgun": 0,
     "air_yards": 0.0, "yards_after_catch": 0.0, "xyac_mean_yardage": 0.0, "yards_gained": 0.0,
     "epa": 0.0, "wpa": 0.0, "cpoe": 0.0, "complete_pass": 0, "pass_attempt": 0, "rush_attempt": 0,
     "down": 3, "ydstogo": 10, "yardline_100": 65, "series_success": 0, "touchdown": 0, "interception": 0, "sack": 0,
     "timeout": 1, "timeout_team": "BAL", "timeout_coach": "John Harbaugh",
     "posteam_timeouts_remaining": 1, "defteam_timeouts_remaining": 2,
     "team_win": 0, "home_score": 27, "away_score": 20, "qtr": 4,
     "desc": "(01:10 Q4) Timeout #2 by BAL at 01:10."},

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


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float):
        return math.isnan(v) or math.isinf(v)
    if isinstance(v, str):
        s = v.strip().lower()
        return s in ("", "na", "nan", "null", "none", "<na>")
    return False


def _safe_float(v: Any, default: float = 0.0) -> float:
    if _is_missing(v):
        return default
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    if _is_missing(v):
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, str) and v.strip().lower() in ("true", "t", "yes"):
        return 1
    if isinstance(v, str) and v.strip().lower() in ("false", "f", "no"):
        return 0
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else int(round(f))
    except (ValueError, TypeError):
        return default


def _safe_str(v: Any, default: str = "") -> str:
    if _is_missing(v):
        return default
    return str(v).strip()


def _safe_opt_flag(v: Any) -> Optional[int]:
    if _is_missing(v):
        return None
    return 1 if _safe_int(v, 0) != 0 else 0


class NoSeasonDataError(ValueError):
    """Raised when the requested season has no loaded play-by-play rows (no silent cross-season fallback)."""


def available_seasons(plays: List[Dict[str, Any]]) -> List[int]:
    return sorted({_safe_int(p.get("season"), -1) for p in plays if _safe_int(p.get("season"), -1) > 0})


def plays_for_season(plays: List[Dict[str, Any]], season: int) -> List[Dict[str, Any]]:
    return [p for p in plays if _safe_int(p.get("season"), -1) == int(season)]


def require_season_plays(plays: List[Dict[str, Any]], season: int) -> List[Dict[str, Any]]:
    """Return plays for `season`, or raise a clear error listing the seasons that ARE available."""
    s_plays = plays_for_season(plays, season)
    if s_plays:
        return s_plays
    avail = available_seasons(plays)
    avail_str = ", ".join(map(str, avail)) if avail else "none"
    raise NoSeasonDataError(
        f"No play-by-play data loaded for the {season} season (available: {avail_str}). "
        f"Use --season YEAR (or `/season YEAR` in the interactive prompt), or install the live data "
        f"packages (`pip install nfl-stat-cli[live]`) to fetch {season}."
    )


def _downcast_dataframe_floats(df: Any) -> Any:
    """Downcast float64 columns to float32 to reduce memory consumption and speed up processing."""
    try:
        float_cols = df.select_dtypes(include=["float64"]).columns
        if len(float_cols) > 0:
            df[float_cols] = df[float_cols].astype("float32")
    except Exception:
        pass
    return df


class NFLDataBridge:
    """
    Loads NFL Play-by-Play and Roster/Team data from:
    1. nflreadpy / nfl_data_py / sportsdataverse-py (Python)
    2. nflverse R (`nflreadr::load_pbp`, `nflfastR`) via Rscript bridge
    3. Local cache / built-in sample dataset for instant offline operation
    """

    def __init__(self, cache_dir: Optional[Path] = None, engine: str = "auto") -> None:
        self.cache_dir = cache_dir or (Path.home() / ".nfl_stat_cli" / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine.lower()
        self.last_source_used = "built-in-nflverse-sample"
        self.last_error: Optional[str] = None

    def load_pbp(self, seasons: List[int], spinner: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Load play-by-play rows for the requested seasons using the selected engine."""
        seasons_label = ", ".join(map(str, seasons))
        if spinner:
            spinner.update(f"Loading NFL play-by-play data for years [{seasons_label}]...")

        if self.engine in ("auto", "python", "sdv"):
            rows = self._try_sportsdataverse_py(seasons, spinner=spinner)
            if rows:
                self.last_source_used = "nflreadpy / nfl_data_py (Python)"
                return rows

        if self.engine in ("auto", "r", "nflverse"):
            rows = self._try_nflverse_r(seasons, spinner=spinner)
            if rows:
                self.last_source_used = "nflverse / nflreadr (R)"
                return rows

        if spinner:
            spinner.update("Downcasting floats & preparing offline dataset...")

        self.last_source_used = "built-in nflverse/sdv offline dataset"
        norm_sample = [self._normalize_row(r, idx) for idx, r in enumerate(SAMPLE_PBP_PLAYS, 1)]
        # Never substitute another season's rows for the requested ones
        return [r for r in norm_sample if int(r.get("season", 0)) in seasons]

    def _try_sportsdataverse_py(self, seasons: List[int], spinner: Optional[Any] = None) -> Optional[List[Dict[str, Any]]]:
        errors: List[str] = []
        try:
            import nflreadpy as nfl  # type: ignore[import]
            if spinner:
                spinner.update(f"Fetching nflreadpy pbp for years [{', '.join(map(str, seasons))}]...")
            df = nfl.load_pbp(seasons=seasons).to_pandas()
            if spinner:
                spinner.update("Downcasting floats & optimizing dataframe memory...")
            df = _downcast_dataframe_floats(df)
            rows = self._normalize_dataframe(df)
            if rows:
                return rows
        except Exception as exc:
            errors.append(f"nflreadpy: {exc}")
        try:
            import nfl_data_py as nfl_data  # type: ignore[import]
            if spinner:
                spinner.update(f"Importing nfl_data_py for years [{', '.join(map(str, seasons))}]...")
            df = nfl_data.import_pbp_data(seasons, downcast=True)
            if spinner:
                spinner.update("Downcasting floats & optimizing dataframe memory...")
            df = _downcast_dataframe_floats(df)
            rows = self._normalize_dataframe(df)
            if rows:
                return rows
        except Exception as exc:
            errors.append(f"nfl_data_py: {exc}")
        try:
            import sportsdataverse.nfl as sdv_nfl  # type: ignore[import]
            if spinner:
                spinner.update(f"Loading sportsdataverse pbp for years [{', '.join(map(str, seasons))}]...")
            df = sdv_nfl.load_nfl_pbp(seasons=seasons, return_as_pandas=True)
            if spinner:
                spinner.update("Downcasting floats & optimizing dataframe memory...")
            df = _downcast_dataframe_floats(df)
            rows = self._normalize_dataframe(df)
            if rows:
                return rows
        except Exception as exc:
            errors.append(f"sportsdataverse: {exc}")
        if errors:
            self.last_error = "; ".join(errors)
        return None

    def _try_nflverse_r(self, seasons: List[int], spinner: Optional[Any] = None) -> Optional[List[Dict[str, Any]]]:
        rscript_bin = shutil.which("Rscript")
        if not rscript_bin:
            return None
        try:
            # Python 3.9+ resource lookup; retain the path fallback for Python 3.8.
            bridge_resource = resources.files(__package__).joinpath("nflverse_bridge.R")
        except (AttributeError, TypeError):  # Python 3.8 or direct module loading
            bridge_resource = Path(__file__).parent / "nflverse_bridge.R"
        bridge_script = bridge_resource
        out_csv = self.cache_dir / f"nflverse_pbp_{'_'.join(map(str, seasons))}.csv"
        seasons_arg = ",".join(map(str, seasons))
        try:
            # Reuse cached CSV if younger than 12 hours
            use_cached = False
            if out_csv.exists():
                age_sec = dt.datetime.now().timestamp() - out_csv.stat().st_mtime
                if age_sec < 43200 and out_csv.stat().st_size > 256:
                    use_cached = True
            if not use_cached:
                if bridge_script.is_file():
                    with (nullcontext(bridge_script) if isinstance(bridge_script, Path)
                          else resources.as_file(bridge_script)) as bridge_path:
                        cmd = [rscript_bin, str(bridge_path), "--seasons", seasons_arg, "--output", str(out_csv)]
                        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                else:
                    # Pass arguments via commandArgs(trailingOnly=TRUE) — never interpolate paths into R source
                    r_code = (
                        "args <- commandArgs(trailingOnly=TRUE); "
                        "seasons <- as.integer(unlist(strsplit(args[1], ','))); "
                        "out_csv <- args[2]; "
                        "suppressPackageStartupMessages(library(nflreadr)); "
                        "pbp <- load_pbp(seasons=seasons); "
                        "pbp <- pbp[!is.na(pbp$posteam) & ((!is.na(pbp$pass_attempt) & pbp$pass_attempt == 1) | (!is.na(pbp$rush_attempt) & pbp$rush_attempt == 1)), ]; "
                        "write.csv(pbp, file=out_csv, row.names=FALSE, na='')"
                    )
                    cmd = [rscript_bin, "-e", r_code, seasons_arg, str(out_csv)]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                if res.returncode != 0:
                    self.last_error = f"Rscript exit {res.returncode}: {res.stderr.strip()[:160]}"
                    return None
            if out_csv.exists():
                with open(out_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = [self._normalize_row(r, idx) for idx, r in enumerate(reader, 1) if not _is_missing(r.get("posteam"))]
                    if rows:
                        return rows
        except Exception as exc:
            self.last_error = f"Rscript error: {exc}"
            return None
        return None

    def _normalize_dataframe(self, df: Any) -> List[Dict[str, Any]]:
        df = _downcast_dataframe_floats(df)
        records = df.to_dict(orient="records")
        out: List[Dict[str, Any]] = []
        for idx, r in enumerate(records, 1):
            if _is_missing(r.get("posteam")):
                continue
            pa = _safe_int(r.get("pass_attempt"), 0)
            ra = _safe_int(r.get("rush_attempt"), 0)
            pt = _safe_str(r.get("play_type"), "").lower()
            pen = _safe_opt_flag(r.get("penalty")) or 0
            to = _safe_opt_flag(r.get("timeout")) or 0
            desc = _safe_str(r.get("desc"), "").lower()
            if pa == 0 and ra == 0 and pt not in ("pass", "run") and not pen and not to and "penalty" not in desc and "timeout" not in desc:
                continue
            out.append(self._normalize_row(r, idx))
        return out

    def _normalize_row(self, r: Dict[str, Any], idx: int = 1) -> Dict[str, Any]:
        posteam = _safe_str(r.get("posteam"), "")
        defteam = _safe_str(r.get("defteam"), "")
        conf = _safe_str(r.get("conf"), "") or ("AFC" if posteam in AFC_TEAMS else ("NFC" if posteam in NFC_TEAMS else "NFL"))
        division = _safe_str(r.get("division"), "") or TEAM_DIVISIONS.get(posteam, f"{conf} Division")
        air_yards = _safe_float(r.get("air_yards"), 0.0)
        desc = _safe_str(r.get("desc"), "")
        pass_attempt = _safe_int(r.get("pass_attempt"), 0)
        rush_attempt = _safe_int(r.get("rush_attempt"), 0)
        complete_pass = _safe_int(r.get("complete_pass"), 0)
        sack = _safe_int(r.get("sack"), 0)
        qb_scramble = _safe_int(r.get("qb_scramble"), 0)

        raw_screen = _safe_opt_flag(r.get("is_screen"))
        is_screen = raw_screen if raw_screen is not None else (
            1 if ("screen" in desc.lower() or (pass_attempt == 1 and sack == 0 and air_yards <= 0.0 and complete_pass == 1)) else 0
        )

        play_type = _safe_str(r.get("play_type"), "") or ("pass" if pass_attempt else "run")
        raw_pa = _safe_opt_flag(r.get("play_action"))
        play_action = raw_pa if raw_pa is not None else (
            1 if ("play-action" in desc.lower() or "play action" in desc.lower()) else 0
        )
        play_concept = _safe_str(r.get("play_concept"), "") or (
            "screen" if is_screen else (
                "play_action_deep" if (play_action or air_yards >= 18) and play_type == "pass" else (
                    "pass_intermediate" if air_yards >= 10 and play_type == "pass" else (
                        "pass_short" if play_type == "pass" else "rush_outside"
                    )
                )
            )
        )
        direction = _infer_play_direction(r, desc)
        yards_gained = _safe_float(r.get("yards_gained"), 0.0)
        ydstogo = _safe_int(r.get("ydstogo"), 10)
        touchdown = _safe_int(r.get("touchdown"), 0)
        pass_td = _safe_int(r.get("pass_touchdown"), touchdown if (pass_attempt == 1 and sack == 0) else 0)
        rush_td = _safe_int(r.get("rush_touchdown"), touchdown if rush_attempt == 1 else 0)
        yardline_100 = _safe_int(r.get("yardline_100"), 50)
        raw_fd = _safe_opt_flag(r.get("first_down"))
        first_down = raw_fd if raw_fd is not None else (1 if (yards_gained >= ydstogo or touchdown == 1) else 0)

        passer_name = _safe_str(r.get("passer_player_name"), "")
        rusher_name = _safe_str(r.get("rusher_player_name"), "")
        explicit_qb = _safe_str(r.get("qb_name"), "")
        if explicit_qb:
            qb_name = explicit_qb
        elif passer_name:
            qb_name = passer_name
        elif qb_scramble == 1 and rusher_name:
            qb_name = rusher_name
        else:
            qb_name = ""

        receiver_name = _safe_str(r.get("receiver_player_name"), "")
        kicker_name = _safe_str(r.get("kicker_player_name"), "")
        punter_name = _safe_str(r.get("punter_player_name"), "")
        if not rusher_name and rush_attempt and qb_name:
            rusher_name = qb_name
        explicit_player = _safe_str(r.get("player_name"), "")
        skill_player = explicit_player or receiver_name or rusher_name or qb_name or kicker_name or punter_name

        receiver_pos = _safe_str(r.get("receiver_position") or r.get("receiver_pos"), "")
        rusher_pos = _safe_str(r.get("rusher_position") or r.get("rusher_pos"), "")
        passer_pos = _safe_str(r.get("passer_position") or r.get("passer_pos"), "")
        explicit_pos = _safe_str(r.get("player_position") or r.get("position") or r.get("pos"), "")

        if receiver_name and not receiver_pos:
            receiver_pos = get_player_position(receiver_name) or ""
        if rusher_name and not rusher_pos:
            rusher_pos = get_player_position(rusher_name) or ""
        if qb_name and not passer_pos:
            passer_pos = "QB"
        if skill_player and not explicit_pos:
            explicit_pos = receiver_pos if (skill_player == receiver_name and receiver_pos) else (
                rusher_pos if (skill_player == rusher_name and rusher_pos) else (
                    passer_pos if (skill_player == qb_name and passer_pos) else (get_player_position(skill_player) or "")
                )
            )

        home_score = _safe_int(r.get("home_score"), 0)
        away_score = _safe_int(r.get("away_score"), 0)
        score_diff = _safe_float(r.get("score_differential"), float(abs(home_score - away_score)))

        # Derive team_win accurately from explicit flag, result + home_team/away_team, or final scores
        raw_tw = _safe_opt_flag(r.get("team_win"))
        if raw_tw is not None:
            team_win = raw_tw
        else:
            home_team = _safe_str(r.get("home_team"), "")
            away_team = _safe_str(r.get("away_team"), "")
            if not _is_missing(r.get("result")) and (home_team or away_team):
                res_val = _safe_float(r.get("result"), 0.0)
                if posteam == home_team:
                    team_win = 1 if res_val > 0 else 0
                elif posteam == away_team:
                    team_win = 1 if res_val < 0 else 0
                else:
                    team_win = 0
            elif home_team and away_team and (home_score != away_score):
                team_win = 1 if ((posteam == home_team and home_score > away_score) or (posteam == away_team and away_score > home_score)) else 0
            else:
                team_win = 0

        epa_val = _safe_float(r.get("epa"), 0.0)
        raw_ss = _safe_opt_flag(r.get("success"))
        if raw_ss is None:
            raw_ss = _safe_opt_flag(r.get("series_success"))
        series_success = raw_ss if raw_ss is not None else (1 if epa_val > 0.0 else 0)

        # Penalty attributes
        raw_pen = _safe_opt_flag(r.get("penalty"))
        penalty = raw_pen if raw_pen is not None else (
            1 if any(k in desc.lower() for k in ("penalty", "penalized", "holding", "false start", "pass interference", "roughing the passer", "unnecessary roughness", "face mask")) else 0
        )
        penalty_type = _safe_str(r.get("penalty_type"), "")
        if not penalty_type and penalty:
            d_low = desc.lower()
            if "holding" in d_low:
                penalty_type = "Offensive Holding" if "offensive holding" in d_low else "Defensive Holding"
            elif "false start" in d_low:
                penalty_type = "False Start"
            elif "pass interference" in d_low:
                penalty_type = "Defensive Pass Interference" if "defensive pass interference" in d_low else "Offensive Pass Interference"
            elif "roughing the passer" in d_low:
                penalty_type = "Roughing the Passer"
            elif "unnecessary roughness" in d_low:
                penalty_type = "Unnecessary Roughness"
            elif "neutral zone" in d_low:
                penalty_type = "Neutral Zone Infraction"
            elif "offside" in d_low:
                penalty_type = "Offside"
            elif "delay of game" in d_low:
                penalty_type = "Delay of Game"
            else:
                penalty_type = "Penalty"

        penalty_yards = _safe_float(r.get("penalty_yards"), 0.0)
        if penalty and penalty_yards == 0.0:
            m_yds = re.search(r"(\d+)\s+yards?", desc, re.IGNORECASE)
            if m_yds and ("penalty" in desc.lower() or "holding" in desc.lower() or "interference" in desc.lower()):
                penalty_yards = float(m_yds.group(1))

        penalty_team = _safe_str(r.get("penalty_team"), "")
        if not penalty_team and penalty:
            m_pteam = re.search(r"\bpenalty\s+on\s+([A-Za-z]+)\b", desc, re.IGNORECASE)
            if m_pteam:
                penalty_team = resolve_team_abbr(m_pteam.group(1)) or m_pteam.group(1).upper()
            else:
                penalty_team = posteam if penalty else ""
        penalty_player_name = _safe_str(r.get("penalty_player_name"), "")
        if not penalty_player_name and penalty:
            m_pplayer = re.search(r"\bpenalty\s+on\s+[A-Za-z]+-(?:\d+-)?([A-Za-z\.\'\-]+(?:\s+[A-Za-z\.\'\-]+)?)\b", desc, re.IGNORECASE)
            if m_pplayer:
                penalty_player_name = m_pplayer.group(1).strip()

        # Coaching attributes
        season_val = _safe_int(r.get("season"), 2025)
        home_team = _safe_str(r.get("home_team"), "") or posteam
        away_team = _safe_str(r.get("away_team"), "") or defteam
        home_coach = _safe_str(r.get("home_coach"), "") or get_team_head_coach(home_team, season=season_val)
        away_coach = _safe_str(r.get("away_coach"), "") or get_team_head_coach(away_team, season=season_val)
        coach = home_coach if posteam == home_team else away_coach
        staff = get_team_coaching_staff(posteam, season=season_val)
        oc = str(staff.get("oc", ""))
        def_staff = get_team_coaching_staff(defteam, season=season_val)
        dc = str(def_staff.get("dc", ""))

        # Beneficiary / Favored team for penalty
        penalty_favored_team = ""
        if penalty and penalty_team:
            if penalty_team == posteam:
                penalty_favored_team = defteam
            elif penalty_team == defteam:
                penalty_favored_team = posteam
            elif penalty_team == home_team:
                penalty_favored_team = away_team
            elif penalty_team == away_team:
                penalty_favored_team = home_team
            else:
                penalty_favored_team = defteam if posteam == penalty_team else posteam

        penalty_coach = get_team_head_coach(penalty_team, season=season_val) if penalty_team else coach
        penalty_favored_coach = get_team_head_coach(penalty_favored_team, season=season_val) if penalty_favored_team else ""

        # Timeout attributes
        raw_to = _safe_opt_flag(r.get("timeout"))
        timeout = raw_to if raw_to is not None else (
            1 if (re.search(r"\btimeout\b", desc, re.IGNORECASE) and not re.search(r"\binjury\s+timeout\b", desc, re.IGNORECASE)) else 0
        )
        timeout_team = _safe_str(r.get("timeout_team"), "")
        if timeout and not timeout_team:
            m_to = re.search(r"\btimeout\s+(?:#\d+\s+)?(?:by|of)\s+([A-Za-z]+)\b", desc, re.IGNORECASE)
            if m_to:
                timeout_team = resolve_team_abbr(m_to.group(1)) or m_to.group(1).upper()
            else:
                timeout_team = posteam
        timeout_coach = get_team_head_coach(timeout_team, season=season_val) if timeout_team else coach
        posteam_timeouts_rem = _safe_int(r.get("posteam_timeouts_remaining"), 3)
        defteam_timeouts_rem = _safe_int(r.get("defteam_timeouts_remaining"), 3)

        return {
            "play_id": _safe_int(r.get("play_id"), idx),
            "season": season_val,
            "week": _safe_int(r.get("week"), 1),
            "game_id": _safe_str(r.get("game_id"), "2025_01_UNK"),
            "posteam": posteam,
            "defteam": defteam,
            "conf": conf,
            "division": division,
            "qb_name": qb_name,
            "receiver_player_name": receiver_name,
            "rusher_player_name": rusher_name,
            "kicker_player_name": kicker_name,
            "punter_player_name": punter_name,
            "player_name": skill_player,
            "receiver_position": receiver_pos,
            "rusher_position": rusher_pos,
            "passer_position": passer_pos,
            "player_position": explicit_pos,
            "position": explicit_pos,
            "coach": coach,
            "head_coach": coach,
            "oc": oc,
            "dc": dc,
            "home_coach": home_coach,
            "away_coach": away_coach,
            "penalty": penalty,
            "penalty_type": penalty_type,
            "penalty_yards": penalty_yards,
            "penalty_team": penalty_team,
            "penalty_player_name": penalty_player_name,
            "penalty_favored_team": penalty_favored_team,
            "penalty_coach": penalty_coach,
            "penalty_favored_coach": penalty_favored_coach,
            "timeout": timeout,
            "timeout_team": timeout_team,
            "timeout_coach": timeout_coach,
            "posteam_timeouts_remaining": posteam_timeouts_rem,
            "defteam_timeouts_remaining": defteam_timeouts_rem,
            "play_type": play_type,
            "play_concept": play_concept,
            "play_direction": direction,
            "is_screen": is_screen,
            "play_action": play_action,
            "shotgun": _safe_int(r.get("shotgun"), 0),
            "no_huddle": _safe_int(r.get("no_huddle"), 0),
            "red_zone": 1 if yardline_100 <= 20 else 0,
            "air_yards": air_yards,
            "yards_after_catch": _safe_float(r.get("yards_after_catch"), 0.0),
            "xyac_mean_yardage": _safe_float(r.get("xyac_mean_yardage"), 0.0),
            "yards_gained": yards_gained,
            "epa": epa_val,
            "wpa": _safe_float(r.get("wpa"), 0.0),
            "cpoe": _safe_float(r.get("cpoe"), 0.0),
            "complete_pass": complete_pass,
            "pass_attempt": pass_attempt,
            "rush_attempt": rush_attempt,
            "down": _safe_int(r.get("down"), 1),
            "ydstogo": ydstogo,
            "yardline_100": yardline_100,
            "series_success": series_success,
            "first_down": first_down,
            "explosive_play": 1 if yards_gained >= 20.0 else 0,
            "touchdown": touchdown,
            "pass_touchdown": pass_td,
            "rush_touchdown": rush_td,
            "interception": _safe_int(r.get("interception"), 0),
            "fumble_lost": _safe_int(r.get("fumble_lost"), 0),
            "sack": sack,
            "team_win": team_win,
            "home_score": home_score,
            "away_score": away_score,
            "score_differential": score_diff,
            "qtr": _safe_int(r.get("qtr"), 1),
            "desc": desc,
        }


# ---------------------------------------------------------------------------
# Safe Formula & Filter Evaluator (Supports Numbers, Strings, Booleans, AST)
# ---------------------------------------------------------------------------

def _safe_pow(a: Any, b: Any) -> float:
    fa, fb = float(a), float(b)
    if abs(fb) > 100.0:
        raise ValueError(f"Exponent {fb} exceeds maximum allowed magnitude (100)")
    res = math.pow(fa, fb)
    if not math.isfinite(res):
        return 0.0
    return res


def _safe_arith(op_fn: Callable[[float, float], float]) -> Callable[[Any, Any], float]:
    def _wrapped(a: Any, b: Any) -> float:
        if isinstance(a, str) or isinstance(b, str):
            raise ValueError("String operands are not permitted in arithmetic operations")
        res = op_fn(float(a), float(b))
        return res if math.isfinite(res) else 0.0
    return _wrapped


DIV_ZERO_WARNING = (
    "[!] Warning: Division by zero encountered (returned 0.0). "
    "Recommended: Use 'nz(denominator, default)' or 'ifelse(denominator > 0, num / denom, 0.0)'."
)

# Counts zero-denominator divisions since the last reset, so renderers can surface one warning per evaluation
_div_zero_events: Dict[str, int] = {"count": 0}


def reset_div_zero_events() -> None:
    _div_zero_events["count"] = 0


def div_zero_event_count() -> int:
    return _div_zero_events["count"]


def _safe_div(a: float, b: float) -> float:
    if b == 0.0:
        _div_zero_events["count"] += 1
        return 0.0
    return a / b


def unguarded_division_warning(formula: str) -> Optional[str]:
    """Return a note when a formula divides without an nz()/ifelse() guard (a zero denominator yields 0.0)."""
    if "/" not in formula or re.search(r"\b(?:nz|ifelse)\s*\(", formula):
        return None
    return (
        "Note: un-guarded division may yield 0.0 on zero denominators; "
        "consider nz(denom, 0.0) or ifelse(denom > 0, num / denom, 0.0)."
    )


ALLOWED_AST_OPS: Dict[Any, Callable[..., Any]] = {
    ast.Add: _safe_arith(operator.add),
    ast.Sub: _safe_arith(operator.sub),
    ast.Mult: _safe_arith(operator.mul),
    ast.Div: _safe_arith(_safe_div),
    ast.Mod: _safe_arith(lambda a, b: (a % b) if b != 0.0 else 0.0),
    ast.Pow: _safe_pow,
    ast.USub: lambda a: -float(a),
    ast.UAdd: lambda a: +float(a),
    ast.BitAnd: lambda a, b: 1.0 if (bool(a) and bool(b)) else 0.0,
    ast.BitOr: lambda a, b: 1.0 if (bool(a) or bool(b)) else 0.0,
}

ALLOWED_FUNCS: Dict[str, Callable[..., Any]] = {
    "min": lambda *args: float(min(float(x) for x in args)),
    "max": lambda *args: float(max(float(x) for x in args)),
    "abs": lambda x: abs(float(x)),
    "round": lambda x, n=0: float(round(float(x), int(n))),
    "sqrt": lambda x: math.sqrt(max(0.0, float(x))),
    "log": lambda x: math.log(max(1e-9, float(x))),
    "pow": _safe_pow,
    "clamp": lambda x, lo, hi: max(float(lo), min(float(hi), float(x))),
    "ifelse": lambda cond, t_val, f_val: t_val if bool(cond) else f_val,
    "nz": lambda x, default=0.0:float(x) if (not _is_missing(x) and float(x) != 0.0) else float(default),
}

MAX_FORMULA_LENGTH = 500
MAX_AST_NODES = 120


@functools.lru_cache(maxsize=512)
def _parse_and_validate_expr(expr: str) -> ast.Expression:
    cleaned = expr.strip()
    if len(cleaned) > MAX_FORMULA_LENGTH:
        raise ValueError(f"Formula exceeds maximum length of {MAX_FORMULA_LENGTH} characters")
    tree = ast.parse(cleaned, mode="eval")
    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_AST_NODES:
        raise ValueError(f"Formula exceeds maximum AST complexity ({node_count} > {MAX_AST_NODES} nodes)")
    return tree


def safe_eval_expr(expr: str, context: Dict[str, Any]) -> Any:
    """Safely evaluate a mathematical or boolean filter/stat expression using Python's AST."""
    tree = _parse_and_validate_expr(expr)

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
            if node.keywords:
                raise ValueError(f"Keyword arguments are not supported in function '{fname}()'")
            if fname == "ifelse":
                if len(node.args) != 3:
                    raise ValueError("ifelse(condition, true_val, false_val) requires exactly 3 arguments")
                return _eval(node.args[1]) if bool(_eval(node.args[0])) else _eval(node.args[2])
            if fname in ALLOWED_FUNCS:
                args = [_eval(a) for a in node.args]
                return ALLOWED_FUNCS[fname](*args)
        raise ValueError(f"Unsupported syntax in formula: {ast.dump(node)}")

    return _eval(tree)


def safe_eval_formula(expr: str, context: Dict[str, Any]) -> float:
    """Evaluate a formula and return a finite float value."""
    val = float(safe_eval_expr(expr, context))
    return val if math.isfinite(val) else 0.0


def extract_formula_dependencies(expr: str) -> List[str]:
    """Extract all variable identifiers referenced by a custom stat formula."""
    if not expr or not expr.strip():
        return []
    try:
        tree = _parse_and_validate_expr(expr)
    except Exception:
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
    # Traditional stats (built-in baseline and advanced NFL rate/volume metrics)
    "yards_per_play": StatDefinition(
        name="yards_per_play",
        title="Yards Per Play (YPP)",
        category="traditional",
        group_by="play_concept",
        filter_expr="pass_attempt == 1 or rush_attempt == 1",
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
    "completion_pct": StatDefinition(
        name="completion_pct",
        title="Completion Percentage (Comp %)",
        category="traditional",
        group_by="qb",
        formula="(completions / nz(pass_attempts, 1)) * 100.0",
        description="Percentage of pass attempts completed.",
        calculation_explained="Completions divided by official pass attempts (excluding sacks) multiplied by 100.",
        unit="%",
        dependencies=["completions", "pass_attempts"],
    ),
    "yards_per_attempt": StatDefinition(
        name="yards_per_attempt",
        title="Yards Per Pass Attempt (Y/A)",
        category="traditional",
        group_by="qb",
        formula="passing_yards / nz(pass_attempts, 1)",
        description="Average passing yards gained per dropback pass attempt.",
        calculation_explained="Passing yards gained divided by official pass attempts.",
        unit="yds/att",
        dependencies=["passing_yards", "pass_attempts"],
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
    "yards_per_rush": StatDefinition(
        name="yards_per_rush",
        title="Yards Per Rush Attempt (YPC)",
        category="traditional",
        group_by="rusher",
        formula="rushing_yards / nz(rush_attempts, 1)",
        description="Average rushing yards gained per designed run attempt.",
        calculation_explained="Rushing yards divided by rushing attempts.",
        unit="yds/rush",
        dependencies=["rushing_yards", "rush_attempts"],
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
    "first_down_rate": StatDefinition(
        name="first_down_rate",
        title="First Down Conversion Rate (%)",
        category="traditional",
        group_by="team",
        formula="(first_downs / plays) * 100.0",
        description="Percentage of offensive plays that result in a first down or touchdown.",
        calculation_explained="Counts plays earning first downs divided by total plays multiplied by 100.",
        unit="%",
        dependencies=["first_downs", "plays"],
    ),
    "touchdown_rate": StatDefinition(
        name="touchdown_rate",
        title="Touchdown Rate (%)",
        category="traditional",
        group_by="team",
        formula="(touchdowns / plays) * 100.0",
        description="Percentage of offensive plays resulting in a touchdown.",
        calculation_explained="Touchdowns scored divided by total offensive snaps multiplied by 100.",
        unit="%",
        dependencies=["touchdowns", "plays"],
    ),
    "interception_rate": StatDefinition(
        name="interception_rate",
        title="Interception Rate (INT %)",
        category="traditional",
        group_by="qb",
        formula="(interceptions / nz(pass_attempts, 1)) * 100.0",
        description="Percentage of pass attempts intercepted by the defense.",
        calculation_explained="Interceptions thrown divided by total pass attempts multiplied by 100.",
        unit="%",
        dependencies=["interceptions", "pass_attempts"],
    ),
    "sack_rate": StatDefinition(
        name="sack_rate",
        title="Sack Rate (%)",
        category="traditional",
        group_by="qb",
        formula="(sacks / nz(pass_attempts + sacks, 1)) * 100.0",
        description="Percentage of pass dropbacks resulting in a quarterback sack.",
        calculation_explained="Sacks divided by total dropbacks (pass attempts + sacks) multiplied by 100.",
        unit="%",
        dependencies=["sacks", "pass_attempts"],
    ),
    "turnover_rate": StatDefinition(
        name="turnover_rate",
        title="Turnover Rate (%)",
        category="traditional",
        group_by="team",
        formula="(turnovers / plays) * 100.0",
        description="Percentage of offensive plays that end in a turnover (interception or lost fumble).",
        calculation_explained="Turnovers (interceptions + fumbles lost) divided by total snaps multiplied by 100.",
        unit="%",
        dependencies=["turnovers", "plays"],
    ),
    "turnovers": StatDefinition(
        name="turnovers",
        title="Turnovers (Takeaways / Giveaways)",
        category="traditional",
        group_by="team",
        formula="turnovers",
        description="Total turnovers (interceptions + lost fumbles). Reflects takeaways when grouped by defense, and giveaways when grouped by offense/team.",
        calculation_explained="Sum of interceptions and lost fumbles.",
        unit="TO",
        dependencies=["turnovers"],
    ),
    "takeaways": StatDefinition(
        name="takeaways",
        title="Takeaways (Turnovers Forced)",
        category="traditional",
        group_by="defteam",
        formula="turnovers",
        description="Total turnovers forced by defense (interceptions + opposing fumbles recovered).",
        calculation_explained="Sum of defensive takeaways: interceptions + fumbles lost by opposing offense.",
        unit="TO",
        dependencies=["turnovers"],
    ),
    "fantasy_points": StatDefinition(
        name="fantasy_points",
        title="Fantasy Points (Standard)",
        category="traditional",
        group_by="player",
        formula="fantasy_points",
        description="NFL Standard (0 PPR) fantasy points: 0.04/pass yd, 4/pass TD, -2/INT, 0.1/rush yd, 6/rush TD, -2/lost fumble.",
        calculation_explained="Standard non-PPR scoring applied to player passing, rushing, receiving, and turnovers.",
        unit="pts",
        dependencies=["fantasy_points"],
    ),
    "fantasy_points_ppr": StatDefinition(
        name="fantasy_points_ppr",
        title="Fantasy Points (PPR)",
        category="traditional",
        group_by="player",
        formula="fantasy_points_ppr",
        description="Point-Per-Reception (PPR) fantasy points (Standard + 1.0 point per reception).",
        calculation_explained="Standard scoring + 1.0 pt per catch (PPR).",
        unit="pts",
        dependencies=["fantasy_points_ppr"],
    ),
    "fantasy_points_half_ppr": StatDefinition(
        name="fantasy_points_half_ppr",
        title="Fantasy Points (Half-PPR)",
        category="traditional",
        group_by="player",
        formula="fantasy_points_half_ppr",
        description="Half-PPR fantasy points (Standard + 0.5 points per reception).",
        calculation_explained="Standard scoring + 0.5 pts per catch (Half-PPR).",
        unit="pts",
        dependencies=["fantasy_points_half_ppr"],
    ),
    "fantasy_ppg": StatDefinition(
        name="fantasy_ppg",
        title="Fantasy PPG (PPR)",
        category="traditional",
        group_by="player",
        formula="fantasy_ppg_ppr",
        description="Average Fantasy Points Per Game in PPR format.",
        calculation_explained="PPR fantasy points divided by games played.",
        unit="ppg",
        dependencies=["fantasy_ppg_ppr"],
    ),
    "clean_play_score": StatDefinition(
        name="clean_play_score",
        title="Clean Play Score",
        category="traditional",
        group_by="play_concept",
        filter_expr="pass_attempt == 1 or rush_attempt == 1",
        formula="yards_per_play + (touchdowns / plays) * 6.0 - (turnovers / plays) * 40.0 - (penalties / plays) * 15.0",
        description="Yards plus scoring per snap, discounted for turnovers and penalties that occur on those snaps; rewards the most productive plays that stay clean.",
        calculation_explained="yards per play + 6 x touchdown rate - 40 x turnover rate - 15 x penalty rate, over scrimmage pass/rush snaps.",
        unit="pts",
        dependencies=["yards_per_play", "touchdowns", "turnovers", "penalties", "plays"],
    ),
    "plays": StatDefinition(
        name="plays",
        title="Total Plays",
        category="traditional",
        group_by="team",
        formula="plays",
        description="Total offensive snaps or matching plays.",
        calculation_explained="Count of plays across matching criteria.",
        unit="plays",
        dependencies=["plays"],
    ),
    "pass_attempts": StatDefinition(
        name="pass_attempts",
        title="Pass Attempts",
        category="traditional",
        group_by="qb",
        formula="pass_attempts",
        description="Total pass attempts thrown (excluding sacks).",
        calculation_explained="Sum of pass attempts across matching plays.",
        unit="att",
        dependencies=["pass_attempts"],
    ),
    "yards_after_catch": StatDefinition(
        name="yards_after_catch",
        title="Yards After Catch (YAC)",
        category="traditional",
        group_by="receiver",
        formula="total_yac",
        description="Total yards gained by receivers after catching the ball across all completed pass plays.",
        calculation_explained="Sum of yards_after_catch across all completed pass plays (complete_pass == 1).",
        unit="yds",
        filter_expr="complete_pass == 1",
        dependencies=["total_yac"],
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
    "passing_yards": StatDefinition(
        name="passing_yards",
        title="Passing Yards (Pass Yds)",
        category="traditional",
        group_by="qb",
        formula="passing_yards",
        description="Total passing yards gained on completed and intercepted pass attempts.",
        calculation_explained="Sum of yards gained on dropbacks (excluding sacks).",
        unit="yds",
        dependencies=["passing_yards"],
    ),
    "rushing_yards": StatDefinition(
        name="rushing_yards",
        title="Rushing Yards (Rush Yds)",
        category="traditional",
        group_by="rusher",
        formula="rushing_yards",
        description="Total rushing yards gained on designed runs and scrambles.",
        calculation_explained="Sum of yards gained on official rush attempts.",
        unit="yds",
        dependencies=["rushing_yards"],
    ),
    "touchdowns": StatDefinition(
        name="touchdowns",
        title="Total Touchdowns (TD)",
        category="traditional",
        group_by="player",
        formula="touchdowns",
        description="Total offensive touchdowns scored (passing, rushing, and receiving).",
        calculation_explained="Sum of all touchdowns scored across matching plays.",
        unit="TD",
        dependencies=["touchdowns"],
    ),
    "pass_touchdowns": StatDefinition(
        name="pass_touchdowns",
        title="Passing Touchdowns (Pass TD)",
        category="traditional",
        group_by="qb",
        formula="pass_touchdowns",
        description="Touchdown passes thrown by the quarterback.",
        calculation_explained="Total touchdowns thrown on completed pass attempts.",
        unit="TD",
        dependencies=["pass_touchdowns"],
    ),
    "rush_touchdowns": StatDefinition(
        name="rush_touchdowns",
        title="Rushing Touchdowns (Rush TD)",
        category="traditional",
        group_by="rusher",
        formula="rush_touchdowns",
        description="Rushing touchdowns scored on running attempts.",
        calculation_explained="Total touchdowns scored on designed runs or scrambles.",
        unit="TD",
        dependencies=["rush_touchdowns"],
    ),
    "interceptions": StatDefinition(
        name="interceptions",
        title="Interceptions Thrown (INT)",
        category="traditional",
        group_by="qb",
        formula="interceptions",
        description="Total interceptions thrown by the passer.",
        calculation_explained="Sum of intercepted pass attempts.",
        unit="INT",
        dependencies=["interceptions"],
    ),
    "sacks": StatDefinition(
        name="sacks",
        title="Quarterback Sacks (Sacks)",
        category="traditional",
        group_by="qb",
        formula="sacks",
        description="Total sacks taken behind line of scrimmage.",
        calculation_explained="Sum of quarterback sacks on dropbacks.",
        unit="sacks",
        dependencies=["sacks"],
    ),
    "completions": StatDefinition(
        name="completions",
        title="Pass Completions (Comp)",
        category="traditional",
        group_by="qb",
        formula="completions",
        description="Total successful pass completions.",
        calculation_explained="Sum of completed pass attempts.",
        unit="comp",
        dependencies=["completions"],
    ),
    "first_downs": StatDefinition(
        name="first_downs",
        title="First Downs (1st Downs)",
        category="traditional",
        group_by="team",
        formula="first_downs",
        description="Total first downs gained on offense.",
        calculation_explained="Total plays achieving a first down or touchdown.",
        unit="1st",
        dependencies=["first_downs"],
    ),
    "penalties": StatDefinition(
        name="penalties",
        title="Total Penalties (Pen)",
        category="traditional",
        group_by="team",
        formula="penalties",
        description="Total penalties committed and accepted.",
        calculation_explained="Sum of plays where a penalty occurred against the team or player (penalty == 1).",
        unit="pen",
        dependencies=["penalties"],
    ),
    "penalty_yards": StatDefinition(
        name="penalty_yards",
        title="Penalty Yards (Pen Yds)",
        category="traditional",
        group_by="team",
        formula="penalty_yards",
        description="Total penalty yards assessed against the team or player.",
        calculation_explained="Sum of penalty_yards across matching plays.",
        unit="yds",
        dependencies=["penalty_yards"],
    ),
    "penalties_drawn": StatDefinition(
        name="penalties_drawn",
        title="Penalties in Favor / Drawn (Pen Drawn)",
        category="traditional",
        group_by="team",
        formula="penalties_drawn",
        description="Total penalties called against opponents that benefited this team (penalties in their favor).",
        calculation_explained="Sum of plays where an accepted penalty was called on the opponent in favor of this team.",
        unit="pen",
        dependencies=["penalties_drawn"],
    ),
    "penalty_yards_drawn": StatDefinition(
        name="penalty_yards_drawn",
        title="Penalty Yards in Favor / Drawn (Pen Yds Drawn)",
        category="traditional",
        group_by="team",
        formula="penalty_yards_drawn",
        description="Total penalty yards awarded to this team from opponent infractions (penalty yards in their favor).",
        calculation_explained="Sum of penalty yards assessed against the opponent on accepted penalties.",
        unit="yds",
        dependencies=["penalty_yards_drawn"],
    ),
    "net_penalties": StatDefinition(
        name="net_penalties",
        title="Net Penalty Differential (Net Pen)",
        category="traditional",
        group_by="team",
        formula="penalties_drawn - penalties",
        description="Net penalty differential (penalties in team's favor minus penalties committed).",
        calculation_explained="Penalties drawn in team's favor minus penalties committed by the team.",
        unit="pen",
        dependencies=["penalties_drawn", "penalties"],
    ),
    "net_penalty_yards": StatDefinition(
        name="net_penalty_yards",
        title="Net Penalty Yards Differential (Net Pen Yds)",
        category="traditional",
        group_by="team",
        formula="penalty_yards_drawn - penalty_yards",
        description="Net penalty yards differential (penalty yards in team's favor minus penalty yards assessed).",
        calculation_explained="Penalty yards drawn in team's favor minus penalty yards assessed against team.",
        unit="yds",
        dependencies=["penalty_yards_drawn", "penalty_yards"],
    ),
    "timeouts": StatDefinition(
        name="timeouts",
        title="Timeouts Used (TO Used)",
        category="traditional",
        group_by="coach",
        formula="timeouts",
        description="Total timeouts called / used by the head coach or team.",
        calculation_explained="Sum of timeout events charged to the coach or team (timeout == 1).",
        unit="TO",
        dependencies=["timeouts"],
    ),
}

# Example / Showcase Custom Stats (demonstrating how custom stats work without polluting a fresh install)
EXAMPLE_CUSTOM_STATS: Dict[str, StatDefinition] = {
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
    "explosive_pass_rate": StatDefinition(
        name="explosive_pass_rate",
        title="Explosive Pass Rate (%)",
        category="custom",
        group_by="team",
        formula="(explosive_plays / nz(pass_attempts, 1)) * 100.0",
        description="Percentage of pass attempts that gain 20 or more yards.",
        calculation_explained="Explosive pass plays (>= 20 yards) divided by total pass attempts multiplied by 100.",
        unit="%",
        filter_expr="pass_attempt == 1",
        scope="season",
        agg="formula",
        dependencies=["explosive_plays", "pass_attempts"],
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
    "coach": "coach",
    "head_coach": "head_coach",
    "oc": "oc",
    "dc": "dc",
    "penalty_type": "penalty_type",
    "penalty_team": "penalty_team",
    "penalty_favored_team": "penalty_favored_team",
    "timeout_team": "timeout_team",
    "timeout_coach": "timeout_coach",
    "play_concept": "play_concept",
    "play_type": "play_type",
    "conference": "conf",
    "division": "division",
    "down": "down",
    "qtr": "qtr",
    "game": "game_id",
}


BASE_METRIC_KEYS: Set[str] = {
    "plays", "games_played", "games_won", "games_lost", "team_win", "win_rate",
    "total_yards", "yards_per_play", "passing_yards", "yards_per_attempt",
    "yards_per_completion", "rushing_yards", "yards_per_rush", "total_air_yards",
    "air_yards_per_play", "air_yards_per_attempt", "total_yac", "yac_per_play",
    "yac_per_completion", "total_xyac", "xyac_per_completion", "completions",
    "incompletions", "completion_pct", "pass_attempts", "rush_attempts",
    "screen_plays", "play_action_plays", "total_epa", "epa_per_play",
    "pass_epa_per_play", "rush_epa_per_play", "total_wpa", "wpa_per_play",
    "wpa_per_game", "avg_cpoe", "touchdowns", "pass_touchdowns", "rush_touchdowns",
    "interceptions", "fumbles_lost", "turnovers", "sacks", "sack_yards_estimated",
    "first_downs", "first_down_rate", "explosive_plays", "explosive_play_rate",
    "turnover_rate", "sack_rate", "td_rate", "int_rate", "success_rate",
    "nfl_passer_rating", "penalties", "penalty_yards", "penalty_rate",
    "penalties_per_game", "penalty_yards_per_game",
    "penalties_drawn", "penalty_yards_drawn", "net_penalties", "net_penalty_yards",
    "timeouts", "timeouts_used", "timeouts_called",
    "fantasy_points", "fantasy_points_std", "fantasy_points_ppr", "fantasy_points_half_ppr",
    "fantasy_ppg", "fantasy_ppg_ppr", "fantasy_ppg_std",
}

PLAY_ROW_KEYS: Set[str] = {
    "play_id", "season", "week", "game_id", "posteam", "defteam", "conf", "division",
    "qb_name", "receiver_player_name", "rusher_player_name", "player_name",
    "coach", "head_coach", "oc", "dc", "home_coach", "away_coach",
    "penalty", "penalty_type", "penalty_yards", "penalty_team", "penalty_player_name",
    "penalty_favored_team", "penalty_coach", "penalty_favored_coach",
    "timeout", "timeout_team", "timeout_coach",
    "posteam_timeouts_remaining", "defteam_timeouts_remaining",
    "play_type", "play_concept", "play_direction", "is_screen", "play_action",
    "shotgun", "no_huddle", "red_zone", "air_yards", "yards_after_catch",
    "xyac_mean_yardage", "yards_gained", "epa", "wpa", "cpoe", "complete_pass",
    "pass_attempt", "rush_attempt", "down", "ydstogo", "yardline_100",
    "series_success", "first_down", "explosive_play", "touchdown",
    "pass_touchdown", "rush_touchdown", "interception", "fumble_lost", "sack",
    "team_win", "home_score", "away_score", "score_differential", "qtr", "desc",
}


def _atomic_write_json(target: Path, payload: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def calculate_passer_rating(
    attempts: int,
    completions: int,
    passing_yards: float,
    touchdowns: int,
    interceptions: int,
) -> float:
    """Calculate official NFL passer rating bounded to [0.0, 158.3]."""
    if attempts <= 0:
        return 0.0
    att_nz = float(attempts)
    pr_a = max(0.0, min(2.375, ((float(completions) / att_nz) - 0.3) * 5.0))
    pr_b = max(0.0, min(2.375, ((float(passing_yards) / att_nz) - 3.0) * 0.25))
    pr_c = max(0.0, min(2.375, (float(touchdowns) / att_nz) * 20.0))
    pr_d = max(0.0, min(2.375, 2.375 - ((float(interceptions) / att_nz) * 25.0)))
    return ((pr_a + pr_b + pr_c + pr_d) / 6.0) * 100.0


class StatEngine:
    """Manages custom stats, evaluates multi-scope composable formulas, and tracks the user's Stat Page."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = storage_dir or (Path.home() / ".nfl_stat_cli")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.custom_stats_file = self.storage_dir / "custom_stats.json"
        self.stat_page_file = self.storage_dir / "stat_page.json"
        self.stats: Dict[str, StatDefinition] = dict(DEFAULT_STATS)
        self.ephemeral_stats: Set[str] = set()
        self.stat_page: Dict[str, Any] = {
            "title": "My NFL Analytics Stat Page",
            "pinned_stats": [
                "qb_impact_score",
                "qb_meaningful_win",
                "qb_meaningful_loss",
                "yards_after_catch",
                "passer_rating",
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
                stats_map = data.get("stats", {}) if isinstance(data, dict) else {}
                for name, item in stats_map.items():
                    try:
                        if not isinstance(item, dict) or "formula" not in item:
                            continue
                        if name in DEFAULT_STATS:
                            item.setdefault("scope", DEFAULT_STATS[name].scope)
                            item.setdefault("agg", DEFAULT_STATS[name].agg)
                        self.stats[name] = StatDefinition(
                            name=item.get("name", name),
                            title=strip_ansi(item.get("title", name)),
                            category="traditional" if (name in DEFAULT_STATS and DEFAULT_STATS[name].category == "traditional") else "custom",
                            group_by=item.get("group_by", "qb"),
                            formula=item["formula"],
                            description=strip_ansi(item.get("description", "")),
                            calculation_explained=strip_ansi(item.get("calculation_explained", "")),
                            unit=strip_ansi(item.get("unit", "")),
                            filter_expr=item.get("filter_expr", ""),
                            scope=item.get("scope", "season"),
                            agg=item.get("agg", "formula"),
                            dependencies=item.get("dependencies") or extract_formula_dependencies(item["formula"]),
                            created_at=item.get("created_at", ""),
                        )
                    except Exception:
                        continue
            except Exception:
                try:
                    backup = self.custom_stats_file.with_suffix(".json.corrupt")
                    shutil.copy2(self.custom_stats_file, backup)
                except Exception:
                    pass
        if self.stat_page_file.exists():
            try:
                loaded_page = json.loads(self.stat_page_file.read_text(encoding="utf-8"))
                if isinstance(loaded_page, dict):
                    for k, v in loaded_page.items():
                        self.stat_page[k] = v
                    if not isinstance(self.stat_page.get("pinned_stats"), list):
                        self.stat_page["pinned_stats"] = list(DEFAULT_STATS.keys())[:6]
            except Exception:
                pass

    def save_state(self) -> None:
        ephemeral = getattr(self, "ephemeral_stats", set())
        custom_only = {
            k: asdict(v)
            for k, v in self.stats.items()
            if v.category == "custom" and k not in ephemeral
        }
        payload = {
            "schema_version": "2.0",
            "exported_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": custom_only,
        }
        _atomic_write_json(self.custom_stats_file, payload)
        clean_stat_page = dict(self.stat_page)
        if "pinned_stats" in clean_stat_page and isinstance(clean_stat_page["pinned_stats"], list):
            clean_stat_page["pinned_stats"] = [s for s in clean_stat_page["pinned_stats"] if s not in ephemeral]
        _atomic_write_json(self.stat_page_file, clean_stat_page)

    def _validate_stat_definition(
        self,
        clean_name: str,
        group_by: str,
        formula: str,
        filter_expr: str,
        scope: str,
        agg: str,
        extra_known_stats: Optional[Set[str]] = None,
        calculation_notes: Optional[List[str]] = None,
    ) -> List[str]:
        if not clean_name or not clean_name.isidentifier():
            raise ValueError(f"Invalid stat ID '{clean_name}': must be a valid identifier (letters, digits, underscores, not starting with a digit).")
        if clean_name in BASE_METRIC_KEYS:
            raise ValueError(f"Stat ID '{clean_name}' collides with a reserved base metric name.")
        if clean_name in DEFAULT_STATS and DEFAULT_STATS[clean_name].category == "traditional":
            raise ValueError(f"Cannot overwrite built-in traditional stat '{clean_name}'.")
        if group_by not in GROUP_BY_COLUMN_MAP:
            raise ValueError(f"Invalid group_by '{group_by}'. Allowed: {', '.join(GROUP_BY_COLUMN_MAP.keys())}")
        if scope not in ("season", "game", "play"):
            raise ValueError(f"Invalid scope '{scope}'. Allowed: season, game, play")
        if agg.lower() not in ("formula", "sum", "avg", "mean", "count_true", "rate", "max", "min"):
            raise ValueError(f"Invalid aggregation '{agg}'. Allowed: formula, sum, avg, count_true, rate, max, min")

        deps = extract_formula_dependencies(formula)
        allowed_vars = set(BASE_METRIC_KEYS) | set(self.stats.keys()) | (extra_known_stats or set())
        if scope == "play":
            allowed_vars |= PLAY_ROW_KEYS
        unknown = [d for d in deps if d not in allowed_vars]
        if unknown:
            raise ValueError(
                f"Unknown building block(s) in formula: {', '.join(unknown)}. "
                f"Run `list-stats` or `/stats` to see valid building blocks."
            )
        if clean_name in deps:
            raise ValueError(f"Self-referential dependency cycle detected in '{clean_name}'.")

        # Detect multi-hop dependency cycles
        visited: Set[str] = set()
        stack = list(deps)
        while stack:
            cur = stack.pop()
            if cur == clean_name:
                raise ValueError(f"Circular dependency detected involving '{clean_name}'.")
            if cur not in visited and cur in self.stats:
                visited.add(cur)
                stack.extend(self.stats[cur].dependencies)

        dummy_ctx: Dict[str, Any] = {k: 1.0 for k in allowed_vars}
        safe_eval_formula(formula, dummy_ctx)

        if filter_expr and filter_expr.strip():
            f_deps = extract_formula_dependencies(filter_expr)
            allowed_f_vars = PLAY_ROW_KEYS | BASE_METRIC_KEYS | set(self.stats.keys())
            unknown_f = [d for d in f_deps if d not in allowed_f_vars]
            if unknown_f:
                raise ValueError(f"Unknown play field(s) in filter_expr: {', '.join(unknown_f)}")
            sample_play = dict(SAMPLE_PBP_PLAYS[0])
            sample_play.setdefault("red_zone", 0)
            sample_play.setdefault("explosive_play", 0)
            safe_eval_formula(filter_expr, sample_play)

        warning = unguarded_division_warning(formula)
        if warning and calculation_notes is not None:
            calculation_notes.append(warning)
        return deps

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
        persist: bool = True,
    ) -> StatDefinition:
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower()).strip("_")
        if clean_name and clean_name[0].isdigit():
            clean_name = f"stat_{clean_name}"
        calculation_notes: List[str] = []
        deps = self._validate_stat_definition(
            clean_name, group_by, formula, filter_expr, scope, agg,
            calculation_notes=calculation_notes,
        )
        for note in calculation_notes:
            if note not in calculation_explained:
                calculation_explained = f"{calculation_explained} {note}".strip()

        if scope in ("game", "play") and agg == "formula":
            agg = "sum" if "ifelse" in formula else "avg"

        stat_def = StatDefinition(
            name=clean_name,
            title=strip_ansi(title),
            category="custom",
            group_by=group_by,
            formula=formula.strip(),
            description=strip_ansi(description),
            calculation_explained=strip_ansi(calculation_explained),
            unit=strip_ansi(unit),
            filter_expr=filter_expr.strip(),
            scope=scope,
            agg=agg,
            dependencies=deps,
        )
        self.stats[clean_name] = stat_def
        if persist:
            if hasattr(self, "ephemeral_stats"):
                self.ephemeral_stats.discard(clean_name)
            if pin_to_page and clean_name not in self.stat_page["pinned_stats"]:
                self.stat_page["pinned_stats"].append(clean_name)
            self.save_state()
        else:
            if hasattr(self, "ephemeral_stats"):
                self.ephemeral_stats.add(clean_name)
            if clean_name in self.stat_page.get("pinned_stats", []):
                self.stat_page["pinned_stats"].remove(clean_name)
        return stat_def

    def delete_custom_stat(self, name: str) -> StatDefinition:
        """
        Delete a user-created custom stat definition.
        Built-in traditional stats cannot be deleted.
        Removes the stat from self.stats, unpins from stat_page, and cleans lookback history.
        """
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower()).strip("_")
        if clean_name not in self.stats:
            for k, v in self.stats.items():
                if v.title.lower() == name.strip().lower():
                    clean_name = k
                    break
        if clean_name not in self.stats:
            matches = difflib.get_close_matches(clean_name, [k for k, v in self.stats.items() if v.category == "custom"], n=3, cutoff=0.5)
            hint = f" Did you mean: {', '.join(matches)}?" if matches else ""
            raise KeyError(f"Stat '{name}' is not registered.{hint}")

        target = self.stats[clean_name]
        if target.category == "traditional":
            raise ValueError(f"Cannot delete built-in traditional stat '{target.name}' ({target.title}). Only custom stats can be deleted.")

        dependent_stats = [
            k for k, v in self.stats.items()
            if v.category == "custom" and k != clean_name and clean_name in v.dependencies
        ]
        if dependent_stats:
            raise ValueError(
                f"Cannot delete custom stat '{clean_name}' because other custom stats depend on it: {', '.join(dependent_stats)}. "
                f"Please delete dependent stats first."
            )

        del self.stats[clean_name]
        if hasattr(self, "ephemeral_stats"):
            self.ephemeral_stats.discard(clean_name)

        if clean_name in self.stat_page.get("pinned_stats", []):
            self.stat_page["pinned_stats"].remove(clean_name)
        if "lookback_history" in self.stat_page and clean_name in self.stat_page["lookback_history"]:
            del self.stat_page["lookback_history"][clean_name]

        self.save_state()
        return target

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
        _atomic_write_json(target_path, payload)
        return target_path

    def import_custom_stats_json(self, source_path: Path) -> List[str]:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        stats_dict = raw.get("stats", raw) if isinstance(raw, dict) else {}
        if not isinstance(stats_dict, dict):
            raise ValueError("Invalid custom stats JSON: root or 'stats' must be a JSON object.")

        # Validate all entries first (transactional import before mutating state)
        batch_names = {
            re.sub(r"[^a-zA-Z0-9_]", "_", str(item.get("name", name)).strip().lower()).strip("_")
            for name, item in stats_dict.items()
            if isinstance(item, dict) and "formula" in item
        }
        staged: List[StatDefinition] = []
        for name, item in stats_dict.items():
            if not isinstance(item, dict) or "formula" not in item:
                continue
            raw_name = str(item.get("name", name)).strip().lower()
            clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_")
            if clean_name and clean_name[0].isdigit():
                clean_name = f"stat_{clean_name}"
            if clean_name in DEFAULT_STATS and DEFAULT_STATS[clean_name].category == "traditional":
                continue
            group_by = str(item.get("group_by", "qb"))
            formula = str(item["formula"]).strip()
            filter_expr = str(item.get("filter_expr", "")).strip()
            scope = str(item.get("scope", "season")).lower()
            agg = str(item.get("agg", "formula")).lower()
            calculation_notes: List[str] = []
            deps = self._validate_stat_definition(
                clean_name, group_by, formula, filter_expr, scope, agg,
                extra_known_stats=batch_names, calculation_notes=calculation_notes,
            )
            calculation_explained = item.get("calculation_explained", f"Calculated via formula: {formula}")
            for note in calculation_notes:
                if note not in calculation_explained:
                    calculation_explained = f"{calculation_explained} {note}".strip()
            staged.append(StatDefinition(
                name=clean_name,
                title=strip_ansi(item.get("title", clean_name)),
                category="custom",
                group_by=group_by,
                formula=formula,
                description=strip_ansi(item.get("description", "Imported custom NFL stat.")),
                calculation_explained=strip_ansi(calculation_explained),
                unit=strip_ansi(item.get("unit", "")),
                filter_expr=filter_expr,
                scope=scope,
                agg=agg,
                dependencies=deps,
            ))

        imported_names: List[str] = []
        for stat_def in staged:
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
        division: Optional[str] = None,
        week: Optional[int] = None,
        qtr: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        result = plays
        if conf:
            result = [p for p in result if str(p.get("conf", "")).upper() == conf.upper()]
        if team:
            result = [p for p in result if str(p.get("posteam", "")).upper() == team.upper()]
        if division:
            div_clean = division.strip().lower()
            result = [p for p in result if str(p.get("division", "")).strip().lower() == div_clean]
        if week is not None:
            result = [p for p in result if int(p.get("week", -999)) == int(week)]
        if qtr is not None:
            result = [p for p in result if int(p.get("qtr", -999)) == int(qtr)]
        if not filter_expr or not filter_expr.strip():
            return result
        # Validate syntax and identifiers once before filtering rows
        _parse_and_validate_expr(filter_expr)
        filtered: List[Dict[str, Any]] = []
        for p in result:
            try:
                if safe_eval_formula(filter_expr, p) > 0:
                    filtered.append(p)
            except ValueError as exc:
                if "Unknown variable" in str(exc) or "Unsupported" in str(exc) or "Exponent" in str(exc):
                    raise
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
        # Official pass attempts exclude sacks (in nflverse, pass_attempt == 1 on sacks)
        pass_attempts = sum(1 for p in plays if int(p.get("pass_attempt", 0)) == 1 and int(p.get("sack", 0)) == 0)
        rush_attempts = sum(int(p.get("rush_attempt", 0)) for p in plays)
        touchdowns = sum(int(p.get("touchdown", 0)) for p in plays)
        pass_touchdowns = sum(
            int(p.get("pass_touchdown", p.get("touchdown", 0) if (int(p.get("pass_attempt", 0)) == 1 and int(p.get("sack", 0)) == 0) else 0))
            for p in plays
        )
        rush_touchdowns = sum(
            int(p.get("rush_touchdown", p.get("touchdown", 0) if int(p.get("rush_attempt", 0)) == 1 else 0))
            for p in plays
        )
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
        penalties = sum(int(p.get("penalty", 0)) for p in plays)
        penalty_yards = sum(float(p.get("penalty_yards", 0.0)) for p in plays)
        penalties_drawn = sum(int(p.get("penalty_drawn", p.get("penalty", 0))) for p in plays)
        penalty_yards_drawn = sum(float(p.get("penalty_yards_drawn", p.get("penalty_yards", 0.0))) for p in plays)
        timeouts = sum(int(p.get("timeout", 0)) for p in plays)

        # Key games by (game_id, posteam) so multi-team groups count team-game outcomes accurately
        games: Dict[Tuple[str, str], int] = {}
        for p in plays:
            gid = str(p.get("game_id", "game"))
            pteam = str(p.get("posteam", ""))
            games[(gid, pteam)] = int(p.get("team_win", 0))
        games_played = max(1, len(games))
        games_won = sum(1 for w in games.values() if w == 1)
        games_lost = games_played - games_won

        cpoe_vals = [float(p.get("cpoe", 0.0)) for p in pass_plays if int(p.get("sack", 0)) == 0]
        avg_cpoe = (sum(cpoe_vals) / len(cpoe_vals)) if cpoe_vals else 0.0

        att_nz = float(max(1, pass_attempts))
        comp_nz = float(max(1, completions))
        rush_nz = float(max(1, rush_attempts))

        # Official NFL Passer Rating calculation (uses passing_yards and pass_touchdowns)
        nfl_passer_rating = calculate_passer_rating(pass_attempts, completions, passing_yards, pass_touchdowns, interceptions)

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
            "yards_after_catch": total_yac,
            "yac": total_yac,
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
            "pass_touchdowns": float(pass_touchdowns),
            "rush_touchdowns": float(rush_touchdowns),
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
            "penalties": float(penalties),
            "penalty_yards": float(penalty_yards),
            "penalty_rate": (float(penalties) / n) * 100.0,
            "penalties_per_game": float(penalties) / float(games_played),
            "penalty_yards_per_game": float(penalty_yards) / float(games_played),
            "penalties_drawn": float(penalties_drawn),
            "penalty_yards_drawn": float(penalty_yards_drawn),
            "net_penalties": float(penalties_drawn - penalties),
            "net_penalty_yards": float(penalty_yards_drawn - penalty_yards),
            "timeouts": float(timeouts),
            "timeouts_used": float(timeouts),
            "timeouts_called": float(timeouts),
            "fantasy_points": round((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0), 2),
            "fantasy_points_std": round((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0), 2),
            "fantasy_points_ppr": round((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0) + float(completions), 2),
            "fantasy_points_half_ppr": round((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0) + (float(completions) * 0.5), 2),
            "fantasy_ppg": round(((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0) + float(completions)) / float(games_played), 2),
            "fantasy_ppg_ppr": round(((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0) + float(completions)) / float(games_played), 2),
            "fantasy_ppg_std": round(((passing_yards * 0.04) + (pass_touchdowns * 4.0) - (interceptions * 2.0) + (rushing_yards * 0.10) + (rush_touchdowns * 6.0) - (fumbles_lost * 2.0)) / float(games_played), 2),
        }
        return base

    @staticmethod
    def _aggregate_values(vals: List[float], agg: str) -> float:
        finite_vals = [v for v in vals if math.isfinite(v)]
        if not finite_vals:
            return 0.0
        agg_l = agg.lower()
        if agg_l == "sum":
            return sum(finite_vals)
        if agg_l in ("avg", "mean", "formula"):
            return sum(finite_vals) / len(finite_vals)
        if agg_l == "count_true":
            return float(sum(1 for v in finite_vals if v > 0.0))
        if agg_l == "rate":
            return (float(sum(1 for v in finite_vals if v > 0.0)) / len(finite_vals)) * 100.0
        if agg_l == "max":
            return max(finite_vals)
        if agg_l == "min":
            return min(finite_vals)
        return sum(finite_vals) / len(finite_vals)

    def _resolve_season_formulas(
        self,
        ctx: Dict[str, float],
        stat_defs: List[StatDefinition],
        plays: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        filtered_ctx_cache: Dict[str, Dict[str, float]] = {}
        for _ in range(len(stat_defs) + 2):
            progressed = False
            for sdef in stat_defs:
                if sdef.scope == "season":
                    try:
                        eval_ctx = ctx
                        if plays is not None and sdef.filter_expr:
                            f_key = sdef.filter_expr.strip()
                            if f_key not in filtered_ctx_cache:
                                f_plays = self.apply_filter(plays, f_key)
                                filtered_ctx_cache[f_key] = self._compute_base_metrics(f_plays) if f_plays else {k: 0.0 for k in BASE_METRIC_KEYS}
                            # Merge already-resolved stats with filtered base metrics
                            eval_ctx = dict(ctx)
                            eval_ctx.update(filtered_ctx_cache[f_key])
                        val = safe_eval_formula(sdef.formula, eval_ctx)
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
        3. Season-scoped custom stats (evaluated on the entity's season context in dependency order, honoring each stat's filter_expr)
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
        self._resolve_season_formulas(ctx, all_defs, plays=plays)

        # 3. Game-scoped custom stats (evaluated per (game_id, posteam))
        game_defs = [s for s in all_defs if s.scope == "game"]
        if game_defs:
            games_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for p in plays:
                gid = str(p.get("game_id", "game"))
                pteam = str(p.get("posteam", ""))
                games_map.setdefault((gid, pteam), []).append(p)

            game_contexts: List[Dict[str, float]] = []
            for gplays in games_map.values():
                g_ctx = self._compute_base_metrics(gplays)
                for sdef in play_defs:
                    gp_sub = self.apply_filter(gplays, sdef.filter_expr) if sdef.filter_expr else gplays
                    gp_vals = []
                    for p in gp_sub:
                        try:
                            gp_vals.append(safe_eval_formula(sdef.formula, p))
                        except Exception:
                            pass
                    g_ctx[sdef.name] = self._aggregate_values(gp_vals, sdef.agg)
                self._resolve_season_formulas(g_ctx, all_defs, plays=gplays)
                # Resolve game-scoped stats inside each game context in dependency order
                for _ in range(len(game_defs) + 2):
                    for gdef in game_defs:
                        try:
                            eval_g_ctx = g_ctx
                            if gdef.filter_expr:
                                gf_plays = self.apply_filter(gplays, gdef.filter_expr)
                                eval_g_ctx = dict(g_ctx)
                                eval_g_ctx.update(self._compute_base_metrics(gf_plays) if gf_plays else {k: 0.0 for k in BASE_METRIC_KEYS})
                            g_ctx[gdef.name] = safe_eval_formula(gdef.formula, eval_g_ctx)
                        except Exception:
                            pass
                game_contexts.append(g_ctx)

            for gdef in game_defs:
                g_vals = [gc.get(gdef.name, 0.0) for gc in game_contexts]
                ctx[gdef.name] = self._aggregate_values(g_vals, gdef.agg)

        # 4. Final pass for season-scoped custom stats that depend on game-scoped or play-scoped custom stats
        self._resolve_season_formulas(ctx, all_defs, plays=plays)
        return ctx

    def evaluate_stat_leaderboard(
        self,
        stat_name: str,
        plays: List[Dict[str, Any]],
        conf: Optional[str] = None,
        team: Optional[str] = None,
        group_override: Optional[str] = None,
        extra_filter: str = "",
        division: Optional[str] = None,
        week: Optional[int] = None,
        qtr: Optional[int] = None,
        position: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate a traditional or custom stat across entities and return a sorted leaderboard."""
        if stat_name not in self.stats:
            matches = difflib.get_close_matches(stat_name, list(self.stats.keys()), n=3, cutoff=0.5)
            hint = f" Did you mean: {', '.join(matches)}?" if matches else " Run `list-stats` or `/stats` to see available stats."
            raise KeyError(f"Stat '{stat_name}' is not registered.{hint}")
        sdef = self.stats[stat_name]
        filtered = self.apply_filter(plays, sdef.filter_expr, conf=conf, team=team, division=division, week=week, qtr=qtr)
        if extra_filter:
            filtered = self.apply_filter(filtered, extra_filter)
        group_col = group_override if (group_override and group_override in GROUP_BY_COLUMN_MAP) else sdef.group_by
        if stat_name in ("penalties", "penalty_yards", "penalty_rate", "penalties_per_game", "penalty_yards_per_game"):
            if group_col in ("coach", "head_coach"):
                key_field = "penalty_coach"
            elif group_col in ("player", "rusher", "receiver", "qb"):
                key_field = "penalty_player_name"
            elif group_col == "penalty_type":
                key_field = "penalty_type"
            else:
                key_field = "penalty_team"
            filtered = [p for p in filtered if int(p.get("penalty", 0)) == 1 and p.get(key_field)]
        elif stat_name in ("penalties_drawn", "penalty_yards_drawn", "net_penalties", "net_penalty_yards"):
            if group_col in ("coach", "head_coach"):
                key_field = "penalty_favored_coach"
            else:
                key_field = "penalty_favored_team"
            filtered = [p for p in filtered if int(p.get("penalty", 0)) == 1 and p.get(key_field)]
        elif stat_name in ("timeouts", "timeouts_used", "timeouts_called"):
            if group_col in ("team", "timeout_team"):
                key_field = "timeout_team"
            else:
                key_field = "timeout_coach"
            filtered = [p for p in filtered if int(p.get("timeout", 0)) == 1 and p.get(key_field)]
        else:
            key_field = GROUP_BY_COLUMN_MAP.get(group_col, "posteam")

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in filtered:
            gval = str(p.get(key_field) or "").strip()
            if not gval and key_field == "player_name":
                gval = str(p.get("receiver_player_name") or p.get("rusher_player_name") or p.get("qb_name") or p.get("kicker_player_name") or p.get("punter_player_name") or "").strip()
            if not gval or gval.lower() in ("unknown qb", "unknown player", "unknown coach", "none", ""):
                continue
            groups.setdefault(gval, []).append(p)

        pos_target = position.upper() if position else None
        is_player_group = (
            group_col in ("player", "rusher", "receiver", "qb")
            or key_field in ("player_name", "receiver_player_name", "rusher_player_name", "qb_name", "penalty_player_name")
        )

        rows: List[Dict[str, Any]] = []
        for gval, gplays in groups.items():
            ent_pos = get_player_position(gval, gplays) or ""
            if pos_target and is_player_group:
                if ent_pos and ent_pos != pos_target:
                    continue

            metrics = self.evaluate_all_metrics_for_group(gplays)
            sample_play = max(gplays, key=lambda x: float(x.get("yards_gained", 0.0)))
            mw = int(round(metrics.get("qb_meaningful_win", 0.0)))
            ml = int(round(metrics.get("qb_meaningful_loss", 0.0)))
            gp = int(metrics["games_played"])
            val = float(metrics.get(stat_name, 0.0))
            if not math.isfinite(val):
                val = 0.0
            if group_col == "defteam" or key_field == "defteam":
                ent_team = str(gval)
            else:
                ent_team = str(gplays[0].get("timeout_team") if stat_name in ("timeouts", "timeouts_used") else (
                    gplays[0].get("penalty_favored_team") if stat_name in ("penalties_drawn", "penalty_yards_drawn") else (
                        gplays[0].get("penalty_team") if stat_name in ("penalties", "penalty_yards") else gplays[0].get("posteam", "")
                    )
                ))
            if not ent_team and key_field in ("coach", "head_coach", "penalty_coach", "timeout_coach"):
                c_inf = find_coach_team(gval)
                ent_team = c_inf[0] if c_inf else ""
            ent_conf = "AFC" if ent_team in AFC_TEAMS else ("NFC" if ent_team in NFC_TEAMS else str(gplays[0].get("conf", "")))
            rows.append({
                "entity": gval,
                "team": ent_team,
                "conf": ent_conf,
                "position": ent_pos,
                "value": round(val, 2),
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
        player: Optional[str] = None,
        qb: Optional[str] = None,
        concept: Optional[str] = None,
        play_type: Optional[str] = None,
        filter_expr: str = "",
        sort_by: str = "yards_gained",
        play_id: Optional[int] = None,
        game_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filter and rank individual plays for play-level inspection and ASCII field visualization."""
        res = list(plays)
        if season is not None:
            res = [p for p in res if _safe_int(p.get("season"), -1) == int(season)]
        if game_id:
            g_low = game_id.strip().lower()
            res = [p for p in res if str(p.get("game_id", "")).lower() == g_low]
        if play_id is not None:
            return [p for p in res if int(p.get("play_id", -1)) == int(play_id)]
        if conf:
            res = [p for p in res if str(p.get("conf", "")).upper() == conf.upper()]
        if team:
            res = [p for p in res if team.upper() in (str(p.get("posteam", "")).upper(), str(p.get("defteam", "")).upper())]
        target_player = player or qb
        if target_player:
            p_parts = str(target_player).strip().split()
            candidates = {str(target_player).lower()}
            if len(p_parts) >= 2:
                candidates.add(f"{p_parts[0][0].lower()}.{p_parts[-1].lower()}")
                candidates.add(f"{p_parts[0][0].lower()} {p_parts[-1].lower()}")
                candidates.add(p_parts[-1].lower())
            res = [
                p for p in res
                if any(
                    c in str(p.get("player_name", "")).lower()
                    or c in str(p.get("qb_name", "")).lower()
                    or c in str(p.get("receiver_player_name", "")).lower()
                    or c in str(p.get("rusher_player_name", "")).lower()
                    or c in str(p.get("kicker_player_name", "")).lower()
                    or c in str(p.get("punter_player_name", "")).lower()
                    or c in str(p.get("desc", "")).lower()
                    for c in candidates
                )
            ]
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

    def update_stat_page_tracking(
        self,
        all_plays: List[Dict[str, Any]],
        on_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Update lookback & forward season snapshots for all pinned stats on the Stat Page."""
        seasons = available_seasons(all_plays)
        history = self.stat_page.setdefault("lookback_history", {})
        pinned = [s for s in self.stat_page.get("pinned_stats", []) if s in self.stats]
        total_pinned = len(pinned)

        for idx, stat_name in enumerate(pinned, 1):
            if on_progress:
                on_progress(stat_name, idx, total_pinned)
            stat_hist = history.setdefault(stat_name, {})
            for s in seasons:
                s_plays = plays_for_season(all_plays, s)
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
            f"{C.BOLD}{C.GOLD}╔═══════════════════════════════════════════════════════════════════════════════════════╗{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.BOLD}{C.CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗{C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.BOLD}{C.CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║{C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.BOLD}{C.WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║{C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.BOLD}{C.GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║{C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.BOLD}{C.GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║{C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}║{C.RESET} {C.DIM}{C.WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Play Visualizer    {C.RESET} {C.BOLD}{C.GOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}╚═══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
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
    def render_situation_hud(cls, play: Dict[str, Any]) -> str:
        """
        Render a prominent, high-visibility Game Situation & Field Context HUD box
        highlighting:
        - Exact game clock and quarter/OT time remaining
        - Field location, yardline, and distance to opponent end zone
        - Down and distance (including Goal-to-Go context)
        - Game score and possession
        """
        desc = str(play.get("desc", ""))
        qtr = int(play.get("qtr", 1))
        q_str = "Overtime (OT)" if qtr >= 5 else f"Quarter {qtr} (Q{qtr})"

        clock_time = ""
        if "(" in desc and ")" in desc:
            inside = desc.split("(", 1)[1].split(")", 1)[0].strip()
            for token in inside.split():
                if ":" in token and any(c.isdigit() for c in token):
                    clock_time = token
                    break

        if clock_time:
            time_display = f"{clock_time} remaining in {q_str}"
        else:
            time_display = f"{q_str}"

        down = int(play.get("down", 1))
        ydstogo = int(play.get("ydstogo", 10))
        y100 = int(round(float(play.get("yardline_100", 50))))
        suffix = "st" if down == 1 else ("nd" if down == 2 else ("rd" if down == 3 else "th"))
        is_goal = (y100 <= ydstogo) or (y100 <= 10 and down == 1 and ydstogo >= y100)

        if is_goal:
            dnd_display = f"{down}{suffix} & Goal ({ydstogo} yd{'s' if ydstogo != 1 else ''} to go)"
        else:
            dnd_display = f"{down}{suffix} & {ydstogo} ({ydstogo} yards to first down)"

        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        if y100 == 50:
            loc_display = "50 Yardline (Midfield • Exactly 50 yds to Opponent End Zone)"
        elif y100 < 50:
            dist_desc = "Goal-to-Go territory" if y100 <= 10 else f"{y100} yds to Opponent End Zone"
            loc_display = f"{defteam} {y100} (Opponent {y100} • {dist_desc})"
        else:
            own_yd = 100 - y100
            loc_display = f"{posteam} {own_yd} (Own {own_yd} • {y100} yds to Opponent End Zone)"

        h_score = play.get("home_score", 0)
        a_score = play.get("away_score", 0)
        score_display = f"{defteam} {a_score} - {posteam} {h_score}"

        w = 87
        lines = [
            f"{C.BOLD}{C.GOLD}╔═ 🏈 GAME SITUATION & SNAP CONTEXT " + "═" * (w - 38) + f"╗{C.RESET}",
            f"{C.BOLD}║{C.RESET}  {C.BOLD}{C.CYAN}⏱️  GAME CLOCK:{C.RESET}       {C.BOLD}{pad_ansi(time_display, w - 24, 'left')}{C.RESET} {C.BOLD}║{C.RESET}",
            f"{C.BOLD}║{C.RESET}  {C.BOLD}{C.YELLOW}📍 FIELD LOCATION:{C.RESET}    {C.BOLD}{pad_ansi(loc_display, w - 24, 'left')}{C.RESET} {C.BOLD}║{C.RESET}",
            f"{C.BOLD}║{C.RESET}  {C.BOLD}{C.GREEN}🎯 DOWN & DISTANCE:{C.RESET}   {C.BOLD}{pad_ansi(dnd_display, w - 24, 'left')}{C.RESET} {C.BOLD}║{C.RESET}",
            f"{C.BOLD}║{C.RESET}  {C.BOLD}{C.WHITE}🛡️  POSSESSION:{C.RESET}        {pad_ansi(f'{posteam} Offense vs {defteam} Defense  │  Score: {score_display}', w - 24, 'left')} {C.BOLD}║{C.RESET}",
            f"{C.BOLD}{C.GOLD}╚" + "═" * (w - 2) + f"╝{C.RESET}",
        ]
        return "\n".join(lines)

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
        hud = cls.render_situation_hud(play)
        cam = camera.strip().lower().replace("_", "-")
        if cam in ("offense", "behind-offense", "qb", "all22-offense"):
            body = cls.render_behind_offense(play, title=title)
        elif cam in ("defense", "behind-defense", "def", "all22-defense"):
            body = cls.render_behind_defense(play, title=title)
        elif cam in ("all", "both", "all-angles"):
            body = (
                cls.render_behind_offense(play, title=f"{title} [BEHIND OFFENSE]")
                + "\n"
                + cls.render_behind_defense(play, title=f"{title} [BEHIND DEFENSE]")
                + "\n"
                + cls.render_sideline(play, title=f"{title} [SIDELINE VIEW]")
            )
        else:
            body = cls.render_sideline(play, title=title)
        return hud + "\n" + body

    @staticmethod
    def _format_spot(yardline_100: int) -> str:
        if yardline_100 > 50:
            return f"Own {100 - yardline_100}"
        if yardline_100 == 50:
            return "50"
        return f"Opp {yardline_100}"

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
        qb_name = str(play.get("qb_name") or "QB")
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        yardline_100 = int(play.get("yardline_100", 50))
        los_yard = max(1, min(99, 100 - yardline_100))
        spot_label = cls._format_spot(yardline_100)
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
        is_complete = int(play.get("complete_pass", 0)) == 1

        width = 56
        total_rows = 15
        los_row = 11  # Row 11 is Line of Scrimmage; Rows 0..10 are upfield (+33y down to +3y); Rows 12..14 are backfield

        def depth_to_row(rel_yards: float) -> int:
            r = int(round(los_row - (rel_yards / 3.0)))
            return max(0, min(total_rows - 1, r))

        dir_col_map = {"left": 12, "middle": 28, "right": 44}
        target_col = dir_col_map.get(direction, 28)
        qb_row, qb_col = 13, 28
        catch_row = depth_to_row(air_yards) if play_type == "pass" else los_row
        end_row = 0 if is_td else (catch_row if (play_type == "pass" and not is_complete and not is_sack) else depth_to_row(yards_gained))
        fd_row = depth_to_row(float(ydstogo))
        if fd_row == los_row and ydstogo > 0:
            fd_row = max(0, los_row - 1)

        ez_banner = f"{C.BOLD}{C.WHITE}╔══════╦{'═' * width}╦══════╗{C.RESET}"
        ez_title = pad_ansi(f"▲ OPPONENT END ZONE ({defteam}) • OFFENSE DRIVING UPFIELD ▲", width, "center")
        ez_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE}  TD  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.BOLD}{C.GOLD}{ez_title}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE}  TD  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        mid_sep = f"{C.BOLD}{C.WHITE}╠══════╬{'═' * width}╬══════╣{C.RESET}"
        bot_border = f"{C.BOLD}{C.WHITE}╚══════╩{'═' * width}╩══════╝{C.RESET}"
        side_hdr = f"        {C.DIM}◀ OFFENSE LEFT            HASH :     : HASH           OFFENSE RIGHT ▶{C.RESET}"

        out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} — [CAMERA: BEHIND THE OFFENSE]{C.RESET}",
            f"  {C.BOLD}{posteam}{C.RESET} vs {C.BOLD}{defteam}{C.RESET} ({conf}) │ Q{qtr} • {down}&{ydstogo} at {spot_label} │ Direction: {C.CYAN}{direction.upper()}{C.RESET}",
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
            steps = max(1, max(abs(catch_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (catch_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                ch = "╱" if target_col > qb_col + 3 else ("╲" if target_col < qb_col - 3 else "⋮")
                air_points[(r_p, c_p)] = ch
            # YAC only when pass is completed
            if is_complete and not is_int and end_row != catch_row:
                step_r = -1 if end_row < catch_row else 1
                for r_p in range(catch_row + step_r, end_row, step_r):
                    yac_points[(r_p, target_col)] = "║"
        else:
            steps = max(1, max(abs(end_row - qb_row), abs(target_col - qb_col)))
            for s in range(1, steps):
                r_p = int(round(qb_row + (end_row - qb_row) * (s / steps)))
                c_p = int(round(qb_col + (target_col - qb_col) * (s / steps)))
                yac_points[(r_p, c_p)] = "║"

        for r_idx in range(total_rows):
            rel_yds = (los_row - r_idx) * 3
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

            if is_screen and r_idx == max(0, catch_row - 1):
                for blk_c in (target_col - 2, target_col, target_col + 2):
                    if 0 <= blk_c < width:
                        row_chars[blk_c] = f"{C.BOLD}{C.ORANGE}▓{C.RESET}"

            for (pr, pc), ch in air_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.CYAN}{ch}{C.RESET}"
            for (pr, pc), ch in yac_points.items():
                if pr == r_idx and 0 <= pc < width:
                    row_chars[pc] = f"{C.BOLD}{C.GREEN}{ch}{C.RESET}"

            # Catch Point & End Spot (single-width glyphs so border never shifts)
            if play_type == "pass" and r_idx == catch_row and not is_sack:
                marker = f"{C.BOLD}{C.MAGENTA}◎{C.RESET}" if (is_complete and not is_int) else f"{C.BOLD}{C.RED}✖{C.RESET}"
                row_chars[target_col] = marker
            if r_idx == end_row and (play_type != "pass" or is_complete or is_sack):
                end_marker = f"{C.BOLD}{C.RED}✖{C.RESET}" if (is_sack or is_int) else f"{C.BOLD}{C.GOLD}★{C.RESET}"
                row_chars[target_col] = end_marker

            if r_idx == los_row:
                lbl = f"{C.BOLD}{C.BLUE}  LOS {C.RESET}"
            elif r_idx == fd_row:
                lbl = f"{C.BOLD}{C.YELLOW}  1ST {C.RESET}"
            else:
                lbl = f"{C.GRAY}{rel_yds:+4d}y {C.RESET}"

            out.append(f"{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}{''.join(row_chars)}{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}")

        out.append(bot_border)
        out.append(cls._play_legend_and_summary(play, qb_name, target_name, spot_label, down, ydstogo, air_yards, yac, yards_gained, concept, "BEHIND OFFENSE (Looking ▲ Upfield)"))
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
        qb_name = str(play.get("qb_name") or "QB")
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        yardline_100 = int(play.get("yardline_100", 50))
        los_yard = max(1, min(99, 100 - yardline_100))
        spot_label = cls._format_spot(yardline_100)
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
        is_complete = int(play.get("complete_pass", 0)) == 1

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
        end_row = total_rows - 1 if is_td else (catch_row if (play_type == "pass" and not is_complete and not is_sack) else depth_to_row(yards_gained))
        fd_row = depth_to_row(float(ydstogo))
        if fd_row == los_row and ydstogo > 0:
            fd_row = min(total_rows - 1, los_row + 1)

        top_banner = f"{C.BOLD}{C.WHITE}╔══════╦{'═' * width}╦══════╗{C.RESET}"
        off_hdr = pad_ansi(f"▼ OFFENSE BACKFIELD ({posteam}) DRIVING TOWARD DEFENSE ▼", width, "center")
        off_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.WHITE} OFF  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.BOLD}{C.CYAN}{off_hdr}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_AFC}{C.WHITE} OFF  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        mid_sep = f"{C.BOLD}{C.WHITE}╠══════╬{'═' * width}╬══════╣{C.RESET}"
        def_hdr = pad_ansi(f"♦ DEFENSE SECONDARY VIEW ({defteam} END ZONE BEHIND VIEWER) ♦", width, "center")
        def_row = f"{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE} DEF  {C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.BOLD}{C.GOLD}{def_hdr}{C.RESET}{C.BOLD}{C.WHITE}║{C.BG_ENDZONE_NFC}{C.WHITE} DEF  {C.RESET}{C.BOLD}{C.WHITE}║{C.RESET}"
        bot_border = f"{C.BOLD}{C.WHITE}╚══════╩{'═' * width}╩══════╝{C.RESET}"
        side_hdr = f"        {C.DIM}◀ DEF LEFT (OFF RIGHT)   HASH :     : HASH   DEF RIGHT (OFF LEFT) ▶{C.RESET}"

        out = [
            f"\n{C.BOLD}{C.GOLD}🏈 {title} — [CAMERA: BEHIND THE DEFENSE]{C.RESET}",
            f"  {C.BOLD}{defteam} Defense POV{C.RESET} vs {C.BOLD}{posteam} Offense{C.RESET} ({conf}) │ Q{qtr} • {down}&{ydstogo} at {spot_label} │ Off Direction: {C.CYAN}{direction.upper()}{C.RESET}",
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
            if is_complete and not is_int and end_row != catch_row:
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
                marker = f"{C.BOLD}{C.MAGENTA}◎{C.RESET}" if (is_complete and not is_int) else f"{C.BOLD}{C.RED}✖{C.RESET}"
                row_chars[target_col] = marker
            if r_idx == end_row and (play_type != "pass" or is_complete or is_sack):
                end_marker = f"{C.BOLD}{C.RED}✖{C.RESET}" if (is_sack or is_int) else f"{C.BOLD}{C.GOLD}★{C.RESET}"
                row_chars[target_col] = end_marker

            if r_idx == los_row:
                lbl = f"{C.BOLD}{C.BLUE}  LOS {C.RESET}"
            elif r_idx == fd_row:
                lbl = f"{C.BOLD}{C.YELLOW}  1ST {C.RESET}"
            else:
                lbl = f"{C.GRAY}{rel_yds:+4d}y {C.RESET}"

            out.append(f"{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}{''.join(row_chars)}{C.BOLD}{C.WHITE}║{C.RESET}{lbl}{C.BOLD}{C.WHITE}║{C.RESET}")

        out.extend([mid_sep, def_row, bot_border])
        out.append(cls._play_legend_and_summary(play, qb_name, target_name, spot_label, down, ydstogo, air_yards, yac, yards_gained, concept, "BEHIND DEFENSE (Offense Driving ▼ Toward Viewer)"))
        return "\n".join(out)

    @classmethod
    def render_sideline(cls, play: Dict[str, Any], title: str = "SIDELINE BROADCAST PLAY VIEW") -> str:
        """Render a colorized 100-yard sideline view (left-to-right) with lateral direction awareness."""
        posteam = str(play.get("posteam", "OFF"))
        defteam = str(play.get("defteam", "DEF"))
        conf = str(play.get("conf", "NFL"))
        yardline_100 = int(play.get("yardline_100", 60))
        los_yard = max(1, min(99, 100 - yardline_100))
        spot_label = cls._format_spot(yardline_100)
        yards_gained = float(play.get("yards_gained", 15.0))
        air_yards = float(play.get("air_yards", 0.0))
        yac = float(play.get("yards_after_catch", 0.0))
        ydstogo = int(play.get("ydstogo", 10))
        down = int(play.get("down", 1))
        is_screen = int(play.get("is_screen", 0)) == 1
        play_type = str(play.get("play_type", "pass"))
        concept = str(play.get("play_concept", "pass"))
        qb_name = str(play.get("qb_name") or "QB")
        target_name = str(play.get("receiver_player_name") or play.get("rusher_player_name") or "")
        direction = _infer_play_direction(play, str(play.get("desc", "")))
        is_int = int(play.get("interception", 0)) == 1
        is_sack = int(play.get("sack", 0)) == 1
        is_complete = int(play.get("complete_pass", 0)) == 1

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

        ez_left = ["  " + posteam[:3].ljust(3) + " ", " OWN  ", " END  ", " ZONE ", "  ♦♦  ", "      ", "      "]
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
                if is_sack:
                    row_chars[qb_col] = f"{C.BOLD}{C.RED}✖{C.RESET}"
                elif play_type == "pass":
                    step = 1 if catch_col >= qb_col else -1
                    for c in range(qb_col + step, catch_col, step):
                        if 0 <= c < field_width:
                            row_chars[c] = f"{C.BOLD}{C.CYAN}~{C.RESET}"
                    if is_complete and not is_int:
                        row_chars[catch_col] = f"{C.BOLD}{C.MAGENTA}◎{C.RESET}"
                        for c in range(min(catch_col, end_col) + 1, max(catch_col, end_col)):
                            if 0 <= c < field_width:
                                row_chars[c] = f"{C.BOLD}{C.GREEN}═{C.RESET}"
                        row_chars[end_col] = f"{C.BOLD}{C.GOLD}★{C.RESET}"
                    else:
                        row_chars[catch_col] = f"{C.BOLD}{C.RED}✖{C.RESET}"
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
        rows_out.append(cls._play_legend_and_summary(play, qb_name, target_name, spot_label, down, ydstogo, air_yards, yac, yards_gained, concept, "SIDELINE (Left ▶ Right)"))
        return "\n".join(rows_out)

    @staticmethod
    def _play_legend_and_summary(
        play: Dict[str, Any],
        qb_name: str,
        target_name: str,
        spot_label: str,
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
            f"{C.BOLD}{C.BLUE}━/┃{C.RESET}=LOS ({spot_label})  "
            f"{C.BOLD}{C.YELLOW}┄/┇{C.RESET}=1st Down ({down}&{ydstogo})  "
            f"{C.BOLD}{C.CYAN}⋮/╱/╲{C.RESET}=Air ({air_yards:+.0f}y)  "
            f"{C.BOLD}{C.MAGENTA}◎{C.RESET}=Catch  "
            f"{C.BOLD}{C.RED}✖{C.RESET}=Inc/Int/Sack  "
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

    @classmethod
    def render_generic_play_concept_diagram(cls, concept_key: str, title: Optional[str] = None) -> str:
        """
        Render a generic playbook chalkboard diagram for a play concept/sub-type
        showing player alignments, movement vectors, and tactical scheme notes.
        """
        ck = str(concept_key or "").strip().lower()
        alias_map = {
            "screen_pass": "screen", "bubble": "screen", "tunnel": "screen",
            "play_action": "play_action_deep", "deep": "play_action_deep", "post": "play_action_deep",
            "slant": "quick_slant", "slants": "quick_slant", "pass_short": "quick_slant", "quick": "quick_slant",
            "cross": "intermediate_cross", "crosser": "intermediate_cross", "mesh": "intermediate_cross", "pass_intermediate": "intermediate_cross",
            "outside_zone": "rush_outside", "stretch": "rush_outside", "sweep": "rush_outside", "pitch": "rush_outside",
            "inside_zone": "rush_inside", "dive": "rush_inside", "iso": "rush_inside", "run": "rush_inside",
            "power": "power_gap", "counter": "power_gap", "gap": "power_gap",
            "scramble": "qb_scramble", "keep": "qb_scramble", "option": "qb_scramble",
            "sack": "pass_rush_sack", "blitz": "pass_rush_sack", "pressure": "pass_rush_sack",
            "int": "turnover_interception", "interception": "turnover_interception", "takeaway": "turnover_interception",
            "tfl": "tfl_run_stop", "stop": "tfl_run_stop", "run_stop": "tfl_run_stop",
            "fg": "field_goal", "fieldgoal": "field_goal", "extra_point": "field_goal", "kick": "field_goal",
            "punts": "punt",
        }
        resolved = alias_map.get(ck, ck)

        schemes: Dict[str, Dict[str, Any]] = {
            "screen": {
                "title": "SCREEN PASS SCHEME (Offense • Pass)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  +15 yds",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +10 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DE]{C.RESET}               │  +05 yds",
                    f"───┼───────────────────────────────────────────────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            {C.GREEN}(WR2){C.RESET}            {C.GREEN}(LT){C.RESET}   {C.GREEN}(LG){C.RESET}   {C.GREEN}(C){C.RESET}   {C.GREEN}(RG){C.RESET}   {C.GREEN}(RT){C.RESET}                       │",
                    f"   │              │                                          │                         │  -05 yds",
                    f"   │              │ (Perimeter Block)                        │ (Pull & Lead)           │",
                    f"   │              ▼                                          ▼                         │",
                    f"   │           {C.GREEN}(WR1){C.RESET} ◄══════════════════ {C.CYAN}[QB]{C.RESET}                                          │  -07 yds",
                    f"   │       (Catch Behind LOS)              \\                                           │",
                    f"   │                                        \\-(RB Seal)                                │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Lures aggressive edge rushers upfield, releasing linemen into flat convoy.",
                    f"• {C.BOLD}Blocking Scheme:{C.RESET} Center & LT pass-set; RG & RT pull into perimeter alley.",
                    f"• {C.BOLD}Read Progression:{C.RESET} Catch snap -> 1-step trigger to WR1 in flat -> WR2 & RG seal alley.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} 2nd/3rd & 7+ against heavy pass rush or blitz look.",
                ],
            },
            "play_action_deep": {
                "title": "PLAY-ACTION DEEP SHOT SCHEME (Offense • Pass)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                       ▲                                           │  +35 yds (Post)",
                    f"   │                                       │                                           │",
                    f"   │               ▲                       │ (Deep Post Cut)                           │  +25 yds",
                    f"   │               │ (Go Route)          {C.BLUE}[FS]{C.RESET}                                          │",
                    f"   │             {C.BLUE}[CB]{C.RESET}                      │                             {C.BLUE}[CB]{C.RESET}          │  +15 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DE]{C.RESET}               │  +05 yds",
                    f"───┼───────────────────────────────────────────────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            {C.GREEN}(WR1){C.RESET}            {C.GREEN}(LT){C.RESET}   {C.GREEN}(LG){C.RESET}   {C.GREEN}(C){C.RESET}   {C.GREEN}(RG){C.RESET}   {C.GREEN}(RT){C.RESET}            {C.GREEN}(WR2){C.RESET}          │",
                    f"   │              ▲                         (Max Protect)            ▲                 │  -05 yds",
                    f"   │              │                                                 / (Post Angle)     │",
                    f"   │              │                      {C.CYAN}[QB]{C.RESET}                        /                  │  -07 yds",
                    f"   │              │                       ▲  (Fake Hand-off)       /                   │",
                    f"   │              │                       └── {C.GREEN}(RB){C.RESET} ──► (Mesh)                         │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Sells run at the mesh point to pull linebackers up, creating a deep vertical window.",
                    f"• {C.BOLD}Protection:{C.RESET} 7-man max protection with RB chip & check-release.",
                    f"• {C.BOLD}Read Progression:{C.RESET} 1. Deep Post (WR2), 2. Go route (WR1), 3. RB checkdown.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} 1st & 10 or 2nd & 2-4 off successful run establishment.",
                ],
            },
            "quick_slant": {
                "title": "QUICK GAME & SLANT SCHEME (Offense • Pass)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │  +15 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +10 yds",
                    f"   │                   \\                      {C.BLUE}[MLB]{C.RESET}                                    │",
                    f"   │                    ▼ (Slant Cut)                                                  │  +05 yds",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DE]{C.RESET}               │",
                    f"───┼───────────────────────────────────────────────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            {C.GREEN}(WR1){C.RESET} ──►       {C.GREEN}(LT){C.RESET}   {C.GREEN}(LG){C.RESET}   {C.GREEN}(C){C.RESET}   {C.GREEN}(RG){C.RESET}   {C.GREEN}(RT){C.RESET}            {C.GREEN}(TE){C.RESET}           │",
                    f"   │            (3-step timing)                                                        │  -05 yds",
                    f"   │                                     {C.CYAN}[QB]{C.RESET} (1-3 Step Trigger)                        │",
                    f"   │                                       ▲                                           │  -07 yds",
                    f"   │                                       │                                           │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} High-percentage rhythm throw getting ball out in under 2.2 seconds before rush arrives.",
                    f"• {C.BOLD}Footwork:{C.RESET} 3 steps from under center or 1 hitch in shotgun.",
                    f"• {C.BOLD}Target Window:{C.RESET} In between the numbers and hash, underneath dropping zone linebackers.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} 3rd & 3-6 or beat blitz/man coverage.",
                ],
            },
            "intermediate_cross": {
                "title": "INTERMEDIATE CROSSER & MESH SCHEME (Offense • Pass)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │  +20 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +15 yds",
                    f"   │                    ◄═════════════════════════════════════ (Deep Crosser)          │  +12 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DE]{C.RESET}               │  +05 yds",
                    f"───┼───────────────────────────────────────────────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            {C.GREEN}(WR1){C.RESET}            {C.GREEN}(LT){C.RESET}   {C.GREEN}(LG){C.RESET}   {C.GREEN}(C){C.RESET}   {C.GREEN}(RG){C.RESET}   {C.GREEN}(RT){C.RESET}            {C.GREEN}(WR2){C.RESET}          │",
                    f"   │              ▲                                                     ▲              │  -05 yds",
                    f"   │              │ (Clearout)                           {C.CYAN}[QB]{C.RESET}           │ (Over Route) │",
                    f"   │              │                                        ▼            │              │  -07 yds",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Deep crossing route runs away from man coverage leverage across open field turf.",
                    f"• {C.BOLD}Clearout:{C.RESET} Playside WR takes boundary cornerback deep to vacate intermediate honey hole.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} 2nd & medium or 3rd & 6-10 vs Cover 1 / Cover 3.",
                ],
            },
            "rush_inside": {
                "title": "INSIDE ZONE & DIVE SCHEME (Offense • Run)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │  +15 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +10 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}        ▲     {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DE]{C.RESET}               │  +05 yds",
                    f"───┼───────────────────────────────────────────────┼───────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            {C.GREEN}(WR1){C.RESET}            {C.GREEN}(LT){C.RESET}──►{C.GREEN}(LG){C.RESET}──►{C.GREEN}(C){C.RESET} │ ──►{C.GREEN}(RG){C.RESET}   {C.GREEN}(RT){C.RESET}            {C.GREEN}(TE){C.RESET}           │",
                    f"   │                                    (A-Gap Crease)                                 │  -05 yds",
                    f"   │                                     {C.CYAN}[QB]{C.RESET}    ▲                                     │",
                    f"   │                                       \\    │ (One-Cut Vertical)                   │  -07 yds",
                    f"   │                                        \\── {C.GREEN}(RB){C.RESET}                                   │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Offensive linemen take lateral zone steps, combo-blocking down lineman to second-level LB.",
                    f"• {C.BOLD}RB Track:{C.RESET} Aim at frontside guard, read 1-technique helmet, plant and cut vertically.",
                    f"• {C.BOLD}Crease Options:{C.RESET} Frontside A-gap, Frontside B-gap, or Backside Cutback.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} Base 1st down or short-yardage power situations.",
                ],
            },
            "rush_outside": {
                "title": "OUTSIDE ZONE & STRETCH SCHEME (Offense • Run)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │  +15 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +10 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET}   ▲    {C.BLUE}[DE]{C.RESET}               │  +05 yds",
                    f"───┼─────────────────────────────────────────────────────────────┼─────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │                         {C.GREEN}(LT)──► (LG)──► (C)──► (RG)──► (RT){C.RESET} │          {C.GREEN}(TE){C.RESET}          │",
                    f"   │                               (Lateral Stretch Flow)        │ (Perimeter Edge)    │  -05 yds",
                    f"   │                                     {C.CYAN}[QB]{C.RESET}                    │                     │",
                    f"   │                                       \\════════════════════►{C.GREEN}(RB){C.RESET}                  │  -07 yds",
                    f"   │                                                              (Speed to Corner)    │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Flow offensive line wide to perimeter, forcing defensive front to stretch laterally.",
                    f"• {C.BOLD}RB Read:{C.RESET} Press edge outside tight end; if edge is sealed, turn corner; if edge widens, one-cut vertical.",
                    f"• {C.BOLD}Key Block:{C.RESET} Reach block by playside tackle and tight end on defensive end.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} Explosive chunk running play against heavy interior fronts.",
                ],
            },
            "power_gap": {
                "title": "POWER & COUNTER GAP SCHEME (Offense • Run)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET}                                          │  +15 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET}                                                  {C.BLUE}[CB]{C.RESET}          │  +10 yds",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}        {C.BLUE}[SLB]{C.RESET}                      │",
                    f"   │                      {C.BLUE}[DE]{C.RESET}        {C.BLUE}[DT]{C.RESET}              {C.BLUE}[DT]{C.RESET} ◄─── {C.BLUE}[DE]{C.RESET} (Kickout)     │  +05 yds",
                    f"───┼─────────────────────────────────────────────────────────────┼─────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │                         {C.GREEN}(LT)     (LG)──►(C)    (RG)     (RT){C.RESET} │          {C.GREEN}(TE){C.RESET}          │",
                    f"   │                                   │                      ▲  │ (C-Gap Hole)        │  -05 yds",
                    f"   │                                   └───────(Pulling Guard)┘  │                     │",
                    f"   │                                     {C.CYAN}[QB]{C.RESET}                    ▲                     │  -07 yds",
                    f"   │                                       \\                      │ (Follow Puller)     │",
                    f"   │                                        \\───────────────────►{C.GREEN}(RB){C.RESET}                  │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Man/gap blocking scheme with backside guard pulling across formation to kick out DE.",
                    f"• {C.BOLD}Lead Blocker:{C.RESET} H-back/fullback wraps through C-gap to seal playside linebacker.",
                    f"• {C.BOLD}Ideal Situation:{C.RESET} Red zone, 3rd & 1-2, goal line physical interior running.",
                ],
            },
            "qb_scramble": {
                "title": "QB KEEP & SCRAMBLE SCHEME (Offense • Run)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET} (Deep Drop)                              │  +20 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET} (Turned Back in Man)                             {C.BLUE}[CB]{C.RESET}          │  +15 yds",
                    f"   │                                                              ▲ (Vacated Alley)    │",
                    f"   │                              {C.BLUE}[WLB]{C.RESET}        {C.BLUE}[MLB]{C.RESET}                  │                    │  +10 yds",
                    f"   │                      {C.BLUE}[DE]{C.RESET}─►      {C.BLUE}[DT]{C.RESET}        {C.BLUE}[DT]{C.RESET}       {C.BLUE}[DE]{C.RESET}       │                    │  +05 yds",
                    f"───┼───────────────────────\\───────┼───────┼───────/──────┼────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │                        \\    {C.GREEN}(LT)     (C)     (RT){C.RESET}  /               │                    │",
                    f"   │                         \\   (Pocket Flushed) /               │                    │  -05 yds",
                    f"   │                          \\                  /                │                    │",
                    f"   │                           ▼               ▼                  │                    │  -08 yds",
                    f"   │                                          {C.CYAN}[QB] ═══════════════┘{C.RESET}                    │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} When secondary coverage locks down receivers, mobile QB exploits vacated rush lanes.",
                    f"• {C.BOLD}Impact:{C.RESET} Deflates defensive coverage and forces defense to assign a spy LB.",
                ],
            },
            "pass_rush_sack": {
                "title": "PASS RUSH & SACK SCHEME (Defense • Pressure)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     [FS]                                          │  +15 yds",
                    f"   │               [CB]                                                  [CB]          │  +10 yds",
                    f"   │                              [WLB]        [MLB]        ▲                          │",
                    f"   │                      ▲           ▲                     │ (Green Dog Blitz)        │  +05 yds",
                    f"   │              (Speed) │           │ (A-Gap Stunt)       │                          │",
                    f"───┼──────────────────────┼───────────┼─────────────────────┼──────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │                     {C.BLUE}[DE]{C.RESET}─►     {C.BLUE}[DT]{C.RESET}             {C.BLUE}[DT]{C.RESET}     {C.BLUE}[DE]{C.RESET} ◄─ (Speed Bend)     │",
                    f"   │                     (LT)        (LG)   (C)   (RG)     (RT)                        │  -05 yds",
                    f"   │                       \\           │                    /                          │",
                    f"   │                        \\          │                   /                           │",
                    f"   │                         ▼         ▼                  ▼                            │  -08 yds",
                    f"   │                                  {C.RED}💥 SACK ON [QB]{C.RESET}                                  │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Defensive front collapses pocket from edge and interior before routes can develop.",
                    f"• {C.BOLD}Technique:{C.RESET} Edge rusher speed-to-power rip move with interior tackle stunting across center's face.",
                    f"• {C.BOLD}Result:{C.RESET} Negative yardage, forced turnover opportunity, third-down shutdown.",
                ],
            },
            "turnover_interception": {
                "title": "TAKEAWAY & INTERCEPTION SCHEME (Defense • Turnover)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     {C.BLUE}[FS]{C.RESET} (Centerfield Range)                      │  +20 yds",
                    f"   │               {C.BLUE}[CB]{C.RESET} ◄─── (Undercut Route)                                   [CB]          │  +15 yds",
                    f"   │                 \\                                                                 │",
                    f"   │                  ▼ {C.RED}🏈 INTERCEPTION!{C.RESET}                                                │  +10 yds",
                    f"   │                 · · · · · · · · · (Ball Flight Trajectory)                        │",
                    f"───┼─────────────────·─────────────────────────────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │            (WR1) ·          (LT)   (LG)   (C)   (RG)   (RT)                       │",
                    f"   │                  ·                                                                │  -05 yds",
                    f"   │                   · · · · · · · · · [QB] (Forced Throw Under Duress)              │  -07 yds",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Coverage baiting and quick break on ball flight in response to QB release.",
                    f"• {C.BOLD}Technique:{C.RESET} Cornerback / safety reads QB eyes, undercuts inside leverage, drives through receiver hands.",
                    f"• {C.BOLD}Impact:{C.RESET} Instant change of possession and sudden-change field position swing.",
                ],
            },
            "tfl_run_stop": {
                "title": "RUN STOP & TACKLE FOR LOSS SCHEME (Defense • Run Defense)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                                     [FS]                                          │  +15 yds",
                    f"   │               [CB]                                                  [CB]          │  +10 yds",
                    f"   │                              [WLB]        ▲ (Fill Hole)     [SLB]                 │",
                    f"   │                      [DE]                 │ (Stuffed at LOS)                      │  +05 yds",
                    f"   │                              {C.BLUE}[DT]{C.RESET} ◄───────┼───────► {C.BLUE}[DT]{C.RESET}                         │",
                    f"───┼───────────────────────────────\\───────────────────/───────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │                              {C.RED}▼ (Shoots B-Gap)    ▼{C.RESET}                                │",
                    f"   │                             (LT)   (LG)   (C)   (RG)   (RT)                       │  -03 yds",
                    f"   │                                       \\   │   /                                   │",
                    f"   │                                    {C.RED}🛑 TACKLE FOR LOSS{C.RESET}                             │  -05 yds",
                    f"   │                                        {C.GREEN}(RB){C.RESET}                                       │",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Philosophy:{C.RESET} Interior penetration disrupts backfield footwork and denies cutback lanes.",
                    f"• {C.BOLD}Assignment:{C.RESET} Defensive tackle disengages reach block, linebackers fast-flow to seal B/C gaps.",
                ],
            },
            "field_goal": {
                "title": "FIELD GOAL & EXTRA POINT UNIT (Special Teams)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │                            \\                       /                              │  GOALPOSTS",
                    f"   │                             \\  {C.YELLOW}🏈 (BALL SPLITS){C.RESET}   /                               │  UPRIGHTS",
                    f"   │                              \\═══════════════════/                                │",
                    f"   │                                        ▲                                          │  +10 yds",
                    f"   │                      [Rush Block]      │ [Kick Trajectory]  [Rush Block]          │",
                    f"───┼────────────────────────────────────────┼──────────────────────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │       (LW)  (LT)  (LG)  (LS: Long Snap)  (RG)  (RT)  (RW)                        │",
                    f"   │                           │                                                       │  -04 yds",
                    f"   │                           ▼ (7-8 Yard Snap)                                       │",
                    f"   │                          {C.GREEN}(H){C.RESET} [Holder: Catch, Laces Away]                          │  -07 yds",
                    f"   │                            \\                                                      │",
                    f"   │                             \\──► {C.CYAN}(K){C.RESET} [Kicker: 3-Step Follow Through]             │  -09 yds",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Operation Time:{C.RESET} Snap-to-kick executed in 1.25 to 1.30 seconds.",
                    f"• {C.BOLD}Protection:{C.RESET} Wings and tight ends step inside to pinch A/B rush gaps.",
                    f"• {C.BOLD}Holder Execution:{C.RESET} Catch at spot, spin laces away toward target, plant index finger.",
                ],
            },
            "punt": {
                "title": "PUNT & COVERAGE UNIT (Special Teams)",
                "art": [
                    f"   {C.BOLD}LEFT SIDELINE{C.RESET}                                                           {C.BOLD}RIGHT SIDELINE{C.RESET}",
                    f"   │  ▲ (Gunner Race)                                       ▲ (Gunner Race)            │  +45 yds",
                    f"   │  │                                                     │                          │",
                    f"   │  │                                 {C.YELLOW}🏈 (Deep Spiral){C.RESET}    │                          │  +30 yds",
                    f"   │  │                                    /                │                          │",
                    f"   │  │                       [Blockers]  /   [Blockers]    │                          │  +15 yds",
                    f"───┼──┼──────────────────────────────────/──────────────────┼──────────────────────────┼── {C.YELLOW}LOS 00{C.RESET}",
                    f"   │ (G1)   (T)   (G)   (LS: Long Snap)   (G)   (T)        (G2)                        │",
                    f"   │                           │                                                       │  -06 yds",
                    f"   │                           ▼ (14-15 Yard Snap)                                     │",
                    f"   │                                                                                   │  -12 yds",
                    f"   │                         {C.CYAN}[P]{C.RESET} (Punter 2-Step Drop & Directional Punt)          │  -15 yds",
                    f"   └───────────────────────────────────────────────────────────────────────────────────┘",
                ],
                "notes": [
                    f"• {C.BOLD}Hangtime Goal:{C.RESET} 4.40+ seconds to allow gunners to down ball inside 20-yard line.",
                    f"• {C.BOLD}Directional Pin:{C.RESET} Angled toward boundary sideline to eliminate lateral return lanes.",
                    f"• {C.BOLD}Protection:{C.RESET} Shield protectors absorb free rushers after 15-yard snap.",
                ],
            },
        }

        scheme = schemes.get(resolved, schemes["screen"])
        display_title = title or scheme["title"]
        header = [
            f"\n{C.BOLD}{C.GOLD}╔═══════════════════════════════════════════════════════════════════════════════════════╗",
            f"║  🏈 PLAYBOOK CHALKBOARD: {pad_ansi(display_title, 76, 'left')} ║",
            f"╚═══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        ]
        out_lines = header + scheme["art"] + [f"   {C.BOLD}{C.CYAN}📋 Tactical Playbook Breakdown:{C.RESET}"] + [f"   {n}" for n in scheme["notes"]]
        return "\n".join(out_lines)


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

    TEAM_NICKNAME_MAP: Dict[str, str] = {
        "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
        "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
        "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
        "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
        "raiders": "LV", "chargers": "LAC", "rams": "LA", "dolphins": "MIA",
        "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
        "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "49ers": "SF",
        "niners": "SF", "seahawks": "SEA", "buccaneers": "TB", "bucs": "TB",
        "titans": "TEN", "commanders": "WAS",
    }

    AMBIGUOUS_TEAM_ABBRS: Set[str] = {"NO", "MIN", "LA", "NE", "SEA", "TEN", "IND", "WAS", "BUF", "CAR"}

    KNOWN_PLAYERS: Tuple[str, ...] = (
        # Quarterbacks
        "bo nix", "patrick mahomes", "lamar jackson", "josh allen", "cj stroud", "c.j. stroud",
        "caleb williams", "jayden daniels", "drake maye", "justin fields", "jared goff",
        "brock purdy", "joe burrow", "jalen hurts", "justin herbert", "jordan love",
        "dak prescott", "matthew stafford", "tua tagovailoa", "aaron rodgers", "kirk cousins",
        "kyler murray", "trevor lawrence", "baker mayfield", "sam darnold",
        "mahomes", "allen", "jackson", "stroud", "watson", "fields", "goff", "purdy", "burrow",
        "hurts", "herbert", "love", "prescott", "stafford", "tagovailoa", "daniels", "williams",
        "maye", "nix", "rodgers", "cousins", "murray", "lawrence", "levis", "young", "minshew",
        "brissett", "darnold", "carr", "o'connell", "devito", "ridder", "lance", "dalton",
        "tannehill", "flacco", "wilson", "pickett", "trubisky", "winston", "lock", "rush",
        "browning", "heinicke",
        # Running backs
        "gibbs", "cook", "henry", "barkley", "mccaffrey", "taylor", "kamara", "jacobs", "hall",
        "warren", "jeanty", "tuten", "mixon", "walker", "pollard", "bijan", "robinson", "montgomery",
        "achane", "kyren", "swift", "conner", "mostert", "etienne", "harris", "stevenson", "charbonnet",
        "dowdle", "hubbard", "ford", "singletary", "benson", "corum", "vidal", "guerendo", "mason",
        # Wide receivers
        "worthy", "jefferson", "chase", "lamb", "hill", "st brown", "st. brown", "adams", "aiyuk",
        "samuel", "diggs", "evans", "collins", "nacua", "kupp", "moore", "pickens", "metcalf",
        "smith", "higgins", "flowers", "olave", "london", "reed", "rice", "dell", "waddle",
        "hopkins", "mclaurin", "godwin", "sutton", "ridley", "lockett", "shakir", "jeudy",
        "legette", "thomas", "nabers", "odunze", "harrison", "downs", "thielen", "douglas",
        "meyers", "palmer", "cooper", "mcconkey", "lazard", "slayton", "washington", "wester",
        # Tight ends
        "fannin", "kelce", "kittle", "laporta", "andrews", "bowers", "hockenson", "goedert", "ferguson",
        "njoku", "pitts", "kmet", "kraft", "likely", "otton", "schultz", "engram", "freiermuth",
        "fant", "gesicki", "conklin",
        # Specialists (K/P)
        "butker", "tucker", "boswell", "moody", "bass", "mcpherson", "dicker", "aubrey",
        "koo", "folk", "prater", "fairbairn", "gay", "santoso", "townsend", "stonehouse",
        "cole", "bojorquez", "dixon", "gillikin", "fox", "wishnowsky",
        # Defensive players
        "parsons", "watt", "bosa", "garrett", "crosby", "hutchinson", "surtain", "gardner",
        "hamilton", "warner", "hunter", "sweat", "jones", "donald", "mack", "queen",
        "winfield", "kerby", "branch", "bland", "roquan", "sneed", "bowman", "burns",
        "thibodeaux",
    )

    STAT_SYNONYM_MAP: Tuple[Tuple[str, str, str], ...] = (
        # Clean / successful plays net of turnovers & penalties ("most successful ... with the least penalties and turnovers")
        (
            r"\b(?:most|best|more)\s+(?:successful|productive|effective)\b.*\b(?:least|fewest|lowest|minimal|without|no|avoid\w*)\b.*\b(?:penalt\w*|turnover\w*)\b|"
            r"\b(?:least|fewest|lowest|minimal)\b.*\b(?:penalt\w*|turnover\w*)\b.*\b(?:most|best)\s+(?:successful|productive|effective)\b|"
            r"\bclean(?:est)?\s+(?:plays?|success|production)\b",
            "clean_play_score",
            "play_concept",
        ),
        # Passing Yards (singular & plural, colloquial phrases)
        (r"\b(?:passing|pass)\s+(?:yard|yards|yds|yd)\b|\b(?:most\s+yards\s+passing|passed\s+for\s+the\s+most\s+yards|threw\s+for\s+the\s+most\s+yards)\b", "passing_yards", "qb"),
        # Rushing Yards (singular & plural, colloquial phrases)
        (r"\b(?:rushing|rush)\s+(?:yard|yards|yds|yd)\b|\b(?:most\s+yards\s+rushing|ran\s+for\s+the\s+most\s+yards|rushed\s+for\s+the\s+most\s+yards)\b", "rushing_yards", "rusher"),
        # Passing Touchdowns
        (r"\b(?:passing|pass)\s+(?:touchdown|touchdowns|td|tds)\b|\b(?:touchdown\s+passes|threw\s+(?:the\s+)?most\s+touchdowns)\b", "pass_touchdowns", "qb"),
        # Rushing Touchdowns
        (r"\b(?:rushing|rush)\s+(?:touchdown|touchdowns|td|tds)\b|\b(?:ran\s+for\s+(?:the\s+)?most\s+touchdowns)\b", "rush_touchdowns", "rusher"),
        # Total Touchdowns
        (r"\b(?:touchdown|touchdowns|tds|td)\b", "touchdowns", "player"),
        # Interceptions
        (r"\b(?:interception|interceptions|picks|int|ints)\b|\b(?:threw\s+(?:the\s+)?most\s+picks)\b", "interceptions", "qb"),
        # Sacks
        (r"\b(?:sack|sacks)\b", "sacks", "qb"),
        # Completions
        (r"\b(?:completion|completions|completed\s+passes)\b", "completions", "qb"),
        # Completion Percentage
        (r"\b(?:completion\s+(?:percentage|pct|rate)|comp\s*%(?:age)?)\b", "completion_pct", "qb"),
        # Yards per Attempt
        (r"\b(?:yards\s+per\s+attempt|yards\s+per\s+pass|ypa|y/a)\b", "yards_per_attempt", "qb"),
        # Yards per Rush / Carry
        (r"\b(?:yards\s+per\s+(?:rush|carry)|ypc)\b", "yards_per_rush", "rusher"),
        # ANY/A
        (r"\b(?:any/a|adjusted\s+net\s+yards)\b", "any_a", "qb"),
        # Passer Rating
        (r"\b(?:passer\s+rating|qb\s+rating|passing\s+rating)\b", "passer_rating", "qb"),
        # First Downs
        (r"\b(?:first\s+down|first\s+downs|1st\s+downs)\b", "first_downs", "team"),
        # Timeouts Used / Called
        (r"\b(?:timeouts?\s+used|timeouts?\s+called|used\s+(?:the\s+)?most\s+timeouts?|called\s+(?:the\s+)?most\s+timeouts?|call\s+(?:the\s+)?most\s+timeouts?|most\s+timeouts?|timeouts?|timeout)\b", "timeouts", "coach"),
        # Penalty Yards in Favor / Drawn / Benefited
        (
            r"\b(?:(?:total\s+)?(?:yards|yardage|yds)\s+(?:in|of|from|on)\s+penalt(?:y|ies)\s+in\s+(?:their|its)?\s*favor)\b|"
            r"\b(?:penalt(?:y|ies)\s+(?:yards|yardage|yds)\s+in\s+(?:their|its)?\s*favor)\b|"
            r"\b(?:penalty\s+yards\s+drawn|opponent\s+penalty\s+yards|penalty\s+yardage\s+drawn|penalty\s+yardage\s+in\s+(?:their|its)?\s*favor)\b|"
            r"\b(?:benefited\s+(?:the\s+most\s+)?(?:in|from)\s+penalt(?:y|ies)\s+yards)\b|"
            r"\b(?:benefitted\s+(?:the\s+most\s+)?(?:in|from)\s+penalt(?:y|ies)\s+yards)\b|"
            r"\b(?:penalty\s+yards\s+awarded|yards\s+from\s+opponent\s+penalties)\b",
            "penalty_yards_drawn",
            "team",
        ),
        # Penalties in Favor / Drawn / Benefited
        (
            r"\b(?:penalties\s+in\s+(?:their|its)?\s*favor|penalties\s+drawn|opponent\s+penalties|penalties\s+against\s+(?:their\s+)?opponents?)\b|"
            r"\b(?:benefited\s+(?:the\s+most\s+)?from\s+penalties|benefitted\s+(?:the\s+most\s+)?from\s+penalties)\b|"
            r"\b(?:penalties\s+awarded|penalties\s+in\s+favor)\b",
            "penalties_drawn",
            "team",
        ),
        # Net Penalty Yards
        (
            r"\b(?:net\s+(?:total\s+)?(?:penalty\s+yards|penalty\s+yardage|yards\s+in\s+penalties))\b|"
            r"\b(?:penalty\s+yards\s+differential|penalty\s+yards\s+margin)\b",
            "net_penalty_yards",
            "team",
        ),
        # Net Penalties
        (
            r"\b(?:net\s+penalties|net\s+penalty|penalty\s+differential|penalty\s+margin)\b",
            "net_penalties",
            "team",
        ),
        # Penalty Yards (Assessed / Committed)
        (
            r"\b(?:(?:total\s+)?(?:yards|yardage|yds)\s+(?:in|of|from|to|on)\s+penalt(?:y|ies))\b|"
            r"\b(?:penalt(?:y|ies)\s+(?:yards|yardage|yds))\b|"
            r"\b(?:penalized\s+(?:for\s+)?(?:the\s+)?(?:most\s+)?(?:total\s+)?yards)\b|"
            r"\b(?:(?:lost|gave\s+up|surrendered)\s+(?:the\s+)?(?:most\s+)?yards\s+(?:to|on|from|in)\s+penalt(?:y|ies))\b|"
            r"\b(?:pen\s+yds|penalty\s+yardage|yards\s+penalized)\b|"
            r"\b(?:most\s+penalty\s+yards|highest\s+penalty\s+yards|total\s+penalty\s+yards)\b",
            "penalty_yards",
            "team",
        ),
        # Total Penalties (Count)
        (
            r"\b(?:penalties|penalty|flags)\b|"
            r"\b(?:most\s+penalties|fewest\s+penalties|least\s+penalties|penalized\s+the\s+most)\b",
            "penalties",
            "team",
        ),
        # Explosive Play Rate
        (r"\b(?:explosive\s+play\s+rate|explosive\s+plays)\b", "explosive_play_rate", "team"),
        # Success Rate
        (r"\b(?:success\s+rate|offensive\s+success)\b", "success_rate_pct", "team"),
        # EPA per Play
        (r"\b(?:epa\s+per\s+play|epa/play|epa)\b", "epa_per_play", "qb"),
        # Play Count / Volume (including screens, passes, runs, plays)
        (r"\b(?:most\s+screen\s+plays|most\s+screen\s+passes|most\s+screens|screen\s+passes|screen\s+plays)\b", "plays", "team"),
        (r"\b(?:most\s+plays|total\s+plays|offensive\s+snaps|snaps)\b", "plays", "team"),
        (r"\b(?:pass\s+attempts|dropbacks)\b", "pass_attempts", "qb"),
        # YAC over Expected
        (r"\b(?:yac\s+over\s+expected|yacoe)\b", "yac_over_expected", "team"),
        # Yards After Catch (General YAC across all completed passes)
        (r"\b(?:yards\s+after\s+(?:the\s+)?catch|yac)\b", "yards_after_catch", "receiver"),
        # Yards per play / Average yards per play / Play Efficiency
        (
            r"\b(?:yards?\s+per\s+play|ypp)\b|"
            r"\b(?:(?:most|highest|best|avg|average|leading|top)\s+yards?\s+(?:on\s+average|per\s+play))\b|"
            r"\b(?:(?:produces?|produced|gain(?:ed|s)?|averages?|generates?|got)\s+(?:the\s+)?(?:most|highest|best|top)?\s*yards?\s+(?:on\s+average|per\s+play))\b|"
            r"\b(?:has\s+(?:produces?|produced|gained?)\s+(?:the\s+)?(?:most|highest)?\s*yards?\s+(?:on\s+average|per\s+play))\b|"
            r"\b(?:averages?\s+(?:the\s+)?most\s+yards?)\b|"
            r"\b(?:yards?\s+on\s+average|average\s+yards?(?:\s+gained)?|avg\s+yards?(?:\s+gained)?)\b|"
            r"\b(?:most\s+yards?\s+on\s+average|highest\s+average\s+yards?)\b|"
            r"\b(?:play\s+concept\s+efficiency|play\s+efficiency|most\s+efficient\s+plays?|efficient\s+plays?)\b",
            "yards_per_play",
            "play_concept",
        ),
        # General / Overall Yardage Leaders ("most yards", "who had the most yards", "which player has the most yards", "yards this year", etc.)
        (r"\b(?:most\s+yards|highest\s+yards|leading\s+(?:in\s+)?(?:the\s+most\s+)?yards|leader\s+in\s+yards|leaders\s+in\s+yards|has\s+the\s+most\s+yards|had\s+the\s+most\s+yards|more\s+yards|yards\s+leader|yards\s+leaders|total\s+yards)\b", "passing_yards", "qb"),
        (r"\b(?:yards|yds)\b", "passing_yards", "qb"),
        # Fantasy Points (PPR)
        (r"\b(?:ppr\s+fantasy\s+points|ppr\s+fantasy|ppr\s+points|ppr\s+scoring)\b", "fantasy_points_ppr", "player"),
        # Fantasy Points (Half PPR)
        (r"\b(?:half[\s-]ppr\s+fantasy\s+points|half[\s-]ppr\s+fantasy|half[\s-]ppr\s+points|0\.5\s+ppr)\b", "fantasy_points_half_ppr", "player"),
        # Fantasy Points (Standard)
        (r"\b(?:standard\s+fantasy\s+points|standard\s+fantasy|non-ppr\s+fantasy)\b", "fantasy_points", "player"),
        # Fantasy Points General
        (r"\b(?:fantasy\s+points|fantasy\s+score|fantasy\s+scoring|fantasy\s+pts)\b", "fantasy_points_ppr", "player"),
        # Fantasy PPG
        (r"\b(?:fantasy\s+points\s+per\s+game|fantasy\s+ppg|fppg)\b", "fantasy_ppg", "player"),
    )

    @classmethod
    def detect_ollama_model(cls, requested_model: Optional[str] = None) -> Optional[str]:
        if requested_model and requested_model.strip().lower() in ("none", "off", "disable", "disabled"):
            return None
        if requested_model and requested_model.strip().lower() != "auto":
            return requested_model.strip()
        env_model = os.environ.get("NFL_STAT_SLM_MODEL")
        if env_model:
            if env_model.strip().lower() in ("none", "off", "disable", "disabled"):
                return None
            return env_model.strip()
        base_url = os.environ.get("NFL_STAT_OLLAMA_URL", "http://127.0.0.1:11434")
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
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
    def _validate_slm_response(cls, parsed: Dict[str, Any], engine: Optional[StatEngine]) -> Optional[Dict[str, Any]]:
        intent = str(parsed.get("intent") or "").strip().lower()
        if intent not in (
            "stat_query", "specific_play", "create_stat", "qb_wins_report",
            "team_drilldown", "player_drilldown", "stat_page", "delete_stat",
            "dataset_info", "fantasy_report", "sportsbook_report", "contract_report"
        ):
            return None
        parsed["intent"] = intent
        if "show_field" in parsed:
            sf = parsed["show_field"]
            parsed["show_field"] = (sf is True) or (isinstance(sf, str) and sf.strip().lower() == "true")
        cam = str(parsed.get("camera") or "behind-offense").strip().lower()
        if cam not in ("behind-offense", "behind-defense", "sideline", "offense", "defense", "side", "all"):
            cam = "behind-offense"
        parsed["camera"] = cam
        grp = parsed.get("group_by")
        if grp and str(grp).lower() not in GROUP_BY_COLUMN_MAP:
            parsed["group_by"] = None
        if "qb" in parsed:
            if "player" not in parsed or not parsed["player"]:
                parsed["player"] = parsed.pop("qb")
            else:
                parsed.pop("qb")
        if engine and intent == "stat_query":
            sname = str(parsed.get("stat_name") or "").strip().lower()
            if sname not in engine.stats:
                parsed["stat_name"] = None
        return parsed

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
            "2. 'specific_play': ONLY when the user asks to see, diagram, or find a specific single play (e.g. longest play, touchdown play, specific QB/player/team play, or behind offense/defense view). "
            "Set 'show_field': true and 'camera': 'behind-offense' | 'behind-defense' | 'sideline'.\n"
            "3. 'create_stat': when the user wants to define/create/make a new custom stat.\n"
            f"Available stats: {', '.join(available_stats)}.\n"
            "JSON keys: {\"intent\": \"stat_query|specific_play|create_stat\", \"stat_name\": \"...\", "
            "\"group_by\": \"qb|team|play_concept|conference|receiver|rusher|game\", \"filter_expr\": \"...\", "
            "\"season\": 2025, \"conf\": null, \"team\": null, \"player\": null, \"concept\": null, "
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
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(body.get("response", "{}"))
                if isinstance(parsed, dict) and "intent" in parsed:
                    validated = cls._validate_slm_response(parsed, engine)
                    if validated:
                        validated["slm_model_used"] = model_name
                        return validated
        except Exception:
            return None
        return None

    @classmethod
    def interpret_query(
        cls,
        query: str,
        engine: Optional[StatEngine] = None,
        slm_model: Optional[str] = None,
        pre_detected_model: Optional[str] = None,
        default_season: int = CURRENT_SEASON,
    ) -> Dict[str, Any]:
        """
        Interpret a user's natural language question using a local SLM (if available)
        or the deterministic rule/AST parser.
        Never forces an ASCII field when the user is asking for an average or leaderboard across the year!
        """
        effective_mode = (slm_model or "auto").strip().lower()
        if engine is not None and effective_mode not in ("none", "off", "disable", "disabled"):
            detected = pre_detected_model or cls.detect_ollama_model(slm_model)
            if detected:
                slm_res = cls.query_local_slm(query, engine, detected)
                if slm_res and (slm_res.get("intent") != "stat_query" or slm_res.get("stat_name")):
                    return slm_res

        q = query.strip()
        ql = q.lower()

        season_match = re.search(r"\b(20\d{2})\b", ql)
        if season_match:
            season = int(season_match.group(1))
        elif any(phrase in ql for phrase in ("last year", "last season", "previous year", "previous season")):
            season = default_season - 1
        else:
            season = default_season
        conf = "AFC" if re.search(r"\bafc\b", ql) else ("NFC" if re.search(r"\bnfc\b", ql) else None)

        # 1. Division detection
        division: Optional[str] = None
        div_m = re.search(r"\b(afc|nfc)\s+(east|north|south|west)\b", ql)
        if div_m:
            conf = div_m.group(1).upper()
            division = f"{conf} {div_m.group(2).title()}"
        else:
            div_stand = re.search(r"\b(east|north|south|west)\s+(?:div|division)\b", ql)
            if div_stand and conf:
                division = f"{conf} {div_stand.group(1).title()}"

        # 2. Week detection
        week: Optional[int] = None
        week_m = re.search(r"\b(?:week|wk|w)\s*(\d{1,2})\b", ql)
        if week_m:
            week = int(week_m.group(1))

        # 3. Quarter detection
        qtr: Optional[int] = None
        if re.search(r"\b(?:1st|first)\s+(?:quarter|qtr|qrt)\b|\bq1\b|\b(?:quarter|qtr|qrt)\s*1\b|\bin\s+the\s+1st\b", ql):
            qtr = 1
        elif re.search(r"\b(?:2nd|second)\s+(?:quarter|qtr|qrt)\b|\bq2\b|\b(?:quarter|qtr|qrt)\s*2\b|\bin\s+the\s+2nd\b", ql):
            qtr = 2
        elif re.search(r"\b(?:3rd|third)\s+(?:quarter|qtr|qrt)\b|\bq3\b|\b(?:quarter|qtr|qrt)\s*3\b|\bin\s+the\s+3rd\b", ql):
            qtr = 3
        elif re.search(r"\b(?:4th|fourth)\s+(?:quarter|qtr|qrt)\b|\bq4\b|\b(?:quarter|qtr|qrt)\s*4\b|\bin\s+the\s+4th\b", ql):
            qtr = 4
        elif re.search(r"\b(?:5th|fifth)\s+(?:quarter|qtr|qrt)\b|\b(?:overtime|ot)\b|\bq5\b|\b(?:quarter|qtr|qrt)\s*5\b|\bin\s+(?:ot|overtime)\b", ql):
            qtr = 5

        # 4. Position detection
        position: Optional[str] = None
        has_generic_player_prompt = any(w in ql for w in ("which player", "what player", "who is the player", "per player", "by player"))
        if re.search(r"\b(?:quarterback|quarterbacks|qb|qbs)\b", ql):
            position = "QB"
        elif re.search(r"\b(?:running\s*back|running\s*backs|rb|rbs|halfback|tailback)\b", ql):
            position = "RB"
        elif re.search(r"\b(?:wide\s*receiver|wide\s*receivers|wr|wrs|wideout|wideouts)\b", ql):
            position = "WR"
        elif re.search(r"\b(?:tight\s*end|tight\s*ends|te|tes)\b", ql):
            position = "TE"
        elif re.search(r"\b(?:kicker|kickers|placekicker|pk)\b", ql):
            position = "K"
        elif re.search(r"\b(?:punter|punters)\b", ql):
            position = "P"
        elif re.search(r"\b(?:defense|defensive|pass\s*rusher|edge\s*rusher|cornerback|safety|linebacker|def)\b", ql):
            position = "DEF"
        elif not has_generic_player_prompt:
            if re.search(r"\b(?:passer|passers|passing|pass)\b", ql):
                position = "QB"
            elif re.search(r"\b(?:rusher|rushers|rushing|rush)\b", ql):
                position = "RB"
            elif re.search(r"\b(?:kicking)\b", ql):
                position = "K"
            elif re.search(r"\b(?:punting)\b", ql):
                position = "P"

        # 5. Situation / Down & Distance
        filter_parts: List[str] = []
        if re.search(r"\b(?:3rd|third)\s+(?:and|&)\s+short\b", ql):
            filter_parts.append("down == 3 and ydstogo <= 2")
        elif re.search(r"\b(?:3rd|third)\s+(?:and|&)\s+long\b", ql):
            filter_parts.append("down == 3 and ydstogo >= 7")
        elif re.search(r"\b(?:4th|fourth)\s+(?:and|&)\s+(?:1|one|inches)\b", ql):
            filter_parts.append("down == 4 and ydstogo <= 1")
        elif re.search(r"\b(?:1st|first)\s+down\b", ql):
            filter_parts.append("down == 1")
        elif re.search(r"\b(?:2nd|second)\s+down\b", ql):
            filter_parts.append("down == 2")
        elif re.search(r"\b(?:3rd|third)\s+down\b", ql):
            filter_parts.append("down == 3")
        elif re.search(r"\b(?:4th|fourth)\s+down\b", ql):
            filter_parts.append("down == 4")

        if "red zone" in ql or "redzone" in ql or "inside the 20" in ql:
            filter_parts.append("yardline_100 <= 20")
        if "goal line" in ql or "goalline" in ql or "inside the 5" in ql:
            filter_parts.append("yardline_100 <= 5")
        if "two minute" in ql or "2 minute" in ql:
            filter_parts.append("half_seconds_remaining <= 120")
        if "play action" in ql or "play-action" in ql:
            filter_parts.append("play_action == 1")
        if "screen" in ql:
            filter_parts.append("is_screen == 1")

        # Detect camera perspective
        camera = "behind-offense"
        if any(p in ql for p in ("behind the defense", "behind defense", "defense view", "defensive view", "from defense")):
            camera = "behind-defense"
        elif any(p in ql for p in ("behind the offense", "behind offense", "offense view", "offensive view", "behind qb")):
            camera = "behind-offense"
        elif any(p in ql for p in ("sideline", "broadcast view", "side view")):
            camera = "sideline"

        # Detect team filter deterministically without matching common lowercase English words like "no", "in", "min"
        team_filter: Optional[str] = None
        for alias, abbr in sorted(cls.TEAM_NICKNAME_MAP.items()):
            if re.search(rf"\b{re.escape(alias)}\b", ql):
                team_filter = abbr
                break
        if not team_filter:
            for t_abbr in sorted(AFC_TEAMS | NFC_TEAMS):
                if t_abbr in cls.AMBIGUOUS_TEAM_ABBRS:
                    if re.search(rf"\b{t_abbr}\b", q) or re.search(rf"\b(?:for|by|vs|team)\s+{t_abbr.lower()}\b", ql):
                        team_filter = t_abbr
                        break
                else:
                    if re.search(rf"\b{t_abbr.lower()}\b", ql):
                        team_filter = t_abbr
                        break

        player_filter: Optional[str] = None
        ql_no_apostrophe = re.sub(r"['’]s\b", "", ql)
        for p_key in cls.KNOWN_PLAYERS:
            if re.search(rf"\b{re.escape(p_key)}\b", ql_no_apostrophe):
                player_filter = p_key
                break

        if not player_filter:
            q_clean_player_prompts = re.sub(r"\b(?:which|what|any|each|every|the|a)\s+player\b", "", q, flags=re.IGNORECASE)
            p_pat = re.search(
                r"\b(?:player\s+stats\s+for|stats\s+for|stats\s+on|player\s+profile\s+for|for\s+player|player|for|show|diagram)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\b",
                q_clean_player_prompts,
            )
            if p_pat:
                cand = p_pat.group(1).strip()
                cand_low = cand.lower()
                ignore_words = {
                    "the", "a", "an", "all", "each", "any", "every", "me", "play", "plays", "stat", "stats",
                    "leaderboard", "rankings", "field", "ascii", "offense", "defense", "special",
                    "teams", "team", "screen", "pass", "run", "touchdown", "interception",
                    "sack", "longest", "best", "meaningful", "win", "loss", "impact", "score",
                    "passer", "rating", "cpoe", "epa", "wpa", "yac", "afc", "nfc", "auto",
                    "season", "game", "quarter", "qtr", "qrt", "down", "view", "sideline", "camera",
                    "week", "division", "most", "highest", "last", "latest", "data", "who", "what",
                    "which", "has", "had", "have", "is", "was", "are", "were", "with", "in", "at",
                    "to", "of", "from", "by", "on", "this", "that", "there", "leading", "leader",
                    "leaders", "led", "leads", "year", "years", "yard", "yards", "yds", "more",
                    "player", "players", "qb", "qbs", "quarterback", "quarterbacks", "rusher",
                    "rushers", "receiver", "receivers", "kicker", "punter",
                    "coach", "coaches", "coaching", "staff", "hc", "oc", "dc", "coordinator",
                    "penalty", "penalties", "flags", "timeout", "timeouts", "favor", "benefited", "benefitted", "drawn", "called", "used",
                } | set(cls.TEAM_NICKNAME_MAP.keys()) | {t.lower() for t in AFC_TEAMS | NFC_TEAMS}
                cand_words = set(cand_low.split())
                if not cand_words.intersection(ignore_words) and not any(cand_low == t.lower() for t in cls.TEAM_NICKNAME_MAP):
                    player_filter = cand

        # Check if user is asking for Coaching Staff information
        has_stat_term = any(w in ql for w in (
            "epa", "yards", "stat", "stats", "leaderboard", "rank", "ranking", "rate", "rating",
            "success", "cpoe", "wpa", "points", "touchdowns", "timeout", "timeouts", "penalty",
            "penalties", "flags", "favor", "benefited", "benefitted", "drawn", "differential",
            "contract", "contracts", "salary", "salaries", "paid", "payroll", "cap", "apy"
        ))
        is_coaching_query = (not has_stat_term) and (
            any(phrase in ql for phrase in (
                "head coach", "coach of", "coaches the", "coached by", "offensive coordinator",
                "defensive coordinator", "coaching staff", "coaches for", "coaching for",
                "who coaches", "who is the coach", "who is the hc", "who is the oc", "who is the dc",
                "qb coach", "ol coach", "position coach", "coordinator for", "coordinator of",
                "coach for", "coaches on", "coaching tree",
            )) or bool(re.search(r"\b(?:hc|oc|dc)\s+(?:for|of|at)\b", ql)) or (
                bool(re.search(r"\b(?:coach|coaches)\b", ql)) and bool(team_filter)
            )
        )

        c_found_team: Optional[str] = team_filter
        c_found_role: Optional[str] = None
        if not c_found_team:
            words = re.sub(r"[^\w\s]", " ", ql).split()
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                c_info = find_coach_team(bigram)
                if c_info:
                    c_found_team = c_info[0]
                    c_found_role = c_info[2]
                    break
            if not c_found_team:
                for word in words:
                    c_info = find_coach_team(word)
                    if c_info:
                        c_found_team = c_info[0]
                        c_found_role = c_info[2]
                        break

        if not c_found_team and player_filter:
            c_info = find_coach_team(player_filter)
            if c_info:
                c_found_team = c_info[0]
                c_found_role = c_info[2]
                player_filter = None

        if not has_stat_term and (is_coaching_query or c_found_role or (c_found_team and any(w in ql for w in ("coach", "coaches", "hc", "oc", "dc", "staff")))):
            role_req: Optional[str] = c_found_role
            if "offensive coordinator" in ql or re.search(r"\boc\b", ql):
                role_req = "oc"
            elif "defensive coordinator" in ql or re.search(r"\bdc\b", ql):
                role_req = "dc"
            elif "head coach" in ql or re.search(r"\bhc\b", ql) or "who is the coach" in ql:
                role_req = "hc"
            elif "qb coach" in ql or "quarterbacks coach" in ql:
                role_req = "qb"
            elif "ol coach" in ql or "offensive line coach" in ql:
                role_req = "ol"

            target_team = c_found_team or "KC"
            role_label = role_req.upper() if role_req else "coaching staff"
            return {
                "intent": "coaching_staff",
                "query": query,
                "team": target_team,
                "role": role_req,
                "season": season,
                "stat_name": None,
                "group_by": None,
                "week": None,
                "qtr": None,
                "division": None,
                "conf": None,
                "player": None,
                "position": None,
                "filter_expr": "",
                "show_field": False,
                "explanation": f"Reported {role_label} for {target_team} ({season}).",
            }

        # Check if user is asking for Dataset Info / Game Information
        has_play_or_stat_subject = any(w in ql for w in (
            "play", "plays", "touchdown", "td", "interception", "pass", "rush", "run",
            "throw", "stat", "stats", "yard", "yards", "epa", "top", "rank", "leader",
            "best", "worst", "longest", "efficiency"
        ))
        is_dataset_query = not has_play_or_stat_subject and (
            any(phrase in ql for phrase in (
                "what is the last game", "what was the last game", "what games do you have", "what data do you have",
                "games you have data from", "games you have data for", "games do you have data",
                "what data is loaded", "available games", "games loaded", "which games do you have",
                "games in the dataset", "show all games", "list all games", "what games are in",
            )) or (
                ("game" in ql or "games" in ql) and any(w in ql for w in ("data from", "data for", "you have", "loaded", "available"))
            ) or (
                re.search(r"\b(?:what|which|list|show)\s+(?:are\s+the\s+)?games\b", ql) is not None
            ) or (
                ql.strip() in ("last game", "latest game", "most recent game", "last game played", "latest game played")
            )
        )

        if is_dataset_query:
            subq = "last_game" if any(w in ql for w in ("last", "latest", "most recent", "newest")) else "all_games"
            return {
                "intent": "dataset_info",
                "subquery": subq,
                "query": query,
                "stat_name": None,
                "group_by": None,
                "season": season,
                "week": week,
                "qtr": qtr,
                "division": division,
                "conf": conf,
                "team": team_filter,
                "player": None,
                "position": position,
                "filter_expr": " and ".join(filter_parts),
                "show_field": False,
                "explanation": f"Report information on {'the latest loaded NFL game' if subq == 'last_game' else 'loaded games in the dataset'}.",
            }

        # Check if user is asking for Stat Page
        if any(ql == p or ql.startswith(p + " ") for p in ("stat page", "show stat page", "view stat page", "my stat page", "saved stat page", "stat tracking", "saved stats", "stat-page")):
            return {
                "intent": "stat_page",
                "query": query,
                "stat_name": None,
                "group_by": None,
                "season": season,
                "week": week,
                "qtr": qtr,
                "division": division,
                "conf": None,
                "team": None,
                "player": None,
                "position": None,
                "filter_expr": "",
                "show_field": False,
                "explanation": "Display Saved Stat Page with historical lookback and forward tracking.",
            }

        # Check if user is asking to DELETE a custom stat
        del_m = re.match(r"^(?:delete|remove|drop)\s+(?:custom\s+)?stat\s+([a-zA-Z0-9_]+)$", ql)
        if del_m:
            return {
                "intent": "delete_stat",
                "stat_name": del_m.group(1),
                "query": query,
                "group_by": None,
                "season": season,
                "week": week,
                "qtr": qtr,
                "division": division,
                "conf": None,
                "team": None,
                "player": None,
                "position": None,
                "filter_expr": "",
                "show_field": False,
                "explanation": f"Delete custom stat `{del_m.group(1)}`.",
            }

        # Check if user is asking to CREATE a custom stat
        if any(ql.startswith(prefix) for prefix in ("create stat", "create a stat", "make a stat", "make stat", "define stat", "build stat")):
            name_m = re.search(r"(?:called|named)\s+([a-zA-Z0-9_]+)", ql)
            formula_m = re.search(r"formula\s+(.+?)(?:\s+where\s+|\s+by\s+(?:qb|team|play_concept|conference|receiver|rusher|player|game)\b|$)", q, flags=re.IGNORECASE)
            where_m = re.search(r"\bwhere\s+(.+?)(?:\s+by\s+(?:qb|team|play_concept|conference|receiver|rusher|player|game)\b|$)", q, flags=re.IGNORECASE)
            by_m = re.search(r"\bby\s+(qb|team|play_concept|conference|receiver|rusher|player|game)\b", ql)
            s_name = name_m.group(1) if name_m else "custom_user_stat"
            s_formula = formula_m.group(1).strip() if formula_m else "yards_per_play + (epa_per_play * 10)"
            s_filter = where_m.group(1).strip() if where_m else ""
            s_group = by_m.group(1) if by_m else "qb"
            return {
                "intent": "create_stat",
                "stat_name": s_name,
                "query": query,
                "title": s_name.replace("_", " ").title(),
                "group_by": s_group,
                "formula": s_formula,
                "filter_expr": s_filter,
                "scope": "game" if "game" in ql and "win" in ql else "season",
                "agg": "sum" if "ifelse" in s_formula else "formula",
                "season": season,
                "week": week,
                "qtr": qtr,
                "division": division,
                "conf": conf,
                "team": team_filter,
                "player": player_filter,
                "position": position,
                "show_field": False,
                "explanation": f"Created custom stat `{s_name}` grouped by `{s_group}` using formula `{s_formula}`.",
            }

        # Check if user is asking to DRILL DOWN into a team or player
        is_drill_kw = any(w in ql for w in ("drill down", "drilldown", "team profile", "team breakdown", "player profile", "player breakdown"))
        has_specific_stat_kw = any(w in ql for w in (
            "epa", "rating", "yac", "cpoe", "wpa", "yards per play", "success rate", "explosive", "meaningful win", "qb win",
            "passing yard", "rushing yard", "touchdown", "sack", "interception", "pass yards", "rush yards", "td",
            "turnover", "turnovers", "takeaway", "takeaways",
            "fantasy", "ppr", "contract", "contracts", "salary", "salaries", "paid", "payroll", "spread", "odds",
        ))
        if not has_specific_stat_kw and (is_drill_kw or (
            team_filter and any(w in ql for w in ("team stats", "stats for the chiefs", "stats for the bills", "stats for the lions", "team overview"))
        ) or (
            player_filter and any(w in ql for w in ("stats for", "player stats", "stats", "overview", "profile", "breakdown", "drill"))
        )):
            if team_filter and not player_filter:
                return {
                    "intent": "team_drilldown",
                    "query": query,
                    "stat_name": None,
                    "group_by": "team",
                    "season": season,
                    "week": week,
                    "qtr": qtr,
                    "division": division,
                    "team": team_filter,
                    "player": player_filter,
                    "position": position,
                    "conf": conf,
                    "filter_expr": " and ".join(filter_parts),
                    "show_field": False,
                    "explanation": f"Drill-down into team analytics, offense/defense profile, and roster leaders for {team_filter} ({season}).",
                }
            if player_filter:
                return {
                    "intent": "player_drilldown",
                    "query": query,
                    "stat_name": None,
                    "group_by": "player",
                    "season": season,
                    "week": week,
                    "qtr": qtr,
                    "division": division,
                    "player": player_filter,
                    "position": position,
                    "conf": conf,
                    "team": team_filter,
                    "filter_expr": " and ".join(filter_parts),
                    "show_field": False,
                    "explanation": f"Drill-down into player passing, rushing, receiving, and situational stats for {player_filter.title()} ({season}).",
                }

        # Check if user is asking about FANTASY FOOTBALL
        if any(w in ql for w in ("fantasy", "ppr", "half-ppr", "half ppr", "fppg")):
            scoring_fmt = "ppr"
            if "standard" in ql or "non-ppr" in ql or "non ppr" in ql:
                scoring_fmt = "standard"
            elif "half" in ql:
                scoring_fmt = "half_ppr"

            top_m = re.search(r"\btop\s+(\d+)\b", ql)
            lim_val = int(top_m.group(1)) if top_m else 15

            if player_filter:
                return {
                    "intent": "fantasy_report",
                    "subquery": "player",
                    "query": query,
                    "player": player_filter,
                    "position": position,
                    "season": season,
                    "week": week,
                    "scoring_format": scoring_fmt,
                    "limit": lim_val,
                    "show_field": False,
                    "explanation": f"Fantasy Football profile and scoring breakdown for {player_filter.title()} ({season}).",
                }
            return {
                "intent": "fantasy_report",
                "subquery": "leaderboard",
                "query": query,
                "player": None,
                "position": position,
                "season": season,
                "week": week,
                "scoring_format": scoring_fmt,
                "limit": lim_val,
                "show_field": False,
                "explanation": f"Fantasy Football {scoring_fmt.upper()} leaderboard for {position or 'all positions'} ({season}).",
            }

        # Check if user is asking about SPORTSBOOK HANDICAPPING / BETTING ODDS
        if any(w in ql for w in (
            "spread", "spreads", "point spread", "handicap", "handicapping",
            "sportsbook", "odds", "betting line", "betting lines", "moneyline",
            "moneylines", "over under", "over/under", "who is favored", "underdog",
            "power rating", "power ratings", "power ranking", "power rankings", "betting"
        )):
            if any(w in ql for w in ("power", "ratings", "rankings")):
                return {
                    "intent": "sportsbook_report",
                    "subquery": "power_ratings",
                    "query": query,
                    "season": season,
                    "week": week,
                    "team": team_filter,
                    "show_field": False,
                    "explanation": f"Quantitative team power ratings derived from Net EPA/play and scoring differentials ({season}).",
                }

            # Check for matchup teams
            matchup_teams = None
            m_vs = re.search(r"\b([a-zA-Z]+)\s+(?:vs\.?|against|at|@)\s+([a-zA-Z]+)\b", ql)
            if m_vs:
                t1 = resolve_team_abbr(m_vs.group(1))
                t2 = resolve_team_abbr(m_vs.group(2))
                if t1 and t2:
                    matchup_teams = (t2, t1) if (" at " in ql or " @ " in ql) else (t1, t2)
            if not matchup_teams:
                m_between = re.search(r"\bbetween\s+([a-zA-Z]+)\s+and\s+([a-zA-Z]+)\b", ql)
                if m_between:
                    t1 = resolve_team_abbr(m_between.group(1))
                    t2 = resolve_team_abbr(m_between.group(2))
                    if t1 and t2:
                        matchup_teams = (t1, t2)

            if matchup_teams:
                home_t, away_t = matchup_teams
                return {
                    "intent": "sportsbook_report",
                    "subquery": "matchup",
                    "query": query,
                    "home_team": home_t,
                    "away_team": away_t,
                    "season": season,
                    "week": week,
                    "show_field": False,
                    "explanation": f"Sportsbook handicap dossier, spread, moneyline, and total for {away_t} at {home_t} ({season}).",
                }

            return {
                "intent": "sportsbook_report",
                "subquery": "board",
                "query": query,
                "team": team_filter,
                "season": season,
                "week": week,
                "show_field": False,
                "explanation": f"Sportsbook betting board, projected lines, and ATS results{' for Week ' + str(week) if week else ''} ({season}).",
            }

        # Check if user is asking about PLAYER & COACH CONTRACTS / SALARIES
        if any(w in ql for w in (
            "contract", "contracts", "salary", "salaries", "payroll", "cap hit", "apy",
            "guaranteed money", "guarantees", "highest paid", "top paid", "most paid", "best paid"
        )) or bool(re.search(r"\bhow\s+much\s+(?:does|is|do)\b.*\b(?:make|paid|earn)\b", ql)):
            top_m = re.search(r"\btop\s+(\d+)\b", ql)
            lim_val = int(top_m.group(1)) if top_m else 15

            found_contract_name = None
            if player_filter:
                found_contract_name = player_filter
            else:
                for c in NFL_CONTRACTS:
                    if c.name.lower() in ql:
                        found_contract_name = c.name
                        break
                    last_name = c.name.split()[-1].lower()
                    if len(last_name) > 3 and re.search(rf"\b{re.escape(last_name)}\b", ql):
                        found_contract_name = c.name
                        break

            is_coach = any(w in ql for w in ("coach", "coaches", "head coach", "hc", "staff"))
            if found_contract_name:
                return {
                    "intent": "contract_report",
                    "subquery": "player",
                    "query": query,
                    "player": found_contract_name,
                    "season": season,
                    "show_field": False,
                    "explanation": f"Contract details, APY, guarantees, and performance efficiency for {found_contract_name.title()} ({season}).",
                }
            if team_filter and any(w in ql for w in ("payroll", "team", "cap", "salary", "salaries")):
                return {
                    "intent": "contract_report",
                    "subquery": "team",
                    "query": query,
                    "team": team_filter,
                    "season": season,
                    "show_field": False,
                    "explanation": f"Team payroll, active contracts, and cap allocation for {team_filter} ({season}).",
                }
            if is_coach:
                return {
                    "intent": "contract_report",
                    "subquery": "coaches",
                    "query": query,
                    "season": season,
                    "limit": lim_val,
                    "show_field": False,
                    "explanation": "NFL Head Coach contract and salary leaderboard.",
                }
            return {
                "intent": "contract_report",
                "subquery": "leaderboard",
                "query": query,
                "position": position,
                "team": team_filter,
                "season": season,
                "limit": lim_val,
                "show_field": False,
                "explanation": f"NFL contract leaderboard for {position or 'all players'}{' on ' + team_filter if team_filter else ''}.",
            }

        # Check if user is asking about a SPECIFIC PLAY vs an AVERAGE/LEADERBOARD across the year
        ql_without_stat_phrases = re.sub(
            r"\b(?:per\s+play|play[\s_-]*action|explosive\s+play\s+rate|play\s+concept\s+efficiency|passing\s+yard|rushing\s+yard|pass\s+yard|rush\s+yard|which\s+play|what\s+play|which\s+plays|what\s+plays|by\s+play|each\s+play|play\s+concept|play\s+type)\b",
            "",
            ql,
        )
        is_aggregate_request = any(w in ql for w in (
            "average", "avg", "per play", "across the year", "across the season", "leaderboard",
            "rankings", "rank teams", "rank qbs", "rank players", "rank plays", "rank coaches",
            "by team", "by qb", "by player", "by concept", "by play", "by coach",
            "which play", "what play", "which plays", "what plays",
            "which player", "which team", "which coach", "which qb", "which receiver", "which rusher",
            "effectiveness", "meaningful win", "meaningful loss", "impact score",
            "passer rating", "completion", "success rate", "explosive play rate", "cpoe",
            "who had the most", "who has the most", "who led", "who leads", "most", "highest", "leader", "leaders",
            "produces the most", "produces", "produced",
            "turnover", "turnovers", "takeaway", "takeaways",
        ))

        top_m = re.search(r"\btop\s+(\d+)\b", ql)
        limit_val: Optional[int] = int(top_m.group(1)) if top_m else None
        is_latest_game = any(phrase in ql for phrase in (
            "latest game", "last game", "most recent game", "in his latest game",
            "in their latest game", "in the latest game", "in the last game"
        ))
        is_individual_plays_rank = bool(re.search(r"\b(?:top\s+\d+|longest|best|individual|specific)\s+plays?\b", ql)) or (
            bool(re.search(r"\bplays?\b", ql)) and limit_val is not None and not any(w in ql for w in ("per play", "yards per play", "ypp", "explosive play rate"))
        )

        is_specific_play_request = (
            is_individual_plays_rank
            or any(p in ql for p in (
                "specific play", "single play", "show play", "show a play", "show the play",
                "diagram", "on the field", "ascii field", "behind the offense", "behind offense",
                "behind the defense", "behind defense", "longest play", "best play", "top play",
                "touchdown play", "interception play", "sack play",
            ))
            or (bool(re.search(r"\bplays?\b", ql_without_stat_phrases)) and not is_aggregate_request and (
                any(w in ql for w in ("show", "diagram", "longest", "best", "top", "most efficient", "touchdown", "interception", "sack", "yards gained", "in terms of"))
                or player_filter is not None
            ))
        )

        if is_specific_play_request and not (not is_individual_plays_rank and ("average" in ql or "across the year" in ql or is_aggregate_request)):
            concept_filter = "screen" if "screen" in ql else ("play_action_deep" if ("deep" in ql or "play action" in ql) else None)
            extra_filter = "touchdown == 1" if "touchdown" in ql else ("interception == 1" if "interception" in ql else ("sack == 1" if "sack" in ql else ""))
            sort_by = "yards_gained" if any(w in ql for w in ("yard", "yards", "yards gained", "yd", "yds")) else (
                "epa" if ("epa" in ql or "efficient" in ql) else ("wpa" if "wpa" in ql else ("yac" if "yac" in ql else "yards_gained"))
            )
            return {
                "intent": "specific_play",
                "query": query,
                "stat_name": None,
                "group_by": None,
                "season": season,
                "week": week,
                "qtr": qtr,
                "division": division,
                "conf": conf,
                "team": team_filter,
                "player": player_filter,
                "position": position,
                "concept": concept_filter,
                "filter_expr": extra_filter,
                "sort_by": sort_by,
                "camera": camera,
                "limit": limit_val or 1,
                "latest_game": is_latest_game,
                "show_field": True,
                "explanation": f"Top {limit_val or 1} matching plays for {player_filter or 'season'} (sorted by {sort_by}{', latest game' if is_latest_game else ''}).",
            }

        # Match stat using canonical STAT_SYNONYM_MAP first
        matched_stat: Optional[str] = None
        matched_group: Optional[str] = None
        for pat, s_name, def_grp in cls.STAT_SYNONYM_MAP:
            if re.search(pat, ql):
                matched_stat = s_name
                matched_group = def_grp
                break

        # Whole-word matching on registered stats in engine
        if not matched_stat and engine:
            best_len = 0
            for sname, sdef in engine.stats.items():
                for phrase in {sname.lower(), sname.lower().replace("_", " "), sdef.title.strip().lower()}:
                    if len(phrase) < 3 or len(phrase) <= best_len:
                        continue
                    if re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", ql):
                        matched_stat, best_len = sname, len(phrase)
                        matched_group = sdef.group_by

        if not matched_stat:
            if any(w in ql for w in ("meaningful win", "qb win", "pitcher", "meaningful loss", "impact score")):
                return {
                    "intent": "qb_wins_report",
                    "stat_name": "qb_impact_score",
                    "query": query,
                    "group_by": "qb",
                    "season": season,
                    "week": week,
                    "qtr": qtr,
                    "division": division,
                    "conf": conf,
                    "team": team_filter,
                    "player": player_filter,
                    "position": position or "QB",
                    "filter_expr": " and ".join(filter_parts),
                    "show_field": False,
                    "explanation": f"Evaluated per-game MLB-style QB Meaningful Wins (MW), Losses (ML), No-Decisions (ND), and 0-100 Impact Scores for {season}.",
                }
            elif "passer rating" in ql:
                matched_stat = "passer_rating"
                matched_group = "qb"
            elif "any/a" in ql or "adjusted net yards" in ql:
                matched_stat = "any_a"
                matched_group = "qb"
            elif "explosive" in ql:
                matched_stat = "explosive_play_rate"
                matched_group = "team"
            elif "success rate" in ql:
                matched_stat = "success_rate_pct"
                matched_group = "team"
            elif "yac" in ql or "after catch" in ql:
                matched_stat = "yac_over_expected" if "expected" in ql else "yards_after_catch"
                matched_group = "receiver"
            elif "screen" in ql or "screens" in ql:
                matched_stat = "plays"
                matched_group = "team"
            elif "epa" in ql:
                matched_stat = "epa_per_play"
                matched_group = "qb"
            elif any(w in ql for w in ("turnover", "turnovers", "takeaway", "takeaways", "turn overs", "turn over")):
                if any(w in ql for w in ("rate", "pct", "percent", "percentage", "%")):
                    matched_stat = "turnover_rate"
                    matched_group = "team"
                elif any(w in ql for w in ("defense", "defensive", "defenses", "takeaway", "takeaways", "forced", "produced", "produces")):
                    matched_stat = "takeaways"
                    matched_group = "defteam"
                else:
                    matched_stat = "turnovers"
                    matched_group = "team"
            else:
                return {
                    "intent": "ambiguous",
                    "query": query,
                    "stat_name": None,
                    "group_by": None,
                    "season": season,
                    "week": week,
                    "qtr": qtr,
                    "division": division,
                    "conf": conf,
                    "team": team_filter,
                    "player": player_filter,
                    "position": position,
                    "filter_expr": " and ".join(filter_parts),
                    "show_field": False,
                    "explanation": f"Could not determine a specific stat or play from query: '{query}'.",
                }

        if matched_stat in ("turnovers", "takeaways"):
            if any(w in ql for w in ("defense", "defensive", "defenses", "takeaway", "takeaways", "forced", "produced", "produces")):
                matched_stat = "takeaways"
                matched_group = "defteam"

        # Determine group_by override from query
        group_override: Optional[str] = None
        if any(w in ql for w in (
            "by defense", "defense", "defenses", "defensive", "team's defense", "team defense", "defteam"
        )) and not any(w in ql for w in ("behind defense", "behind-defense")):
            group_override = "defteam"
            position = None
        elif any(w in ql for w in ("by qb", "qbs", "each qb", "quarterback", "quarterbacks", "per qb")):
            group_override = "qb"
        elif any(w in ql for w in ("by player", "players", "each player", "per player", "which player", "what player", "who committed")):
            group_override = "player"
        elif any(w in ql for w in ("by receiver", "receivers", "wide receiver", "each receiver", "which receiver", "what receiver", "which wr", "what wr")):
            group_override = "receiver"
        elif any(w in ql for w in ("by rusher", "rushers", "running back", "each rusher", "which rusher", "what rusher", "which rb", "what rb")):
            group_override = "rusher"
        elif any(w in ql for w in ("by team", "teams", "each team", "team's", "per team", "which team", "what team")):
            group_override = "team"
        elif any(w in ql for w in ("by division", "divisions", "each division", "which division", "what division")):
            group_override = "division"
        elif any(w in ql for w in ("by conference", "conferences", "each conference", "which conference", "what conference")):
            group_override = "conference"
        elif any(w in ql for w in (
            "by concept", "play concept", "play concepts", "offensive play", "offensive plays",
            "by play", "by play concept", "per play concept", "play type", "play types",
            "which play", "what play", "which plays", "what plays", "which concept", "what concept",
            "which play concept", "what play concept", "type of play", "types of play", "rank plays",
        )):
            group_override = "play_concept"
        elif any(w in ql for w in ("by coach", "coaches", "each coach", "head coach", "per coach", "best coach", "rank coach", "which coach", "what coach")):
            group_override = "coach"
        elif position:
            pos_map = {"QB": "qb", "RB": "rusher", "WR": "receiver", "TE": "receiver", "K": "player", "P": "player", "DEF": "player"}
            group_override = pos_map.get(position, matched_group)
        elif matched_group:
            group_override = matched_group
        elif player_filter and not group_override:
            group_override = "player" if "player" in GROUP_BY_COLUMN_MAP else "qb"

        receiving_stats = {"yards_after_catch", "yac_over_expected", "receptions", "targets", "receiving_yards", "yac_per_reception"}
        if matched_stat in receiving_stats or matched_group == "receiver":
            if group_override not in ("player", "receiver"):
                group_override = "receiver"

        if matched_stat in ("timeouts", "timeouts_used", "timeouts_called"):
            if "team" in ql:
                group_override = "team"
            elif "coach" in ql or "who " in ql or not group_override:
                group_override = "coach"
        elif matched_stat in ("penalties_drawn", "penalty_yards_drawn", "net_penalties", "net_penalty_yards"):
            if "coach" in ql:
                group_override = "coach"
            elif "team" in ql or not group_override:
                group_override = "team"
        elif matched_stat in ("penalties", "penalty_yards"):
            if any(w in ql for w in ("player", "who committed", "which player", "what player")):
                group_override = "player"
            elif any(w in ql for w in ("coach", "coaches")):
                group_override = "coach"

        if matched_stat == "passing_yards" and position == "RB":
            matched_stat = "rushing_yards"
            matched_group = "rusher"
            group_override = "rusher"

        if group_override == "play_concept" and matched_stat in ("passing_yards", None):
            matched_stat = "yards_per_play"

        if not position and not has_generic_player_prompt:
            if matched_stat in ("rushing_yards", "rush_touchdowns", "yards_per_rush"):
                position = "RB"
            elif matched_stat in ("passing_yards", "passer_rating", "pass_touchdowns", "any_a", "completion_pct", "yards_per_attempt", "qb_impact_score"):
                position = "QB"

        is_leader_query = any(w in ql for w in (
            "who had the most", "who has the most", "which player has the most", "which qb has the most",
            "which running back has the most", "who is leading", "leading in", "leader in", "leaders in",
            "who led", "who leads", "leader", "leaders", "leading", "most", "highest", "best", "top",
            "used the most", "called the most", "had the most", "has had the most", "as had the most",
            "produces the most", "produced the most", "produces", "averages the most",
        ))
        top_m = re.search(r"\btop\s+(\d+)\b", ql)
        limit_val: Optional[int] = None
        if top_m:
            limit_val = int(top_m.group(1))
        elif is_leader_query:
            limit_val = 5

        exp_prefix = f"Evaluated `{matched_stat}` leaders for {season}" if is_leader_query else f"Evaluated `{matched_stat}` across {season}"

        return {
            "intent": "stat_query",
            "query": query,
            "stat_name": matched_stat,
            "group_by": group_override,
            "season": season,
            "week": week,
            "qtr": qtr,
            "division": division,
            "conf": conf,
            "team": team_filter,
            "player": player_filter,
            "position": position,
            "filter_expr": " and ".join([f for f in filter_parts if f]),
            "show_field": False,
            "camera": camera,
            "limit": limit_val,
            "is_leader": is_leader_query,
            "explanation": f"{exp_prefix} (season aggregate/leaderboard — no ASCII field needed).",
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
    division: Optional[str] = None,
    week: Optional[int] = None,
    qtr: Optional[int] = None,
    limit: Optional[int] = None,
    position: Optional[str] = None,
) -> str:
    if stat_name not in engine.stats:
        matches = difflib.get_close_matches(stat_name, list(engine.stats.keys()), n=3, cutoff=0.5)
        hint = f" Did you mean: {', '.join(matches)}?" if matches else " Run `list-stats` or `/stats` to see available stats."
        raise KeyError(f"Unknown stat '{stat_name}'.{hint}")
    sdef = engine.stats[stat_name]
    group_col = group_override if (group_override and group_override in GROUP_BY_COLUMN_MAP) else sdef.group_by
    board = engine.evaluate_stat_leaderboard(
        stat_name, plays, conf=conf, team=team, group_override=group_col, extra_filter=extra_filter, division=division, week=week, qtr=qtr, position=position
    )
    display_board = board[:limit] if (limit and limit > 0) else board

    out: List[str] = []
    if _should_show_table(view_mode, is_play_query=False):
        unit_sfx = f" {sdef.unit}" if sdef.unit else ""
        if group_col in ("play_concept", "penalty_type"):
            group_header = "PLAY CONCEPT" if group_col == "play_concept" else "PENALTY TYPE"
            headers = ["Rank", group_header, f"{sdef.title}", "Plays", "Avg Yds/Play", "EPA/Play", "Success %"]
            rows = []
            for idx, r in enumerate(display_board, 1):
                rows.append([
                    f"#{idx}",
                    f"{C.BOLD}{r['entity']}{C.RESET}",
                    f"{C.BOLD}{C.GREEN}{r['value']:.2f}{unit_sfx}{C.RESET}",
                    r["plays"],
                    f"{r['yards_per_play']:.2f}",
                    f"{r['epa_per_play']:+.2f}",
                    f"{r['success_rate_pct']:.1f}%",
                ])
            alignments = ["right", "left", "right", "right", "right", "right", "right"]
        elif group_col in ("team", "defteam"):
            group_header = "DEFENSE" if group_col == "defteam" else "TEAM"
            headers = ["Rank", group_header, "Conf", f"{sdef.title}", "Plays", "Avg Yds/Play", "EPA/Play", "Success %"]
            rows = []
            for idx, r in enumerate(display_board, 1):
                rows.append([
                    f"#{idx}",
                    f"{C.BOLD}{r['entity']}{C.RESET}",
                    r["conf"],
                    f"{C.BOLD}{C.GREEN}{r['value']:.2f}{unit_sfx}{C.RESET}",
                    r["plays"],
                    f"{r['yards_per_play']:.2f}",
                    f"{r['epa_per_play']:+.2f}",
                    f"{r['success_rate_pct']:.1f}%",
                ])
            alignments = ["right", "left", "center", "right", "right", "right", "right", "right"]
        else:
            group_header = group_col.upper()
            headers = ["Rank", group_header, "Team", "Conf", f"{sdef.title}", "Plays", "Avg Yds/Play", "EPA/Play", "Success %"]
            rows = []
            for idx, r in enumerate(display_board, 1):
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
            alignments = ["right", "left", "center", "center", "right", "right", "right", "right", "right"]
        sub_desc_parts = [str(season)]
        if limit and len(board) > limit:
            sub_desc_parts.append(f"Top {len(display_board)}")
        if position:
            sub_desc_parts.append(f"Pos: {position.upper()}")
        if conf:
            sub_desc_parts.append(conf)
        if division:
            sub_desc_parts.append(division)
        if week is not None:
            sub_desc_parts.append(f"Week {week}")
        if qtr is not None:
            sub_desc_parts.append(f"Q{qtr}" if qtr <= 4 else "OT")
        if team:
            sub_desc_parts.append(team)
        if extra_filter or sdef.filter_expr:
            sub_desc_parts.append(f"Filter: {extra_filter or sdef.filter_expr}")
        title_context = " • ".join(sub_desc_parts)

        out.append(AsciiArtRenderer.render_table(
            f"{sdef.title} ({title_context})",
            headers,
            rows,
            alignments=alignments,
        ))
        if board:
            overall_avg = sum(r["value"] for r in board) / len(board)
            shown_note = f" (showing top {len(display_board)} of {len(board)})" if (limit and len(board) > limit) else ""
            group_label_plural = "Play Concepts" if group_col == "play_concept" else ("Penalty Types" if group_col == "penalty_type" else f"{group_col.upper()}s")
            out.append(
                f"  {C.BOLD}Season Average Across Qualified {group_label_plural}:{C.RESET} "
                f"{C.GOLD}{overall_avg:.2f}{unit_sfx}{C.RESET}  │  "
                f"{C.BOLD}Leader:{C.RESET} {C.CYAN}{board[0]['entity']}{C.RESET} ({board[0]['value']:.2f}{unit_sfx}){shown_note}"
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
            limit=parsed.get("limit"),
            game_id=parsed.get("game_id"),
        ))
    return "\n".join(out)


def render_specific_play_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: Optional[int] = None,
    conf: Optional[str] = None,
    team: Optional[str] = None,
    player: Optional[str] = None,
    qb: Optional[str] = None,
    concept: Optional[str] = None,
    play_type: Optional[str] = None,
    filter_expr: str = "",
    sort_by: str = "yards_gained",
    play_id: Optional[int] = None,
    game_id: Optional[str] = None,
    camera: str = "behind-offense",
    limit: Optional[int] = None,
) -> str:
    target_player = player or qb
    matched = engine.query_plays(
        plays,
        season=season,
        conf=conf,
        team=team,
        player=target_player,
        qb=target_player,
        concept=concept,
        play_type=play_type,
        filter_expr=filter_expr,
        sort_by=sort_by,
        play_id=play_id,
        game_id=game_id,
    )
    if not matched:
        return f"\n{C.RED}No matching play found for the given criteria.{C.RESET}"

    out: List[str] = []
    display_plays = matched[:limit] if (limit and limit > 1) else [matched[0]]
    if limit and limit > 1 and len(matched) > 1:
        headers = ["Rank", "Play ID", "Qtr", "Down & Dist", "Yards", "EPA", "Concept", "Description"]
        rows = []
        for idx, p in enumerate(display_plays, 1):
            down_val = p.get("down")
            down_str = f"{down_val}&{p.get('ydstogo', '')}" if down_val else "-"
            concept_str = str(p.get("play_concept") or p.get("play_type") or "scrimmage")
            desc_raw = str(p.get("desc", ""))
            desc_short = desc_raw[:55] + "..." if len(desc_raw) > 55 else desc_raw
            rows.append([
                f"#{idx}",
                f"{p.get('play_id', '')}",
                f"Q{p.get('qtr', '')}",
                down_str,
                f"{C.BOLD}{C.GREEN}{float(p.get('yards_gained', 0.0)):.1f} yds{C.RESET}",
                f"{float(p.get('epa', 0.0)):+.2f}",
                concept_str,
                desc_short,
            ])
        top_title = f"Top {len(display_plays)} Plays"
        if target_player:
            top_title += f" for {target_player}"
        if game_id:
            top_title += f" ({game_id})"
        top_title += f" • Sorted by {sort_by}"
        out.append(AsciiArtRenderer.render_table(
            top_title,
            headers,
            rows,
            alignments=["right", "center", "center", "center", "right", "right", "left", "left"],
        ))
        out.append("")

    chosen = display_plays[0]
    p_name = (
        chosen.get("player_name")
        or chosen.get("receiver_player_name")
        or chosen.get("rusher_player_name")
        or chosen.get("kicker_player_name")
        or chosen.get("punter_player_name")
        or chosen.get("qb_name")
        or target_player
        or "Play"
    )
    title = f"SPECIFIC PLAY DIAGRAM — {p_name} ({chosen.get('posteam', '')} vs {chosen.get('defteam', '')} • {float(chosen.get('yards_gained', 0.0)):.1f} yds)"
    out.append(AsciiArtRenderer.render_field_and_play(chosen, title=title, camera=camera))
    return "\n".join(out)


def render_qb_meaningful_wins_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: Optional[str],
    view_mode: str = "auto",
    camera: str = "behind-offense",
    team: Optional[str] = None,
) -> str:
    eval_engine = engine
    needed_example_stats = [k for k in ("qb_impact_score", "qb_meaningful_win", "qb_meaningful_loss") if k not in engine.stats]
    if needed_example_stats:
        eval_engine = copy.copy(engine)
        eval_engine.stats = dict(engine.stats)
        for k in needed_example_stats:
            eval_engine.stats[k] = EXAMPLE_CUSTOM_STATS[k]

    board = eval_engine.evaluate_stat_leaderboard("qb_impact_score", plays, conf=conf, team=team, group_override="qb")
    sdef_win = eval_engine.stats["qb_meaningful_win"]
    sdef_loss = eval_engine.stats["qb_meaningful_loss"]
    sdef_imp = eval_engine.stats["qb_impact_score"]

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


def render_custom_stat_example_walkthrough(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int = CURRENT_SEASON,
    conf: Optional[str] = None,
    team: Optional[str] = None,
) -> str:
    """
    Interactive guide demonstrating how to design and build custom stats in nfl-stat-cli,
    using MLB-style QB Meaningful Wins (MW / ML) and QB Impact Score as the canonical example.
    """
    s_plays = plays_for_season(plays, season)
    display_season = season
    if not s_plays:
        avail = available_seasons(plays)
        if avail:
            display_season = avail[-1]
            s_plays = plays_for_season(plays, display_season)
        else:
            s_plays = plays
    report_table = render_qb_meaningful_wins_view(engine, s_plays, display_season, conf=conf, view_mode="table", team=team)

    guide_lines = [
        f"\n{C.BOLD}{C.GOLD}╔═══════════════════════════════════════════════════════════════════════════════════════╗",
        f"║  🏈  HOW TO BUILD A CUSTOM STAT (FEATURED EXAMPLE: MLB-STYLE QB WINS)                 ║",
        f"╚═══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        f"\n{C.BOLD}{C.CYAN}1. The Concept & Problem to Solve:{C.RESET}",
        f"   In traditional NFL box scores, 'QB Wins' (`team_win == 1`) credit the quarterback even when",
        f"   the defense carries a subpar performance, or tag them with a loss in a 42-38 shootout.",
        f"   {C.GREEN}Goal:{C.RESET} Build an MLB-pitcher style Decision System — Meaningful Wins (MW), Meaningful Losses (ML),",
        f"   and No-Decisions (ND) based on whether the QB met an objective performance threshold.",
        f"\n{C.BOLD}{C.CYAN}2. The 3-Step Construction in nfl-stat-cli:{C.RESET}",
        f"   {C.BOLD}Step A: Select Evaluation Scope{C.RESET}",
        f"     • Scope: `{C.YELLOW}game{C.RESET}` (evaluates each individual game rather than the full season aggregate)",
        f"     • Aggregation: `{C.YELLOW}sum{C.RESET}` (sums the 1s and 0s across all games in the season)",
        f"     • Group Dimension: `{C.YELLOW}qb{C.RESET}`",
        f"",
        f"   {C.BOLD}Step B: Layer Composable Custom Stats{C.RESET}",
        f"     • {C.BOLD}Base Metric 1 (0–100 Game Impact Score):{C.RESET}",
        f"       `qb_impact_score = clamp(50 + (epa_per_play * 18.0) + (wpa_per_game * 85.0) + (avg_cpoe * 0.85) - (turnover_rate * 120.0), 0, 100)`",
        f"     • {C.BOLD}Base Metric 2 (Meaningful Win):{C.RESET} Awarded ONLY when the team won AND QB impact was high:",
        f"       `qb_meaningful_win = ifelse((team_win == 1) and (qb_impact_score >= 55.0), 1, 0)`",
        f"     • {C.BOLD}Base Metric 3 (Meaningful Loss):{C.RESET} Charged ONLY when the team lost AND QB impact was low:",
        f"       `qb_meaningful_loss = ifelse((team_win == 0) and (qb_impact_score <= 42.0), 1, 0)`",
        f"     • {C.BOLD}No-Decision (ND):{C.RESET} Games won despite sub-55 impact, or lost despite heroic 43+ impact!",
        f"",
        f"   {C.BOLD}Step C: Three Ways You Can Build Any Custom Stat:{C.RESET}",
        f"     1. {C.BOLD}Interactive Builder:{C.RESET} Type {C.CYAN}/create{C.RESET} in the prompt to launch the step-by-step wizard.",
        f"     2. {C.BOLD}Natural Language:{C.RESET} Type directly in plain English:",
        f"        {C.DIM}\"create stat called clutch_win with formula ifelse(epa_per_play > 0.15 and team_win == 1, 1, 0) by qb\"{C.RESET}",
        f"     3. {C.BOLD}CLI Command:{C.RESET}",
        f"        {C.DIM}nfl-stat create-stat --name qb_meaningful_win --scope game --agg sum --formula \"ifelse((team_win == 1) and (qb_impact_score >= 55.0), 1, 0)\" --title \"Meaningful Win\" --description \"...\" --explained \"...\"{C.RESET}",
        f"\n{C.BOLD}{C.GREEN}3. Live Example Demonstration ({display_season} Leaderboard):{C.RESET}\n",
        report_table,
    ]
    return "\n".join(guide_lines)


def render_screen_pass_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: Optional[str],
    view_mode: str = "auto",
    camera: str = "behind-offense",
    team: Optional[str] = None,
) -> str:
    """Render screen pass plays using standard yardage efficiency and play filtering."""
    return render_general_stat_view(
        engine,
        plays,
        stat_name="yards_per_play",
        season=season,
        conf=conf,
        team=team,
        extra_filter="is_screen == 1",
        view_mode=view_mode,
        camera=camera,
    )


def render_play_efficiency_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    conf: str,
    view_mode: str = "auto",
    camera: str = "behind-offense",
    team: Optional[str] = None,
) -> str:
    board = engine.evaluate_stat_leaderboard("yards_per_play", plays, conf=conf, team=team, group_override="play_concept")
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


def render_stat_page(
    engine: StatEngine,
    all_plays: List[Dict[str, Any]],
    show_progress: bool = True,
) -> str:
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    pinned = [s for s in engine.stat_page.get("pinned_stats", []) if s in engine.stats]
    total_pinned = len(pinned)
    loaded = available_seasons(all_plays)
    cur_season = loaded[-1] if loaded else CURRENT_SEASON
    prev_season = cur_season - 1

    if show_progress:
        seasons_str = f"{prev_season} (lookback) and {cur_season} (current)" if len(loaded) >= 2 else f"season {cur_season}"
        intro_msg = f"  {C.BOLD}{C.GOLD}Loading...{C.RESET} {C.DIM}Evaluating Saved Stat Page tracking across {seasons_str} for {total_pinned} pinned metrics...{C.RESET}"
        if is_tty:
            sys.stdout.write(f"\n{intro_msg}\n")
            sys.stdout.flush()
        else:
            print(f"\n{intro_msg}", flush=True)

    def _progress_cb(stat_name: str, cur_idx: int, total: int) -> None:
        if not show_progress:
            return
        pct = int(cur_idx * 100 / max(total, 1))
        bar_len = 24
        filled = int(bar_len * cur_idx / max(total, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        stat_title = engine.stats[stat_name].title if stat_name in engine.stats else stat_name
        msg = f"\r  {C.BOLD}{C.GOLD}Loading... [{bar}] {pct:3d}%{C.RESET} {C.DIM}Evaluating [{stat_name}] ({stat_title[:32]}) across seasons ({cur_idx}/{total})...{C.RESET}"
        if is_tty:
            sys.stdout.write(msg[:120].ljust(120))
            sys.stdout.flush()

    page = engine.update_stat_page_tracking(
        all_plays,
        on_progress=_progress_cb if show_progress else None,
    )

    if show_progress and is_tty:
        sys.stdout.write("\r" + " " * 120 + "\r")
        sys.stdout.flush()
    headers = ["Stat ID", "Title", "Type", "Scope", f"{prev_season} Lookback Leader", f"{cur_season} Current Leader", "YoY Avg Trend", "Formula / Basis"]
    rows = []
    for sname in page.get("pinned_stats", []):
        if sname not in engine.stats:
            continue
        sdef = engine.stats[sname]
        hist = page.get("lookback_history", {}).get(sname, {})
        h24 = hist.get(str(prev_season))
        h25 = hist.get(str(cur_season))
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
        f"📌 SAVED STAT PAGE — Lookback ({prev_season}) & Forward Tracking ({cur_season}) • Updated {page.get('last_updated')}",
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


def render_dataset_info_view(
    all_plays: List[Dict[str, Any]],
    parsed: Dict[str, Any],
) -> str:
    subquery = parsed.get("subquery", "last_game")
    season_val = parsed.get("season")
    season_explicit = bool(re.search(r"\b20\d{2}\b", str(parsed.get("query", ""))))
    target_season = season_val if season_explicit else None
    summaries = extract_games_summary(all_plays, season=target_season)
    if not summaries and target_season is not None:
        summaries = extract_games_summary(all_plays)

    week_flt = parsed.get("week")
    if week_flt is not None:
        summaries = [g for g in summaries if g["week"] == week_flt]

    team_flt = parsed.get("team")
    if team_flt:
        t_up = team_flt.upper()
        summaries = [g for g in summaries if t_up in (g["away_team"], g["home_team"])]

    div_flt = parsed.get("division")
    if div_flt:
        div_clean = div_flt.strip().lower()
        summaries = [
            g for g in summaries
            if TEAM_DIVISIONS.get(g["away_team"], "").lower() == div_clean
            or TEAM_DIVISIONS.get(g["home_team"], "").lower() == div_clean
        ]

    if not summaries:
        avail = ", ".join(map(str, available_seasons(all_plays))) or "none"
        return (
            f"\n  {C.YELLOW}⚠ No games found matching query criteria in loaded dataset.{C.RESET}\n"
            f"  {C.DIM}Loaded seasons: {avail}. Total play records: {len(all_plays)}.{C.RESET}"
        )

    summaries.sort(key=lambda g: (int(g["season"]), int(g["week"]), str(g["game_id"])))

    if subquery == "last_game" or any(w in str(parsed.get("query", "")).lower() for w in ("last", "latest", "most recent", "newest")):
        last_g = summaries[-1]
        gid = last_g["game_id"]
        away = last_g["away_team"]
        home = last_g["home_team"]
        a_sc = last_g["away_score"]
        h_sc = last_g["home_score"]
        wk = last_g["week"]
        sea = last_g["season"]
        ot_txt = "Yes (Overtime)" if last_g.get("has_ot") else "No (Regulation)"
        if h_sc > a_sc:
            winner_str = f"{home} (+{h_sc - a_sc})"
        elif a_sc > h_sc:
            winner_str = f"{away} (+{a_sc - h_sc})"
        else:
            winner_str = "Tied"
        quarters_str = ", ".join(f"Q{q}" if q <= 4 else "OT" for q in last_g.get("quarters", [1, 2, 3, 4]))

        total_games_all = len(extract_games_summary(all_plays))
        avail_seasons = ", ".join(map(str, available_seasons(all_plays)))

        lines = [
            f"\n{C.BOLD}{C.CYAN}══════════════════════════════════════════════════════════════════════════════{C.RESET}",
            f"{C.BOLD}🏈 LATEST LOADED GAME IN DATASET{C.RESET}",
            f"{C.BOLD}{C.CYAN}══════════════════════════════════════════════════════════════════════════════{C.RESET}",
            f"  • {C.BOLD}Game ID:{C.RESET}       {C.GREEN}{gid}{C.RESET} ({sea} Season • Week {wk})",
            f"  • {C.BOLD}Matchup:{C.RESET}       {away} @ {home}",
            f"  • {C.BOLD}Final Score:{C.RESET}   {away} {a_sc} – {home} {h_sc} ({C.BOLD}Winner:{C.RESET} {winner_str})",
            f"  • {C.BOLD}Quarters:{C.RESET}      {quarters_str} ({ot_txt})",
            f"  • {C.BOLD}Play Records:{C.RESET}  {last_g['total_plays']} snaps logged in dataset",
            f"{C.CYAN}──────────────────────────────────────────────────────────────────────────────{C.RESET}",
            f"  {C.BOLD}📊 Dataset Overview:{C.RESET}",
            f"    • Total Games Loaded:   {total_games_all} game(s) across seasons: [{avail_seasons}]",
            f"    • Total Plays Loaded:   {len(all_plays)} play-by-play events",
            f"    • Interactive Browser:  Type {C.CYAN}/games{C.RESET} or {C.CYAN}/games {wk}{C.RESET} to explore quarter-by-quarter plays",
            f"{C.BOLD}{C.CYAN}══════════════════════════════════════════════════════════════════════════════{C.RESET}",
        ]
        return "\n".join(lines)

    headers = ["Week", "Game ID", "Away", "Home", "Score", "Quarters", "Snaps"]
    rows = []
    for g in summaries:
        score_str = f"{g['away_team']} {g['away_score']} - {g['home_team']} {g['home_score']}"
        q_str = "OT" if g.get("has_ot") else f"{len(g.get('quarters', [1,2,3,4]))} Qtrs"
        rows.append([
            f"Wk {g['week']}",
            g['game_id'],
            g['away_team'],
            g['home_team'],
            score_str,
            q_str,
            g['total_plays'],
        ])
    tbl = AsciiArtRenderer.render_table(
        f"NFL Loaded Games ({len(summaries)} games in dataset)",
        headers,
        rows,
        alignments=["center", "left", "center", "center", "center", "center", "right"],
    )
    return f"\n{tbl}\n  {C.DIM}Tip: Type `/games` to browse games or `/games <week>` to inspect a matchup.{C.RESET}"


def handle_nl_query_result(
    parsed: Dict[str, Any],
    engine: StatEngine,
    all_plays: List[Dict[str, Any]],
    view_override: str = "auto",
    camera_override: Optional[str] = None,
    interactive: bool = False,
) -> str:
    intent = parsed.get("intent", "stat_query")
    if intent == "ambiguous":
        stat_list = ", ".join(list(engine.stats.keys())[:8]) + "..."
        return (
            f"\n{C.BOLD}{C.RED}\u2716 Unsupported or ambiguous query:{C.RESET} \"{parsed.get('query', '')}\"\n"
            f"  {C.YELLOW}\U0001f4a1 Could not match your question to a recognized stat, play diagram, or custom stat action.{C.RESET}\n"
            f"  \u2022 {C.BOLD}To evaluate a stat:{C.RESET} try 'epa per play', 'passer rating', 'yards after catch', or 'qb impact score'.\n"
            f"  \u2022 {C.BOLD}To diagram a play:{C.RESET} try 'show Mahomes touchdown play' or 'diagram Goff screen play'.\n"
            f"  \u2022 {C.BOLD}Available stats:{C.RESET} {stat_list} (type {C.CYAN}/stats{C.RESET} for full catalog, or {C.CYAN}/help{C.RESET} for guidance)."
        )

    slm_tag = f" [SLM: {parsed['slm_model_used']}]" if parsed.get("slm_model_used") else " [Local Rule/AST Parser]"
    header = f"\n{C.BOLD}{C.CYAN}🤖 Query Interpretation{slm_tag}:{C.RESET} {parsed.get('explanation', '')}"

    if intent == "dataset_info":
        return header + "\n" + render_dataset_info_view(all_plays, parsed)

    season = int(parsed.get("season") or CURRENT_SEASON)
    season_explicit = bool(re.search(r"\b20\d{2}\b", str(parsed.get("query", ""))))
    if not season_explicit and not plays_for_season(all_plays, season):
        avail = available_seasons(all_plays)
        if avail:
            season = max(avail)

    s_plays = require_season_plays(all_plays, season)
    conf = parsed.get("conf")
    team = parsed.get("team")
    division = parsed.get("division")
    week = parsed.get("week")
    qtr = parsed.get("qtr")
    player = parsed.get("player") or parsed.get("qb")
    camera = camera_override or parsed.get("camera") or "behind-offense"

    if division:
        div_low = division.strip().lower()
        div_filtered = [p for p in s_plays if str(p.get("division", "")).strip().lower() == div_low]
        if div_filtered:
            s_plays = div_filtered
    if week is not None:
        w_filtered = [p for p in s_plays if int(p.get("week", -999)) == int(week)]
        if w_filtered:
            s_plays = w_filtered
    if qtr is not None:
        q_filtered = [p for p in s_plays if int(p.get("qtr", -999)) == int(qtr)]
        if q_filtered:
            s_plays = q_filtered

    if parsed.get("latest_game") and s_plays:
        target_p = player or parsed.get("qb")
        game_filtered = None
        if target_p:
            p_parts = str(target_p).strip().split()
            candidates = {str(target_p).lower()}
            if len(p_parts) >= 2:
                candidates.add(f"{p_parts[0][0].lower()}.{p_parts[-1].lower()}")
                candidates.add(p_parts[-1].lower())
            matching_player_plays = [
                p for p in s_plays
                if any(
                    c in str(p.get("player_name", "")).lower()
                    or c in str(p.get("qb_name", "")).lower()
                    or c in str(p.get("receiver_player_name", "")).lower()
                    or c in str(p.get("rusher_player_name", "")).lower()
                    or c in str(p.get("desc", "")).lower()
                    for c in candidates
                )
            ]
            if matching_player_plays:
                best_play = max(matching_player_plays, key=lambda x: (_safe_int(x.get("week"), 0), str(x.get("game_id", ""))))
                latest_gid = best_play.get("game_id")
                if latest_gid:
                    game_filtered = [p for p in s_plays if str(p.get("game_id")) == str(latest_gid)]
        elif team:
            t_clean = resolve_team_abbr(team) or team
            team_plays = [p for p in s_plays if str(p.get("posteam", "")).upper() == t_clean.upper() or str(p.get("defteam", "")).upper() == t_clean.upper()]
            if team_plays:
                best_play = max(team_plays, key=lambda x: (_safe_int(x.get("week"), 0), str(x.get("game_id", ""))))
                latest_gid = best_play.get("game_id")
                if latest_gid:
                    game_filtered = [p for p in s_plays if str(p.get("game_id")) == str(latest_gid)]
        if not game_filtered:
            best_play = max(s_plays, key=lambda x: (_safe_int(x.get("week"), 0), str(x.get("game_id", ""))))
            latest_gid = best_play.get("game_id")
            if latest_gid:
                game_filtered = [p for p in s_plays if str(p.get("game_id")) == str(latest_gid)]
        if game_filtered:
            s_plays = game_filtered

    if intent in ("stat_page", "page"):
        return header + "\n" + render_stat_page(engine, all_plays)

    if intent == "delete_stat":
        stat_to_del = parsed.get("stat_name", "")
        try:
            deleted = engine.delete_custom_stat(stat_to_del)
            return header + f"\n  {C.GREEN}✔ Successfully deleted custom stat `{deleted.name}` ({deleted.title}).{C.RESET}"
        except (KeyError, ValueError) as err:
            return header + f"\n  {C.RED}✖ {err}{C.RESET}"

    if intent == "coaching_staff":
        resolved_t = resolve_team_abbr(team) or team or "KC"
        return header + "\n" + render_coaching_staff_view(resolved_t, role_filter=parsed.get("role"))

    if intent == "team_drilldown":
        resolved_t = resolve_team_abbr(team) or team or "KC"
        return header + "\n" + render_team_drilldown_view(engine, s_plays, season, resolved_t)

    if intent == "player_drilldown":
        target_player = player or "Mahomes"
        return header + "\n" + render_player_drilldown_view(engine, s_plays, season, target_player, team=team, interactive=False)

    if intent == "fantasy_report":
        subq = parsed.get("subquery", "leaderboard")
        target_p = parsed.get("player") or player
        scoring = parsed.get("scoring_format") or "ppr"
        if subq == "player" and target_p:
            return header + "\n" + render_player_fantasy_profile_view(target_p, s_plays, season=season)
        pos = parsed.get("position")
        w_filter = parsed.get("week")
        lim = parsed.get("limit") or 15
        return header + "\n" + render_fantasy_leaderboard_view(
            s_plays, season=season, scoring_format=scoring, position=pos, week=w_filter, limit=lim
        )

    if intent == "sportsbook_report":
        subq = parsed.get("subquery", "board")
        if subq == "power_ratings":
            return header + "\n" + render_power_ratings_view(s_plays, season=season)
        if subq == "matchup":
            home_t = parsed.get("home_team") or team or "KC"
            away_t = parsed.get("away_team") or "BUF"
            w_val = parsed.get("week")
            return header + "\n" + render_game_handicap_dossier_view(home_t, away_t, s_plays, season=season, week=w_val)
        w_filter = parsed.get("week")
        return header + "\n" + render_sportsbook_board_view(s_plays, season=season, week_filter=w_filter)

    if intent == "contract_report":
        subq = parsed.get("subquery", "leaderboard")
        target_p = parsed.get("player") or player
        if subq == "player" and target_p:
            return header + "\n" + render_player_contract_view(target_p, plays=s_plays, season=season)
        if subq == "team":
            target_t = resolve_team_abbr(team) or team or "KC"
            return header + "\n" + render_team_payroll_view(target_t)
        if subq == "coaches":
            return header + "\n" + render_contracts_leaderboard_view(contract_type="coach", limit=parsed.get("limit", 15))
        pos = parsed.get("position")
        return header + "\n" + render_contracts_leaderboard_view(
            contract_type="player", position_filter=pos, team_filter=team, limit=parsed.get("limit", 15)
        )

    if intent == "create_stat":
        stat_name = parsed.get("stat_name", "custom_stat")
        title = parsed.get("title", "Custom Stat")
        group_by = parsed.get("group_by") or "qb"
        formula = parsed.get("formula", "yards_per_play")
        description = parsed.get("explanation", "User-created custom stat.")
        filter_expr = parsed.get("filter_expr", "")
        scope = parsed.get("scope", "season")
        agg = parsed.get("agg", "formula")

        save_stat = parsed.get("save_stat")
        if save_stat is None:
            if interactive:
                try:
                    ans = prompt_input(
                        f"\n  {C.CYAN}? Save custom stat '{stat_name}' permanently to your catalog? [Y/n] (default: Y): {C.RESET}"
                    ).strip().lower()
                    save_stat = ans not in ("n", "no")
                except (EOFError, KeyboardInterrupt):
                    save_stat = False
            else:
                save_stat = True

        sdef = engine.register_custom_stat(
            name=stat_name,
            title=title,
            group_by=group_by,
            formula=formula,
            description=description,
            calculation_explained=f"Evaluated via formula `{formula}` (scope={scope}).",
            filter_expr=filter_expr,
            scope=scope,
            agg=agg,
            pin_to_page=save_stat,
            persist=save_stat,
        )
        status_msg = (
            f"  {C.GREEN}✔ Saved '{sdef.name}' permanently to custom_stats.json and pinned to Stat Page.{C.RESET}\n"
            if save_stat
            else f"  {C.YELLOW}ℹ Evaluated '{sdef.name}' for this session only (not saved to custom_stats.json).{C.RESET}\n"
        )
        return header + "\n" + status_msg + render_general_stat_view(
            engine, s_plays, sdef.name, season, conf=conf, team=team, view_mode="table", division=division, week=week, qtr=qtr
        )

    if intent == "specific_play" or parsed.get("show_field") is True:
        return header + "\n" + render_specific_play_view(
            engine,
            s_plays,
            season=season,
            conf=conf,
            team=team,
            player=player,
            qb=player,
            concept=parsed.get("concept"),
            filter_expr=parsed.get("filter_expr", ""),
            sort_by=parsed.get("sort_by", "yards_gained"),
            camera=camera,
            limit=parsed.get("limit"),
            game_id=parsed.get("game_id"),
        )

    if player:
        p_low = str(player).lower()
        player_filtered = [
            p for p in s_plays
            if p_low in str(p.get("player_name", "")).lower()
            or p_low in str(p.get("qb_name", "")).lower()
            or p_low in str(p.get("receiver_player_name", "")).lower()
            or p_low in str(p.get("rusher_player_name", "")).lower()
            or p_low in str(p.get("kicker_player_name", "")).lower()
            or p_low in str(p.get("punter_player_name", "")).lower()
            or p_low in str(p.get("desc", "")).lower()
        ]
        if player_filtered:
            s_plays = player_filtered

    if intent == "qb_wins_report":
        return header + "\n" + render_qb_meaningful_wins_view(engine, s_plays, season, conf, view_mode=view_override, camera=camera, team=team)

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
        division=division,
        week=week,
        qtr=qtr,
        limit=parsed.get("limit"),
        position=parsed.get("position"),
    )


# ---------------------------------------------------------------------------
# Phase Categorization, Play Deep Dive, and Team/Player Drill-Down Views
# ---------------------------------------------------------------------------

def classify_play_phase(p: Dict[str, Any]) -> str:
    """Classify a play into 'offense', 'defense', or 'special_teams'."""
    pt = str(p.get("play_type", "")).lower()
    desc = str(p.get("desc", "")).lower()
    if pt in ("field_goal", "extra_point", "punt", "kickoff") or any(k in desc for k in ("field goal", "punt", "punts", "kicks", "extra point", "touchback")):
        return "special_teams"
    if int(p.get("sack", 0)) == 1 or int(p.get("interception", 0)) == 1 or int(p.get("fumble_lost", 0)) == 1 or "sacked" in desc or "intercepted" in desc or pt == "defense":
        return "defense"
    return "offense"


def filter_plays_by_phase(plays: List[Dict[str, Any]], phase: str) -> List[Dict[str, Any]]:
    """Filter plays for a season down to the chosen unit/phase ('offense', 'defense', or 'special_teams')."""
    ph = phase.strip().lower()
    if ph in ("defense", "def", "d", "2"):
        res = [p for p in plays if classify_play_phase(p) == "defense"]
        return res if res else plays
    elif ph in ("special_teams", "special", "st", "sp", "3"):
        res = [p for p in plays if classify_play_phase(p) == "special_teams"]
        return res
    else:  # offense
        res = [p for p in plays if classify_play_phase(p) == "offense"]
        return res if res else plays


def classify_play_concept_hierarchy(p: Dict[str, Any]) -> Dict[str, str]:
    """
    Classify a play into a 3-tier taxonomy:
    phase (offense/defense/special_teams) -> category (pass/run/trick/pass_rush/takeaway/run_stop/etc.) -> concept_key/name
    """
    phase = classify_play_phase(p)
    pt = str(p.get("play_type", "")).lower()
    desc = str(p.get("desc", "")).lower()
    conc = str(p.get("play_concept", "")).lower()

    if phase == "special_teams":
        if pt in ("field_goal", "extra_point") or "field goal" in desc or "extra point" in desc:
            return {"phase": "special_teams", "category": "field_goal", "concept_key": "field_goal", "concept_name": "Field Goal & Extra Point"}
        if pt == "punt" or "punt" in desc:
            return {"phase": "special_teams", "category": "punt", "concept_key": "punt", "concept_name": "Punt & Coverage"}
        return {"phase": "special_teams", "category": "field_goal", "concept_key": "field_goal", "concept_name": "Special Teams Unit"}

    if phase == "defense":
        if int(p.get("interception", 0)) == 1 or "intercepted" in desc or "fumble recovered" in desc or "recovered by" in desc:
            return {"phase": "defense", "category": "takeaway", "concept_key": "turnover_interception", "concept_name": "Takeaways & Interceptions"}
        if int(p.get("sack", 0)) == 1 or "sacked" in desc:
            return {"phase": "defense", "category": "pass_rush", "concept_key": "pass_rush_sack", "concept_name": "Pass Rush & Sacks"}
        return {"phase": "defense", "category": "run_stop", "concept_key": "tfl_run_stop", "concept_name": "Run Stops & Tackles for Loss"}

    # Offense
    if pt == "run":
        if "scramble" in desc or p.get("qb_name") == p.get("rusher_player_name"):
            return {"phase": "offense", "category": "run", "concept_key": "qb_scramble", "concept_name": "QB Keep & Scramble"}
        if conc == "rush_outside" or any(w in desc for w in ("outside", "end", "sweep", "pitch")):
            return {"phase": "offense", "category": "run", "concept_key": "rush_outside", "concept_name": "Outside Zone & Stretch"}
        if any(w in desc for w in ("power", "counter", "guard", "pull")):
            return {"phase": "offense", "category": "run", "concept_key": "power_gap", "concept_name": "Power & Counter Gap"}
        return {"phase": "offense", "category": "run", "concept_key": "rush_inside", "concept_name": "Inside Zone & Dive"}

    # Pass
    if int(p.get("is_screen", 0)) == 1 or "screen" in desc or conc == "screen":
        return {"phase": "offense", "category": "pass", "concept_key": "screen", "concept_name": "Screen Pass"}
    if int(p.get("play_action", 0)) == 1 or "play_action" in conc or "deep" in desc or float(p.get("air_yards", 0.0)) >= 20.0:
        return {"phase": "offense", "category": "pass", "concept_key": "play_action_deep", "concept_name": "Play-Action Deep Shot"}
    if float(p.get("air_yards", 0.0)) <= 6.0 or any(w in desc for w in ("short", "slant", "flat", "hitch")):
        return {"phase": "offense", "category": "pass", "concept_key": "quick_slant", "concept_name": "Quick Game & Slant"}
    return {"phase": "offense", "category": "pass", "concept_key": "intermediate_cross", "concept_name": "Intermediate Crosser & Mesh"}


def filter_plays_by_concept_key(plays: List[Dict[str, Any]], concept_key: str) -> List[Dict[str, Any]]:
    """Filter plays down to those matching the given tactical concept key."""
    ck = concept_key.lower().strip()
    return [p for p in plays if classify_play_concept_hierarchy(p)["concept_key"] == ck]


def get_play_key_players(play: Dict[str, Any]) -> List[str]:
    """Extract names of key players involved in a play (passer, receiver, rusher, defensive stopper)."""
    names: List[str] = []
    for k in ("qb_name", "receiver_player_name", "rusher_player_name", "kicker_player_name", "punter_player_name", "player_name"):
        v = str(play.get(k) or "").strip()
        if v and v not in names and v.lower() not in ("none", "null", "unknown", ""):
            names.append(v)
    desc = str(play.get("desc", ""))
    m_int = re.search(r"INTERCEPTED by ([A-Z]\.[A-Za-z\-]+)", desc)
    if m_int and m_int.group(1) not in names:
        names.append(m_int.group(1))
    m_sack = re.search(r"sacked.*?\(([A-Z]\.[A-Za-z\-]+)\)", desc)
    if m_sack and m_sack.group(1) not in names:
        names.append(m_sack.group(1))
    return names


def render_single_play_deep_dive(play: Dict[str, Any]) -> str:
    """Render an in-depth analytics card for an individual play (EPA, WPA, Air Yards, YAC, Situation)."""
    pid = play.get("play_id", "N/A")
    gid = play.get("game_id", "N/A")
    qtr = play.get("qtr", 1)
    down = play.get("down", 1)
    ydstogo = play.get("ydstogo", 10)
    ydline = int(play.get("yardline_100", 50))
    spot = AsciiArtRenderer._format_spot(ydline)
    post = play.get("posteam", "OFF")
    defe = play.get("defteam", "DEF")
    h_score = play.get("home_score", 0)
    a_score = play.get("away_score", 0)
    ptype = str(play.get("play_type", "scrimmage")).upper()
    concept = play.get("play_concept", "standard")
    direction = play.get("play_direction", "middle")
    yards = float(play.get("yards_gained", 0.0))
    air = float(play.get("air_yards", 0.0))
    yac = float(play.get("yards_after_catch", 0.0))
    xyac = float(play.get("xyac_mean_yardage", 0.0))
    epa = float(play.get("epa", 0.0))
    wpa = float(play.get("wpa", 0.0))
    cpoe = float(play.get("cpoe", 0.0))
    is_td = int(play.get("touchdown", 0)) == 1
    is_int = int(play.get("interception", 0)) == 1
    is_sack = int(play.get("sack", 0)) == 1
    is_screen = int(play.get("is_screen", 0)) == 1
    is_pa = int(play.get("play_action", 0)) == 1
    success = int(play.get("series_success", 0)) == 1
    desc = play.get("desc", "No description available.")

    lines = [
        f"\n{C.BOLD}{C.CYAN}┌────────────────────────────────────────────────────────────────────────────────────────┐",
        f"│                     🏈 IN-DEPTH PLAY ANALYTICS & SITUATION                             │",
        f"├────────────────────────────────────────────────────────────────────────────────────────┤{C.RESET}",
        f"  Play ID: {C.BOLD}#{pid}{C.RESET}  |  Game: {gid}  |  Quarter: Q{qtr}  |  Matchup: {post} vs {defe} ({h_score}-{a_score})",
        f"  Situation: {C.BOLD}{down} & {ydstogo}{C.RESET} at {spot} ({ydline} yds to endzone)  |  Red Zone: {'YES' if play.get('red_zone') else 'NO'}",
        f"  Formation: Shotgun={'YES' if play.get('shotgun') else 'NO'} • No-Huddle={'YES' if play.get('no_huddle') else 'NO'}",
        "",
        f"  {C.BOLD}{C.GOLD}Concept & Execution:{C.RESET}",
        f"    • Type: {C.BOLD}{ptype}{C.RESET} • Concept: `{concept}` • Direction: `{direction}`",
        f"    • Play-Action: {'YES' if is_pa else 'NO'} • Screen Pass: {'YES' if is_screen else 'NO'}",
        f"    • Passer: {play.get('qb_name') or 'N/A'}  |  Target/Rusher: {play.get('receiver_player_name') or play.get('rusher_player_name') or play.get('player_name') or 'N/A'}",
        "",
        f"  {C.BOLD}{C.GOLD}Outcome & Advanced Metrics:{C.RESET}",
        f"    • Yards Gained: {C.BOLD}{yards:+.1f} yds{C.RESET}  |  Air Yards: {air:.1f} yds  |  YAC: {yac:.1f} yds (Expected: {xyac:.1f})",
        f"    • Expected Points Added (EPA): {C.BOLD}{epa:+.3f} EPA{C.RESET}",
        f"    • Win Probability Added (WPA): {C.BOLD}{wpa:+.3%}{C.RESET}",
        f"    • CPOE (Pass Accuracy): {cpoe:+.1f}%  |  Series Success: {'SUCCESS' if success else 'FAILED'}",
        f"    • Result Flags: {'TOUCHDOWN! ' if is_td else ''}{'INTERCEPTION ' if is_int else ''}{'SACK ' if is_sack else ''}{'First Down' if play.get('first_down') else ''}",
        "",
        f"  {C.BOLD}{C.GOLD}Official Play Call:{C.RESET}",
        f"    {C.DIM}\"{desc}\"{C.RESET}",
        f"{C.BOLD}{C.CYAN}└────────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
    ]
    return "\n".join(lines)


def find_player_plays(plays: List[Dict[str, Any]], player_name: str, season: Optional[int] = None) -> List[Dict[str, Any]]:
    """Locate all play records matching a player's name across passer, rusher, receiver, and kicking roles."""
    p_low = player_name.strip().lower()
    matching: List[Dict[str, Any]] = []
    tokens = [t for t in p_low.replace(".", " ").split() if len(t) > 1]
    for p in plays:
        if season is not None and _safe_int(p.get("season"), -1) != int(season):
            continue
        qb_n = str(p.get("qb_name", "")).lower()
        rec_n = str(p.get("receiver_player_name", "")).lower()
        rush_n = str(p.get("rusher_player_name", "")).lower()
        kick_n = str(p.get("kicker_player_name", "")).lower()
        punt_n = str(p.get("punter_player_name", "")).lower()
        gen_n = str(p.get("player_name", "")).lower()
        desc = str(p.get("desc", "")).lower()

        if (p_low in qb_n or p_low in rec_n or p_low in rush_n or p_low in gen_n
            or p_low in kick_n or p_low in punt_n or p_low in desc):
            matching.append(p)
            continue
        if any(tok in qb_n or tok in rec_n or tok in rush_n or tok in gen_n or tok in desc for tok in tokens if len(tok) >= 3):
            matching.append(p)
    return matching


def get_player_teams(player_plays: List[Dict[str, Any]], player_name: str) -> List[str]:
    """
    List all unique NFL teams a player played for across the provided plays.
    Used for smart team detection (if exactly one team, do not prompt!).
    """
    teams: Set[str] = set()
    p_low = player_name.strip().lower()
    for p in player_plays:
        post = str(p.get("posteam", "")).upper()
        defe = str(p.get("defteam", "")).upper()
        qb_n = str(p.get("qb_name", "")).lower()
        rec_n = str(p.get("receiver_player_name", "")).lower()
        rush_n = str(p.get("rusher_player_name", "")).lower()
        desc = str(p.get("desc", "")).lower()
        if (p_low in qb_n or p_low in rec_n or p_low in rush_n) and post:
            teams.add(post)
        elif any(kw in desc for kw in ("intercepted by", "sacked", "fumble forced by")) and p_low in desc:
            if defe:
                teams.add(defe)
            elif post:
                teams.add(post)
        elif post:
            teams.add(post)
    return sorted(t for t in teams if t)


def render_player_drilldown_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    player_name: str,
    team: Optional[str] = None,
    interactive: bool = True,
) -> str:
    """
    Drill down into comprehensive individual player statistics for a season.
    Smart team detection: lists all teams played for; if only 1 team in the season, does not ask!
    """
    s_plays = plays_for_season(plays, season)
    matching_plays = find_player_plays(s_plays, player_name, season=season)
    if not matching_plays:
        all_matches = find_player_plays(plays, player_name)
        if all_matches:
            seasons_found = sorted({p.get('season') for p in all_matches if p.get('season')})
            return (
                f"\n{C.YELLOW}⚠ No plays found for player '{player_name}' in the {season} season.{C.RESET}\n"
                f"  💡 That player has data in season(s): {', '.join(map(str, seasons_found))}. Try `/season {seasons_found[-1]}`."
            )
        return f"\n{C.RED}✖ No plays found for player '{player_name}'.{C.RESET}"

    # SMART TEAM DETECTION:
    # "If the user picks a player be smart enough to list the teams they played for
    #  and if it was only one team for the selected season don't ask"
    teams_played_for = get_player_teams(matching_plays, player_name)
    selected_team: Optional[str] = resolve_team_abbr(team) if team else None
    team_selection_note = ""

    if selected_team is None:
        if len(teams_played_for) == 1:
            # ONLY ONE TEAM: DO NOT PROMPT/ASK!
            selected_team = teams_played_for[0]
            team_selection_note = f"{selected_team} (1 team in {season} — auto-selected)"
        elif len(teams_played_for) > 1:
            if interactive and sys.stdin.isatty():
                print(f"\n  {C.BOLD}{C.CYAN}{player_name} played for {len(teams_played_for)} teams in {season}:{C.RESET}")
                for idx, t in enumerate(teams_played_for, 1):
                    t_count = sum(1 for p in matching_plays if str(p.get("posteam", "")).upper() == t)
                    print(f"    [{idx}] {t} ({t_count} plays)")
                print(f"    [{len(teams_played_for) + 1}] All Teams (Combined)")
                try:
                    sel = prompt_input(f"  Select team [1-{len(teams_played_for) + 1}] (default: {len(teams_played_for) + 1}): ").strip()
                    if sel.isdigit() and 1 <= int(sel) <= len(teams_played_for):
                        selected_team = teams_played_for[int(sel) - 1]
                        team_selection_note = f"{selected_team} (Selected from {', '.join(teams_played_for)})"
                    else:
                        selected_team = None
                        team_selection_note = f"{', '.join(teams_played_for)} (Combined All Teams)"
                except (EOFError, KeyboardInterrupt):
                    selected_team = None
                    team_selection_note = f"{', '.join(teams_played_for)} (Combined All Teams)"
            else:
                selected_team = None
                team_selection_note = f"{', '.join(teams_played_for)} (Combined All Teams)"
        else:
            team_selection_note = "Free Agent / Unknown"
    else:
        team_selection_note = selected_team

    if selected_team:
        active_plays = [
            p for p in matching_plays
            if str(p.get("posteam", "")).upper() == selected_team
            or str(p.get("defteam", "")).upper() == selected_team
        ]
        if not active_plays:
            active_plays = matching_plays
    else:
        active_plays = matching_plays

    p_low = player_name.strip().lower()
    p_tokens = [t for t in p_low.replace(".", " ").split() if len(t) >= 3]

    def _matches_name(val: str) -> bool:
        v = val.strip().lower()
        if not v:
            return False
        return p_low in v or v in p_low or any(tok in v for tok in p_tokens)

    # Determine roles & split plays
    pass_plays = [
        p for p in active_plays
        if (_matches_name(str(p.get("qb_name", ""))) or _matches_name(str(p.get("passer_player_name", ""))))
        and (int(p.get("pass_attempt", 0)) == 1 or p.get("play_type") == "pass")
    ]
    rush_plays = [
        p for p in active_plays
        if (_matches_name(str(p.get("rusher_player_name", ""))) or (not p.get("rusher_player_name") and _matches_name(str(p.get("qb_name", "")))))
        and (int(p.get("rush_attempt", 0)) == 1 or p.get("play_type") == "run")
    ]
    rec_plays = [
        p for p in active_plays
        if _matches_name(str(p.get("receiver_player_name", "")))
    ]
    kick_plays = [
        p for p in active_plays
        if _matches_name(str(p.get("kicker_player_name", ""))) or p.get("play_type") == "field_goal"
    ]
    punt_plays = [
        p for p in active_plays
        if _matches_name(str(p.get("punter_player_name", ""))) or p.get("play_type") == "punt"
    ]
    def_plays = [
        p for p in active_plays
        if (p.get("sack") or p.get("interception") or p.get("fumble_lost"))
        and (_matches_name(str(p.get("player_name", ""))) or any(tok in str(p.get("desc", "")).lower() for tok in (p_tokens or [p_low])))
        and not pass_plays and not rush_plays and not rec_plays
    ]

    canonical_name = player_name.title()
    for p in active_plays:
        for k in ("qb_name", "receiver_player_name", "rusher_player_name", "kicker_player_name", "punter_player_name", "player_name"):
            cand = str(p.get(k) or "").strip()
            if cand and _matches_name(cand):
                canonical_name = cand
                break
        if canonical_name != player_name.title():
            break

    role_str = "Quarterback (QB)" if pass_plays else (
        "Running Back (RB)" if rush_plays and not rec_plays else (
            "Wide Receiver / Tight End (WR/TE)" if rec_plays and not rush_plays else (
                "Running Back / All-Purpose (RB/WR)" if rush_plays and rec_plays else (
                    "Placekicker (K)" if kick_plays else (
                        "Punter (P)" if punt_plays else (
                            "Defensive Player (DEF)" if def_plays else "Player / Skill"
                        )
                    )
                )
            )
        )
    )

    out = [
        f"\n{C.BOLD}{C.CYAN}┌────────────────────────────────────────────────────────────────────────────────────────┐",
        f"│                     PLAYER DRILL-DOWN : {canonical_name.upper():<46} │",
        f"├────────────────────────────────────────────────────────────────────────────────────────┤{C.RESET}",
        f"  Player: {C.BOLD}{canonical_name}{C.RESET}  |  Primary Role: {C.BOLD}{role_str}{C.RESET}",
        f"  Team: {C.BOLD}{team_selection_note}{C.RESET}  |  Season: {season}  |  Total Plays Involved: {len(active_plays)}",
        "",
    ]

    # Passing Section
    if pass_plays:
        p_att = len(pass_plays)
        p_comp = sum(int(p.get("complete_pass", 0)) for p in pass_plays)
        p_pct = (100.0 * p_comp / p_att) if p_att else 0.0
        p_yds = sum(float(p.get("yards_gained", 0.0)) for p in pass_plays if int(p.get("sack", 0)) == 0)
        p_ypa = (p_yds / p_att) if p_att else 0.0
        p_tds = sum(int(p.get("pass_touchdown", 0) or p.get("touchdown", 0)) for p in pass_plays)
        p_ints = sum(int(p.get("interception", 0)) for p in pass_plays)
        p_sacks = sum(int(p.get("sack", 0)) for p in pass_plays)
        p_sack_yds = sum(abs(float(p.get("yards_gained", 0.0))) for p in pass_plays if int(p.get("sack", 0)) == 1 and float(p.get("yards_gained", 0.0)) < 0)
        p_rating = calculate_passer_rating(p_att, p_comp, p_yds, p_tds, p_ints)
        p_epa = sum(float(p.get("epa", 0.0)) for p in pass_plays)
        p_epa_att = (p_epa / p_att) if p_att else 0.0
        cpoe_vals = [float(p.get("cpoe", 0.0)) for p in pass_plays if int(p.get("sack", 0)) == 0]
        p_cpoe = (sum(cpoe_vals) / len(cpoe_vals)) if cpoe_vals else 0.0

        impact_score_val: Optional[float] = None
        mw_val = 0
        ml_val = 0
        if "qb_impact_score" in engine.stats:
            try:
                board = engine.evaluate_stat_leaderboard("qb_impact_score", s_plays, team=selected_team, group_override="qb")
                for r in board:
                    if p_low in str(r.get("entity", "")).lower():
                        impact_score_val = float(r.get("value", 0.0))
                        mw_val = int(r.get("meaningful_wins", 0))
                        ml_val = int(r.get("meaningful_losses", 0))
                        break
            except Exception:
                pass

        out.extend([
            f"  {C.BOLD}{C.GOLD}┌─ PASSING STATISTICS ─────────────────────────────────────────────────────────────────┐{C.RESET}",
            f"  │ Pass Attempts:       {p_att:<14} Completions:             {p_comp:<22} │",
            f"  │ Completion %:        {p_pct:<13.1f}% Passing Yards:           {p_yds:<10.1f} yds       │",
            f"  │ Yards / Attempt:     {p_ypa:<13.2f} ypa Passing Touchdowns:      {p_tds:<22} │",
            f"  │ Interceptions:       {p_ints:<14} Sacks Taken:             {p_sacks} ({p_sack_yds:.1f} yds lost)        │",
            f"  │ NFL Passer Rating:   {p_rating:<14.1f} Avg CPOE:                {p_cpoe:<+6.1f}%                 │",
            f"  │ Total Passing EPA:   {p_epa:<+14.2f} EPA / Pass Attempt:      {p_epa_att:<+10.2f} EPA/att   │",
        ])
        if impact_score_val is not None:
            out.append(f"  │ QB Impact Score:     {impact_score_val:<6.1f} / 100   QB Meaningful Record:    {mw_val} MW - {ml_val} ML         │")
        out.append(f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}")
        out.append("")

    # Rushing Section
    if rush_plays:
        r_car = len(rush_plays)
        r_yds = sum(float(p.get("yards_gained", 0.0)) for p in rush_plays)
        r_ypc = (r_yds / r_car) if r_car else 0.0
        r_tds = sum(int(p.get("rush_touchdown", 0) or (p.get("touchdown", 0) and p.get("rush_attempt", 0) == 1)) for p in rush_plays)
        r_long = max((float(p.get("yards_gained", 0.0)) for p in rush_plays), default=0.0)
        r_epa = sum(float(p.get("epa", 0.0)) for p in rush_plays)
        r_epa_car = (r_epa / r_car) if r_car else 0.0
        r_fd = sum(int(p.get("first_down", 0)) for p in rush_plays)
        out.extend([
            f"  {C.BOLD}{C.GREEN}┌─ RUSHING STATISTICS ─────────────────────────────────────────────────────────────────┐{C.RESET}",
            f"  │ Rushing Carries:     {r_car:<14} Rushing Yards:           {r_yds:<10.1f} yds       │",
            f"  │ Yards / Carry (YPC): {r_ypc:<14.2f} Rushing Touchdowns:     {r_tds:<22} │",
            f"  │ Longest Rush:        {r_long:<10.0f} yds   First Downs Gained:      {r_fd:<22} │",
            f"  │ Total Rushing EPA:   {r_epa:<+14.2f} EPA / Carry:             {r_epa_car:<+10.2f} EPA/car   │",
            f"  {C.BOLD}{C.GREEN}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
            "",
        ])

    # Receiving Section
    if rec_plays:
        rc_tgt = len(rec_plays)
        rc_cat = sum(int(p.get("complete_pass", 0)) for p in rec_plays)
        rc_pct = (100.0 * rc_cat / rc_tgt) if rc_tgt else 0.0
        rc_yds = sum(float(p.get("yards_gained", 0.0)) for p in rec_plays if int(p.get("complete_pass", 0)) == 1)
        rc_ypr = (rc_yds / rc_cat) if rc_cat else 0.0
        rc_tds = sum(int(p.get("touchdown", 0)) for p in rec_plays if int(p.get("complete_pass", 0)) == 1)
        rc_yac = sum(float(p.get("yards_after_catch", 0.0)) for p in rec_plays if int(p.get("complete_pass", 0)) == 1)
        rc_yac_cat = (rc_yac / rc_cat) if rc_cat else 0.0
        rc_screen = sum(1 for p in rec_plays if int(p.get("is_screen", 0)) == 1)
        rc_screen_yac = sum(float(p.get("yards_after_catch", 0.0)) for p in rec_plays if int(p.get("is_screen", 0)) == 1 and int(p.get("complete_pass", 0)) == 1)
        out.extend([
            f"  {C.BOLD}{C.BLUE}┌─ RECEIVING & YAC STATISTICS ─────────────────────────────────────────────────────────┐{C.RESET}",
            f"  │ Targets:             {rc_tgt:<14} Receptions (Catches):    {rc_cat:<22} │",
            f"  │ Catch %:             {rc_pct:<13.1f}% Receiving Yards:         {rc_yds:<10.1f} yds       │",
            f"  │ Yards / Catch (YPR): {rc_ypr:<13.2f} yds Receiving Touchdowns:    {rc_tds:<22} │",
            f"  │ Total YAC:           {rc_yac:<10.1f} yds   YAC / Reception:         {rc_yac_cat:<10.2f} yds/rec   │",
            f"  │ Screen Targets:      {rc_screen:<14} Screen YAC:              {rc_screen_yac:<10.1f} yds       │",
            f"  {C.BOLD}{C.BLUE}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
            "",
        ])

    # Kicking / Punting Section
    if kick_plays:
        fg_yds = sum(float(p.get("yards_gained", 0.0)) for p in kick_plays)
        out.extend([
            f"  {C.BOLD}{C.GOLD}┌─ SPECIAL TEAMS (KICKING) ────────────────────────────────────────────────────────────┐{C.RESET}",
            f"  │ Field Goals Made:    {len(kick_plays):<14} Longest Field Goal:      {fg_yds:<10.0f} yds       │",
            f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
            "",
        ])
    if punt_plays:
        punt_yds = sum(float(p.get("yards_gained", 0.0)) for p in punt_plays)
        avg_punt = (punt_yds / len(punt_plays)) if punt_plays else 0.0
        out.extend([
            f"  {C.BOLD}{C.GOLD}┌─ SPECIAL TEAMS (PUNTING) ────────────────────────────────────────────────────────────┐{C.RESET}",
            f"  │ Punts Attempted:     {len(punt_plays):<14} Average Punt Distance:   {avg_punt:<10.1f} yds       │",
            f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
            "",
        ])

    # Situational Efficiency Card
    t_downs = [p for p in active_plays if int(p.get("down", 0)) == 3]
    t_conv = sum(1 for p in t_downs if int(p.get("series_success", 0)) == 1 or int(p.get("first_down", 0)) == 1 or float(p.get("yards_gained", 0.0)) >= int(p.get("ydstogo", 10)))
    t_rate = (100.0 * t_conv / len(t_downs)) if t_downs else 0.0
    rz_plays = [p for p in active_plays if int(p.get("red_zone", 0)) == 1]
    rz_tds = sum(1 for p in rz_plays if int(p.get("touchdown", 0)) == 1)
    rz_rate = (100.0 * rz_tds / len(rz_plays)) if rz_plays else 0.0

    out.extend([
        f"  {C.BOLD}{C.MAGENTA}┌─ SITUATIONAL BREAKDOWN ──────────────────────────────────────────────────────────────┐{C.RESET}",
        f"  │ 3rd Down Conversions: {t_conv}/{len(t_downs)} ({t_rate:.1f}%)     Red Zone Touchdowns:     {rz_tds}/{len(rz_plays)} ({rz_rate:.1f}%)          │",
        f"  {C.BOLD}{C.MAGENTA}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
    ])

    # Top Signature Plays for player
    top_plays = sorted(active_plays, key=lambda p: (float(p.get("epa", 0.0)), float(p.get("yards_gained", 0.0))), reverse=True)[:3]
    if top_plays:
        out.append("")
        out.append(f"  {C.BOLD}{C.GOLD}┌─ SIGNATURE PLAYS FOR {canonical_name.upper()} ───────────────────────────────────────────┐{C.RESET}")
        for s_idx, sp in enumerate(top_plays, 1):
            pid = sp.get("play_id", "N/A")
            opp = sp.get("defteam") if sp.get("posteam") == (selected_team or (teams_played_for[0] if teams_played_for else "")) else sp.get("posteam")
            qtr = sp.get("qtr", 1)
            dn = sp.get("down", 1)
            dist = sp.get("ydstogo", 10)
            yds = float(sp.get("yards_gained", 0.0))
            epa = float(sp.get("epa", 0.0))
            td_str = " (TD)" if sp.get("touchdown") else ""
            desc = sp.get("desc", "")[:76]
            out.append(f"  │ [{s_idx}] Play #{pid} vs {opp} (Q{qtr} {dn}&{dist}): {yds:+.1f} yds, {epa:+.2f} EPA{td_str}")
            out.append(f"  │     {C.DIM}\"{desc}\"{C.RESET}")
        out.append(f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}")

    out.append(f"\n  {C.DIM}💡 Tip: Run `/play` to diagram any of {canonical_name}'s signature plays on the ASCII gridiron.{C.RESET}")
    return "\n".join(out)


def render_coaching_staff_view(team_abbr: str, role_filter: Optional[str] = None) -> str:
    """Render a structured, colorized ASCII table detailing team coaching staff (HC, OC, DC, position coaches)."""
    resolved_t = resolve_team_abbr(team_abbr) or team_abbr.upper()
    staff = get_team_coaching_staff(resolved_t)
    full_name = TEAM_FULL_NAMES.get(resolved_t, f"{resolved_t} Football Team")
    headers = ["Role / Position", "Coach Name", "Category"]
    rows = []
    role_map = [
        ("Head Coach (HC)", staff.get("hc", "N/A"), "Head Coach"),
        ("Offensive Coordinator (OC)", staff.get("oc", "N/A"), "Coordinator"),
        ("Defensive Coordinator (DC)", staff.get("dc", "N/A"), "Coordinator"),
        ("Special Teams Coordinator", staff.get("st", "Dave Toub" if resolved_t == "KC" else "Special Teams Staff"), "Coordinator"),
        ("Quarterbacks Coach", staff.get("qb_coach", "N/A"), "Position Coach"),
        ("Offensive Line Coach", staff.get("ol_coach", "N/A"), "Position Coach"),
        ("Wide Receivers Coach", staff.get("wr_coach", "N/A"), "Position Coach"),
        ("Running Backs Coach", staff.get("rb_coach", "N/A"), "Position Coach"),
        ("Defensive Line Coach", staff.get("dl_coach", "N/A"), "Position Coach"),
        ("Linebackers Coach", staff.get("lb_coach", "N/A"), "Position Coach"),
    ]
    for r_label, c_name, cat in role_map:
        if role_filter:
            rf = role_filter.lower()
            if rf == "hc" and "head" not in r_label.lower():
                continue
            if rf == "oc" and "offensive coord" not in r_label.lower():
                continue
            if rf == "dc" and "defensive coord" not in r_label.lower():
                continue
            if rf in ("qb", "qb_coach") and "quarterback" not in r_label.lower():
                continue
            if rf in ("ol", "ol_coach") and "offensive line" not in r_label.lower():
                continue
            if rf in ("wr", "wr_coach") and "wide receiver" not in r_label.lower():
                continue
            if rf in ("rb", "rb_coach") and "running back" not in r_label.lower():
                continue
            if rf in ("dl", "dl_coach") and "defensive line" not in r_label.lower():
                continue
            if rf in ("lb", "lb_coach") and "linebacker" not in r_label.lower():
                continue
        rows.append([r_label, f"{C.BOLD}{c_name}{C.RESET}", cat])

    table = AsciiArtRenderer.render_table(
        f"COACHING STAFF : {full_name.upper()} ({resolved_t})",
        headers,
        rows,
        alignments=["left", "left", "center"],
    )
    hc_name = staff.get("hc", "N/A")
    oc_name = staff.get("oc", "N/A")
    dc_name = staff.get("dc", "N/A")
    summary = f"  {C.BOLD}Head Coach:{C.RESET} {C.CYAN}{hc_name}{C.RESET}  │  {C.BOLD}OC:{C.RESET} {oc_name}  │  {C.BOLD}DC:{C.RESET} {dc_name}\n"
    return summary + table


def render_team_drilldown_view(
    engine: StatEngine,
    plays: List[Dict[str, Any]],
    season: int,
    team: str,
) -> str:
    """Drill down into comprehensive team offensive, defensive, coaching, and roster stats for a season."""
    team_abbr = resolve_team_abbr(team) or team.upper()
    s_plays = plays_for_season(plays, season)
    off_plays = [p for p in s_plays if str(p.get("posteam", "")).upper() == team_abbr]
    def_plays = [p for p in s_plays if str(p.get("defteam", "")).upper() == team_abbr]
    if not off_plays and not def_plays:
        avail = sorted({p.get("posteam") for p in s_plays if p.get("posteam")})
        return f"\n{C.YELLOW}⚠ No play data found for team `{team_abbr}` in {season}.{C.RESET}\n  Tip: Available teams with data: {', '.join(avail)}"

    full_name = TEAM_FULL_NAMES.get(team_abbr, f"{team_abbr} Football Team")
    conf = "AFC" if team_abbr in AFC_TEAMS else ("NFC" if team_abbr in NFC_TEAMS else "NFL")
    division = TEAM_DIVISIONS.get(team_abbr, f"{conf} Division")

    games: Dict[str, int] = {}
    for p in off_plays:
        gid = str(p.get("game_id", "game"))
        games[gid] = int(p.get("team_win", 0))
    games_played = len(games)
    games_won = sum(1 for w in games.values() if w == 1)
    games_lost = games_played - games_won
    record_str = f"{games_won}-{games_lost}" if games_played > 0 else "N/A"
    win_pct_str = f"({games_won / games_played:.3f})" if games_played > 0 else ""

    tot_off = len(off_plays)
    tot_off_yds = sum(float(p.get("yards_gained", 0.0)) for p in off_plays)
    off_ypp = (tot_off_yds / tot_off) if tot_off else 0.0
    tot_off_epa = sum(float(p.get("epa", 0.0)) for p in off_plays)
    off_epa_play = (tot_off_epa / tot_off) if tot_off else 0.0
    off_succ = sum(1 for p in off_plays if int(p.get("series_success", 0)) == 1)
    off_succ_rate = (100.0 * off_succ / tot_off) if tot_off else 0.0

    all_team_plays = off_plays + def_plays
    pens_committed = sum(1 for p in all_team_plays if int(p.get("penalty", 0)) == 1 and (p.get("penalty_team") == team_abbr or (not p.get("penalty_team") and p.get("posteam") == team_abbr)))
    pen_yds_committed = sum(float(p.get("penalty_yards", 0.0)) for p in all_team_plays if int(p.get("penalty", 0)) == 1 and (p.get("penalty_team") == team_abbr or (not p.get("penalty_team") and p.get("posteam") == team_abbr)))
    pens_drawn = sum(1 for p in all_team_plays if int(p.get("penalty", 0)) == 1 and (p.get("penalty_favored_team") == team_abbr or (p.get("penalty_team") and p.get("penalty_team") != team_abbr)))
    pen_yds_drawn = sum(float(p.get("penalty_yards", 0.0)) for p in all_team_plays if int(p.get("penalty", 0)) == 1 and (p.get("penalty_favored_team") == team_abbr or (p.get("penalty_team") and p.get("penalty_team") != team_abbr)))
    timeouts_called = sum(1 for p in all_team_plays if int(p.get("timeout", 0)) == 1 and p.get("timeout_team") == team_abbr)

    off_pens = pens_committed
    off_pen_yds = pen_yds_committed
    def_pens = pens_drawn
    def_pen_yds = pen_yds_drawn

    pass_plays = [p for p in off_plays if int(p.get("pass_attempt", 0)) == 1 or p.get("play_type") == "pass"]
    rush_plays = [p for p in off_plays if int(p.get("rush_attempt", 0)) == 1 or p.get("play_type") == "run"]
    pass_att = len(pass_plays)
    pass_comp = sum(int(p.get("complete_pass", 0)) for p in pass_plays)
    pass_pct = (100.0 * pass_comp / pass_att) if pass_att else 0.0
    pass_yds = sum(float(p.get("yards_gained", 0.0)) for p in pass_plays if int(p.get("sack", 0)) == 0)
    pass_tds = sum(int(p.get("pass_touchdown", 0) or p.get("touchdown", 0)) for p in pass_plays)
    pass_ints = sum(int(p.get("interception", 0)) for p in pass_plays)
    sacks_all = sum(int(p.get("sack", 0)) for p in pass_plays)
    sack_yds = sum(abs(float(p.get("yards_gained", 0.0))) for p in pass_plays if int(p.get("sack", 0)) == 1 and float(p.get("yards_gained", 0.0)) < 0)

    rush_att = len(rush_plays)
    rush_yds = sum(float(p.get("yards_gained", 0.0)) for p in rush_plays)
    rush_ypc = (rush_yds / rush_att) if rush_att else 0.0
    rush_tds = sum(int(p.get("rush_touchdown", 0) or (p.get("touchdown", 0) and p.get("rush_attempt", 0) == 1)) for p in rush_plays)

    tot_scrim = pass_att + rush_att
    call_pass_pct = (100.0 * pass_att / tot_scrim) if tot_scrim else 0.0
    call_rush_pct = (100.0 * rush_att / tot_scrim) if tot_scrim else 0.0

    exp_pass = sum(1 for p in pass_plays if float(p.get("yards_gained", 0.0)) >= 20.0)
    exp_rush = sum(1 for p in rush_plays if float(p.get("yards_gained", 0.0)) >= 10.0)

    t_downs = [p for p in off_plays if int(p.get("down", 0)) == 3]
    t_conv = sum(1 for p in t_downs if int(p.get("series_success", 0)) == 1 or int(p.get("first_down", 0)) == 1 or float(p.get("yards_gained", 0.0)) >= int(p.get("ydstogo", 10)))
    t_rate = (100.0 * t_conv / len(t_downs)) if t_downs else 0.0

    rz_plays = [p for p in off_plays if int(p.get("red_zone", 0)) == 1]
    rz_tds = sum(1 for p in rz_plays if int(p.get("touchdown", 0)) == 1)
    rz_rate = (100.0 * rz_tds / len(rz_plays)) if rz_plays else 0.0

    tot_def = len(def_plays)
    def_yds = sum(float(p.get("yards_gained", 0.0)) for p in def_plays)
    def_ypp = (def_yds / tot_def) if tot_def else 0.0
    def_epa = sum(float(p.get("epa", 0.0)) for p in def_plays)
    def_epa_play = (def_epa / tot_def) if tot_def else 0.0
    def_sacks = sum(int(p.get("sack", 0)) for p in def_plays)
    def_ints = sum(int(p.get("interception", 0)) for p in def_plays)
    def_fumb = sum(int(p.get("fumble_lost", 0)) for p in def_plays)
    def_to = def_ints + def_fumb
    def_stops = sum(1 for p in def_plays if int(p.get("series_success", 0)) == 0)
    def_stop_rate = (100.0 * def_stops / tot_def) if tot_def else 0.0

    passers: Dict[str, List[Dict[str, Any]]] = {}
    for p in pass_plays:
        q_n = p.get("qb_name") or p.get("player_name") or "Passer"
        passers.setdefault(q_n, []).append(p)

    rushers: Dict[str, List[Dict[str, Any]]] = {}
    for p in rush_plays:
        r_n = p.get("rusher_player_name") or p.get("player_name") or "Rusher"
        rushers.setdefault(r_n, []).append(p)

    receivers: Dict[str, List[Dict[str, Any]]] = {}
    for p in off_plays:
        rc_n = p.get("receiver_player_name")
        if rc_n:
            receivers.setdefault(rc_n, []).append(p)

    staff = get_team_coaching_staff(team_abbr, season)
    pos_coaches = [
        f"QB: {staff.get('qb_coach')}" if staff.get("qb_coach") else "",
        f"OL: {staff.get('ol_coach')}" if staff.get("ol_coach") else "",
        f"WR: {staff.get('wr_coach')}" if staff.get("wr_coach") else "",
        f"RB: {staff.get('rb_coach')}" if staff.get("rb_coach") else "",
        f"DL: {staff.get('dl_coach')}" if staff.get("dl_coach") else "",
    ]
    pos_str = " • ".join([p for p in pos_coaches if p])

    out = [
        f"\n{C.BOLD}{C.CYAN}┌────────────────────────────────────────────────────────────────────────────────────────┐",
        f"│                     TEAM DRILL-DOWN : {full_name.upper():<48} │",
        f"├────────────────────────────────────────────────────────────────────────────────────────┤{C.RESET}",
        f"  Season: {C.BOLD}{season}{C.RESET}  |  Abbreviation: {C.BOLD}{team_abbr}{C.RESET}  |  Conference: {conf}  |  Division: {division}",
        f"  Team Record: {C.BOLD}{record_str}{C.RESET} {win_pct_str}  |  Offensive Plays Tracked: {tot_off}  |  Defensive Plays: {tot_def}",
        "",
        f"  {C.BOLD}{C.MAGENTA}┌─ COACHING STAFF & LEADERSHIP ────────────────────────────────────────────────────────┐{C.RESET}",
        f"  │ Head Coach (HC):            {C.BOLD}{staff.get('hc', 'N/A'):<56}{C.RESET}│",
        f"  │ Offensive Coordinator (OC): {staff.get('oc', 'N/A'):<56}│",
        f"  │ Defensive Coordinator (DC): {staff.get('dc', 'N/A'):<56}│",
        f"  │ Key Position Coaches:       {pos_str:<56}│",
        f"  {C.BOLD}{C.MAGENTA}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
        "",
        f"  {C.BOLD}{C.GOLD}┌─ OFFENSIVE EFFICIENCY & PLAY CALLING ────────────────────────────────────────────────┐{C.RESET}",
        f"  │ Total Plays:         {tot_off:<14} Total Yards Gained:      {tot_off_yds:<10.1f} yds       │",
        f"  │ Yards Per Play (YPP): {off_ypp:<13.2f} EPA / Play:             {off_epa_play:<+10.2f} EPA/play   │",
        f"  │ Total Offensive EPA: {tot_off_epa:<+14.2f} Offensive Success Rate:  {off_succ_rate:<6.1f}%                 │",
        f"  │ Penalties Committed: {off_pens:<14} Penalty Yards Conceded: {off_pen_yds:<10.1f} yds       │",
        f"  │ Play-Calling Split:  {call_pass_pct:4.1f}% Pass / {call_rush_pct:4.1f}% Rush ({pass_att} pass, {rush_att} rush)                │",
        f"  │ Passing Comp/Att:    {pass_comp}/{pass_att} ({pass_pct:.1f}%)    Passing Yards:           {pass_yds:<10.1f} yds       │",
        f"  │ Passing Touchdowns:  {pass_tds:<14} Passing Interceptions:   {pass_ints:<22} │",
        f"  │ Sacks Allowed:       {sacks_all:<14} Sack Yards Lost:         {sack_yds:<10.1f} yds       │",
        f"  │ Rushing Carries:     {rush_att:<14} Rushing Yards:           {rush_yds:<10.1f} yds       │",
        f"  │ Yards / Carry (YPC): {rush_ypc:<14.2f} Rushing Touchdowns:     {rush_tds:<22} │",
        f"  │ Explosive Plays:     {exp_pass + exp_rush:<14} (20+ Pass: {exp_pass}, 10+ Rush: {exp_rush})                   │",
        f"  │ 3rd Down Efficiency: {t_conv}/{len(t_downs)} ({t_rate:.1f}%)     Red Zone TD Rate:        {rz_tds}/{len(rz_plays)} ({rz_rate:.1f}%)          │",
        f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
        "",
        f"  {C.BOLD}{C.GREEN}┌─ DEFENSIVE PROFILE (OPPONENT SCRIMMAGE FACED) ───────────────────────────────────────┐{C.RESET}",
        f"  │ Opponent Plays:      {tot_def:<14} Yards Allowed:           {def_yds:<10.1f} yds       │",
        f"  │ Yards / Play Allowed:{def_ypp:<14.2f} Defensive EPA / Play:   {def_epa_play:<+10.2f} EPA/play   │",
        f"  │ Sacks Generated:     {def_sacks:<14} Interceptions Caught:    {def_ints:<22} │",
        f"  │ Turnovers Forced:    {def_to:<14} Defensive Stop Rate:    {def_stops}/{tot_def} ({def_stop_rate:.1f}%)           │",
        f"  │ Penalties Committed: {pens_committed:<14} Penalty Yds Conceded:   {pen_yds_committed:<10.1f} yds       │",
        f"  │ Penalties in Favor:  {pens_drawn:<14} Penalty Yds in Favor:  {pen_yds_drawn:<10.1f} yds       │",
        f"  │ Timeouts Charged:    {timeouts_called:<14} Net Penalty Margin:     {pens_drawn - pens_committed:<+6} ({pen_yds_drawn - pen_yds_committed:+.1f} yds)  │",
        f"  {C.BOLD}{C.GREEN}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}",
        "",
        f"  {C.BOLD}{C.CYAN}┌─ ROSTER & UNIT LEADERS ──────────────────────────────────────────────────────────────┐{C.RESET}",
    ]

    if passers:
        out.append(f"  │ {C.BOLD}PASSING LEADERS:{C.RESET}")
        for q_n, q_plays in sorted(passers.items(), key=lambda x: len(x[1]), reverse=True)[:3]:
            q_att = len(q_plays)
            q_comp = sum(int(p.get("complete_pass", 0)) for p in q_plays)
            q_yds = sum(float(p.get("yards_gained", 0.0)) for p in q_plays if int(p.get("sack", 0)) == 0)
            q_tds = sum(int(p.get("pass_touchdown", 0) or p.get("touchdown", 0)) for p in q_plays)
            q_ints = sum(int(p.get("interception", 0)) for p in q_plays)
            q_rtg = calculate_passer_rating(q_att, q_comp, q_yds, q_tds, q_ints)
            q_epa = (sum(float(p.get("epa", 0.0)) for p in q_plays) / q_att) if q_att else 0.0
            q_pct = (100.0 * q_comp / q_att) if q_att else 0.0
            out.append(f"  │   • {C.BOLD}{q_n:<14}{C.RESET} {q_comp}/{q_att} ({q_pct:4.1f}%), {q_yds:5.1f} yds, {q_tds} TD, {q_ints} INT, {q_rtg:5.1f} Rating, {q_epa:+4.2f} EPA/att")
    else:
        out.append("  │   • Passing: No pass attempts recorded.")

    if rushers:
        out.append(f"  │ {C.BOLD}RUSHING LEADERS:{C.RESET}")
        for r_n, r_plays in sorted(rushers.items(), key=lambda x: sum(float(p.get("yards_gained", 0.0)) for p in x[1]), reverse=True)[:3]:
            r_car = len(r_plays)
            r_yds = sum(float(p.get("yards_gained", 0.0)) for p in r_plays)
            r_ypc = (r_yds / r_car) if r_car else 0.0
            r_tds = sum(int(p.get("rush_touchdown", 0) or (p.get("touchdown", 0) and p.get("rush_attempt", 0) == 1)) for p in r_plays)
            r_long = max((float(p.get("yards_gained", 0.0)) for p in r_plays), default=0.0)
            out.append(f"  │   • {C.BOLD}{r_n:<14}{C.RESET} {r_car:2d} car, {r_yds:5.1f} yds, {r_ypc:4.2f} ypc, {r_tds} TD, Long: {r_long:3.0f} yds")

    if receivers:
        out.append(f"  │ {C.BOLD}RECEIVING LEADERS:{C.RESET}")
        for rc_n, rc_plays in sorted(receivers.items(), key=lambda x: sum(float(p.get("yards_gained", 0.0)) for p in x[1]), reverse=True)[:3]:
            rc_tgt = len(rc_plays)
            rc_cat = sum(int(p.get("complete_pass", 0)) for p in rc_plays)
            rc_yds = sum(float(p.get("yards_gained", 0.0)) for p in rc_plays if int(p.get("complete_pass", 0)) == 1)
            rc_tds = sum(int(p.get("touchdown", 0)) for p in rc_plays if int(p.get("complete_pass", 0)) == 1)
            rc_yac = sum(float(p.get("yards_after_catch", 0.0)) for p in rc_plays if int(p.get("complete_pass", 0)) == 1)
            rc_ypr = (rc_yds / rc_cat) if rc_cat else 0.0
            out.append(f"  │   • {C.BOLD}{rc_n:<14}{C.RESET} {rc_cat}/{rc_tgt} rec, {rc_yds:5.1f} yds, {rc_tds} TD, {rc_ypr:4.1f} yds/rec, {rc_yac:4.1f} YAC")

    out.append(f"  {C.BOLD}{C.CYAN}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}")

    top_plays = sorted(off_plays + def_plays, key=lambda p: (float(p.get("epa", 0.0)), float(p.get("yards_gained", 0.0))), reverse=True)[:3]
    if top_plays:
        out.append("")
        out.append(f"  {C.BOLD}{C.GOLD}┌─ TOP SIGNATURE PLAYS ({team_abbr} • {season}) ───────────────────────────────────────────┐{C.RESET}")
        for s_idx, sp in enumerate(top_plays, 1):
            pid = sp.get("play_id", "N/A")
            opp = sp.get("defteam") if sp.get("posteam") == team_abbr else sp.get("posteam")
            qtr = sp.get("qtr", 1)
            dn = sp.get("down", 1)
            dist = sp.get("ydstogo", 10)
            yds = float(sp.get("yards_gained", 0.0))
            epa = float(sp.get("epa", 0.0))
            td_str = " (TD)" if sp.get("touchdown") else ""
            desc = sp.get("desc", "")[:76]
            out.append(f"  │ [{s_idx}] Play #{pid} vs {opp} (Q{qtr} {dn}&{dist}): {yds:+.1f} yds, {epa:+.2f} EPA{td_str}")
            out.append(f"  │     {C.DIM}\"{desc}\"{C.RESET}")
        out.append(f"  {C.BOLD}{C.GOLD}└──────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}")

    out.append(f"\n  {C.DIM}💡 Tip: Use `/play` to diagram any of these plays on the ASCII gridiron.{C.RESET}")
    return "\n".join(out)


def format_yardline_str(p: Dict[str, Any]) -> str:
    y = p.get("yardline_100")
    if y is None:
        return "N/A"
    try:
        y_val = int(round(float(y)))
    except (ValueError, TypeError):
        return str(y)
    if y_val == 50:
        return "MID 50"
    if y_val < 50:
        return f"{p.get('defteam') or 'OPP'} {y_val}"
    return f"{p.get('posteam') or 'OWN'} {100 - y_val}"


def extract_games_summary(plays: List[Dict[str, Any]], season: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Summarize games from plays for a given season.
    Returns list of game dicts with:
      game_id, season, week, home_team, away_team,
      home_score, away_score, total_plays, quarters (sorted list), has_ot, plays
    """
    target_plays = [p for p in plays if season is None or int(p.get("season", 0)) == int(season)]
    games_map: Dict[str, List[Dict[str, Any]]] = {}
    for p in target_plays:
        gid = p.get("game_id")
        if not gid:
            continue
        games_map.setdefault(gid, []).append(p)

    summaries: List[Dict[str, Any]] = []
    for gid, pls in games_map.items():
        parts = gid.split("_")
        away = parts[2] if len(parts) >= 4 else (pls[0].get("defteam") or "AWAY")
        home = parts[3] if len(parts) >= 4 else (pls[0].get("posteam") or "HOME")
        week = int(pls[0].get("week", 1))
        pls_sorted = sorted(pls, key=lambda x: (int(x.get("qtr", 1)), int(x.get("play_id", 0))))
        last_p = pls_sorted[-1]
        h_score = int(last_p.get("home_score", 0))
        a_score = int(last_p.get("away_score", 0))
        qtrs = sorted({int(p.get("qtr", 1)) for p in pls})
        has_ot = any(
            int(p.get("qtr", 0)) >= 5
            or "ot" in str(p.get("desc", "")).lower()
            or "overtime" in str(p.get("desc", "")).lower()
            for p in pls
        )
        summaries.append({
            "game_id": gid,
            "season": int(pls[0].get("season", season or CURRENT_SEASON)),
            "week": week,
            "away_team": away,
            "home_team": home,
            "away_score": a_score,
            "home_score": h_score,
            "has_ot": has_ot,
            "quarters": qtrs,
            "total_plays": len(pls),
            "plays": pls_sorted,
        })
    summaries.sort(key=lambda g: (int(g["season"]), int(g["week"]), str(g["game_id"])))
    return summaries


def render_game_plays_table(
    game_plays: List[Dict[str, Any]],
    title: str = "GAME PLAYS",
    highlight_play_id: Optional[int] = None,
) -> str:
    """
    Renders an ASCII table of plays for a game / quarter with:
    # | Play | Qtr | Team | Dn&Dist | Yardline | Concept / Scheme | Gain | EPA | Score | Key Description
    """
    clean_title = title.upper()
    lines = [
        f"{C.BOLD}{C.CYAN}┌─ {clean_title} " + "─" * max(0, 108 - len(clean_title)) + f"┐{C.RESET}",
        f"{C.BOLD}│ #  │ Play │ Qtr │ Team │ Dn&Dist  │ Yardline │ Concept / Scheme │ Gain       │ EPA    │ Score      │ Key Description            │{C.RESET}",
        f"{C.BOLD}├────┼──────┼─────┼──────┼──────────┼──────────┼──────────────────┼────────────┼────────┼────────────┼────────────────────────────┤{C.RESET}",
    ]
    for idx, p in enumerate(game_plays, 1):
        pid_num = p.get("play_id", 0)
        pid_str = f"#{pid_num}"
        q = "OT" if int(p.get("qtr", 1)) >= 5 else f"Q{p.get('qtr', 1)}"
        tm = str(p.get("posteam") or "")[:4]
        d = p.get("down", 1)
        dist = p.get("ydstogo", 10)
        suffix = "st" if d == 1 else ("nd" if d == 2 else ("rd" if d == 3 else "th"))
        dnd = f"{d}{suffix} & {dist}"
        ydl = format_yardline_str(p)[:8]
        conc = str(p.get("play_concept") or p.get("play_type") or "play")[:16]
        g = float(p.get("yards_gained", 0.0))
        td = " (TD)" if p.get("touchdown") else ""
        gain = f"{g:+.1f}{td}"[:10]
        epa = f"{float(p.get('epa', 0.0)):+5.2f}"
        sc = f"{p.get('away_score', 0)}-{p.get('home_score', 0)}"[:10]
        desc = p.get("desc", "")
        if "(" in desc and ")" in desc:
            desc = desc.split(")", 1)[1].strip()
        desc = desc[:26]

        hl_on = f"{C.BOLD}{C.GOLD}" if highlight_play_id and pid_num == highlight_play_id else ""
        hl_off = C.RESET if hl_on else ""
        lines.append(
            f"│{hl_on}{idx:3d} │ {pid_str:<4} │ {q:<3} │ {tm:<4} │ {dnd:<8} │ {ydl:<8} │ {conc:<16} │ {gain:<10} │ {epa:<6} │ {sc:<10} │ {desc:<26}{hl_off} │"
        )
    lines.append(f"{C.BOLD}{C.CYAN}└────┴──────┴─────┴──────┴──────────┴──────────┴──────────────────┴────────────┴────────┴────────────┴────────────────────────────┘{C.RESET}")
    return "\n".join(lines)


def _play_navigation_loop(
    chosen_play: Dict[str, Any],
    game_plays: List[Dict[str, Any]],
    chosen_game: Dict[str, Any],
    engine: StatEngine,
    bridge: NFLDataBridge,
    all_plays: List[Dict[str, Any]],
    active_season: int,
    default_camera: str,
) -> str:
    """
    Sub-loop for stepping through plays in a game or jumping to chalkboard/explorer.
    Returns: 'exit', 'change_game', or 'change_quarter'.
    """
    current_cam = default_camera
    while True:
        pid = chosen_play.get("play_id", "N/A")
        qtr = chosen_play.get("qtr", 1)
        q_label = "OT" if qtr >= 5 else f"Q{qtr}"
        play_title = f"GAME VIEW: PLAY #{pid} — {q_label} ({chosen_play.get('posteam')} vs {chosen_play.get('defteam')})"
        print("\n" + AsciiArtRenderer.render_field_and_play(chosen_play, title=play_title, camera=current_cam))

        # Determine index in game_plays
        curr_idx = -1
        for i, p in enumerate(game_plays):
            if p.get("play_id") == chosen_play.get("play_id"):
                curr_idx = i
                break

        has_prev = curr_idx > 0
        has_next = curr_idx >= 0 and curr_idx + 1 < len(game_plays)

        print(f"\n  {C.BOLD}{C.GOLD}Play Action & Game Navigation Menu (Play #{pid} • {q_label}):{C.RESET}")
        print(f"    [N] {C.BOLD}Next Play in Game{C.RESET}     {'[▶ Next snap]' if has_next else '[End of Game]'}")
        print(f"    [P] {C.BOLD}Previous Play in Game{C.RESET} {'[◀ Prev snap]' if has_prev else '[Start of Game]'}")
        print(f"    [C] {C.BOLD}Concept Chalkboard{C.RESET}    (View generic playbook chalkboard diagram for this scheme)")
        print(f"    [S] {C.BOLD}Play Stats{C.RESET}            (In-depth analytics: EPA, WPA, Air Yards, YAC)")
        print(f"    [T] {C.BOLD}Drill Down Team{C.RESET}       (Team efficiency, rankings & roster leaders)")
        print(f"    [L] {C.BOLD}Drill Down Player{C.RESET}     (Player profile, stats breakdown & signature plays)")
        print(f"    [E] {C.BOLD}Play Explorer (/play){C.RESET} (Open interactive playbook concept explorer)")
        print(f"    [V] {C.BOLD}Switch Camera{C.RESET}         (Change view: behind-offense / behind-defense / sideline)")
        print(f"    [Q] {C.BOLD}Change Quarter{C.RESET}        (Return to quarter play table)")
        print(f"    [G] {C.BOLD}Change Game{C.RESET}           (Return to matchup browser)")
        print(f"    [X] {C.BOLD}Exit Game View{C.RESET}        (Return to main prompt)")

        try:
            act_in = prompt_input("  Choice [N/P/C/S/T/L/E/V/Q/G/X] (default: N): ").strip().lower() or "n"
        except (EOFError, KeyboardInterrupt):
            return "exit"

        if act_in in ("x", "exit", "close"):
            return "exit"
        if act_in in ("g", "change game", "games"):
            return "change_game"
        if act_in in ("q", "quarter", "change quarter"):
            return "change_quarter"

        if act_in in ("n", "next", "next play", "1"):
            if has_next:
                chosen_play = game_plays[curr_idx + 1]
                nxt_q = "OT" if chosen_play.get("qtr", 1) >= 5 else f"Q{chosen_play.get('qtr', 1)}"
                print(f"\n  {C.GREEN}▶ Stepping to Next Play #{chosen_play['play_id']} ({nxt_q} {chosen_play.get('down', 1)}&{chosen_play.get('ydstogo', 10)}){C.RESET}")
            else:
                print(f"\n  {C.YELLOW}⚠ Already at the final play of this game ({chosen_game['away_team']} @ {chosen_game['home_team']}).{C.RESET}")
        elif act_in in ("p", "prev", "previous", "previous play", "2"):
            if has_prev:
                chosen_play = game_plays[curr_idx - 1]
                prv_q = "OT" if chosen_play.get("qtr", 1) >= 5 else f"Q{chosen_play.get('qtr', 1)}"
                print(f"\n  {C.CYAN}◀ Stepping to Previous Play #{chosen_play['play_id']} ({prv_q} {chosen_play.get('down', 1)}&{chosen_play.get('ydstogo', 10)}){C.RESET}")
            else:
                print(f"\n  {C.YELLOW}⚠ Already at the opening play of this game.{C.RESET}")
        elif act_in in ("c", "concept", "chalkboard"):
            h = classify_play_concept_hierarchy(chosen_play)
            print("\n" + AsciiArtRenderer.render_generic_play_concept_diagram(h["concept_key"]))
        elif act_in in ("s", "stats", "play stats"):
            print("\n" + render_single_play_deep_dive(chosen_play))
        elif act_in in ("t", "team", "drill down team"):
            p_tm = str(chosen_play.get("posteam", ""))
            d_tm = str(chosen_play.get("defteam", ""))
            target_t = p_tm or d_tm or chosen_game["home_team"]
            print("\n" + render_team_drilldown_view(engine, all_plays, season=active_season, team=target_t))
        elif act_in in ("l", "player", "drill down player"):
            players_here = get_play_key_players(chosen_play)
            target_p = players_here[0] if players_here else "Mahomes"
            print("\n" + render_player_drilldown_view(engine, all_plays, season=active_season, player_name=target_p, interactive=False))
        elif act_in in ("e", "explorer", "play", "/play"):
            interactive_play_explorer(engine, bridge, all_plays, active_season=active_season, default_camera=current_cam)
        elif act_in in ("v", "camera", "switch camera"):
            try:
                c_in = prompt_input("  Camera perspective [1] behind-offense  [2] behind-defense  [3] sideline  [4] all (default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                c_in = "1"
            c_map = {"1": "behind-offense", "2": "behind-defense", "3": "sideline", "4": "all"}
            current_cam = c_map.get(c_in, c_in)


def interactive_game_browser(
    engine: StatEngine,
    bridge: NFLDataBridge,
    plays: List[Dict[str, Any]],
    active_season: int = CURRENT_SEASON,
    default_camera: str = "behind-offense",
    initial_game_id: Optional[str] = None,
    initial_play_id: Optional[int] = None,
    initial_team: Optional[str] = None,
    initial_week: Optional[int] = None,
    initial_qtr: Optional[int] = None,
) -> None:
    """
    Interactive NFL Game Center & Play-by-Play Browser:
    - First category: Browse by Team (Teams -> Week/Matchup) or Browse by Week (Week -> Matchup) or All Games.
    - Matchup selection -> Quarter selection (including Overtime/OT if applicable).
    - Renders ASCII table of plays in that quarter.
    - Selecting a play diagrams it on the field with Next Play / Prev Play navigation and Concept Chalkboard cross-linking.
    """
    s_plays = plays_for_season(plays, active_season)
    if not s_plays:
        print(f"\n{C.YELLOW}⚠ No play-by-play data loaded for season {active_season}. Use `/season` to switch seasons.{C.RESET}")
        return

    all_games = extract_games_summary(plays, active_season)
    if not all_games:
        print(f"\n{C.YELLOW}⚠ No games recorded in dataset for season {active_season}.{C.RESET}")
        return

    chosen_game: Optional[Dict[str, Any]] = None
    if initial_game_id:
        chosen_game = next((g for g in all_games if g["game_id"] == initial_game_id), None)
    elif initial_play_id:
        target_p = next((p for p in s_plays if p.get("play_id") == initial_play_id), None)
        if target_p and target_p.get("game_id"):
            chosen_game = next((g for g in all_games if g["game_id"] == target_p["game_id"]), None)

    jump_play_id = initial_play_id

    while True:
        if not chosen_game:
            print(f"\n{C.BOLD}{C.GREEN}=== 🏟️ NFL GAME CENTER & PLAY-BY-PLAY BROWSER ==={C.RESET}")
            print(f"  Active Season: {C.BOLD}{active_season}{C.RESET} • Total Games: {C.BOLD}{len(all_games)}{C.RESET}")
            print("  Select Game Browsing Mode:")
            print(f"    [1] {C.BOLD}Browse by Team{C.RESET}  (Teams -> Weekly Schedule & Matchups)")
            print(f"    [2] {C.BOLD}Browse by Week{C.RESET}  (Week -> All Matchups in that Week)")
            print(f"    [3] {C.BOLD}All Games{C.RESET}       (Direct Matchup List)")

            if initial_team:
                mode_choice = "1"
            elif initial_week:
                mode_choice = "2"
            else:
                try:
                    mode_choice = prompt_input("  Choose mode [1-3] (or 'q' to exit, default: 1): ").strip().lower() or "1"
                except (EOFError, KeyboardInterrupt):
                    break

            if mode_choice in ("q", "quit", "exit"):
                break

            if mode_choice in ("1", "team", "by team"):
                all_teams = sorted({g["away_team"] for g in all_games} | {g["home_team"] for g in all_games})
                if initial_team and initial_team in all_teams:
                    sel_team = initial_team
                    initial_team = None
                else:
                    print(f"\n  {C.BOLD}{C.CYAN}Available Teams in {active_season} Games ({len(all_teams)} teams):{C.RESET}")
                    for t_i, tm in enumerate(all_teams, 1):
                        g_count = sum(1 for g in all_games if g["away_team"] == tm or g["home_team"] == tm)
                        print(f"    [{t_i:2d}] {C.BOLD}{tm:<4}{C.RESET} ({g_count} game{'s' if g_count != 1 else ''})")
                    try:
                        tm_in = prompt_input(f"  Select team number or abbreviation [1-{len(all_teams)}] (or 'b' for back, default: 1): ").strip() or "1"
                    except (EOFError, KeyboardInterrupt):
                        break
                    if tm_in.lower() in ("b", "back"):
                        continue
                    if tm_in.lower() in ("q", "quit", "exit"):
                        break
                    if tm_in.isdigit() and 1 <= int(tm_in) <= len(all_teams):
                        sel_team = all_teams[int(tm_in) - 1]
                    else:
                        resolved = resolve_team_abbr(tm_in) or tm_in.upper()
                        sel_team = resolved if resolved in all_teams else all_teams[0]

                team_games = [g for g in all_games if g["away_team"] == sel_team or g["home_team"] == sel_team]
                print(f"\n  {C.BOLD}{C.GOLD}Schedule & Games for {sel_team} ({active_season} • {len(team_games)} matchups):{C.RESET}")
                for tg_i, tg in enumerate(team_games, 1):
                    ot_badge = f" {C.YELLOW}(OT){C.RESET}" if tg["has_ot"] else ""
                    print(f"    [{tg_i:2d}] Week {tg['week']:2d}: {C.BOLD}{tg['away_team']:<3} @ {tg['home_team']:<3}{C.RESET} ({tg['away_team']} {tg['away_score']} - {tg['home_team']} {tg['home_score']}{ot_badge}) [{tg['total_plays']} plays]")
                try:
                    match_in = prompt_input(f"  Select matchup [1-{len(team_games)}] (or 'b' for teams, default: 1): ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    break
                if match_in.lower() in ("b", "back"):
                    continue
                if match_in.lower() in ("q", "quit", "exit"):
                    break
                tg_idx = int(match_in) - 1 if match_in.isdigit() and 1 <= int(match_in) <= len(team_games) else 0
                chosen_game = team_games[tg_idx]

            elif mode_choice in ("2", "week", "by week"):
                avail_weeks = sorted({g["week"] for g in all_games})
                if initial_week and initial_week in avail_weeks:
                    sel_week = initial_week
                    initial_week = None
                else:
                    print(f"\n  {C.BOLD}{C.CYAN}Available Weeks in {active_season} ({len(avail_weeks)} weeks):{C.RESET}")
                    for w_i, wk in enumerate(avail_weeks, 1):
                        w_count = sum(1 for g in all_games if g["week"] == wk)
                        print(f"    [{w_i:2d}] Week {wk:2d} ({w_count} matchup{'s' if w_count != 1 else ''})")
                    try:
                        wk_in = prompt_input(f"  Select week [1-{len(avail_weeks)}] (or 'b' for back, default: 1): ").strip() or "1"
                    except (EOFError, KeyboardInterrupt):
                        break
                    if wk_in.lower() in ("b", "back"):
                        continue
                    if wk_in.lower() in ("q", "quit", "exit"):
                        break
                    if wk_in.isdigit() and int(wk_in) in avail_weeks:
                        sel_week = int(wk_in)
                    elif wk_in.isdigit() and 1 <= int(wk_in) <= len(avail_weeks):
                        sel_week = avail_weeks[int(wk_in) - 1]
                    else:
                        sel_week = avail_weeks[0]

                week_games = [g for g in all_games if g["week"] == sel_week]
                print(f"\n  {C.BOLD}{C.GOLD}Week {sel_week} Matchups ({len(week_games)} games):{C.RESET}")
                for wg_i, wg in enumerate(week_games, 1):
                    ot_badge = f" {C.YELLOW}(OT){C.RESET}" if wg["has_ot"] else ""
                    print(f"    [{wg_i:2d}] {C.BOLD}{wg['away_team']:<3} @ {wg['home_team']:<3}{C.RESET} ({wg['away_team']} {wg['away_score']} - {wg['home_team']} {wg['home_score']}{ot_badge}) [{wg['total_plays']} plays]")
                try:
                    match_in = prompt_input(f"  Select matchup [1-{len(week_games)}] (or 'b' for weeks, default: 1): ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    break
                if match_in.lower() in ("b", "back"):
                    continue
                if match_in.lower() in ("q", "quit", "exit"):
                    break
                wg_idx = int(match_in) - 1 if match_in.isdigit() and 1 <= int(match_in) <= len(week_games) else 0
                chosen_game = week_games[wg_idx]

            else:  # All Games
                print(f"\n  {C.BOLD}{C.GOLD}All {active_season} Matchups ({len(all_games)} games):{C.RESET}")
                for ag_i, ag in enumerate(all_games, 1):
                    ot_badge = f" {C.YELLOW}(OT){C.RESET}" if ag["has_ot"] else ""
                    print(f"    [{ag_i:2d}] Week {ag['week']:2d}: {C.BOLD}{ag['away_team']:<3} @ {ag['home_team']:<3}{C.RESET} ({ag['away_team']} {ag['away_score']} - {ag['home_team']} {ag['home_score']}{ot_badge}) [{ag['total_plays']} plays]")
                try:
                    match_in = prompt_input(f"  Select matchup [1-{len(all_games)}] (or 'b' for menu, default: 1): ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    break
                if match_in.lower() in ("b", "back"):
                    continue
                if match_in.lower() in ("q", "quit", "exit"):
                    break
                ag_idx = int(match_in) - 1 if match_in.isdigit() and 1 <= int(match_in) <= len(all_games) else 0
                chosen_game = all_games[ag_idx]

        # Game is chosen
        game_plays: List[Dict[str, Any]] = chosen_game["plays"]
        has_ot = chosen_game["has_ot"]
        ot_badge = f" {C.YELLOW}(Overtime / OT){C.RESET}" if has_ot else ""

        print(f"\n{C.BOLD}{C.CYAN}╔═══════════════════════════════════════════════════════════════════════════════════════╗{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}║  🏈 GAME CENTER: {chosen_game['away_team']} @ {chosen_game['home_team']} (Week {chosen_game['week']} • {chosen_game['season']}){' ' * max(0, 48 - len(chosen_game['away_team']) - len(chosen_game['home_team']))}║{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}║  Final Score: {chosen_game['away_team']} {chosen_game['away_score']} - {chosen_game['home_team']} {chosen_game['home_score']}{ot_badge}{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}╚═══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}")

        if jump_play_id:
            target_play = next((p for p in game_plays if p.get("play_id") == jump_play_id), None)
            if target_play:
                jump_play_id = None
                chosen_play = target_play
                ret = _play_navigation_loop(
                    chosen_play=chosen_play,
                    game_plays=game_plays,
                    chosen_game=chosen_game,
                    engine=engine,
                    bridge=bridge,
                    all_plays=plays,
                    active_season=active_season,
                    default_camera=default_camera,
                )
                if ret == "exit":
                    return
                elif ret == "change_game":
                    chosen_game = None
                    continue

        q_options = [
            ("1", "Quarter 1 (Q1)", 1),
            ("2", "Quarter 2 (Q2)", 2),
            ("3", "Quarter 3 (Q3)", 3),
            ("4", "Quarter 4 (Q4)", 4),
        ]
        if has_ot:
            q_options.append(("5", "Overtime (OT)", 5))
        q_options.append(("a", "All Quarters (Full Game)", None))

        print(f"\n  {C.BOLD}{C.GOLD}Select Quarter to View Plays:{C.RESET}")
        for q_key, q_lbl, q_val in q_options:
            cnt = len([p for p in game_plays if q_val is None or int(p.get("qtr", 1)) == q_val])
            print(f"    [{q_key.upper()}] {C.BOLD}{q_lbl:<26}{C.RESET} ({cnt} play{'s' if cnt != 1 else ''})")

        try:
            q_in = prompt_input("  Choose quarter [1-4" + (",5" if has_ot else "") + ",A] (or 'g' to change game, 'q' to exit, default: A): ").strip().lower() or "a"
        except (EOFError, KeyboardInterrupt):
            break
        if q_in in ("q", "quit", "exit"):
            break
        if q_in in ("g", "game", "games", "b", "back"):
            chosen_game = None
            continue

        found_qtr = False
        selected_qtr_val = None
        for q_key, q_lbl, q_val in q_options:
            if q_in == q_key.lower():
                selected_qtr_val = q_val
                found_qtr = True
                break
        if not found_qtr:
            for q_key, q_lbl, q_val in q_options:
                if len(q_in) > 1 and q_in in q_lbl.lower():
                    selected_qtr_val = q_val
                    found_qtr = True
                    break

        if selected_qtr_val is not None:
            quarter_plays = [p for p in game_plays if int(p.get("qtr", 1)) == selected_qtr_val]
            q_header = f"Q{selected_qtr_val}" if selected_qtr_val <= 4 else "OT"
        else:
            quarter_plays = list(game_plays)
            q_header = "FULL GAME"

        if not quarter_plays:
            print(f"\n  {C.YELLOW}⚠ No play records found in this dataset for {q_header}.{C.RESET}")
            continue

        tbl_title = f"{chosen_game['away_team']} @ {chosen_game['home_team']} • {q_header} ({len(quarter_plays)} Plays)"
        print("\n" + render_game_plays_table(quarter_plays, title=tbl_title))

        try:
            p_sel_in = prompt_input(f"  Select play [1-{len(quarter_plays)}] to diagram (or 'b' for quarters, 'g' for games, default: 1): ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            break
        if p_sel_in.lower() in ("b", "back"):
            continue
        if p_sel_in.lower() in ("g", "game"):
            chosen_game = None
            continue
        if p_sel_in.lower() in ("q", "quit", "exit"):
            break

        sel_p_idx = int(p_sel_in) - 1 if p_sel_in.isdigit() and 1 <= int(p_sel_in) <= len(quarter_plays) else 0
        chosen_play = quarter_plays[sel_p_idx]

        ret = _play_navigation_loop(
            chosen_play=chosen_play,
            game_plays=game_plays,
            chosen_game=chosen_game,
            engine=engine,
            bridge=bridge,
            all_plays=plays,
            active_season=active_season,
            default_camera=default_camera,
        )
        if ret == "exit":
            return
        elif ret == "change_game":
            chosen_game = None
            continue


def interactive_play_explorer(
    engine: StatEngine,
    bridge: NFLDataBridge,
    plays: List[Dict[str, Any]],
    active_season: int = CURRENT_SEASON,
    default_camera: str = "behind-offense",
) -> None:
    """
    Interactive Play Explorer:
    1. Select Phase: Offense, Defense, Special Teams.
    2. Select Sub-Category: Pass, Run, Pass Rush, Takeaways, Run Stops, Field Goals, Punts.
    3. Select Sub-Type / Scheme Concept: Quick Slant, Intermediate Crosser, Deep Shot, Screen, Inside Zone, Outside Zone, Power, QB Keep, etc.
    4. Shows generic play concept diagram (tactical chalkboard breakdown).
    5. Lists teams or weeks to drill down to a game it was used in (only shows options where it was played in).
    6. Select play to diagram on field.
    7. Play Action Menu: Stats, Team, Player, Go to Game View, Next Play, Prev Play, Concept Chalkboard, Camera.
    """
    s_plays = plays_for_season(plays, active_season)
    if not s_plays:
        print(f"\n{C.YELLOW}⚠ No play data loaded for season {active_season}. Use `/season` to switch seasons.{C.RESET}")
        return

    while True:
        print(f"\n{C.BOLD}{C.GREEN}=== 🏈 INTERACTIVE PLAY EXPLORER & MULTI-ANGLE DIAGRAMMER ==={C.RESET}")
        print(f"  Active Season: {C.BOLD}{active_season}{C.RESET}")
        print("  Select Play Phase / Unit:")
        print(f"    [1] {C.BOLD}Offense{C.RESET}       (Pass, Rush, Play-Action, Screen)")
        print(f"    [2] {C.BOLD}Defense{C.RESET}       (Interceptions, Sacks, Tackles for Loss, Stops)")
        print(f"    [3] {C.BOLD}Special Teams{C.RESET} (Field Goals, Extra Points, Punts, Kickoffs)")
        try:
            ph_in = prompt_input("  Choose phase [1-3] (or 'q' to exit, default: 1): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if ph_in in ("q", "quit", "exit", "close"):
            break

        ph_map = {
            "1": "offense", "offense": "offense", "off": "offense", "o": "offense",
            "2": "defense", "defense": "defense", "def": "defense", "d": "defense",
            "3": "special_teams", "special": "special_teams", "special teams": "special_teams", "st": "special_teams"
        }
        phase = ph_map.get(ph_in, "offense")

        chosen_concept_key = None
        chosen_concept_title = ""

        if phase == "offense":
            print(f"\n  {C.BOLD}{C.CYAN}Select Offensive Play Category:{C.RESET}")
            print(f"    [1] {C.BOLD}Pass{C.RESET} (Quick Slant, Intermediate Crosser, Deep Shot, Screen)")
            print(f"    [2] {C.BOLD}Run{C.RESET}  (Inside Zone, Outside Zone, Power/Counter, QB Keep)")
            try:
                cat_in = prompt_input("  Choose category [1-2] (or 'b' for back, default: 1): ").strip().lower() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if cat_in in ("b", "back"):
                continue
            if cat_in in ("q", "quit", "exit"):
                break

            if cat_in in ("1", "pass", "p"):
                print(f"\n  {C.BOLD}{C.GOLD}Select Pass Scheme / Sub-Type:{C.RESET}")
                print(f"    [1] {C.BOLD}Quick Game & Slant{C.RESET}         (quick_slant)        — 3-step timing, slants, flats, quick hot-read")
                print(f"    [2] {C.BOLD}Intermediate Crosser & Mesh{C.RESET} (intermediate_cross) — 10-18 yd crossing routes, rubs, layered zones")
                print(f"    [3] {C.BOLD}Play-Action Deep Shot{C.RESET}      (play_action_deep)   — Heavy run fake, max protect, deep post/go")
                print(f"    [4] {C.BOLD}Screen Pass{C.RESET}                (screen)             — Slip screen behind convoy of pulling linemen")
                try:
                    sub_in = prompt_input("  Choose scheme [1-4] (or 'b' for back, default: 1): ").strip().lower() or "1"
                except (EOFError, KeyboardInterrupt):
                    break
                if sub_in in ("b", "back"):
                    continue
                if sub_in in ("q", "quit", "exit"):
                    break
                sub_map = {
                    "1": ("quick_slant", "Quick Game & Slant"),
                    "2": ("intermediate_cross", "Intermediate Crosser & Mesh"),
                    "3": ("play_action_deep", "Play-Action Deep Shot"),
                    "4": ("screen", "Screen Pass"),
                }
                chosen_concept_key, chosen_concept_title = sub_map.get(sub_in, ("quick_slant", "Quick Game & Slant"))

            else:  # Run
                print(f"\n  {C.BOLD}{C.GOLD}Select Run Scheme / Sub-Type:{C.RESET}")
                print(f"    [1] {C.BOLD}Inside Zone & Dive{C.RESET}     (rush_inside)   — Double-team interior, cutback lane, north-south plunge")
                print(f"    [2] {C.BOLD}Outside Zone & Stretch{C.RESET} (rush_outside)  — Lateral stretch, reach blocks, perimeter crease")
                print(f"    [3] {C.BOLD}Power & Counter Gap{C.RESET}    (power_gap)     — Pulling guard/tackle, kick-out block & lead wrap")
                print(f"    [4] {C.BOLD}QB Keep & Scramble{C.RESET}     (qb_scramble)   — Read option, bootleg rollout, broken pocket scramble")
                try:
                    sub_in = prompt_input("  Choose scheme [1-4] (or 'b' for back, default: 1): ").strip().lower() or "1"
                except (EOFError, KeyboardInterrupt):
                    break
                if sub_in in ("b", "back"):
                    continue
                if sub_in in ("q", "quit", "exit"):
                    break
                sub_map = {
                    "1": ("rush_inside", "Inside Zone & Dive"),
                    "2": ("rush_outside", "Outside Zone & Stretch"),
                    "3": ("power_gap", "Power & Counter Gap"),
                    "4": ("qb_scramble", "QB Keep & Scramble"),
                }
                chosen_concept_key, chosen_concept_title = sub_map.get(sub_in, ("rush_inside", "Inside Zone & Dive"))

        elif phase == "defense":
            print(f"\n  {C.BOLD}{C.CYAN}Select Defensive Category / Sub-Type:{C.RESET}")
            print(f"    [1] {C.BOLD}Pass Rush & Sacks{C.RESET}            (pass_rush_sack)       — Edge collapse, interior push, stunts & sacks")
            print(f"    [2] {C.BOLD}Takeaways & Interceptions{C.RESET}    (turnover_interception)— Zone jumps, tipped passes, takeaway coverage")
            print(f"    [3] {C.BOLD}Run Stops & Tackles for Loss{C.RESET} (tfl_run_stop)        — Backfield penetration, gang tackle for loss")
            try:
                sub_in = prompt_input("  Choose category [1-3] (or 'b' for back, default: 1): ").strip().lower() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if sub_in in ("b", "back"):
                continue
            if sub_in in ("q", "quit", "exit"):
                break
            sub_map = {
                "1": ("pass_rush_sack", "Pass Rush & Sacks"),
                "2": ("turnover_interception", "Takeaways & Interceptions"),
                "3": ("tfl_run_stop", "Run Stops & Tackles for Loss"),
            }
            chosen_concept_key, chosen_concept_title = sub_map.get(sub_in, ("pass_rush_sack", "Pass Rush & Sacks"))

        else:  # Special Teams
            print(f"\n  {C.BOLD}{C.CYAN}Select Special Teams Unit / Sub-Type:{C.RESET}")
            print(f"    [1] {C.BOLD}Field Goal & Extra Point{C.RESET} (field_goal) — Snap-to-kick 1.3s tempo & line protection wall")
            print(f"    [2] {C.BOLD}Punt & Coverage{C.RESET}          (punt)       — Spiral punt hangtime, gunners & coverage contain")
            try:
                sub_in = prompt_input("  Choose unit [1-2] (or 'b' for back, default: 1): ").strip().lower() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if sub_in in ("b", "back"):
                continue
            if sub_in in ("q", "quit", "exit"):
                break
            sub_map = {
                "1": ("field_goal", "Field Goal & Extra Point"),
                "2": ("punt", "Punt & Coverage"),
            }
            chosen_concept_key, chosen_concept_title = sub_map.get(sub_in, ("field_goal", "Field Goal & Extra Point"))

        # Step 4: Show Generic Play Diagram
        print("\n" + AsciiArtRenderer.render_generic_play_concept_diagram(chosen_concept_key))

        # Step 5: Filter plays by concept and offer drilldown by Team or Week
        matching_plays = filter_plays_by_concept_key(s_plays, chosen_concept_key)
        if not matching_plays:
            matching_plays = filter_plays_by_concept_key(plays, chosen_concept_key)

        if not matching_plays:
            print(f"\n  {C.YELLOW}⚠ No individual game plays found matching concept `{chosen_concept_key}` in loaded data.{C.RESET}")
            try:
                prompt_input("  Press Enter to return to play menu...")
            except (EOFError, KeyboardInterrupt):
                break
            continue

        if phase == "offense":
            avail_teams = sorted({p.get("posteam") for p in matching_plays if p.get("posteam")})
        elif phase == "defense":
            avail_teams = sorted({(p.get("defteam") or p.get("posteam")) for p in matching_plays if (p.get("defteam") or p.get("posteam"))})
        else:
            avail_teams = sorted({(p.get("posteam") or p.get("defteam")) for p in matching_plays if (p.get("posteam") or p.get("defteam"))})

        avail_weeks = sorted({int(p.get("week", 1)) for p in matching_plays})

        # Step 5: Drill down by Team, Week, or All Matchups to reach a Game & Quarter
        all_games = extract_games_summary(plays, active_season)

        print(f"\n  {C.BOLD}{C.CYAN}Drill Down to Matchups executing {chosen_concept_title} ({len(matching_plays)} plays available):{C.RESET}")
        print(f"    [1] {C.BOLD}Browse by Team{C.RESET}  (Teams executing: {', '.join(avail_teams)})")
        print(f"    [2] {C.BOLD}Browse by Week{C.RESET}  (Weeks executed: {', '.join(map(str, avail_weeks))})")
        print(f"    [3] {C.BOLD}All Matchups{C.RESET}    (View matchups that ran this concept)")

        try:
            dd_in = prompt_input("  Choose browsing category [1-3] (or 'b' to change scheme, default: 1): ").strip().lower() or "1"
        except (EOFError, KeyboardInterrupt):
            break
        if dd_in in ("b", "back"):
            continue
        if dd_in in ("q", "quit", "exit"):
            break

        chosen_game: Optional[Dict[str, Any]] = None

        if dd_in in ("1", "team", "by team"):
            print(f"\n  {C.BOLD}{C.GOLD}Teams that executed {chosen_concept_title}:{C.RESET}")
            for t_idx, tm in enumerate(avail_teams, 1):
                t_count = sum(1 for p in matching_plays if p.get("posteam") == tm or p.get("defteam") == tm)
                print(f"    [{t_idx:2d}] {C.BOLD}{tm:<4}{C.RESET} ({t_count} play{'s' if t_count != 1 else ''})")
            try:
                tm_sel = prompt_input(f"  Select team [1-{len(avail_teams)}] (or 'b' for back, default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if tm_sel.lower() in ("b", "back"):
                continue
            if tm_sel.isdigit() and 1 <= int(tm_sel) <= len(avail_teams):
                sel_tm = avail_teams[int(tm_sel) - 1]
            else:
                res_tm = resolve_team_abbr(tm_sel) or tm_sel.upper()
                sel_tm = res_tm if res_tm in avail_teams else avail_teams[0]

            team_concept_plays = [p for p in matching_plays if p.get("posteam") == sel_tm or p.get("defteam") == sel_tm]
            team_game_ids = sorted({p["game_id"] for p in team_concept_plays})
            team_games = [g for g in all_games if g["game_id"] in team_game_ids]

            print(f"\n  {C.BOLD}{C.GOLD}Matchups for {sel_tm} using {chosen_concept_title} ({len(team_games)} games):{C.RESET}")
            for g_idx, tg in enumerate(team_games, 1):
                g_c_cnt = sum(1 for p in team_concept_plays if p.get("game_id") == tg["game_id"])
                ot_str = f" {C.YELLOW}(OT){C.RESET}" if tg["has_ot"] else ""
                print(f"    [{g_idx:2d}] Week {tg['week']:2d}: {C.BOLD}{tg['away_team']:<3} @ {tg['home_team']:<3}{C.RESET} ({tg['away_team']} {tg['away_score']} - {tg['home_team']} {tg['home_score']}{ot_str}) [{g_c_cnt} {chosen_concept_title} play{'s' if g_c_cnt != 1 else ''}]")

            try:
                g_sel = prompt_input(f"  Select matchup [1-{len(team_games)}] (or 'b' for teams, default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if g_sel.lower() in ("b", "back"):
                continue
            tg_idx = int(g_sel) - 1 if g_sel.isdigit() and 1 <= int(g_sel) <= len(team_games) else 0
            chosen_game = team_games[tg_idx]

        elif dd_in in ("2", "week", "by week"):
            print(f"\n  {C.BOLD}{C.GOLD}Weeks where {chosen_concept_title} was executed:{C.RESET}")
            for w_idx, wk in enumerate(avail_weeks, 1):
                w_count = sum(1 for p in matching_plays if int(p.get("week", 1)) == wk)
                print(f"    [{w_idx:2d}] Week {wk:2d} ({w_count} play{'s' if w_count != 1 else ''})")
            try:
                wk_sel = prompt_input(f"  Select week [1-{len(avail_weeks)}] (or 'b' for back, default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if wk_sel.lower() in ("b", "back"):
                continue
            if wk_sel.isdigit() and int(wk_sel) in avail_weeks:
                sel_wk = int(wk_sel)
            elif wk_sel.isdigit() and 1 <= int(wk_sel) <= len(avail_weeks):
                sel_wk = avail_weeks[int(wk_sel) - 1]
            else:
                sel_wk = avail_weeks[0]

            week_concept_plays = [p for p in matching_plays if int(p.get("week", 1)) == sel_wk]
            week_game_ids = sorted({p["game_id"] for p in week_concept_plays})
            week_games = [g for g in all_games if g["game_id"] in week_game_ids]

            print(f"\n  {C.BOLD}{C.GOLD}Week {sel_wk} Matchups using {chosen_concept_title} ({len(week_games)} games):{C.RESET}")
            for wg_idx, wg in enumerate(week_games, 1):
                g_c_cnt = sum(1 for p in week_concept_plays if p.get("game_id") == wg["game_id"])
                ot_str = f" {C.YELLOW}(OT){C.RESET}" if wg["has_ot"] else ""
                print(f"    [{wg_idx:2d}] {C.BOLD}{wg['away_team']:<3} @ {wg['home_team']:<3}{C.RESET} ({wg['away_team']} {wg['away_score']} - {wg['home_team']} {wg['home_score']}{ot_str}) [{g_c_cnt} {chosen_concept_title} play{'s' if g_c_cnt != 1 else ''}]")

            try:
                g_sel = prompt_input(f"  Select matchup [1-{len(week_games)}] (or 'b' for weeks, default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if g_sel.lower() in ("b", "back"):
                continue
            wg_idx = int(g_sel) - 1 if g_sel.isdigit() and 1 <= int(g_sel) <= len(week_games) else 0
            chosen_game = week_games[wg_idx]

        else:  # All Matchups
            concept_game_ids = sorted({p["game_id"] for p in matching_plays})
            concept_games = [g for g in all_games if g["game_id"] in concept_game_ids]

            print(f"\n  {C.BOLD}{C.GOLD}All Matchups using {chosen_concept_title} ({len(concept_games)} games):{C.RESET}")
            for cg_idx, cg in enumerate(concept_games, 1):
                g_c_cnt = sum(1 for p in matching_plays if p.get("game_id") == cg["game_id"])
                ot_str = f" {C.YELLOW}(OT){C.RESET}" if cg["has_ot"] else ""
                print(f"    [{cg_idx:2d}] Week {cg['week']:2d}: {C.BOLD}{cg['away_team']:<3} @ {cg['home_team']:<3}{C.RESET} ({cg['away_team']} {cg['away_score']} - {cg['home_team']} {cg['home_score']}{ot_str}) [{g_c_cnt} {chosen_concept_title} play{'s' if g_c_cnt != 1 else ''}]")

            try:
                g_sel = prompt_input(f"  Select matchup [1-{len(concept_games)}] (or 'b' for menu, default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                break
            if g_sel.lower() in ("b", "back"):
                continue
            cg_idx = int(g_sel) - 1 if g_sel.isdigit() and 1 <= int(g_sel) <= len(concept_games) else 0
            chosen_game = concept_games[cg_idx]

        if not chosen_game:
            continue

        # Step 6: Quarter Selection for chosen_game (NO individual plays displayed until inside quarter!)
        game_all_plays = chosen_game["plays"]
        game_concept_plays = [p for p in matching_plays if p.get("game_id") == chosen_game["game_id"]]
        if not game_concept_plays:
            game_concept_plays = game_all_plays

        has_ot = chosen_game["has_ot"]
        q_options = [
            ("1", "Quarter 1 (Q1)", 1),
            ("2", "Quarter 2 (Q2)", 2),
            ("3", "Quarter 3 (Q3)", 3),
            ("4", "Quarter 4 (Q4)", 4),
        ]
        if has_ot:
            q_options.append(("5", "Overtime (OT)", 5))
        q_options.append(("a", f"All Quarters ({chosen_concept_title})", None))

        print(f"\n  {C.BOLD}{C.GOLD}Select Quarter in {chosen_game['away_team']} @ {chosen_game['home_team']} (Week {chosen_game['week']}):{C.RESET}")
        for q_key, q_lbl, q_val in q_options:
            q_c_cnt = len([p for p in game_concept_plays if q_val is None or int(p.get("qtr", 1)) == q_val])
            print(f"    [{q_key.upper()}] {C.BOLD}{q_lbl:<36}{C.RESET} ({q_c_cnt} play{'s' if q_c_cnt != 1 else ''})")

        try:
            q_in = prompt_input("  Choose quarter [1-4" + (",5" if has_ot else "") + ",A] (or 'b' for matchups, default: A): ").strip().lower() or "a"
        except (EOFError, KeyboardInterrupt):
            break
        if q_in in ("b", "back"):
            continue
        if q_in in ("q", "quit", "exit"):
            break

        found_qtr = False
        selected_qtr_val = None
        for q_key, q_lbl, q_val in q_options:
            if q_in == q_key.lower():
                selected_qtr_val = q_val
                found_qtr = True
                break
        if not found_qtr:
            for q_key, q_lbl, q_val in q_options:
                if len(q_in) > 1 and q_in in q_lbl.lower():
                    selected_qtr_val = q_val
                    found_qtr = True
                    break

        if selected_qtr_val is not None:
            quarter_plays = [p for p in game_concept_plays if int(p.get("qtr", 1)) == selected_qtr_val]
            q_hdr = f"Q{selected_qtr_val}" if selected_qtr_val <= 4 else "OT"
        else:
            quarter_plays = list(game_concept_plays)
            q_hdr = "FULL GAME"

        if not quarter_plays:
            print(f"\n  {C.YELLOW}⚠ No {chosen_concept_title} plays recorded in this dataset for {q_hdr}.{C.RESET}")
            continue

        # Step 7: NOW AND ONLY NOW INSIDE QUARTER LISTING, DISPLAY THE PLAYS!
        tbl_title = f"{chosen_game['away_team']} @ {chosen_game['home_team']} • {q_hdr} • {chosen_concept_title} ({len(quarter_plays)} Plays)"
        print("\n" + render_game_plays_table(quarter_plays, title=tbl_title))

        try:
            sel_in = prompt_input(f"  Select play [1-{len(quarter_plays)}] to diagram (or 'b' to change quarter, default: 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if sel_in.lower() in ("b", "back"):
            continue
        if sel_in.lower() in ("q", "quit", "exit"):
            break

        play_idx = int(sel_in) - 1 if sel_in.isdigit() and 1 <= int(sel_in) <= len(quarter_plays) else 0
        chosen_play = quarter_plays[play_idx]
        current_cam = "behind-defense" if phase == "defense" and default_camera == "behind-offense" else default_camera

        # Step 8: Play Diagram with Prominent Situation HUD
        play_title = f"PLAY #{chosen_play['play_id']} DIAGRAM — {chosen_play.get('qb_name') or chosen_play.get('player_name') or 'Play'} ({chosen_play.get('posteam')} vs {chosen_play.get('defteam')})"
        print("\n" + AsciiArtRenderer.render_field_and_play(chosen_play, title=play_title, camera=current_cam))

        # Step 8: Play Action Menu
        while True:
            game_plays_here = sorted(
                [p for p in plays if p.get("game_id") == chosen_play.get("game_id")],
                key=lambda x: (int(x.get("qtr", 1)), int(x.get("play_id", 0)))
            )
            curr_g_idx = -1
            for gi, gp in enumerate(game_plays_here):
                if gp.get("play_id") == chosen_play.get("play_id"):
                    curr_g_idx = gi
                    break
            has_next = curr_g_idx >= 0 and curr_g_idx + 1 < len(game_plays_here)
            has_prev = curr_g_idx > 0

            print(f"\n  {C.BOLD}{C.GOLD}Play Action Menu for Play #{chosen_play['play_id']} ({chosen_concept_title}):{C.RESET}")
            print(f"    [1]  {C.BOLD}Play Stats{C.RESET}              (In-depth analytics: EPA, WPA, Air Yards, YAC, Situation)")
            print(f"    [2]  {C.BOLD}Drill Down Team{C.RESET}         (Offense/Defense team efficiency, rankings & roster leaders)")
            print(f"    [3]  {C.BOLD}Drill Down Player{C.RESET}       (Player season profile, stats breakdown & signature plays)")
            print(f"    [4]  {C.BOLD}Go to Game View{C.RESET}         (Open in /games: match scoreboard, quarter play log & step plays)")
            print(f"    [5]  {C.BOLD}Next Play in Game{C.RESET}       {'[▶ Next snap]' if has_next else '[End of Game]'}")
            print(f"    [6]  {C.BOLD}Prev Play in Game{C.RESET}       {'[◀ Prev snap]' if has_prev else '[Start of Game]'}")
            print(f"    [7]  {C.BOLD}View Concept Chalkboard{C.RESET} (Re-display tactical chalkboard schematic)")
            print(f"    [8]  {C.BOLD}Switch Camera{C.RESET}           (Change view: behind-offense / behind-defense / sideline)")
            print(f"    [9]  {C.BOLD}Another Play{C.RESET}            (Return to play selection)")
            print(f"    [10] {C.BOLD}Exit Explorer{C.RESET}           (Return to main prompt)")

            try:
                act = prompt_input("  Choice [1-10] (default: 1): ").strip().lower() or "1"
            except (EOFError, KeyboardInterrupt):
                return

            if act in ("1", "stats", "play stats"):
                print(render_single_play_deep_dive(chosen_play))
            elif act in ("2", "team", "drill down team"):
                p_team = str(chosen_play.get("posteam", ""))
                d_team = str(chosen_play.get("defteam", ""))
                if p_team and d_team:
                    try:
                        t_choice = prompt_input(f"  Select Team: [1] {p_team} (Offense)  [2] {d_team} (Defense) (default: 1): ").strip() or "1"
                        target_t = d_team if t_choice in ("2", d_team.lower()) else p_team
                    except (EOFError, KeyboardInterrupt):
                        target_t = p_team
                else:
                    target_t = p_team or d_team or "KC"
                print(render_team_drilldown_view(engine, plays, season=active_season, team=target_t))
            elif act in ("3", "player", "drill down player"):
                players_here = get_play_key_players(chosen_play)
                if not players_here:
                    try:
                        target_p = prompt_input("  Enter player name to drill down: ").strip() or "Mahomes"
                    except (EOFError, KeyboardInterrupt):
                        target_p = "Mahomes"
                elif len(players_here) == 1:
                    target_p = players_here[0]
                    print(f"  {C.CYAN}ℹ Drilling down for player: {target_p}{C.RESET}")
                else:
                    print("  Players on this play:")
                    for p_i, p_n in enumerate(players_here, 1):
                        print(f"    [{p_i}] {p_n}")
                    try:
                        p_sel = prompt_input(f"  Select player [1-{len(players_here)}] (default: 1): ").strip() or "1"
                        p_idx = int(p_sel) - 1 if p_sel.isdigit() and 1 <= int(p_sel) <= len(players_here) else 0
                        target_p = players_here[p_idx]
                    except (EOFError, KeyboardInterrupt):
                        target_p = players_here[0]
                print(render_player_drilldown_view(engine, plays, season=active_season, player_name=target_p, interactive=True))
            elif act in ("4", "game", "game view", "go to game view", "g"):
                interactive_game_browser(
                    engine,
                    bridge,
                    plays,
                    active_season=active_season,
                    default_camera=current_cam,
                    initial_game_id=chosen_play.get("game_id"),
                    initial_play_id=chosen_play.get("play_id"),
                )
            elif act in ("5", "next", "next play", "n"):
                if has_next:
                    chosen_play = game_plays_here[curr_g_idx + 1]
                    q_n = "OT" if chosen_play.get("qtr", 1) >= 5 else f"Q{chosen_play.get('qtr', 1)}"
                    print(f"\n  {C.GREEN}▶ Stepping to Next Play #{chosen_play['play_id']} ({q_n} {chosen_play.get('down', 1)}&{chosen_play.get('ydstogo', 10)}){C.RESET}")
                    pt = f"PLAY #{chosen_play['play_id']} DIAGRAM — {chosen_play.get('qb_name') or chosen_play.get('player_name') or 'Play'} ({chosen_play.get('posteam')} vs {chosen_play.get('defteam')})"
                    print("\n" + AsciiArtRenderer.render_field_and_play(chosen_play, title=pt, camera=current_cam))
                else:
                    print(f"\n  {C.YELLOW}⚠ Already at the final play of this game.{C.RESET}")
            elif act in ("6", "prev", "previous", "previous play", "p"):
                if has_prev:
                    chosen_play = game_plays_here[curr_g_idx - 1]
                    q_p = "OT" if chosen_play.get("qtr", 1) >= 5 else f"Q{chosen_play.get('qtr', 1)}"
                    print(f"\n  {C.CYAN}◀ Stepping to Previous Play #{chosen_play['play_id']} ({q_p} {chosen_play.get('down', 1)}&{chosen_play.get('ydstogo', 10)}){C.RESET}")
                    pt = f"PLAY #{chosen_play['play_id']} DIAGRAM — {chosen_play.get('qb_name') or chosen_play.get('player_name') or 'Play'} ({chosen_play.get('posteam')} vs {chosen_play.get('defteam')})"
                    print("\n" + AsciiArtRenderer.render_field_and_play(chosen_play, title=pt, camera=current_cam))
                else:
                    print(f"\n  {C.YELLOW}⚠ Already at the opening play of this game.{C.RESET}")
            elif act in ("7", "chalkboard", "concept", "c"):
                h_c = classify_play_concept_hierarchy(chosen_play)
                print("\n" + AsciiArtRenderer.render_generic_play_concept_diagram(h_c["concept_key"]))
            elif act in ("8", "camera"):
                try:
                    c_in = prompt_input("  Camera perspective [1] behind-offense  [2] behind-defense  [3] sideline  [4] all (default: 1): ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    c_in = "1"
                c_map = {"1": "behind-offense", "2": "behind-defense", "3": "sideline", "4": "all"}
                current_cam = c_map.get(c_in, c_in)
                pt = f"PLAY #{chosen_play['play_id']} DIAGRAM — {chosen_play.get('qb_name') or chosen_play.get('player_name') or 'Play'} ({chosen_play.get('posteam')} vs {chosen_play.get('defteam')})"
                print("\n" + AsciiArtRenderer.render_field_and_play(chosen_play, title=pt, camera=current_cam))
            elif act in ("9", "another", "back", "b"):
                break
            elif act in ("10", "exit", "q", "quit"):
                return


def interactive_custom_stat_wizard(engine: StatEngine, plays: List[Dict[str, Any]], season: int = CURRENT_SEASON) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}=== 🧪 COMPOSABLE CUSTOM STAT BUILDER ==={C.RESET}")
    print(f"  {C.BOLD}[1]{C.RESET} Build a custom stat from scratch (Season, Game-by-Game, or Play-by-Play scope)")
    print(f"  {C.BOLD}[2]{C.RESET} Start from a customizable template (e.g. Game-Conditional QB Stat, Filtered Concept Stat, 3rd Down Clutch, Chained Stat)")
    mode = prompt_input("  Select mode [1/2] (default: 1): ").strip() or "1"

    preset: Dict[str, str] = {}
    if mode == "2":
        print(f"\n  {C.BOLD}{C.CYAN}Available Customizable Templates:{C.RESET}")
        for idx, tmpl in enumerate(CUSTOM_STAT_TEMPLATES, 1):
            print(f"    [{idx}] {C.BOLD}{tmpl['label']}{C.RESET}")
            print(f"        Formula: `{tmpl['formula']}` | Scope: {tmpl['scope']} ({tmpl['agg']}) | Filter: `{tmpl['filter_expr'] or 'None'}`")
        t_idx = prompt_input(f"  Pick a template [1-{len(CUSTOM_STAT_TEMPLATES)}] (default: 1): ").strip() or "1"
        try:
            preset = dict(CUSTOM_STAT_TEMPLATES[max(0, min(len(CUSTOM_STAT_TEMPLATES) - 1, int(t_idx) - 1))])
        except ValueError:
            preset = dict(CUSTOM_STAT_TEMPLATES[0])

    print(f"\n  {C.CYAN}Available Building Blocks (Traditional + Existing Custom Stats):{C.RESET}")
    building_blocks = sorted(set(engine.stats.keys()) | BASE_METRIC_KEYS)
    print("  " + ", ".join(building_blocks))

    default_name = preset.get("name", "custom_efficiency_score")
    name = prompt_input(f"  Stat ID (default: {default_name}): ").strip() or default_name
    default_title = preset.get("title", name.replace("_", " ").title())
    title = prompt_input(f"  Display Title (default: {default_title}): ").strip() or default_title
    default_group = preset.get("group_by", "qb")
    group_by = prompt_input(f"  Group by [qb/team/receiver/rusher/play_concept/conference/game] (default: {default_group}): ").strip() or default_group
    default_scope = preset.get("scope", "season")
    scope = prompt_input(f"  Evaluation Scope [season / game / play] (default: {default_scope}): ").strip().lower() or default_scope
    default_agg = preset.get("agg", "sum" if scope == "game" else "formula")
    agg = default_agg
    if scope in ("game", "play"):
        agg = prompt_input(f"  Aggregation across {scope}s [sum / avg / count_true / rate / max / min] (default: {default_agg}): ").strip().lower() or default_agg

    default_filter = preset.get("filter_expr", "")
    filter_expr = prompt_input(f"  Optional Play Filter (e.g. `is_screen == 1` or `down == 3` or `conf == 'AFC'`) [{default_filter or 'None'}]: ").strip() or default_filter
    default_formula = preset.get("formula", "(yards_per_play * 2.5) + (epa_per_play * 20.0)")
    formula = prompt_input(f"  Formula (default: {default_formula}): ").strip() or default_formula
    default_unit = preset.get("unit", "pts")
    unit = prompt_input(f"  Unit label (default: {default_unit}): ").strip() or default_unit
    default_desc = preset.get("description", f"Custom {scope}-scoped stat grouped by {group_by}.")
    desc = prompt_input(f"  Description (default: {default_desc}): ").strip() or default_desc
    default_calc = preset.get("calculation_explained", f"Evaluated at {scope} scope ({agg}) with filter `{filter_expr or 'all plays'}` via `{formula}`.")
    calc = prompt_input(f"  Calculation explanation (default: {default_calc}): ").strip() or default_calc

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
        p_season = plays_for_season(plays, season)
        if p_season:
            print(render_general_stat_view(engine, p_season, sdef.name, season, view_mode="table"))
        else:
            print(f"  {C.YELLOW}⚠ Stat saved, but no {season} plays are loaded to preview it (available: {', '.join(map(str, available_seasons(plays))) or 'none'}).{C.RESET}")
    except Exception as exc:
        print(f"\n  {C.RED}✖ Error creating stat: {exc}{C.RESET}")


STAT_CATALOG_GROUPS: List[Tuple[str, str, List[str]]] = [
    (
        "🏈 Quarterback & Passing Analytics",
        "Passer rating, completions, yardage, accuracy, touchdowns, sacks, and dropback efficiency.",
        [
            "passing_yards",
            "completions",
            "pass_attempts",
            "completion_pct",
            "yards_per_attempt",
            "any_a",
            "passer_rating",
            "pass_touchdowns",
            "interceptions",
            "interception_rate",
            "sacks",
            "sack_rate",
            "epa_per_play",
        ],
    ),
    (
        "🏃 Rushing & Ground Game Analytics",
        "Designed runs, rush yardage, per-carry efficiency, and rushing touchdowns.",
        [
            "rushing_yards",
            "yards_per_rush",
            "rush_touchdowns",
        ],
    ),
    (
        "🎯 Receiving & Yards After Catch (YAC) Analytics",
        "Target distribution, run-after-catch, and model-expected YAC performance across all completions.",
        [
            "yards_after_catch",
            "yac_over_expected",
        ],
    ),
    (
        "⚡ Team Offense, Scoring & Drive Efficiency",
        "Drive-level, per-snap volume, series conversion, explosive plays, and scoring rates.",
        [
            "plays",
            "yards_per_play",
            "first_downs",
            "first_down_rate",
            "touchdowns",
            "touchdown_rate",
            "success_rate_pct",
            "explosive_play_rate",
            "turnover_rate",
            "turnovers",
            "takeaways",
            "clean_play_score",
        ],
    ),
    (
        "🚩 Penalties, Discipline & Situational Operations",
        "Accepted penalties, penalty yardage, penalties drawn, differentials, and timeouts.",
        [
            "penalties",
            "penalty_yards",
            "penalties_drawn",
            "penalty_yards_drawn",
            "net_penalties",
            "net_penalty_yards",
            "timeouts",
        ],
    ),
    (
        "🏆 Advanced QB Impact & Game Decisions (Built-in Analytics)",
        "Composite game impact rating (0-100), meaningful wins/losses, quality starts, and explosive pass rate.",
        [
            "qb_impact_score",
            "qb_meaningful_win",
            "qb_meaningful_loss",
            "qb_quality_start",
            "explosive_pass_rate",
        ],
    ),
    (
        "🏈 Fantasy Football Analytics",
        "PPR, Half-PPR, and Standard fantasy points, per-game averages, and weekly scoring profiles.",
        [
            "fantasy_points",
            "fantasy_points_ppr",
            "fantasy_points_half_ppr",
            "fantasy_ppg",
        ],
    ),
]


def render_stats_catalog(engine: StatEngine) -> str:
    """
    Renders an organized, human-readable catalog of all registered traditional and custom stats,
    grouped by football category with clear descriptions, formulas, and evaluation scopes.
    """
    all_stats = engine.stats
    categorized: Set[str] = set()
    for _, _, keys in STAT_CATALOG_GROUPS:
        categorized.update(keys)

    # User-created or externally imported stats ONLY (never built-in stats designed at coding stage)
    builtin_names = set(DEFAULT_STATS.keys()) | set(EXAMPLE_CUSTOM_STATS.keys()) | {
        "qb_impact_score", "qb_meaningful_win", "qb_meaningful_loss", "qb_quality_start", "explosive_pass_rate",
    }
    user_created = [k for k in all_stats if k not in categorized and k not in builtin_names]
    sections = list(STAT_CATALOG_GROUPS)
    if user_created:
        sections.append((
            "🧪 User-Created & Imported Custom Stats",
            "Custom statistics created via /create or imported from external JSON files.",
            user_created,
        ))

    trad_count = sum(1 for s in all_stats.values() if s.category == "traditional")
    cust_count = sum(1 for s in all_stats.values() if s.category == "custom")

    lines: List[str] = [
        f"\n{C.BOLD}{C.CYAN}╔═══════════════════════════════════════════════════════════════════════════════════════╗",
        f"║                      📊 REGISTERED STATS & ANALYTICS CATALOG                          ║",
        f"╚═══════════════════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        f"  {C.DIM}Catalog: {len(all_stats)} registered metrics ({trad_count} Traditional • {cust_count} Custom).{C.RESET}",
        f"  {C.DIM}Usage: Run {C.RESET}{C.BOLD}{C.CYAN}/stat <stat_id>{C.RESET}{C.DIM} (e.g. `/stat epa_per_play`) or ask questions in plain English.{C.RESET}\n",
    ]

    for cat_title, cat_desc, keys in sections:
        matching = [all_stats[k] for k in keys if k in all_stats]
        if not matching:
            continue
        lines.append(f"{C.BOLD}{C.GOLD}── {cat_title} ({len(matching)}) ──{C.RESET}")
        lines.append(f"  {C.DIM}{cat_desc}{C.RESET}\n")
        for s in matching:
            type_badge = f"{C.MAGENTA}[CUSTOM]{C.RESET}" if s.category == "custom" else f"{C.BLUE}[TRADITIONAL]{C.RESET}"
            scope_str = f"Scope: {s.scope.upper()}" + (f" ({s.agg})" if s.scope != "season" else "")
            filter_str = f" • Filter: `{s.filter_expr}`" if s.filter_expr else ""
            unit_str = f" • Unit: {s.unit}" if s.unit else ""
            lines.append(f"  {C.BOLD}{C.CYAN}{s.name:<26}{C.RESET} {type_badge} {C.DIM}by {s.group_by.upper()} • {scope_str}{filter_str}{unit_str}{C.RESET}")
            lines.append(f"    {C.BOLD}{s.title}{C.RESET}")
            lines.append(f"    {C.WHITE}{s.description}{C.RESET}")
            lines.append(f"    {C.DIM}Formula: `{s.formula}`{C.RESET}\n")

    lines.append(f"  {C.DIM}💡 Tip: Run {C.RESET}{C.BOLD}{C.CYAN}/example{C.RESET}{C.DIM} for a step-by-step custom stat tutorial, or {C.RESET}{C.BOLD}{C.CYAN}/create{C.RESET}{C.DIM} to build your own.{C.RESET}\n")
    return "\n".join(lines)


# ==============================================================================
# IPC Error Reporting & Self-Healing Agent Signaling
# ==============================================================================

def get_ipc_dir() -> Path:
    """Returns the .error_ipc directory path, creating pending/resolved/history subfolders."""
    try:
        pkg_root = Path(__file__).resolve().parent.parent
        if (pkg_root / ".git").exists() or (pkg_root / "pyproject.toml").exists():
            ipc_path = pkg_root / ".error_ipc"
        else:
            ipc_path = Path.cwd() / ".error_ipc"
    except Exception:
        ipc_path = Path.cwd() / ".error_ipc"
    ipc_path.mkdir(parents=True, exist_ok=True)
    (ipc_path / "pending").mkdir(parents=True, exist_ok=True)
    (ipc_path / "resolved").mkdir(parents=True, exist_ok=True)
    (ipc_path / "history").mkdir(parents=True, exist_ok=True)
    return ipc_path


def create_error_report(
    query_raw: str,
    parsed_nl: Dict[str, Any],
    user_explanation: str = "",
    season: Optional[int] = None,
) -> Dict[str, Any]:
    """Serializes an error report for a natural-language query and writes it to .error_ipc/pending/."""
    ipc_dir = get_ipc_dir()
    now_dt = dt.datetime.now()
    report_id = f"err_{now_dt.strftime('%Y%m%d_%H%M%S')}"
    report_data = {
        "id": report_id,
        "timestamp": now_dt.isoformat(),
        "query": query_raw,
        "user_explanation": user_explanation or "Interpretation mismatch or unexpected query result.",
        "parsed": parsed_nl,
        "season": season or CURRENT_SEASON,
        "version": __version__,
        "status": "pending",
    }
    with open(ipc_dir / "pending" / f"{report_id}.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    with open(ipc_dir / "pending" / "latest.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    return report_data


def write_resolution(
    report_id: str,
    summary: str,
    commit: str = "",
    status: str = "resolved",
) -> Dict[str, Any]:
    """Writes a resolution signal file indicating an error report has been addressed."""
    ipc_dir = get_ipc_dir()
    res_data = {
        "id": report_id,
        "status": status,
        "commit": commit,
        "summary": summary,
        "timestamp": dt.datetime.now().isoformat(),
    }
    with open(ipc_dir / "resolved" / f"{report_id}.json", "w", encoding="utf-8") as f:
        json.dump(res_data, f, indent=2)
    with open(ipc_dir / "resolved" / "latest.json", "w", encoding="utf-8") as f:
        json.dump(res_data, f, indent=2)
    pending_file = ipc_dir / "pending" / f"{report_id}.json"
    if pending_file.exists():
        history_file = ipc_dir / "history" / f"{report_id}.json"
        try:
            shutil.move(str(pending_file), str(history_file))
        except Exception:
            pass
    pending_latest = ipc_dir / "pending" / "latest.json"
    if pending_latest.exists():
        try:
            with open(pending_latest, "r", encoding="utf-8") as f:
                p_data = json.load(f)
            if p_data.get("id") == report_id:
                pending_latest.unlink(missing_ok=True)
        except Exception:
            pass
    return res_data


def wait_for_resolution(
    report_id: str,
    poll_interval: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Polls .error_ipc/resolved/ until the resolution payload appears or the user interrupts."""
    ipc_dir = get_ipc_dir()
    target_res = ipc_dir / "resolved" / f"{report_id}.json"
    latest_res = ipc_dir / "resolved" / "latest.json"

    while True:
        for p in (target_res, latest_res):
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("id") == report_id and data.get("status") == "resolved":
                        return data
                except Exception:
                    pass
        time.sleep(poll_interval)


def render_slash_help() -> str:
    return f"""
{C.BOLD}{C.CYAN}┌───────────────────────────────────────────────────────────────────────────────────────┐
│                      NFL-STAT-CLI : NATURAL LANGUAGE & /COMMANDS                      │
├───────────────────────────────────────────────────────────────────────────────────────┤{C.RESET}
  {C.BOLD}{C.GOLD}Default Mode (Natural Language):{C.RESET}
    Type any question or stat request directly (no slash needed):
    • {C.DIM}"What is the average yards after catch on screen passes in 2025?"{C.RESET}
    • {C.DIM}"Show Patrick Mahomes touchdown play from behind the offense"{C.RESET}
    • {C.DIM}"Show Jared Goff screen play behind the defense"{C.RESET}
    • {C.DIM}"Create a stat called third_down_value with formula yards_per_play * 2 + epa_per_play * 15 where down == 3 by qb"{C.RESET}

  {C.BOLD}{C.GOLD}Slash Commands:{C.RESET}
    {C.BOLD}{C.CYAN}/help{C.RESET}                           Show this command & natural-language reference
    {C.BOLD}{C.CYAN}/team{C.RESET} [abbr/name]              Drill down into team offense, defense, and roster stats
    {C.BOLD}{C.CYAN}/coaches{C.RESET} [abbr/name]           View team coaching staff (HC, OC, DC, position coaches)
    {C.BOLD}{C.CYAN}/player{C.RESET} [name]                  Drill down into player passing, rushing, and receiving stats
    {C.BOLD}{C.CYAN}/stat{C.RESET} [stat_id]                 Evaluate any Traditional or Custom Stat leaderboard (Table only)
    {C.BOLD}{C.CYAN}/create{C.RESET}                         Launch the Composable Custom Stat Builder (Season / Game / Play scope)
    {C.BOLD}{C.CYAN}/delete{C.RESET} [stat_id]                Delete a user-created custom stat (or list custom stats to delete)
    {C.BOLD}{C.CYAN}/play{C.RESET} [phase/query]             Interactive play explorer (pass/run concepts, generic chalkboards & drilldowns)
    {C.BOLD}{C.CYAN}/games{C.RESET} [week/team]             Browse games by team/week, view quarter play tables & step plays
    {C.BOLD}{C.CYAN}/fantasy{C.RESET} [player/week]          Fantasy football center (PPR, Half-PPR, Standard, weekly logs & leaders)
    {C.BOLD}{C.CYAN}/sportsbook{C.RESET} [week/matchup]      Sportsbook handicapper (spreads, totals, moneylines, power ratings & ATS)
    {C.BOLD}{C.CYAN}/contract{C.RESET} [name/team]          NFL player & coach contracts (APY, guarantees, payrolls & cap hits)
    {C.BOLD}{C.CYAN}/camera{C.RESET} <offense|defense|side>  Set default camera angle for play diagrams
    {C.BOLD}{C.CYAN}/season{C.RESET} <year>                  Set active season year (default: current NFL season)
    {C.BOLD}{C.CYAN}/query{C.RESET}                          Run an ad-hoc season filter & group query
    {C.BOLD}{C.CYAN}/stats{C.RESET}                          List all registered traditional and custom stats & formulas
    {C.BOLD}{C.CYAN}/page{C.RESET}                           View Saved Stat Page (prior-season lookback & current-season tracking)
    {C.BOLD}{C.CYAN}/example{C.RESET}                        Guide on how to build custom stats (featuring MLB-style QB Wins)
    {C.BOLD}{C.CYAN}/export{C.RESET} [file.json]             Export custom stats to JSON
    {C.BOLD}{C.CYAN}/import{C.RESET} [file.json]             Import custom stats from JSON
    {C.BOLD}{C.CYAN}/why{C.RESET}                            Show the parsed JSON intent of the last natural-language query
    {C.BOLD}{C.CYAN}/error{C.RESET} [notes]                  Report parsing or interpretation error to Antigravity AI agent
    {C.BOLD}{C.CYAN}/reload{C.RESET} | {C.BOLD}{C.CYAN}/update{C.RESET}             Reload code in-place with latest patches from Antigravity
    {C.BOLD}{C.CYAN}/clear{C.RESET}                          Clear terminal screen
    {C.BOLD}{C.CYAN}/quit{C.RESET} | {C.BOLD}{C.CYAN}/close{C.RESET} | {C.BOLD}{C.CYAN}quit{C.RESET} | {C.BOLD}{C.CYAN}close{C.RESET}   Exit nfl-stat-cli
{C.BOLD}{C.CYAN}└───────────────────────────────────────────────────────────────────────────────────────┘{C.RESET}"""


def _split_cmd_args(raw_in: str) -> List[str]:
    try:
        return shlex.split(raw_in, posix=(os.name != "nt"))
    except ValueError:
        return raw_in.split()


class ConsoleSpinner:
    """
    Animated console spinner for long-running operations (fetching seasons, downcasting floats, etc.).
    Supports context manager (`with ConsoleSpinner(...): ...`) and manual start/update/stop.
    """
    SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    ASCII_FRAMES = ("|", "/", "-", "\\")

    def __init__(self, message: str = "Loading...", enabled: bool = True, speed: float = 0.08) -> None:
        self.message = message
        self.speed = speed
        self.enabled = bool(enabled and hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        try:
            enc = getattr(sys.stdout, "encoding", "") or "utf-8"
            "⠋".encode(enc)
            self.frames = self.SPINNER_FRAMES
        except (UnicodeEncodeError, LookupError, TypeError):
            self.frames = self.ASCII_FRAMES

    def start(self) -> "ConsoleSpinner":
        if not self.enabled:
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            frame = self.frames[idx % len(self.frames)]
            idx += 1
            sys.stdout.write(f"\r  {C.BOLD}{C.GOLD}{frame}{C.RESET} {self.message:<60}")
            sys.stdout.flush()
            time.sleep(self.speed)

    def update(self, new_message: str) -> None:
        self.message = new_message

    def stop(self, final_message: Optional[str] = None, clear: bool = True) -> None:
        if not self.enabled:
            if final_message:
                print(final_message)
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.4)
        if clear:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()
        if final_message:
            sys.stdout.write(f"\r  {final_message}\n")
            sys.stdout.flush()

    def __enter__(self) -> "ConsoleSpinner":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop(clear=True)


def show_startup_loading(is_interactive: bool = True, seasons: Optional[List[int]] = None) -> None:
    """
    Display a smooth loading progress bar with a cycling console spinner during interactive startup,
    displaying progress across initializing the engine, loading years, downcasting floats,
    and visualizers before clearing to the clean prompt.
    """
    if not is_interactive:
        return
    seasons_str = ", ".join(map(str, seasons)) if seasons else f"{CURRENT_SEASON - 1}, {CURRENT_SEASON}"
    steps = [
        ("Initializing stat calculation engine...", 20),
        (f"Loading NFL play-by-play data for years [{seasons_str}]...", 45),
        ("Downcasting floats & optimizing memory...", 70),
        ("Calibrating chalkboard & multi-angle visualizers...", 90),
        ("Ready! Launching NFL-STAT-CLI...", 100),
    ]
    bar_width = 30
    frames = ConsoleSpinner.SPINNER_FRAMES
    try:
        enc = getattr(sys.stdout, "encoding", "") or "utf-8"
        "⠋".encode(enc)
    except (UnicodeEncodeError, LookupError, TypeError):
        frames = ConsoleSpinner.ASCII_FRAMES

    frame_idx = 0
    for label, pct in steps:
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        frame = frames[frame_idx % len(frames)]
        frame_idx += 1
        sys.stdout.write(f"\r  {C.BOLD}{C.GOLD}{frame}{C.RESET} Loading... [{bar}] {pct:3d}% {C.DIM}{label:<52}{C.RESET}")
        sys.stdout.flush()
        time.sleep(0.06)
    time.sleep(0.08)
    os.system("cls" if os.name == "nt" else "clear")


def interactive_tui(
    engine: StatEngine,
    bridge: NFLDataBridge,
    slm_model: Optional[str] = None,
    initial_plays: Optional[List[Dict[str, Any]]] = None,
    default_season: int = CURRENT_SEASON,
    default_conf: Optional[str] = None,
    default_team: Optional[str] = None,
    default_camera: str = "behind-offense",
) -> None:
    """
    Natural-Language-first interactive interface with /command support and
    readline-safe prompt wrapping so multi-line inputs can backspace across line wraps.
    """
    is_interactive = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    active_season = default_season
    seasons_to_load = sorted({active_season - 1, active_season})
    show_startup_loading(is_interactive=is_interactive, seasons=seasons_to_load)
    print(AsciiArtRenderer.banner())
    if initial_plays is not None:
        plays = initial_plays
    else:
        seasons_label = ", ".join(map(str, seasons_to_load))
        with ConsoleSpinner(f"Loading years [{seasons_label}] & downcasting floats...", enabled=is_interactive) as sp:
            plays = bridge.load_pbp(seasons_to_load, spinner=sp)
    detected_slm = NaturalLanguageStatAssistant.detect_ollama_model(slm_model)
    slm_status = f"Ollama SLM ({detected_slm})" if detected_slm else "Built-in Deterministic AST Parser (Offline)"
    if not is_interactive:
        print(f"  {C.GREEN}✔ Loaded {len(plays)} play-by-play records via [{bridge.last_source_used}]{C.RESET}")
        if bridge.last_error and "offline" in bridge.last_source_used:
            print(f"  {C.YELLOW}⚠ Live backend note ({bridge.last_error[:95]}) — using built-in offline dataset.{C.RESET}")
        print(f"  {C.CYAN}✔ Natural Language Engine: [{slm_status}] • Season: [{active_season}] • Camera: [{default_camera}]{C.RESET}")
        if not plays_for_season(plays, active_season):
            avail = ", ".join(map(str, available_seasons(plays))) or "none"
            print(f"  {C.YELLOW}⚠ No {active_season} play-by-play data is loaded (available: {avail}). Use `/season YEAR` to switch seasons.{C.RESET}")
        print(f"  {C.DIM}Ask any NFL stat or play question in plain English, or type {C.RESET}{C.BOLD}{C.GOLD}/help{C.RESET}{C.DIM} for commands ({C.RESET}{C.BOLD}/quit{C.RESET}{C.DIM} or {C.RESET}{C.BOLD}close{C.RESET}{C.DIM} to exit).{C.RESET}")

    last_parsed_nl: Optional[Dict[str, Any]] = None
    last_query_raw: Optional[str] = None

    while True:
        try:
            raw_in = prompt_input(f"\n{C.BOLD}{C.GOLD}nfl-stat > {C.RESET}").lstrip("\ufeff").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting nfl-stat-cli.")
            break

        if not raw_in:
            continue

        low_in = raw_in.lower()
        if low_in in ("q", "quit", "/quit", "/q", "close", "/close", "exit", "/exit"):
            print("Exiting nfl-stat-cli.")
            break

        try:
            # Slash commands (/command)
            if raw_in.startswith("/"):
                parts = _split_cmd_args(raw_in)
                cmd_token = parts[0].lower()
                cmd_args = [a.strip("\"'") for a in parts[1:]]

                if cmd_token in ("/help", "/h", "/?", "/commands", "/menu"):
                    print(render_slash_help())
                elif cmd_token in ("/stats", "/list", "/list-stats", "/catalog"):
                    print(render_stats_catalog(engine))
                elif cmd_token in ("/stat", "/leaderboard"):
                    if cmd_args:
                        req_stat = cmd_args[0].lower()
                        if req_stat not in engine.stats:
                            matches = difflib.get_close_matches(req_stat, list(engine.stats.keys()), n=3, cutoff=0.5)
                            hint = f" Did you mean: {', '.join(matches)}?" if matches else " Type `/stats` to list all stat IDs."
                            print(f"  {C.RED}✖ Unknown stat `{req_stat}`.{hint}{C.RESET}")
                            continue
                        conf_arg = "AFC" if "afc" in [a.lower() for a in cmd_args] else ("NFC" if "nfc" in [a.lower() for a in cmd_args] else default_conf)
                        s_plays = require_season_plays(plays, active_season)
                        print(render_general_stat_view(engine, s_plays, req_stat, active_season, conf=conf_arg, team=default_team, view_mode="table"))
                    else:
                        stat_names = list(engine.stats.keys())
                        print(f"\n  {C.BOLD}{C.CYAN}Available Traditional & Custom Stats:{C.RESET}")
                        for i, sname in enumerate(stat_names, 1):
                            s = engine.stats[sname]
                            print(f"    [{i:2d}] {C.BOLD}{s.name:<28}{C.RESET} — {s.title} [{s.category.upper()} • by {s.group_by}]")
                        sel = prompt_input("  Pick stat number or name (default: 1): ").strip() or "1"
                        chosen_stat = stat_names[0]
                        if sel.isdigit() and 1 <= int(sel) <= len(stat_names):
                            chosen_stat = stat_names[int(sel) - 1]
                        elif sel in engine.stats:
                            chosen_stat = sel
                        else:
                            matches = difflib.get_close_matches(sel, stat_names, n=3, cutoff=0.5)
                            hint = f" Did you mean: {', '.join(matches)}?" if matches else ""
                            print(f"  {C.RED}✖ Unknown stat `{sel}`.{hint}{C.RESET}")
                            continue
                        season_str = prompt_input(f"  Season (default: {active_season}): ").strip() or str(active_season)
                        season_val = int(season_str) if season_str.isdigit() else active_season
                        conf_val = prompt_input("  Conference filter [AFC/NFC/all] (default: all): ").strip().upper()
                        conf_arg = conf_val if conf_val in ("AFC", "NFC") else None
                        group_val = prompt_input(f"  Group by override [qb/team/play_concept/conference/receiver/game] (Enter for default `{engine.stats[chosen_stat].group_by}`): ").strip() or None
                        s_plays = require_season_plays(plays, season_val)
                        if chosen_stat in ("qb_meaningful_win", "qb_meaningful_loss", "qb_impact_score") and not group_val:
                            print(render_qb_meaningful_wins_view(engine, s_plays, season_val, conf_arg, view_mode="table", team=default_team))
                        else:
                            print(render_general_stat_view(engine, s_plays, chosen_stat, season_val, conf=conf_arg, team=default_team, group_override=group_val, view_mode="table"))
                elif cmd_token in ("/create", "/create-stat", "/new", "/build"):
                    interactive_custom_stat_wizard(engine, plays, season=active_season)
                elif cmd_token in ("/delete", "/delete-stat", "/rm-stat", "/remove-stat"):
                    custom_stats = [v for v in engine.stats.values() if v.category == "custom"]
                    if not custom_stats:
                        print(f"  {C.YELLOW}⚠ No custom stats currently exist to delete.{C.RESET}")
                        print(f"  {C.DIM}All registered stats are built-in traditional stats (which cannot be deleted). Use `/create` to build custom stats.{C.RESET}")
                        continue

                    target_name = cmd_args[0].strip() if cmd_args else ""
                    if not target_name:
                        print(f"\n{C.BOLD}{C.RED}=== 🗑️  DELETE CUSTOM STAT ==={C.RESET}")
                        print(f"  Currently registered custom stats ({len(custom_stats)}):")
                        for idx, s in enumerate(custom_stats, 1):
                            deps_str = f" [Depends on: {', '.join(s.dependencies)}]" if s.dependencies else ""
                            print(f"    [{idx}] {C.BOLD}{C.GOLD}{s.name:<24}{C.RESET} ({s.title}){deps_str}")
                        try:
                            sel = prompt_input(f"\n  Select stat to delete [1-{len(custom_stats)}] or enter stat name (or 'c' to cancel): ").strip()
                        except (EOFError, KeyboardInterrupt):
                            continue
                        if not sel or sel.lower() in ("c", "cancel", "q", "quit"):
                            print(f"  {C.DIM}Deletion canceled.{C.RESET}")
                            continue
                        if sel.isdigit() and 1 <= int(sel) <= len(custom_stats):
                            target_name = custom_stats[int(sel) - 1].name
                        else:
                            target_name = sel

                    try:
                        deleted = engine.delete_custom_stat(target_name)
                        print(f"  {C.GREEN}✔ Successfully deleted custom stat `{deleted.name}` ({deleted.title}).{C.RESET}")
                    except (KeyError, ValueError) as err:
                        print(f"  {C.RED}✖ {err}{C.RESET}")
                elif cmd_token in ("/team", "/team-stats", "/team-drilldown"):
                    if cmd_args:
                        t_raw = cmd_args[0]
                        s_val = int(cmd_args[1]) if len(cmd_args) > 1 and cmd_args[1].isdigit() else active_season
                        res_t = resolve_team_abbr(t_raw) or t_raw.upper()
                        print(render_team_drilldown_view(engine, plays, season=s_val, team=res_t))
                    else:
                        def_t = default_team or "KC"
                        t_in = prompt_input(f"  Enter Team abbreviation or nickname (e.g. KC, BUF, Chiefs, Lions) (default: {def_t}): ").strip() or def_t
                        res_t = resolve_team_abbr(t_in) or t_in.upper()
                        print(render_team_drilldown_view(engine, plays, season=active_season, team=res_t))
                elif cmd_token in ("/coaches", "/coach", "/staff"):
                    if cmd_args:
                        t_in = cmd_args[0]
                    else:
                        def_t = default_team or "KC"
                        t_in = prompt_input(f"  Enter Team abbreviation or nickname (e.g. KC, BUF, Chiefs, Lions) (default: {def_t}): ").strip() or def_t
                    res_t = resolve_team_abbr(t_in) or t_in.upper()
                    print(render_coaching_staff_view(res_t))
                elif cmd_token in ("/player", "/player-stats", "/player-drilldown"):
                    if cmd_args:
                        p_arg = " ".join(cmd_args)
                        print(render_player_drilldown_view(engine, plays, season=active_season, player_name=p_arg, interactive=True))
                    else:
                        p_in = prompt_input("  Enter Player name (e.g. Mahomes, Allen, Goff, Worthy) (default: Mahomes): ").strip() or "Mahomes"
                        print(render_player_drilldown_view(engine, plays, season=active_season, player_name=p_in, interactive=True))
                elif cmd_token in ("/play", "/diagram", "/field"):
                    if cmd_args:
                        nl_play_q = "show play " + " ".join(cmd_args)
                        parsed = NaturalLanguageStatAssistant.interpret_query(
                            nl_play_q, engine=engine, slm_model=slm_model, pre_detected_model=detected_slm, default_season=active_season
                        )
                        parsed["intent"] = "specific_play"
                        parsed["show_field"] = True
                        if not any(k in nl_play_q.lower() for k in ("behind", "offense", "defense", "sideline")):
                            parsed["camera"] = default_camera
                        last_parsed_nl = parsed
                        last_query_raw = nl_play_q
                        print(handle_nl_query_result(parsed, engine, plays, interactive=is_interactive))
                    else:
                        interactive_play_explorer(engine, bridge, plays, active_season=active_season, default_camera=default_camera)
                elif cmd_token in ("/games", "/game", "/matchup", "/matchups", "/boxscore", "/pbp"):
                    init_team = None
                    init_week = None
                    if cmd_args:
                        if cmd_args[0].isdigit():
                            init_week = int(cmd_args[0])
                        else:
                            init_team = resolve_team_abbr(cmd_args[0]) or cmd_args[0].upper()
                    interactive_game_browser(
                        engine,
                        bridge,
                        plays,
                        active_season=active_season,
                        default_camera=default_camera,
                        initial_team=init_team,
                        initial_week=init_week,
                    )
                elif cmd_token in ("/fantasy", "/fant", "/fp"):
                    if cmd_args:
                        arg_str = " ".join(cmd_args).strip()
                        pos_match = arg_str.upper() if arg_str.upper() in ("QB", "RB", "WR", "TE", "K") else None
                        if pos_match:
                            s_plays = require_season_plays(plays, active_season)
                            print(render_fantasy_leaderboard_view(s_plays, season=active_season, position=pos_match))
                        elif any(fmt in arg_str.lower() for fmt in ("std", "standard", "half", "ppr")):
                            fmt = "standard" if "std" in arg_str.lower() else ("half_ppr" if "half" in arg_str.lower() else "ppr")
                            s_plays = require_season_plays(plays, active_season)
                            print(render_fantasy_leaderboard_view(s_plays, season=active_season, scoring_format=fmt))
                        else:
                            s_plays = require_season_plays(plays, active_season)
                            print(render_player_fantasy_profile_view(arg_str, s_plays, season=active_season))
                    else:
                        interactive_fantasy_browser(plays, active_season=active_season)
                elif cmd_token in ("/sportsbook", "/odds", "/handicap", "/lines", "/betting"):
                    if cmd_args:
                        arg_str = " ".join(cmd_args).strip()
                        s_plays = require_season_plays(plays, active_season)
                        if any(w in arg_str.lower() for w in ("power", "ratings", "rankings")):
                            print(render_power_ratings_view(s_plays, season=active_season))
                        elif arg_str.isdigit():
                            print(render_sportsbook_board_view(s_plays, season=active_season, week_filter=int(arg_str)))
                        else:
                            match_m = re.search(r"([a-zA-Z]+)\s+(?:vs\.?|at|@)\s+([a-zA-Z]+)", arg_str)
                            if match_m:
                                t1 = resolve_team_abbr(match_m.group(1)) or match_m.group(1).upper()
                                t2 = resolve_team_abbr(match_m.group(2)) or match_m.group(2).upper()
                                home_t, away_t = (t2, t1) if " at " in arg_str or " @ " in arg_str else (t1, t2)
                                print(render_game_handicap_dossier_view(home_t, away_t, s_plays, season=active_season))
                            else:
                                print(render_sportsbook_board_view(s_plays, season=active_season))
                    else:
                        interactive_sportsbook_browser(plays, active_season=active_season)
                elif cmd_token in ("/contract", "/contracts", "/contrat", "/payroll", "/salary", "/salaries"):
                    if cmd_args:
                        arg_str = " ".join(cmd_args).strip()
                        pos_match = arg_str.upper() if arg_str.upper() in ("QB", "RB", "WR", "TE", "OT", "EDGE", "CB", "DT", "S", "K") else None
                        t_match = resolve_team_abbr(arg_str)
                        if any(w in arg_str.lower() for w in ("coach", "coaches", "staff", "hc")):
                            print(render_contracts_leaderboard_view(contract_type="coach"))
                        elif pos_match:
                            print(render_contracts_leaderboard_view(contract_type="player", position_filter=pos_match))
                        elif t_match:
                            print(render_team_payroll_view(t_match))
                        else:
                            s_plays = require_season_plays(plays, active_season)
                            print(render_player_contract_view(arg_str, plays=s_plays, season=active_season))
                    else:
                        interactive_contracts_browser(plays=plays, active_season=active_season)
                elif cmd_token in ("/camera", "/perspective"):
                    if cmd_args:
                        cam_in = cmd_args[0].lower()
                        if cam_in in ("offense", "behind-offense", "behind_offense"):
                            default_camera = "behind-offense"
                            print(f"  {C.GREEN}✔ Default play camera set to: {default_camera}{C.RESET}")
                        elif cam_in in ("defense", "behind-defense", "behind_defense"):
                            default_camera = "behind-defense"
                            print(f"  {C.GREEN}✔ Default play camera set to: {default_camera}{C.RESET}")
                        elif cam_in in ("side", "sideline", "broadcast"):
                            default_camera = "sideline"
                            print(f"  {C.GREEN}✔ Default play camera set to: {default_camera}{C.RESET}")
                        elif cam_in == "all":
                            default_camera = "all"
                            print(f"  {C.GREEN}✔ Default play camera set to: {default_camera}{C.RESET}")
                        else:
                            print(f"  {C.RED}✖ Invalid camera `{cam_in}`. Valid options: behind-offense, behind-defense, sideline, all{C.RESET}")
                    else:
                        print(f"  Current play camera: {C.BOLD}{default_camera}{C.RESET} (Usage: `/camera behind-offense`, `/camera behind-defense`, or `/camera sideline`)")
                elif cmd_token == "/season":
                    if cmd_args and cmd_args[0].isdigit():
                        active_season = int(cmd_args[0])
                        if not plays_for_season(plays, active_season):
                            with ConsoleSpinner(f"Loading year {active_season} & downcasting floats...", enabled=is_interactive) as sp:
                                more = bridge.load_pbp([active_season], spinner=sp)
                            if more:
                                plays.extend(more)
                        print(f"  {C.GREEN}✔ Active season set to: {active_season}{C.RESET}")
                        if not plays_for_season(plays, active_season):
                            avail = ", ".join(map(str, available_seasons(plays))) or "none"
                            print(f"  {C.YELLOW}⚠ No {active_season} play-by-play data available (loaded: {avail}).{C.RESET}")
                    else:
                        print(f"  Current active season: {C.BOLD}{active_season}{C.RESET} (Usage: `/season YEAR`, e.g. `/season {CURRENT_SEASON}`)")
                elif cmd_token == "/why":
                    if last_parsed_nl:
                        print(f"\n{C.BOLD}{C.CYAN}🔍 Last Natural Language Query Parsed Intent:{C.RESET}")
                        print(json.dumps(last_parsed_nl, indent=2))
                    else:
                        print(f"  {C.DIM}No natural-language query has been run in this session yet.{C.RESET}")
                elif cmd_token in ("/error", "/bug", "/report"):
                    if not last_parsed_nl or not last_query_raw:
                        print(f"  {C.YELLOW}⚠ No natural-language query has been run in this session yet.{C.RESET}")
                        print(f"  {C.DIM}Run a query first (e.g. 'which coach has called the most timeouts in the 4th qrt'), then type `/error`.{C.RESET}")
                        continue

                    user_notes = " ".join(cmd_args).strip()
                    if not user_notes:
                        print(f"\n{C.BOLD}{C.RED}=== 🚨 NATURAL LANGUAGE QUERY ERROR REPORT ==={C.RESET}")
                        print(f"  {C.BOLD}Failed Query:{C.RESET} \"{last_query_raw}\"")
                        print(f"  {C.BOLD}Current Interpretation:{C.RESET} `{last_parsed_nl.get('stat_name')}` (group: `{last_parsed_nl.get('group_by')}`, filter: `{last_parsed_nl.get('filter_expr') or 'none'}`)")
                        try:
                            user_notes = prompt_input(f"\n  {C.BOLD}{C.GOLD}What was incorrect or what did you expect?{C.RESET} ").strip()
                        except (EOFError, KeyboardInterrupt):
                            print(f"\n  {C.DIM}Error report cancelled.{C.RESET}")
                            continue

                    rep = create_error_report(
                        query_raw=last_query_raw,
                        parsed_nl=last_parsed_nl,
                        user_explanation=user_notes,
                        season=active_season,
                    )
                    rep_id = rep["id"]
                    print(f"\n  {C.GREEN}✔ Error report `{rep_id}` created & sent to Antigravity IPC!{C.RESET}")
                    print(f"  {C.DIM}Saved to: {get_ipc_dir() / 'pending' / 'latest.json'}{C.RESET}")
                    print(f"  {C.CYAN}💡 Antigravity agent will inspect the AST parser, patch the code, run tests, and push the commit.{C.RESET}")

                    try:
                        wait_choice = prompt_input(f"\n  {C.BOLD}Wait for Antigravity AI fix and auto-reload now? [Y/n]: {C.RESET}").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        wait_choice = "n"

                    if wait_choice in ("", "y", "yes"):
                        print(f"\n  {C.GOLD}⏳ Waiting for Antigravity signal... (Press Ctrl+C to stop waiting and return to prompt){C.RESET}")
                        try:
                            res = wait_for_resolution(rep_id)
                        except KeyboardInterrupt:
                            print(f"\n  {C.YELLOW}Stopped waiting. Report `{rep_id}` remains pending.{C.RESET}")
                            print(f"  {C.DIM}Once the fix is committed, type `/reload` to apply the update.{C.RESET}")
                            continue

                        if res:
                            print(f"\n  {C.GREEN}{C.BOLD}🎉 Issue has been solved by Antigravity!{C.RESET}")
                            if res.get("commit"):
                                print(f"  {C.BOLD}Commit:{C.RESET} {res.get('commit')}")
                            if res.get("summary"):
                                print(f"  {C.BOLD}Fix Details:{C.RESET} {res.get('summary')}")
                            print(f"  {C.CYAN}🔄 Reloading programming and re-evaluating query...{C.RESET}\n")
                            try:
                                import importlib
                                import nfl_stat_cli as _cur_mod
                                importlib.reload(_cur_mod)
                                engine = _cur_mod.StatEngine()
                                re_parsed = _cur_mod.NaturalLanguageStatAssistant.interpret_query(
                                    last_query_raw, engine=engine, slm_model=slm_model, pre_detected_model=detected_slm, default_season=active_season
                                )
                                last_parsed_nl = re_parsed
                                print(_cur_mod.handle_nl_query_result(re_parsed, engine, plays, interactive=is_interactive))
                            except Exception as re_err:
                                print(f"  {C.RED}✖ Error during hot-reload re-evaluation: {re_err}{C.RESET}")
                    else:
                        print(f"  {C.DIM}Report saved. Type `/reload` or `/update` once the fix is deployed to update your programming.{C.RESET}")
                elif cmd_token in ("/reload", "/update", "/refresh"):
                    print(f"  {C.CYAN}🔄 Reloading nfl-stat-cli modules and custom stats in-place...{C.RESET}")
                    try:
                        import importlib
                        import nfl_stat_cli as _cur_mod
                        importlib.reload(_cur_mod)
                        engine = _cur_mod.StatEngine()
                        ipc_dir = get_ipc_dir()
                        latest_res_p = ipc_dir / "resolved" / "latest.json"
                        res_info = ""
                        if latest_res_p.exists():
                            try:
                                with open(latest_res_p, "r", encoding="utf-8") as f:
                                    r_data = json.load(f)
                                if r_data.get("summary"):
                                    res_info = f" (Latest resolution: {r_data.get('summary')})"
                            except Exception:
                                pass
                        print(f"  {C.GREEN}✔ Programming successfully reloaded!{res_info}{C.RESET}")
                    except Exception as r_err:
                        print(f"  {C.RED}✖ Reload failed: {r_err}{C.RESET}")
                elif cmd_token in ("/query", "/filter"):
                    print(f"\n{C.BOLD}{C.CYAN}=== 🔎 AD-HOC SEASON FILTER & GROUP QUERY ==={C.RESET}")
                    stat_q = prompt_input("  Metric to evaluate (e.g. yards_per_play, epa_per_play, screen_yards_after_catch, passer_rating): ").strip() or "yards_per_play"
                    if stat_q not in engine.stats:
                        print(f"  {C.RED}✖ Unknown stat `{stat_q}`.{C.RESET}")
                        continue
                    grp_q = prompt_input("  Group by [qb / team / play_concept / conference / division / down / qtr / game] (default: play_concept): ").strip() or "play_concept"
                    flt_q = prompt_input("  Filter expression (e.g. `conf == 'AFC'`, `is_screen == 1`, `down == 3`, or Enter for none): ").strip()
                    s_plays = require_season_plays(plays, active_season)
                    print(render_general_stat_view(engine, s_plays, stat_q, active_season, group_override=grp_q, extra_filter=flt_q, view_mode="table"))
                elif cmd_token in ("/page", "/stat-page"):
                    print(render_stat_page(engine, plays))
                elif cmd_token in ("/example", "/examples", "/ex", "/qb-wins"):
                    print(render_custom_stat_example_walkthrough(engine, plays, active_season, default_conf, default_team))
                elif cmd_token == "/screen-pass":
                    s_plays = require_season_plays(plays, active_season)
                    print(render_screen_pass_view(engine, s_plays, active_season, default_conf, view_mode="table", team=default_team))
                elif cmd_token == "/play-efficiency":
                    conf_arg = cmd_args[0].upper() if (cmd_args and cmd_args[0].upper() in ("AFC", "NFC")) else (default_conf or "AFC")
                    s_plays = require_season_plays(plays, active_season)
                    print(render_play_efficiency_view(engine, s_plays, active_season, conf_arg, view_mode="table", team=default_team))
                elif cmd_token == "/export":
                    path_str = cmd_args[0] if cmd_args else (prompt_input("  Export filename (default: custom_stats_export.json): ").strip() or "custom_stats_export.json")
                    out_p = engine.export_custom_stats_json(Path(path_str))
                    print(f"  {C.GREEN}✔ Exported custom stats to {out_p.resolve()}{C.RESET}")
                elif cmd_token == "/import":
                    path_str = cmd_args[0] if cmd_args else prompt_input("  Path to JSON file to import: ").strip()
                    if path_str and Path(path_str).exists():
                        names = engine.import_custom_stats_json(Path(path_str))
                        print(f"  {C.GREEN}✔ Imported {len(names)} custom stats: {', '.join(names)}{C.RESET}")
                    else:
                        print(f"  {C.RED}✖ File not found: {path_str}{C.RESET}")
                elif cmd_token in ("/clear", "/cls"):
                    os.system("cls" if os.name == "nt" else "clear")
                    print(AsciiArtRenderer.banner())
                else:
                    print(f"  {C.YELLOW}Unknown command `{cmd_token}`. Type `/help` to see all available slash commands.{C.RESET}")
                continue

            # Default: Natural Language Query
            parsed = NaturalLanguageStatAssistant.interpret_query(
                raw_in, engine=engine, slm_model=slm_model, pre_detected_model=detected_slm, default_season=active_season
            )
            if parsed.get("intent") == "specific_play" and not any(k in low_in for k in ("behind", "offense", "defense", "sideline")):
                parsed["camera"] = default_camera
            last_parsed_nl = parsed
            last_query_raw = raw_in
            print(handle_nl_query_result(parsed, engine, plays, interactive=is_interactive))
        except KeyboardInterrupt:
            print(f"\n  {C.YELLOW}⚠ Operation cancelled.{C.RESET}")
        except Exception as exc:
            print(f"  {C.RED}✖ Error: {exc}{C.RESET}")


def build_arg_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--engine", choices=["auto", "python", "r", "offline"], default=argparse.SUPPRESS, help="Data backend preference")
    common.add_argument("--season", type=int, default=argparse.SUPPRESS, help=f"Season year to analyze (default: current NFL season, {CURRENT_SEASON})")
    common.add_argument("--conf", type=str.upper, choices=["AFC", "NFC"], default=argparse.SUPPRESS, help="Filter by conference (AFC or NFC)")
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
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(
        engine="auto",
        season=CURRENT_SEASON,
        conf=None,
        team=None,
        view="auto",
        camera=None,
        slm_model=None,
        no_color=False,
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", parents=[common], help="Launch interactive colorized terminal interface (default)")

    stat_p = sub.add_parser("stat", parents=[common], help="Evaluate any traditional or custom stat leaderboard / season average (table view by default)")
    stat_p.add_argument("stat_name", nargs="?", default="yards_per_play", help="Stat ID to evaluate (e.g. qb_impact_score, yards_per_play, screen_yards_after_catch)")
    stat_p.add_argument("--group-by", choices=list(GROUP_BY_COLUMN_MAP.keys()), default=None, help="Override grouping dimension")
    stat_p.add_argument("--filter", default="", help="Additional play filter expression (e.g. 'down == 3' or 'is_screen == 1')")
    stat_p.add_argument("--limit", type=int, default=None, help="Limit number of leaderboard rows to show (e.g. --limit 5)")
    stat_p.add_argument("--position", "--pos", default=None, help="Filter leaderboard to a specific player position (e.g. QB, RB, WR, TE, K, P)")

    play_p = sub.add_parser("play", parents=[common], help="Find and diagram a specific play on the ASCII gridiron (supports behind-offense, behind-defense, sideline)")
    play_p.add_argument("--play-id", type=int, default=None, help="Specific play_id to render")
    play_p.add_argument("--game-id", default=None, help="Specific game_id to pair with --play-id (e.g. 2025_01_KC_BAL)")
    play_p.add_argument("--player", "--qb", dest="player", default=None, help="Filter by player name across all positions (e.g. Mahomes, Worthy, Gibbs, Parsons)")
    play_p.add_argument("--concept", default=None, help="Filter by play concept (e.g. screen, play_action_deep, rush_outside)")
    play_p.add_argument("--play-type", choices=["pass", "run"], default=None, help="Filter by pass or run")
    play_p.add_argument("--filter", default="", help="Custom play filter expression (e.g. 'touchdown == 1')")
    play_p.add_argument("--sort-by", choices=["yards_gained", "epa", "wpa", "yac", "air_yards"], default="yards_gained", help="Criterion to pick top matching play")
    play_p.add_argument("--perspective", choices=["behind-offense", "behind-defense", "sideline", "offense", "defense", "side", "all"], default=None, help="Camera angle override")

    team_p = sub.add_parser("team", parents=[common], help="Drill down into team offense, defense, and roster stats")
    team_p.add_argument("team_name", nargs="?", default="KC", help="Team abbreviation or nickname (e.g. KC, BUF, Chiefs, Lions)")

    coaches_p = sub.add_parser("coaches", parents=[common], help="View team coaching staff (HC, OC, DC, position coaches)")
    coaches_p.add_argument("team_name", nargs="?", default="KC", help="Team abbreviation or nickname (e.g. KC, BUF, Chiefs, Lions)")
    coaches_p.add_argument("--role", choices=["hc", "oc", "dc", "qb", "ol", "wr", "rb", "dl", "lb"], default=None, help="Filter to specific coaching role")

    player_p = sub.add_parser("player", parents=[common], help="Drill down into player passing, rushing, and receiving stats")
    player_p.add_argument("player_name", nargs="?", default="Mahomes", help="Player name (e.g. Mahomes, Allen, Goff, Worthy)")

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

    del_p = sub.add_parser("delete-stat", parents=[common], help="Delete a user-created custom statistic")
    del_p.add_argument("name", help="Name or title of custom stat to delete")

    sub.add_parser("stat-page", parents=[common], help="Display saved Stat Page with historical lookback and forward tracking")

    exp_p = sub.add_parser("export-stats", parents=[common], help="Export custom stats (with descriptions & formulas) to JSON")
    exp_p.add_argument("--output", required=True, help="Target JSON file path")
    exp_p.add_argument("--include-traditional", action="store_true", help="Include built-in traditional stats in JSON")

    imp_p = sub.add_parser("import-stats", parents=[common], help="Import custom stats from a JSON file")
    imp_p.add_argument("--input", required=True, help="Source JSON file path")

    ask_p = sub.add_parser("ask", parents=[common], help="Ask a natural-language NFL stat or play question (Local SLM + deterministic parser)")
    ask_p.add_argument("query", help="Natural language question")

    games_p = sub.add_parser("games", parents=[common], help="Browse NFL games by week or team, view quarter play logs, and step through plays")
    games_p.add_argument("--game-id", help="Direct game ID (e.g. 2025_01_BAL_KC or 2025_01_LA_DET)")
    games_p.add_argument("--week", type=int, help="Filter or jump to week (e.g. 1)")
    games_p.add_argument("--qtr", type=int, help="Filter or jump to quarter (1-4 or 5 for OT)")
    games_p.add_argument("--play-id", type=int, help="Jump directly to play ID")

    sub.add_parser("example", parents=[common], help="Walkthrough on how to build a custom stat (featuring QB Meaningful Wins)")

    # Backwards-compatible aliases for example workflows
    sub.add_parser("qb-wins", parents=[common], help="Run MLB-style QB Meaningful Wins (MW), Losses (ML) & 0-100 Impact Score report")
    sub.add_parser("screen-pass", parents=[common], help="Analyze screen pass effectiveness in yards gained, YAC, xYAC, and EPA")
    eff_p = sub.add_parser("play-efficiency", parents=[common], help="Rank most efficient offensive play concepts by yards gained")
    eff_p.add_argument("--conference", type=str.upper, choices=["AFC", "NFC"], default="AFC", help="Conference to rank (default: AFC)")
    sub.add_parser("demo-all", parents=[common], help="Run full showcase of custom stat engine, multi-angle play diagrams, and Stat Page")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.no_color:
        C.disable()

    bridge = NFLDataBridge(engine=args.engine)
    engine = StatEngine()
    resolved_camera = args.camera or "behind-offense"
    cmd = args.command or "tui"

    try:
        if cmd == "tui":
            interactive_tui(
                engine,
                bridge,
                slm_model=args.slm_model,
                default_season=args.season,
                default_conf=args.conf,
                default_team=args.team,
                default_camera=resolved_camera,
            )
            return 0

        # Fast path for metadata / file commands that do not require downloading play-by-play data
        if cmd == "list-stats":
            print(AsciiArtRenderer.banner())
            print(render_stats_catalog(engine))
            return 0
        if cmd == "export-stats":
            print(AsciiArtRenderer.banner())
            out_path = engine.export_custom_stats_json(Path(args.output), include_traditional=args.include_traditional)
            print(f"\n{C.GREEN}✔ Exported custom stats JSON to: {out_path}{C.RESET}")
            return 0
        if cmd == "import-stats":
            print(AsciiArtRenderer.banner())
            names = engine.import_custom_stats_json(Path(args.input))
            print(f"\n{C.GREEN}✔ Imported {len(names)} custom stats: {', '.join(names)}{C.RESET}")
            return 0
        if cmd == "delete-stat":
            print(AsciiArtRenderer.banner())
            deleted = engine.delete_custom_stat(args.name)
            print(f"\n{C.GREEN}✔ Successfully deleted custom stat `{deleted.name}` ({deleted.title}).{C.RESET}")
            return 0
        if cmd == "coaches":
            print(AsciiArtRenderer.banner())
            resolved_t = resolve_team_abbr(args.team_name) or args.team_name or "KC"
            print(render_coaching_staff_view(resolved_t, role_filter=args.role))
            return 0

        if cmd == "ask":
            parsed = NaturalLanguageStatAssistant.interpret_query(args.query, engine=engine, slm_model=args.slm_model, default_season=args.season)
            if parsed.get("intent") == "ambiguous":
                print(AsciiArtRenderer.banner())
                print(handle_nl_query_result(parsed, engine, []))
                return 0
            target_season = int(parsed.get("season") or args.season)
            all_plays = bridge.load_pbp(sorted({target_season - 1, target_season}))
            print(AsciiArtRenderer.banner())
            print(f"  {C.DIM}Data Source: {bridge.last_source_used}  |  Platform: {platform.system()} ({os.name}){C.RESET}")
            print(handle_nl_query_result(parsed, engine, all_plays, view_override=args.view, camera_override=args.camera))
            return 0

        # Load the requested season plus the prior season (Stat Page lookback); no cross-season fallback
        all_plays = bridge.load_pbp(sorted({args.season - 1, args.season}))

        print(AsciiArtRenderer.banner())
        print(f"  {C.DIM}Data Source: {bridge.last_source_used}  |  Platform: {platform.system()} ({os.name}){C.RESET}")
        season_plays = require_season_plays(all_plays, args.season) if cmd != "stat-page" else plays_for_season(all_plays, args.season)

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
                camera=resolved_camera,
                limit=getattr(args, "limit", None),
                position=getattr(args, "position", None),
            ))
        elif cmd == "team":
            resolved_t = resolve_team_abbr(args.team_name) or args.team_name or "KC"
            print(render_team_drilldown_view(engine, season_plays, season=args.season, team=resolved_t))
        elif cmd == "player":
            print(render_player_drilldown_view(engine, season_plays, season=args.season, player_name=args.player_name, team=args.team, interactive=False))
        elif cmd == "play":
            cam = getattr(args, "perspective", None) or resolved_camera
            target_p = getattr(args, "player", None) or getattr(args, "qb", None)
            print(render_specific_play_view(
                engine,
                season_plays,
                season=args.season,
                conf=args.conf,
                team=args.team,
                player=target_p,
                qb=target_p,
                concept=args.concept,
                play_type=args.play_type,
                filter_expr=args.filter,
                sort_by=args.sort_by,
                play_id=args.play_id,
                game_id=getattr(args, "game_id", None),
                camera=cam,
            ))
        elif cmd == "games":
            interactive_game_browser(
                engine,
                bridge,
                all_plays,
                active_season=args.season,
                default_camera=resolved_camera,
                initial_game_id=args.game_id,
                initial_play_id=args.play_id,
                initial_team=args.team,
                initial_week=args.week,
                initial_qtr=args.qtr,
            )
        elif cmd in ("example", "qb-wins"):
            print(render_custom_stat_example_walkthrough(engine, season_plays, args.season, conf=args.conf, team=args.team))
        elif cmd == "screen-pass":
            print(render_screen_pass_view(engine, season_plays, args.season, args.conf, args.view, camera=resolved_camera, team=args.team))
        elif cmd == "play-efficiency":
            conf = args.conf or getattr(args, "conference", "AFC")
            print(render_play_efficiency_view(engine, season_plays, args.season, conf, args.view, camera=resolved_camera, team=args.team))
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
            print(render_general_stat_view(engine, season_plays, sdef.name, args.season, conf=args.conf, team=args.team, view_mode=args.view, camera=resolved_camera))
        elif cmd == "stat-page":
            print(render_stat_page(engine, all_plays))
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
    except (KeyError, ValueError, SyntaxError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"\n{C.RED}✖ Error: {exc}{C.RESET}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
