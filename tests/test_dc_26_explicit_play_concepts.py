"""Issue #26: inferred play concepts must never contradict explicit attributes (synthetic rows only)."""
import pytest

import pro_football_slm as cli


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


@pytest.mark.parametrize("missing", [None, "", "NA", float("nan")])
def test_missing_concept_type_and_gap_values_are_unknown_not_text(missing):
    row = _row(play_type="run", rush_attempt=1, play_concept=missing, run_gap=missing)
    assert row["play_concept"] == "rush" and row["play_concept_source"] == "unknown"
    row = _row(play_type=missing, pass_attempt=1, air_yards=12.0, play_concept=missing)
    assert row["play_concept"] == "pass_intermediate" and row["play_concept_source"] == "inferred"


def test_screen_heuristics_and_their_guards():
    assert _pass(air_yards=-2.0, complete_pass=1)["is_screen"] == 1
    assert _pass(air_yards=-2.0, complete_pass=1)["play_concept"] == "screen"
    assert _pass(air_yards=0.0, sack=1)["is_screen"] == 0
    assert _pass(air_yards=15.0, desc="short pass, screen to the left")["play_concept"] == "screen"


def test_r_style_empty_values_behave_like_missing_values():
    # the R bridge writes NA as '' (is_screen stays blank when air_yards is NA): same result as a missing column
    r_row = _pass(air_yards="", is_screen="", play_action="", complete_pass=1, sack=0)
    assert r_row["is_screen"] == 0 and r_row["play_concept"] == "pass"
    full = _pass(air_yards="-2.0", is_screen="", complete_pass=1)
    assert full["is_screen"] == 1


def test_a_no_play_whose_description_mentions_a_screen_is_not_a_screen():
    row = _row(play_type="no_play", desc="screen pass nullified by a penalty")
    assert row["play_concept"] == "no_play"


def test_untyped_rows_use_their_attempt_flags():
    assert _row(pass_attempt=1, air_yards=20.0)["play_concept"] == "pass_deep"
    assert _row(rush_attempt=1, run_gap="end")["play_concept"] == "rush_outside"


def test_play_action_with_unknown_air_yards_does_not_claim_depth():
    row = _pass(play_action=1)
    assert row["play_concept"] == "play_action" and row["play_concept_source"] == "inferred"


def test_run_gap_tackle_is_not_guessed():
    assert _run(run_gap="tackle", run_location="left")["play_concept"] == "rush"


def test_an_explicit_screen_flag_is_labelled_explicit_and_a_guess_inferred():
    assert _pass(air_yards=12.0, is_screen=1)["play_concept_source"] == "explicit"
    assert _pass(air_yards=-2.0, complete_pass=1)["play_concept_source"] == "inferred"


def test_a_run_whose_description_mentions_a_screen_is_still_a_run():
    row = _run(desc="run up the middle, screen blockers", run_location="middle")
    assert row["play_concept"] == "rush_inside"


def test_unparseable_air_yards_is_unknown_not_zero():
    row = _pass(air_yards="abc", complete_pass=1)
    assert row["play_concept"] == "pass" and row["is_screen"] == 0


def test_row_without_play_type_or_attempts_does_not_emit_a_run():
    row = _row()
    assert row["play_type"] == "" and row["play_concept"] == "unknown"


def test_run_gap_end_wins_over_a_middle_location():
    assert _run(run_gap="end", run_location="middle")["play_concept"] == "rush_outside"


def test_old_play_action_and_outside_labels_do_not_leak_into_other_plays():
    assert _pass(air_yards=40.0, play_action=0)["play_concept"] != "play_action_deep"
    assert _row(play_type="punt")["play_concept"] != "rush_outside"
