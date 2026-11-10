"""Golden tests: pass-play production is credited to the passer, not the receiver (issue #5)."""
import pytest

import pro_football_slm as cli


def _play(idx, **kw):
    base = {
        "play_id": idx, "season": 2025, "week": 1, "game_id": "2025_01_BAL_KC",
        "posteam": "KC", "defteam": "BAL", "conf": "AFC",
        "qb_name": "", "receiver_player_name": "", "rusher_player_name": "",
        "play_type": "pass", "yards_gained": 0.0, "epa": 0.1, "complete_pass": 0,
        "pass_attempt": 0, "rush_attempt": 0, "touchdown": 0, "interception": 0, "sack": 0,
        "down": 1, "ydstogo": 10, "yardline_100": 50, "qtr": 1, "team_win": 1,
        "home_score": 27, "away_score": 20, "desc": "fixture play",
    }
    base.update(kw)
    return base


@pytest.fixture
def plays(tmp_path):
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline")
    raw = [
        # 30-yard TD completion Mahomes -> Worthy
        _play(1, qb_name="P.Mahomes", receiver_player_name="X.Worthy", yards_gained=30.0,
              complete_pass=1, pass_attempt=1, touchdown=1, pass_touchdown=1),
        # incomplete, intercepted
        _play(2, qb_name="P.Mahomes", receiver_player_name="X.Worthy", yards_gained=0.0,
              pass_attempt=1, interception=1),
        # designed run
        _play(3, play_type="run", rusher_player_name="I.Pacheco", yards_gained=12.0, rush_attempt=1),
        # QB scramble
        _play(4, play_type="run", qb_name="P.Mahomes", rusher_player_name="P.Mahomes",
              yards_gained=8.0, rush_attempt=1, qb_scramble=1),
    ]
    return [bridge._normalize_row(r, i) for i, r in enumerate(raw, 1)]


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path / "state")


def _board(engine, stat, plays, group="player"):
    return {r["entity"]: r["value"] for r in engine.evaluate_stat_leaderboard(stat, plays, group_override=group)}


def test_golden_standard_fantasy_player_board(engine, plays):
    # Mahomes: 30*0.04 + 4 (pass TD) - 2 (INT) + 8*0.1 (scramble) = 4.0
    # Worthy : 30*0.1 + 6 (receiving TD)                           = 9.0
    # Pacheco: 12*0.1                                              = 1.2
    assert _board(engine, "fantasy_points", plays) == {"X.Worthy": 9.0, "P.Mahomes": 4.0, "I.Pacheco": 1.2}


def test_golden_ppr_fantasy_player_board(engine, plays):
    # Only the receiver earns the reception point; the passer earns none for the completion
    assert _board(engine, "fantasy_points_ppr", plays) == {"X.Worthy": 10.0, "P.Mahomes": 4.0, "I.Pacheco": 1.2}
    assert _board(engine, "fantasy_points_half_ppr", plays) == {"X.Worthy": 9.5, "P.Mahomes": 4.0, "I.Pacheco": 1.2}


def test_qb_present_and_receiver_not_scored_as_passer(engine, plays):
    board = _board(engine, "fantasy_points", plays)
    assert "P.Mahomes" in board  # QB must not be missing from the fantasy leaderboard
    # Old behaviour scored Worthy's 30 receiving yards at the 0.04 passing rate (+4 pass TD): 5.2
    assert board["X.Worthy"] == 9.0


def test_qb_group_fantasy_matches_player_board(engine, plays):
    assert _board(engine, "fantasy_points", plays, group="qb") == {"P.Mahomes": 4.0}


def test_golden_contract_cap_hit_attaches_to_named_player(engine, plays, monkeypatch):
    # Pin the contract data so the golden values do not depend on the bundled contract table
    def fake_find(name):
        table = {"p.mahomes": 37.0, "x.worthy": 2.5}
        cap = table.get(str(name).strip().lower())
        if cap is None:
            return None
        return cli.ContractRecord(name, "KC", "QB", "player", 100.0, 10.0, 50.0, 4, 2024, 2028, cap, "")
    monkeypatch.setattr(cli, "find_contract_by_name", fake_find)
    engine.register_custom_stat(
        name="cap_probe", title="Cap probe", group_by="player", formula="cap_hit",
        description="cap hit lookup", calculation_explained="returns the entity's current cap hit",
        persist=False,
    )
    board = _board(engine, "cap_probe", plays)
    assert board["P.Mahomes"] == 37.0   # Mahomes' own cap hit, not the receiver's
    assert board["X.Worthy"] == 2.5
    qb_board = _board(engine, "cap_probe", plays, group="qb")
    assert qb_board == {"P.Mahomes": 37.0}


def test_team_group_has_no_misattributed_contract(engine, plays):
    engine.register_custom_stat(
        name="cap_probe_t", title="Cap probe", group_by="team", formula="cap_hit",
        description="cap hit lookup", calculation_explained="aggregate groups have no single contract",
        persist=False,
    )
    assert _board(engine, "cap_probe_t", plays, group="team") == {"KC": 0.0}


def test_team_fantasy_total_unchanged_by_role_attribution(engine, plays):
    # Aggregate (non-entity) groups keep summing team production once
    assert _board(engine, "fantasy_points", plays, group="team")["KC"] == pytest.approx(0.04 * 30 + 4 - 2 + 0.1 * 20)


def test_passer_credited_when_only_passer_player_name_is_set(engine):
    raw = [_play(1, passer_player_name="P.Mahomes", receiver_player_name="X.Worthy", yards_gained=20.0,
                 complete_pass=1, pass_attempt=1)]
    rows = raw  # un-normalized rows: only passer_player_name carries the passer
    board = _board(engine, "fantasy_points", rows)
    assert board == {"P.Mahomes": 0.8, "X.Worthy": 2.0}


def test_pick_six_is_not_a_passing_touchdown(engine, tmp_path):
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline")
    raw = [_play(1, qb_name="P.Mahomes", receiver_player_name="X.Worthy", pass_attempt=1, interception=1, touchdown=1)]
    rows = [bridge._normalize_row(r, 1) for r in raw]  # normalization may flag pass_touchdown on a pick-six
    board = _board(engine, "fantasy_points", rows)
    assert board["P.Mahomes"] == -2.0
    assert board.get("X.Worthy", 0.0) == 0.0


def test_role_attribution_detection_survives_dependency_cycles(engine):
    a = engine.stats["fantasy_points"]
    engine.stats["cyc_a"] = cli.StatDefinition(name="cyc_a", title="a", category="custom", group_by="player", formula="cyc_b", description="", calculation_explained="")
    engine.stats["cyc_b"] = cli.StatDefinition(name="cyc_b", title="b", category="custom", group_by="player", formula="cyc_a", description="", calculation_explained="")
    assert engine._stat_needs_role_attribution(engine.stats["cyc_a"]) is False
    assert engine._stat_needs_role_attribution(a) is True


def test_fumble_lost_rush_touchdown_is_not_a_rushing_td(engine):
    rows = [_play(1, play_type="run", rusher_player_name="I.Pacheco", rush_attempt=1, yards_gained=5.0,
                  touchdown=1, fumble_lost=1)]
    assert _board(engine, "fantasy_points", rows) == {"I.Pacheco": -1.5}  # 0.5 yds pts - 2 (fumble); no 6 for the TD
