"""Issue #17: play-inclusion rules must not distort per-play rates (synthetic rows only)."""
import pytest

import nfl_stat_cli as cli


def _bridge():
    return cli.NFLDataBridge(engine="offline")


def _norm(**kw):
    base = {"posteam": "ZZZ", "defteam": "YYY", "game_id": "2025_03_YYY_ZZZ", "season": 2025, "week": 3,
            "desc": "plain play"}
    base.update(kw)
    return _bridge()._normalize_row(base, 1)


def _metrics(rows, tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)._compute_base_metrics(rows)


def _raw(**kw):
    base = {"posteam": "ZZZ", "play_type": "", "pass_attempt": 0, "rush_attempt": 0, "desc": ""}
    base.update(kw)
    return base


# --- the shared keep/drop predicate -----------------------------------------------------------------

@pytest.mark.parametrize("pt", ["punt", "kickoff", "field_goal", "extra_point", "qb_kneel", "qb_spike"])
def test_declined_penalty_on_a_non_scrimmage_play_is_not_playable(pt):
    desc = "play result. PENALTY on ZZZ-X.Player, Offside, 5 yards, declined."
    assert not cli._pbp_row_is_playable(_raw(play_type=pt, desc=desc))                 # flag missing
    assert not cli._pbp_row_is_playable(_raw(play_type=pt, desc=desc, penalty=0))      # explicit 0 wins


@pytest.mark.parametrize("pt", ["punt", "qb_kneel"])
def test_an_explicit_penalty_flag_is_trusted_and_mixed_accepted_text_is_kept(pt):
    mixed = "PENALTY on ZZZ-A, Holding, declined. PENALTY on YYY-B, Offside, 5 yards, enforced."
    assert cli._pbp_row_is_playable(_raw(play_type=pt, desc="play. PENALTY on ZZZ-A, Offside, declined.", penalty=1))
    assert cli._pbp_row_is_playable(_raw(play_type=pt, desc=mixed))
    assert cli._pbp_row_is_playable(_raw(play_type=pt, desc=mixed, penalty=1))


@pytest.mark.parametrize("pt", ["punt", "kickoff", "qb_kneel", "qb_spike"])
def test_accepted_penalty_on_a_non_scrimmage_play_is_still_kept(pt):
    desc = "play result. PENALTY on ZZZ-X.Player, Holding, 10 yards, enforced."
    assert cli._pbp_row_is_playable(_raw(play_type=pt, desc=desc, penalty=1))
    assert cli._pbp_row_is_playable(_raw(play_type=pt, desc=desc))


def test_a_timeout_mention_alone_does_not_keep_a_typed_special_teams_row():
    assert not cli._pbp_row_is_playable(_raw(play_type="punt", desc="punt after Timeout #1 by ZZZ"))
    assert cli._pbp_row_is_playable(_raw(play_type="punt", desc="punt", timeout=1))
    assert cli._pbp_row_is_playable(_raw(play_type="no_play", desc="Timeout #1 by ZZZ"))


def test_penalty_and_timeout_no_plays_and_attempts_are_unchanged():
    assert cli._pbp_row_is_playable(_raw(play_type="no_play", desc="false start", penalty=1))
    assert cli._pbp_row_is_playable(_raw(play_type="no_play", desc="timeout", timeout=1))
    assert cli._pbp_row_is_playable(_raw(play_type="pass", pass_attempt=1, desc="pass, penalty declined"))
    assert cli._pbp_row_is_playable(_raw(play_type="run", rush_attempt=1))
    assert not cli._pbp_row_is_playable(_raw(play_type="kickoff", desc="kickoff"))


def test_untyped_rows_follow_the_flag_then_the_description():
    assert cli._pbp_row_is_playable(_raw(desc="penalty on the play"))
    assert not cli._pbp_row_is_playable(_raw(desc="penalty declined"))
    assert not cli._pbp_row_is_playable(_raw(desc="penalty on the play", penalty=0))


# --- per-play rates -------------------------------------------------------------------------------

def _downs():
    return [_norm(play_type="pass", pass_attempt=1, complete_pass=1, yards_gained=12.0, epa=1.0, first_down=1),
            _norm(play_type="run", rush_attempt=1, yards_gained=2.0, epa=-0.5)]


def _no_play_rows():
    return [_norm(play_type="no_play", penalty=1, desc="false start, no play"),
            _norm(play_type="no_play", timeout=1, desc="Timeout #1 by ZZZ")]


def test_penalty_and_timeout_rows_do_not_dilute_per_play_rates(tmp_path):
    base = _metrics(_downs(), tmp_path)
    mixed = _metrics(_downs() + _no_play_rows(), tmp_path)
    assert base["plays"] == 2.0 and mixed["plays"] == 2.0
    for key in ("yards_per_play", "epa_per_play", "success_rate", "first_down_rate", "explosive_play_rate", "td_rate"):
        assert mixed[key] == pytest.approx(base[key]), key
    # the penalty and timeout rows themselves are still counted where they belong
    assert mixed["penalties"] == 1.0 and mixed["timeouts"] == 1.0


def test_rows_without_a_play_type_or_attempts_are_not_scrimmage_plays(tmp_path):
    row = _norm(penalty=1, desc="penalty on the play")
    assert row["play_type"] == ""          # not fabricated as "run"
    assert _metrics(_downs() + [row], tmp_path)["plays"] == 2.0


# --- return touchdowns ----------------------------------------------------------------------------

def _pick_six():
    return _norm(play_type="pass", pass_attempt=1, interception=1, touchdown=1, td_team="YYY",
                 return_touchdown=1, desc="pass intercepted, returned for a TOUCHDOWN")


def _offense_td():
    return _norm(play_type="run", rush_attempt=1, touchdown=1, td_team="ZZZ", yards_gained=3.0)


def test_return_touchdowns_are_not_offense_touchdowns(tmp_path):
    m = _metrics(_downs() + [_offense_td(), _pick_six()], tmp_path)
    assert m["touchdowns"] == 1.0
    assert m["td_rate"] == pytest.approx(1.0 / 4.0)
    assert _pick_six()["touchdown"] == 1                      # the raw flag stays, for D/ST scoring
    assert _pick_six()["td_team"] == "YYY"
    assert _pick_six()["pass_touchdown"] == 0 and m["pass_touchdowns"] == 0.0   # not a passing TD either


def test_defensive_return_is_not_a_rushing_td_and_explicit_columns_win():
    fumble_six = _norm(play_type="run", rush_attempt=1, touchdown=1, td_team="YYY", fumble_lost=1)
    assert fumble_six["rush_touchdown"] == 0
    explicit = _norm(play_type="run", rush_attempt=1, touchdown=1, td_team="YYY", rush_touchdown=1)
    assert explicit["rush_touchdown"] == 1


def test_csv_style_string_values_work_and_the_r_bridge_exports_the_columns():
    from pathlib import Path
    row = _norm(play_type="pass", pass_attempt="1", interception="1", touchdown="1", td_team="YYY", return_touchdown="1")
    assert row["return_touchdown"] == 1 and row["td_team"] == "YYY" and row["pass_touchdown"] == 0
    root = Path(__file__).resolve().parent.parent
    for script in (root / "nfl_stat_cli" / "nflverse_bridge.R", root / "nflverse_bridge.R"):
        text = script.read_text(encoding="utf-8")
        assert '"td_team"' in text and '"return_touchdown"' in text


def test_return_touchdown_flag_is_enough_when_td_team_is_missing(tmp_path):
    row = _norm(play_type="pass", pass_attempt=1, interception=1, touchdown=1, return_touchdown=1)
    assert _metrics([row], tmp_path)["touchdowns"] == 0.0
    plain = _norm(play_type="pass", pass_attempt=1, complete_pass=1, touchdown=1, pass_touchdown=1)
    assert _metrics([plain], tmp_path)["touchdowns"] == 1.0


# --- success vs series_success --------------------------------------------------------------------

def test_success_and_series_success_are_distinct_measures():
    positive_epa_no_first_down = _norm(play_type="run", rush_attempt=1, epa=0.4, yards_gained=2.0, ydstogo=10, first_down=0)
    first_down_negative_epa = _norm(play_type="run", rush_attempt=1, epa=-0.2, yards_gained=11.0, ydstogo=10, first_down=1)
    assert (positive_epa_no_first_down["success"], positive_epa_no_first_down["series_success"]) == (1, 0)
    assert (first_down_negative_epa["success"], first_down_negative_epa["series_success"]) == (0, 1)


def test_explicit_success_columns_are_kept_apart():
    row = _norm(play_type="pass", pass_attempt=1, epa=2.0, success=0, series_success=1)
    assert row["success"] == 0 and row["series_success"] == 1


def test_success_rate_counts_positive_epa_plays_not_first_downs(tmp_path):
    # only series_success is present (a first down with negative EPA): success (EPA > 0) must not read it
    rows = [_norm(play_type="run", rush_attempt=1, epa=-0.2, yards_gained=11.0, ydstogo=10, first_down=1,
                  series_success=1),
            _norm(play_type="run", rush_attempt=1, epa=0.4, yards_gained=2.0, first_down=0, series_success=0)]
    assert _metrics(rows, tmp_path)["success_rate"] == pytest.approx(0.5)
    only_first_down = rows[:1]
    assert _metrics(only_first_down, tmp_path)["success_rate"] == 0.0


def test_first_downs_and_touchdowns_on_no_play_rows_do_not_feed_the_rates(tmp_path):
    odd = [_norm(play_type="no_play", penalty=1, first_down=1, touchdown=1, yards_gained=25.0, epa=0.5,
                 desc="defensive holding, automatic first down")]
    base = _metrics(_downs(), tmp_path)
    mixed = _metrics(_downs() + odd, tmp_path)
    for key in ("first_downs", "first_down_rate", "explosive_plays", "explosive_play_rate", "td_rate", "touchdowns",
                "success_rate", "yards_per_play", "epa_per_play", "total_yards", "total_epa"):
        assert mixed[key] == pytest.approx(base[key]), key


@pytest.mark.parametrize("pt,flag", [("qb_kneel", "rush_attempt"), ("qb_spike", "pass_attempt"), ("punt", "")])
def test_clock_plays_and_special_teams_never_feed_the_rates_even_with_attempt_flags(tmp_path, pt, flag):
    extra = {flag: 1} if flag else {"penalty": 1}
    row = _norm(play_type=pt, yards_gained=-1.0 if pt != "punt" else 45.0, epa=0.7, desc="kept for a flag", **extra)
    base = _metrics(_downs(), tmp_path)
    mixed = _metrics(_downs() + [row], tmp_path)
    assert mixed["plays"] == 2.0
    for key in ("yards_per_play", "epa_per_play", "success_rate", "total_epa"):
        assert mixed[key] == pytest.approx(base[key]), key


def test_first_down_and_series_success_fallbacks_ignore_defensive_scores():
    six = _norm(play_type="pass", pass_attempt=1, interception=1, touchdown=1, td_team="YYY", ydstogo=10,
                yards_gained=0.0)
    assert six["first_down"] == 0 and six["series_success"] == 0
    own = _norm(play_type="run", rush_attempt=1, touchdown=1, td_team="ZZZ", ydstogo=10, yards_gained=3.0)
    assert own["first_down"] == 1 and own["series_success"] == 1


def test_success_rate_falls_back_to_epa_for_legacy_rows_without_a_success_column(tmp_path):
    legacy = [{"play_type": "run", "rush_attempt": 1, "epa": 0.5, "series_success": 1, "posteam": "ZZZ",
               "game_id": "g"},
              {"play_type": "run", "rush_attempt": 1, "epa": -0.5, "series_success": 1, "posteam": "ZZZ",
               "game_id": "g"}]
    assert _metrics(legacy, tmp_path)["success_rate"] == pytest.approx(0.5)


# --- no fabricated season / game id ---------------------------------------------------------------

def test_sparse_row_does_not_get_a_fabricated_season_or_game_id():
    row = _bridge()._normalize_row({"posteam": "ZZZ", "defteam": "YYY", "play_type": "run", "rush_attempt": 1}, 1)
    assert row["season"] == 0 and row["week"] == 0
    assert row["game_id"] == "unknown_game"
    assert "UNK" not in row["game_id"] and row["season"] != 2025


def test_season_and_week_come_from_the_game_id_when_the_columns_are_missing():
    row = _bridge()._normalize_row({"posteam": "ZZZ", "defteam": "YYY", "play_type": "run", "rush_attempt": 1,
                                    "game_id": "2023_07_YYY_ZZZ"}, 1)
    assert (row["season"], row["week"], row["game_id"]) == (2023, 7, "2023_07_YYY_ZZZ")


def test_explicit_season_and_week_win_over_the_game_id():
    row = _norm(season=2024, week=9, game_id="2023_07_YYY_ZZZ", play_type="run", rush_attempt=1)
    assert (row["season"], row["week"]) == (2024, 9)
