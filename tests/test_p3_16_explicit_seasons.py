"""Regression tests for the season-selection part of #16: the CLI can load exactly the seasons you ask for.

(The column-projection part of #16 lives in NFLDataBridge._normalize_dataframe and is intentionally not changed here.)
"""
import argparse

import pytest

import nfl_stat_cli as cli


@pytest.mark.parametrize("text,expected", [
    ("2025", [2025]), ("2024,2025", [2024, 2025]), ("2025, 2024", [2024, 2025]), ("2023-2025", [2023, 2024, 2025]),
    ("2024,2024", [2024]), ("2022,2024-2025", [2022, 2024, 2025]),
])
def test_parse_seasons_arg_accepts(text, expected):
    assert cli.parse_seasons_arg(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "2025-2024", "1998", "2999", "2019-2025", "2020,2021,2022,2023,2024,2025", "20x5", "2024;2025", "-1"])
def test_parse_seasons_arg_rejects(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_seasons_arg(text)


def test_parse_seasons_arg_upper_bound_follows_current_season():
    y = cli.CURRENT_SEASON
    assert cli.parse_seasons_arg(str(y + 1)) == [y + 1]
    assert cli.parse_seasons_arg(f"{y - 1}-{y}") == [y - 1, y]
    with pytest.raises(argparse.ArgumentTypeError, match="must be within"):
        cli.parse_seasons_arg(str(y + 2))
    with pytest.raises(argparse.ArgumentTypeError, match="must be within"):
        cli.parse_seasons_arg("1998")
    with pytest.raises(argparse.ArgumentTypeError, match="upward"):
        cli.parse_seasons_arg(f"{y}-{y - 1}")


def test_parse_seasons_arg_rejects_non_ascii_digits():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_seasons_arg("\u0662\u0660\u0662\u0665")


def test_seasons_to_load_defaults_to_lookback_and_honours_explicit():
    assert cli.seasons_to_load(2025) == [2024, 2025]
    assert cli.seasons_to_load(2025, None) == [2024, 2025]
    assert cli.seasons_to_load(2025, [2025]) == [2025]
    assert cli.seasons_to_load(2025, [2023, 2021]) == [2021, 2023]


@pytest.fixture
def loads(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = []
    orig = cli.NFLDataBridge.load_pbp

    def spy(self, seasons, spinner=None):
        seen.append(list(seasons))
        return orig(self, seasons, spinner)

    monkeypatch.setattr(cli.NFLDataBridge, "load_pbp", spy)
    return seen


def test_stat_command_default_still_loads_two_seasons(loads):
    cli.main(["stat", "epa_per_play", "--season", "2025", "--engine", "offline", "--no-color"])
    assert loads == [[2024, 2025]]


def test_stat_command_with_seasons_loads_only_those(loads):
    cli.main(["stat", "epa_per_play", "--season", "2025", "--seasons", "2025", "--engine", "offline", "--no-color"])
    assert loads == [[2025]]


def test_ask_with_seasons_loads_only_those(loads):
    cli.main(["ask", "epa per play", "--season", "2025", "--seasons", "2025", "--engine", "offline", "--no-color", "--slm-model", "off"])
    assert loads == [[2025]]


def test_season_outside_explicit_seasons_warns_on_stderr(loads, capsys):
    cli.main(["stat", "epa_per_play", "--season", "2025", "--seasons", "2023", "--engine", "offline", "--no-color"])
    err = capsys.readouterr().err
    assert "season 2025 is not in --seasons (2023)" in err
    assert loads == [[2023]]


def test_no_warning_when_season_is_included(loads, capsys):
    cli.main(["stat", "epa_per_play", "--season", "2025", "--seasons", "2024,2025", "--engine", "offline", "--no-color"])
    assert "not in --seasons" not in capsys.readouterr().err


def test_ask_warns_when_the_parsed_season_is_not_loaded(loads, capsys):
    cli.main(["ask", "epa per play 2024", "--season", "2025", "--seasons", "2025", "--engine", "offline", "--no-color", "--slm-model", "off"])
    assert "season 2024 is not in --seasons (2025)" in capsys.readouterr().err


def test_ask_default_follows_the_parsed_season(loads):
    cli.main(["ask", "epa per play 2024", "--season", "2025", "--engine", "offline", "--no-color", "--slm-model", "off"])
    assert loads == [[2023, 2024]]


def test_invalid_seasons_value_is_a_usage_error(loads, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["stat", "epa_per_play", "--seasons", "2025-2019"])
    assert exc.value.code == 2 and loads == []
    assert "season" in capsys.readouterr().err.lower()


def test_tui_loads_the_requested_seasons(monkeypatch, tmp_path):
    seen = []

    class Bridge(cli.NFLDataBridge):
        def load_pbp(self, seasons, spinner=None):
            seen.append(list(seasons))
            return list(cli.SAMPLE_PBP_PLAYS)

    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "/quit")
    eng = cli.StatEngine(storage_dir=tmp_path)
    for kwargs, expected in (({}, [2023, 2024]), ({"load_seasons": [2024]}, [2024])):
        before = len(seen)
        try:
            cli.interactive_tui(eng, Bridge(cache_dir=tmp_path / "c", engine="offline"), slm_model="off", default_season=2024, **kwargs)
        except SystemExit:
            pass
        assert len(seen) == before + 1 and seen[-1] == expected


def test_help_mentions_seasons_option_and_lookback_tradeoff(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "400")
    with pytest.raises(SystemExit):
        cli.main(["stat", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--seasons" in out and "lookback" in out


def test_tui_warns_when_the_default_season_is_not_loaded(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "/quit")
    eng = cli.StatEngine(storage_dir=tmp_path)
    try:
        cli.interactive_tui(
            eng, cli.NFLDataBridge(cache_dir=tmp_path / "c", engine="offline"), slm_model="off", default_season=2025,
            initial_plays=list(cli.SAMPLE_PBP_PLAYS), load_seasons=[2023],
        )
    except SystemExit:
        pass
    assert "season 2025 is not in --seasons (2023)" in capsys.readouterr().err
