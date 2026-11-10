"""Issue #50: an abbreviated ROI name that is unique in a season matches across teams; shared keys stay team-gated."""
import pytest

import pro_football_slm as cli
from pro_football_slm import contracts as ct


def _contract(name, team="ZZZ", pos="WR"):
    return ct.ContractRecord(
        name=name, team=team, position=pos, contract_type="player", total_value_m=80.0, apy_m=20.0,
        guaranteed_m=40.0, years=4, signed_year=2024, free_agent_year=2028, cap_hit_current_m=5.0,
    )


def _play(rec, team, epa=0.5, season=2025, week=1, pid=None):
    row = {
        "season": season, "week": week, "game_id": f"{season}_{week:02d}_YYY_{team or 'NA'}", "posteam": team,
        "defteam": "YYY", "qb_name": "", "receiver_player_name": rec, "rusher_player_name": "",
        "play_type": "pass", "pass_attempt": 1, "rush_attempt": 0, "complete_pass": 1, "sack": 0,
        "yards_gained": 10.0, "epa": epa, "touchdown": 0, "interception": 0,
    }
    if pid is not None:
        row["receiver_player_id"] = pid
    return row


def _eff(contract, plays, season=2025):
    return ct.calculate_contract_performance_efficiency(contract, plays, season)


# --- unique key: matches on any team ----------------------------------------------------------------

def test_traded_player_with_a_player_id_gets_plays_from_both_teams_counted():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "XXX", epa=0.4, week=1, pid="id-1"), _play("J.Smith", "XXX", epa=0.2, week=2, pid="id-1"),
             _play("J.Smith", "ZZZ", epa=0.3, week=8, pid="id-1")]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 3
    assert eff["total_epa"] == pytest.approx(0.9)
    assert eff["epa_ambiguous_key"] is False and eff["epa_team_gated_plays"] == 0


def test_a_key_held_by_one_player_on_one_other_team_still_matches_the_contract():
    c = _contract("Jordan Smith", team="ZZZ")  # contract table says ZZZ; every play is under another code
    plays = [_play("J.Smith", "XXX", epa=0.4), _play("J.Smith", "XXX", epa=0.1)]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 2 and eff["total_epa"] == pytest.approx(0.5)


def test_team_code_aliases_are_one_player_not_two():
    c = _contract("Jordan Smith", team="XXX")
    plays = [_play("J.Smith", "LAR", epa=0.4), _play("J.Smith", "LA", epa=0.2)]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 2 and not eff["epa_ambiguous_key"]


def test_rows_with_neither_an_id_nor_a_team_do_not_make_a_key_ambiguous():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "XXX", epa=0.4), _play("J.Smith", None, epa=0.2)]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 2 and not eff["epa_ambiguous_key"]


def test_the_dossier_shows_a_traded_players_total_without_any_warning(monkeypatch):
    c = _contract("Jordan Smith", team="ZZZ")
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [c])
    plays = [_play("J.Smith", "XXX", epa=0.6, pid="id-1"), _play("J.Smith", "ZZZ", epa=0.2, week=9, pid="id-1")]
    out = cli.strip_ansi(ct.render_player_contract_view("Jordan Smith", plays=plays, season=2025))
    assert "+0.8 EPA" in out
    assert "EPA unavailable" not in out and "may be partial" not in out


# --- ambiguous key: still team-gated -----------------------------------------------------------------

def test_two_players_sharing_a_key_by_id_stay_team_gated():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "ZZZ", epa=0.3, pid="id-1"), _play("J.Smith", "XXX", epa=0.9, pid="id-2")]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 1 and eff["total_epa"] == pytest.approx(0.3)
    assert eff["epa_ambiguous_key"] is True and eff["epa_team_gated_plays"] == 1


def test_two_players_sharing_a_key_without_ids_stay_team_gated():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "ZZZ", epa=0.3), _play("J.Smith", "XXX", epa=0.9)]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 1 and eff["total_epa"] == pytest.approx(0.3)
    assert eff["epa_ambiguous_key"] is True and eff["epa_team_gated_plays"] == 1


def test_the_dossier_keeps_the_warning_for_an_ambiguous_key(monkeypatch):
    c = _contract("Jordan Smith", team="ZZZ")
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [c])
    plays = [_play("J.Smith", "ZZZ", epa=0.3, pid="id-1"), _play("J.Smith", "XXX", epa=0.9, pid="id-2")]
    out = cli.strip_ansi(ct.render_player_contract_view("Jordan Smith", plays=plays, season=2025))
    assert "ROI may be partial (2025)" in out and "1 on other teams left out" in out and "+0.3 EPA" in out
    only_other = [_play("J.Smith", "XXX", epa=0.9, pid="id-2"), _play("J.Smith", "WWW", epa=0.1, pid="id-3")]
    out = cli.strip_ansi(ct.render_player_contract_view("Jordan Smith", plays=only_other, season=2025))
    assert "EPA unavailable (2025)" in out and "ROI may be partial" in out


def test_a_matching_team_still_counts_for_an_ambiguous_key_when_the_play_has_no_team():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "ZZZ", epa=0.3, pid="id-1"), _play("J.Smith", "XXX", epa=0.9, pid="id-2"),
             _play("J.Smith", None, epa=0.1)]
    assert _eff(c, plays)["epa_matched_plays"] == 2


# --- uniqueness is decided per season -----------------------------------------------------------------

def test_a_key_ambiguous_in_one_season_is_unique_in_the_next():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [
        _play("J.Smith", "ZZZ", epa=0.3, season=2024, pid="id-1"), _play("J.Smith", "XXX", epa=0.9, season=2024, pid="id-2"),
        _play("J.Smith", "XXX", epa=0.5, season=2025, pid="id-1"), _play("J.Smith", "ZZZ", epa=0.2, season=2025, pid="id-1"),
    ]
    assert _eff(c, plays, 2025)["epa_matched_plays"] == 3          # 2024 ZZZ, 2025 XXX and 2025 ZZZ; 2024 XXX is gated
    assert _eff(c, [p for p in plays if p["season"] == 2025])["epa_matched_plays"] == 2
    assert _eff(c, [p for p in plays if p["season"] == 2024], 2024)["epa_matched_plays"] == 1


def test_ids_on_the_other_fields_identify_players_too():
    c = _contract("Jordan Smith", team="ZZZ", pos="RB")
    rows = []
    for team, pid, week in (("XXX", "r-1", 1), ("ZZZ", "r-1", 9)):
        r = _play("", team, week=week)
        r.update(rusher_player_name="J.Smith", rusher_player_id=pid, rush_attempt=1, pass_attempt=0)
        rows.append(r)
    assert _eff(c, rows)["epa_matched_plays"] == 2


# --- review follow-ups ----------------------------------------------------------------------------------

def test_a_row_naming_the_player_in_several_fields_is_gated_once_and_not_when_a_later_field_accepts_it():
    c = _contract("Jordan Smith", team="ZZZ", pos="QB")
    shared = _play("J.Smith", "XXX", epa=0.9, pid="id-2")
    shared.update(qb_name="J.Smith")                      # two fields carry the shared key on the other team
    own = _play("J.Smith", "ZZZ", epa=0.3, pid="id-1")
    eff = _eff(c, [own, shared])
    assert eff["epa_team_gated_plays"] == 1 and eff["epa_matched_plays"] == 1
    later_exact = _play("J.Smith", "XXX", epa=0.5, pid="id-2")
    later_exact.update(rusher_player_name="Jordan Smith")  # an exact full-name field accepts the row on any team
    eff = _eff(c, [own, shared, later_exact])
    assert eff["epa_matched_plays"] == 2 and eff["epa_team_gated_plays"] == 1


def test_rows_with_and_without_ids_for_the_same_player_and_team_are_one_player():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "XXX", epa=0.4, pid="id-1"), _play("J.Smith", "XXX", epa=0.2),
             _play("J.Smith", "ZZZ", epa=0.3, pid="id-1")]
    eff = _eff(c, plays)
    assert eff["epa_matched_plays"] == 3 and not eff["epa_ambiguous_key"]


def test_an_id_less_row_on_a_team_no_id_row_covers_still_counts_as_another_player():
    c = _contract("Jordan Smith", team="ZZZ")
    plays = [_play("J.Smith", "ZZZ", epa=0.3, pid="id-1"), _play("J.Smith", "XXX", epa=0.9)]
    eff = _eff(c, plays)
    assert eff["epa_ambiguous_key"] is True and eff["epa_matched_plays"] == 1 and eff["epa_team_gated_plays"] == 1
