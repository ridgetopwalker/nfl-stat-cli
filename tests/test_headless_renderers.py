"""Spike for the web terminal (pfs-engine text views): the text renderers run headless.

The web wrapper calls the library's ``render_*`` functions directly, with no terminal attached. These tests
pin down that, with ``interactive=False`` and the same ``C.snapshot()/C.disable()/C.restore()`` pair that
``main()`` uses, each renderer:

  * never prompts (``prompt_input``, ``builtins.input`` and ``sys.stdin`` all raise if touched, even when
    stdin claims to be a TTY),
  * prints nothing to stdout/stderr, opens no file, starts no process and does not exit,
  * returns a ``str`` with no ANSI escape sequences while colour is disabled,
  * leaves the class-level colour state exactly as it found it.

Hermetic: built-in sample data (offline bridge) plus two synthetic plays for an ambiguous surname.
"""
import builtins
import io
import os
import subprocess
import sys

import pytest

import pro_football_slm as cli

SEASON = 2025
ANSI = "\x1b["

# Two players sharing a surname (the built-in sample has no such pair), shaped like sample rows.
AMBIGUOUS_ROWS = [
    {"play_id": 9001, "season": SEASON, "week": 1, "game_id": "2025_01_SF_NYJ", "posteam": "SF", "defteam": "NYJ",
     "rusher_player_name": "C.McCaffrey", "play_type": "run", "rush_attempt": 1, "yards_gained": 4.0,
     "qtr": 1, "down": 1, "ydstogo": 10, "desc": "C.McCaffrey 4 yd run"},
    {"play_id": 9002, "season": SEASON, "week": 1, "game_id": "2025_01_WAS_SF", "posteam": "WAS", "defteam": "SF",
     "receiver_player_name": "L.McCaffrey", "play_type": "pass", "pass_attempt": 1, "complete_pass": 1,
     "yards_gained": 9.0, "qtr": 2, "down": 2, "ydstogo": 6, "desc": "5-J.Daniels pass to 11-L.McCaffrey"},
]


class _NoStdin(io.TextIOBase):
    """A stdin that claims to be a terminal but fails the test if anything reads from it."""

    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty

    def readable(self):
        return True

    def read(self, *_a, **_k):
        raise AssertionError("renderer read sys.stdin")

    def readline(self, *_a, **_k):
        raise AssertionError("renderer read sys.stdin")


def _forbid(what):
    def _raise(*_a, **_k):
        raise AssertionError(f"renderer called {what}")
    return _raise


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


@pytest.fixture
def plays(tmp_path):
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline")
    rows = bridge.load_pbp([SEASON - 1, SEASON])
    assert bridge.is_sample and rows
    return rows + [bridge._normalize_row(r, i) for i, r in enumerate(AMBIGUOUS_ROWS, 9001)]


@pytest.fixture(params=[True, False], ids=["stdin-tty", "stdin-pipe"])
def headless(request, monkeypatch):
    """Forbid every prompt/exit/file/process path; run the call with colour disabled like main() does."""
    monkeypatch.setattr(cli, "prompt_input", _forbid("prompt_input"))
    monkeypatch.setattr(builtins, "input", _forbid("input"))
    monkeypatch.setattr(sys, "stdin", _NoStdin(request.param))
    monkeypatch.setattr(sys, "exit", _forbid("sys.exit"))
    monkeypatch.setattr(os, "system", _forbid("os.system"))
    monkeypatch.setattr(subprocess, "Popen", _forbid("subprocess.Popen"))

    def run(fn, *args, **kwargs):
        before = cli.C.snapshot()
        saved = cli.C.snapshot()
        cli.C.disable()
        monkeypatch.setattr(builtins, "open", _forbid("open"))
        monkeypatch.setattr(io, "open", _forbid("io.open"))
        try:
            out = fn(*args, **kwargs)
        finally:
            monkeypatch.setattr(builtins, "open", _REAL_OPEN)
            monkeypatch.setattr(io, "open", _REAL_IO_OPEN)
            cli.C.restore(saved)
        assert cli.C.snapshot() == before
        assert isinstance(out, str)
        assert ANSI not in out and "\x1b" not in out
        return out

    return run


_REAL_OPEN = builtins.open
_REAL_IO_OPEN = io.open


def _quiet(capsys):
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# --- player drilldown --------------------------------------------------------------------------------------

def test_player_ambiguous_returns_candidates_not_prompt(headless, engine, plays, capsys):
    out = headless(cli.render_player_drilldown_view, engine, plays, SEASON, "McCaffrey", interactive=False)
    _quiet(capsys)
    assert "I can't answer that" in out and "matches several players" in out
    assert "Christian McCaffrey" in out and "Luke McCaffrey" in out


def test_player_unique_returns_drilldown(headless, engine, plays, capsys):
    out = headless(cli.render_player_drilldown_view, engine, plays, SEASON, "Patrick Mahomes", interactive=False)
    _quiet(capsys)
    assert "Mahomes" in out and "I can't answer that" not in out
    assert "═" in out or "─" in out  # a bordered section really rendered


def test_player_unknown_returns_message(headless, engine, plays, capsys):
    out = headless(cli.render_player_drilldown_view, engine, plays, SEASON, "Zzyzx Nobody", interactive=False)
    _quiet(capsys)
    assert "no player matching 'Zzyzx Nobody'" in out


# --- team drilldown ----------------------------------------------------------------------------------------

def test_team_abbreviation_returns_drilldown(headless, engine, plays, capsys):
    out = headless(cli.render_team_drilldown_view, engine, plays, SEASON, "KC", interactive=False)
    _quiet(capsys)
    assert "TEAM DRILL-DOWN : KANSAS CITY CHIEFS" in out


def test_team_ambiguous_region_returns_message(headless, engine, plays, capsys):
    out = headless(cli.render_team_drilldown_view, engine, plays, SEASON, "New York", interactive=False)
    _quiet(capsys)
    assert "matches several teams" in out and "NYG" in out and "NYJ" in out


def test_team_unknown_returns_message(headless, engine, plays, capsys):
    out = headless(cli.render_team_drilldown_view, engine, plays, SEASON, "ZZZ", interactive=False)
    _quiet(capsys)
    assert "No play data found for team `ZZZ`" in out


def test_team_default_is_already_non_interactive(headless, engine, plays, capsys):
    out = headless(cli.render_team_drilldown_view, engine, plays, SEASON, "New York")
    _quiet(capsys)
    assert "matches several teams" in out


# --- other text views the web wraps later ------------------------------------------------------------------

@pytest.mark.parametrize("team,role,season,expect", [
    ("KC", None, SEASON, "COACHING STAFF"),
    ("KC", "hc", SEASON, "Head Coach"),
    ("ZZZ", None, SEASON, "No coaching staff is cataloged"),
    ("KC", None, 2003, "No staff is shown"),
])
def test_coaching_staff_view(headless, capsys, team, role, season, expect):
    out = headless(cli.render_coaching_staff_view, team, role, season)
    _quiet(capsys)
    assert expect in out


def test_specific_play_view_diagram(headless, engine, plays, capsys):
    out = headless(cli.render_specific_play_view, engine, plays, season=SEASON, play_id=101,
                   game_id="2025_01_BAL_KC", camera="sideline")
    _quiet(capsys)
    assert "No matching play" not in out and len(out.splitlines()) > 10


def test_specific_play_view_no_match(headless, engine, plays, capsys):
    out = headless(cli.render_specific_play_view, engine, plays, season=SEASON, play_id=1, game_id="nope")
    _quiet(capsys)
    assert "No matching play found" in out


def test_game_plays_table(headless, plays, capsys):
    game = [p for p in plays if p.get("game_id") == "2025_01_BAL_KC"]
    assert game
    out = headless(cli.render_game_plays_table, game, title="BAL @ KC Q1", highlight_play_id=101)
    _quiet(capsys)
    assert "BAL @ KC Q1" in out and "#101" in out


@pytest.mark.skipif(not cli.C.RESET, reason="colour disabled at import (NO_COLOR / TERM=dumb)")
def test_colour_on_output_has_ansi_so_disable_matters(engine, plays):
    out = cli.render_team_drilldown_view(engine, plays, SEASON, "KC")
    assert ANSI in out


# --- the interactive default is unchanged ------------------------------------------------------------------

def test_player_interactive_default_still_prompts_on_a_tty(engine, plays, monkeypatch, capsys):
    """Today's CLI behaviour (interactive=True, a real terminal) still asks; the web path just never uses it."""
    asked = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "prompt_input", lambda text: asked.append(text) or "1")
    out = cli.strip_ansi(cli.render_player_drilldown_view(engine, plays, SEASON, "McCaffrey"))
    assert asked and "Select player" in asked[0]
    assert "matches several players" not in out
    assert "Multiple players matched" in capsys.readouterr().out


def test_unique_player_on_two_teams_returns_combined_without_prompt(headless, engine, plays, capsys, tmp_path):
    rows = [dict(AMBIGUOUS_ROWS[0], posteam=team, rusher_player_name="T.Traded",
                 play_id=9100 + i, game_id=f"2025_01_{team}_NYJ", yards_gained=7 + i)
            for i, team in enumerate(("SF", "WAS"))]
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "traded-cache", engine="offline")
    normalized = [bridge._normalize_row(row, 9100 + i) for i, row in enumerate(rows)]
    assert set(cli.get_player_teams(normalized, "T.Traded")) == {"SF", "WAS"}
    out = headless(cli.render_player_drilldown_view, engine, plays + normalized,
                   SEASON, "T.Traded", interactive=False)
    _quiet(capsys)
    assert "Combined All Teams" in out and "SF" in out and "WAS" in out
    assert "I can't answer that" not in out
