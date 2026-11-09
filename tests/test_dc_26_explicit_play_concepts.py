"""Issue #26: inferred play concepts must never contradict explicit attributes (synthetic rows only)."""
import pytest

import nfl_stat_cli as cli


def _row(**kw):
    base = {"posteam": "ZZZ", "defteam": "YYY", "game_id": "2025_01_YYY_ZZZ", "season": 2025, "week": 1,
            "desc": "plain play"}
    base.update(kw)
    return cli.NFLDataBridge(engine="offline")._normalize_row(base, 1)


def _pass(**kw):
    return _row(play_type="pass", pass_attempt=1, **kw)


def _run(**kw):
    return _row(play_type="run", rush_attempt=1, **kw)


def test_deep_pass_with_explicit_no_play_action_is_not_a_play_action_concept():
    row = _pass(air_yards=30.0, play_action=0)
    assert row["play_action"] == 0
    assert row["play_concept"] == "pass_deep"
    assert "play_action" not in row["play_concept"]


def test_deep_pass_with_unknown_play_action_does_not_claim_play_action():
    assert "play_action" not in _pass(air_yards=30.0)["play_concept"]


def test_explicit_play_action_is_honoured_and_only_deep_when_air_yards_say_so():
    assert _pass(air_yards=30.0, play_action=1)["play_concept"] == "play_action_deep"
    assert _pass(air_yards=6.0, play_action=1)["play_concept"] == "play_action"


@pytest.mark.parametrize("air,expected", [(25.0, "pass_deep"), (18.0, "pass_deep"), (12.0, "pass_intermediate"),
                                          (10.0, "pass_intermediate"), (4.0, "pass_short"), (-3.0, "pass_short")])
def test_pass_depth_follows_air_yards(air, expected):
    assert _pass(air_yards=air, play_action=0, is_screen=0)["play_concept"] == expected


@pytest.mark.parametrize("missing", [None, "", "NA", float("nan")])
def test_unknown_air_yards_is_unknown_not_zero(missing):
    row = _pass(air_yards=missing, complete_pass=1)
    assert row["play_concept"] == "pass"
    assert row["play_concept_source"] == "unknown"
    assert row["is_screen"] == 0  # an unknown air_yards is not "<= 0 behind the line"


def test_explicit_screen_flag_and_concept_win():
    assert _pass(air_yards=30.0, is_screen=1)["play_concept"] == "screen"
    assert _pass(air_yards=-2.0, complete_pass=1, is_screen=0)["is_screen"] == 0
    row = _pass(air_yards=30.0, play_concept="quick_slant")
    assert row["play_concept"] == "quick_slant" and row["play_concept_source"] == "explicit"


def test_runs_are_inside_or_outside_only_when_gap_or_location_says_so():
    assert _run(run_gap="end", run_location="left")["play_concept"] == "rush_outside"
    assert _run(run_gap="guard", run_location="left")["play_concept"] == "rush_inside"
    assert _run(run_location="middle")["play_concept"] == "rush_inside"
    plain = _run()
    assert plain["play_concept"] == "rush" and plain["play_concept_source"] == "unknown"


@pytest.mark.parametrize("pt", ["punt", "kickoff", "field_goal", "no_play", "qb_kneel", "qb_spike", "extra_point"])
def test_non_scrimmage_plays_are_never_rush_outside(pt):
    row = _row(play_type=pt)
    assert row["play_concept"] == pt
    assert row["play_concept"] != "rush_outside"


def test_row_with_no_play_type_and_no_attempts_has_unknown_concept():
    assert _row()["play_concept"] == "unknown"


def test_concept_source_labels_heuristics():
    assert _pass(air_yards=12.0)["play_concept_source"] == "inferred"
    assert _pass(air_yards=12.0, play_concept="pass_intermediate")["play_concept_source"] == "explicit"


def test_sample_rows_keep_their_explicit_concepts():
    bridge = cli.NFLDataBridge(engine="offline")
    for raw in cli.SAMPLE_PBP_PLAYS:
        norm = bridge._normalize_row(raw, 1)
        assert norm["play_concept"] == raw["play_concept"]
        assert norm["play_concept_source"] == "explicit"
