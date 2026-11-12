"""Synthetic PBP/roster examples. These contain no participation data."""

import pytest

from pro_football_slm import DEFAULT_STATS, NFLDataBridge, StatEngine, _pbp_row_is_playable
from pro_football_slm.exploration import (
    EXPLORATION_COLUMNS, PLAYER_ID_COLUMNS, normalize_rosters, order_game_log, row_refs,
)


@pytest.fixture
def bridge(tmp_path):
    return NFLDataBridge(cache_dir=tmp_path)


def event(play_id, kind, **extra):
    return dict(game_id="2024_01_BAL_KC", play_id=play_id, season=2024,
                posteam="KC", defteam="BAL", play_type=kind, **extra)


@pytest.mark.parametrize("kind", ["kickoff", "punt", "field_goal", "extra_point", "no_play", ""])
def test_full_log_keeps_rows_stats_predicate_drops(bridge, kind):
    raw = event(10, kind)
    assert not _pbp_row_is_playable(raw)
    rows = bridge.normalize_game_log([raw])
    assert len(rows) == 1
    assert rows[0]["play_kind"] == (kind or "untyped")


def test_full_log_keeps_teamless_timeout_and_metadata(bridge):
    raw = event(42, "timeout", timeout=1, drive=2, fixed_drive=3,
                old_game_id="2024090500", order_sequence=1, game_seconds_remaining=3600, time="15:00")
    raw["posteam"] = None
    row = bridge.normalize_game_log([raw])[0]
    assert not _pbp_row_is_playable(raw)
    assert row["play_kind"] == "timeout"
    for column in ("drive", "fixed_drive", "old_game_id", "order_sequence", "game_seconds_remaining", "time"):
        assert row[column] == raw[column]


@pytest.mark.parametrize("column", PLAYER_ID_COLUMNS)
def test_all_recorded_player_roles_have_stable_links(bridge, column):
    row = bridge.normalize_game_log([event(42, "punt", **{column: "00-dummy"})])[0]
    assert row[column] == "00-dummy"
    assert row["player_refs"] == ["player:00-dummy"]
    assert row["players"][0]["role"] == column


def test_refs_are_game_scoped_and_use_roster_names():
    rows = normalize_rosters([
        dict(gsis_id="00-dummy", full_name="Example Player", season=2024, team="KC",
             position="K", depth_chart_position="K", jersey_number=7,
             headshot_url="excluded", birth_date="excluded"),
        dict(gsis_id=None, full_name="No Identity"),
    ])
    a = event(42, "field_goal", kicker_player_id="00-dummy", kicker_player_name="E.Player")
    b = dict(a, game_id="2024_02_KC_CIN")
    assert row_refs(a, rows)["play_ref"] != row_refs(b, rows)["play_ref"]
    assert row_refs(a, rows)["game_ref"] == "game:2024_01_BAL_KC"
    assert row_refs(a, rows)["players"][0]["name"] == "Example Player"
    assert len(rows) == 1
    assert "headshot_url" not in rows[0] and "birth_date" not in rows[0]


def test_order_uses_numeric_sequence_over_clock_and_play_id():
    # Synthetic counterexample, not an extract of the BAL-KC game.
    rows = [event(100, "run", order_sequence="2", game_seconds_remaining=100),
            event(20, "timeout", order_sequence="10", game_seconds_remaining=90),
            event(30, "no_play", order_sequence="1", game_seconds_remaining=110)]
    assert [r["play_id"] for r in order_game_log(rows)] == [30, 100, 20]


def test_missing_order_fields_and_stable_ties():
    rows = [{"play_id": None, "tag": "missing"}, {"play_id": "10", "tag": "a"},
            {"play_id": 2, "tag": "b"}, {"play_id": 10, "tag": "c"}]
    assert [r["tag"] for r in order_game_log(rows)] == ["b", "a", "c", "missing"]


def test_missing_ids_do_not_create_openable_refs(bridge):
    row = bridge.normalize_game_log([{"play_type": "timeout"}])[0]
    assert row["play_id"] is None
    assert row["play_ref"] is None and row["game_ref"] is None


def test_allowlist_excludes_betting_and_private_fields():
    assert not set(EXPLORATION_COLUMNS) & {
        "spread_line", "total_line", "vegas_wp", "vegas_wpa", "home_moneyline", "away_moneyline",
        "headshot_url", "birth_date",
    }


def test_special_teams_definitions_execute_on_full_log(bridge, tmp_path):
    engine = StatEngine(storage_dir=tmp_path)
    rows = bridge.normalize_game_log([
        event(1, "field_goal", kicker_player_id="00-k", field_goal_result="made", kick_distance=40),
        event(2, "field_goal", kicker_player_id="00-k", field_goal_result="missed", kick_distance=50),
        event(3, "field_goal", kicker_player_id="00-other", field_goal_result="made", kick_distance=30),
        event(4, "punt", punter_player_id="00-p", punt_blocked="0", kick_distance="50", return_yards="10", touchback="0"),
        event(5, "punt", punter_player_id="00-p", punt_blocked=0, kick_distance=60, return_yards=0, touchback=1),
    ])
    board = engine.evaluate_stat_leaderboard("field_goal_pct", rows, min_attempts=0)
    assert {r["entity"]: r["value"] for r in board} == {"00-k": 50, "00-other": 100}
    assert engine.evaluate_stat_leaderboard("punt_average", rows, min_attempts=0)[0]["value"] == 55
    assert engine.evaluate_stat_leaderboard("punt_net_average", rows, min_attempts=0)[0]["value"] == 40
    assert DEFAULT_STATS["field_goal_pct"].group_by == "kicker"
    assert DEFAULT_STATS["punt_average"].group_by == "punter"


def test_unknown_kick_facts_are_excluded(bridge, tmp_path):
    engine = StatEngine(storage_dir=tmp_path)
    row = bridge.normalize_game_log([event(1, "punt", punter_player_id="00-p", punt_blocked=0)])[0]
    assert row["kick_distance"] is None and row["punt_net_yards"] is None
    assert engine.evaluate_stat_leaderboard("punt_average", [row], min_attempts=0) == []


@pytest.mark.parametrize("stat,kind", [
    ("field_goal_pct", "field_goal"), ("extra_point_pct", "extra_point"),
    ("punt_average", "punt"), ("punt_net_average", "punt"),
    ("punt_return_average", "punt"), ("kickoff_return_average", "kickoff"),
])
def test_legacy_sparse_rows_do_not_invent_special_teams_results(tmp_path, stat, kind):
    engine = StatEngine(storage_dir=tmp_path)
    assert engine.evaluate_stat_leaderboard(stat, [event(1, kind)], min_attempts=0) == []

@pytest.mark.parametrize("game,count,disagreements,clock_reversals", [
    ("2024_01_BAL_KC", 178, 20, 0),
    ("2024_01_GB_PHI", 196, 26, 0),
    ("2024_01_NE_CIN", 153, 22, 2),
])
def test_known_complete_games_order(game, count, disagreements, clock_reversals):
    import csv
    from pathlib import Path
    with (Path(__file__).parent / "fixtures/ordering_2024.csv").open() as source:
        rows = [row for row in csv.DictReader(source) if row["game_id"] == game]
    assert len(rows) == count
    assert set(rows[0]) == {"game_id", "play_id", "order_sequence",
                            "game_seconds_remaining", "qtr", "time", "play_type"}
    by_id = sorted(rows, key=lambda row: float(row["play_id"]))
    expected = sorted(rows, key=lambda row: float(row["order_sequence"]))
    assert sum(a["play_id"] != b["play_id"] for a, b in zip(by_id, expected)) == disagreements
    def reversals(events):
        clocks = [float(row["game_seconds_remaining"]) for row in events]
        return sum(b > a for a, b in zip(clocks, clocks[1:]))
    assert reversals(by_id) == clock_reversals
    assert reversals(expected) == 0
    assert order_game_log(list(reversed(rows))) == expected
    assert float(expected[0]["game_seconds_remaining"]) == 3600
    assert float(expected[-1]["game_seconds_remaining"]) == 0


def test_stats_row_contract_and_extension_preserve_existing_values(bridge):
    from pro_football_slm.exploration import extend_row
    raw = event(1, "pass", return_touchdown=None)
    row = bridge._normalize_row(raw)
    assert len(row) == 78
    assert row["return_touchdown"] == 0
    assert "players" not in row and "order_sequence" not in row
    extended = extend_row(dict(row), raw)
    assert all(extended[key] == value for key, value in row.items())
    assert type(extended["return_touchdown"]) is int
