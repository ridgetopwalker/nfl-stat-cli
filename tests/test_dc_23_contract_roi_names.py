"""Issue #23: contract ROI must match play-by-play names ("Q.Testarro") to full contract names (synthetic data)."""
import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import contracts as ct


def _contract(name, team="ZZZ", pos="QB", ctype="player", apy=20.0):
    return ct.ContractRecord(
        name=name, team=team, position=pos, contract_type=ctype, total_value_m=apy * 4, apy_m=apy,
        guaranteed_m=apy * 2, years=4, signed_year=2024, free_agent_year=2028, cap_hit_current_m=5.0,
    )


def _play(qb="", rec="", rush="", epa=0.5, posteam="ZZZ", week=1, yards=10.0, game="2025_01_YYY_ZZZ"):
    is_pass = bool(qb)
    return {
        "season": 2025, "week": week, "game_id": game, "posteam": posteam, "defteam": "YYY",
        "qb_name": qb, "receiver_player_name": rec, "rusher_player_name": rush,
        "play_type": "pass" if is_pass else "run", "pass_attempt": 1 if is_pass else 0,
        "rush_attempt": 0 if is_pass else 1, "complete_pass": 1 if is_pass else 0, "sack": 0,
        "yards_gained": yards, "epa": epa, "touchdown": 0, "interception": 0,
    }


def test_abbreviated_play_name_matches_full_contract_name():
    c = _contract("Quincy Testarro")
    plays = [_play(qb="Q.Testarro", epa=0.5), _play(qb="Q.Testarro", epa=0.3), _play(qb="Q.Testarro", epa=-0.1)]
    eff = ct.calculate_contract_performance_efficiency(c, plays, 2025)
    assert eff["total_epa"] == pytest.approx(0.7)
    assert eff["epa_matched_plays"] == 3
    assert eff["cost_per_epa_k"] == pytest.approx(round(20.0 * 1000.0 / 0.7, 1))


def test_exact_full_name_in_plays_still_matches():
    c = _contract("Quincy Testarro")
    eff = ct.calculate_contract_performance_efficiency(c, [_play(qb="Quincy Testarro", epa=0.4)], 2025)
    assert eff["epa_matched_plays"] == 1
    assert eff["total_epa"] == pytest.approx(0.4)


@pytest.mark.parametrize("contract_name,pbp_name", [
    ("Zed St. Marlow", "Z.St. Marlow"),      # surname particle
    ("C.J. Quill", "C.Quill"),               # two-initial first name
    ("Sam Rivers III", "S.Rivers III"),      # generational suffix
    ("Jo'Mar Vale", "J.Vale"),               # apostrophe in first name
])
def test_name_format_variants_match(contract_name, pbp_name):
    c = _contract(contract_name, pos="WR")
    eff = ct.calculate_contract_performance_efficiency(c, [_play(qb="X.Other", rec=pbp_name, epa=0.5)], 2025)
    assert eff["epa_matched_plays"] == 1
    assert eff["total_epa"] == pytest.approx(0.5)


def test_different_player_with_same_surname_is_not_credited():
    c = _contract("Quincy Testarro")
    plays = [_play(qb="R.Testarro", epa=0.9), _play(qb="Q.Testarro", epa=0.1)]
    eff = ct.calculate_contract_performance_efficiency(c, plays, 2025)
    assert eff["epa_matched_plays"] == 1
    assert eff["total_epa"] == pytest.approx(0.1)


def test_unmatched_name_reports_zero_matched_plays():
    c = _contract("Quincy Testarro")
    eff = ct.calculate_contract_performance_efficiency(c, [_play(qb="N.Nobody", epa=0.5)], 2025)
    assert eff["epa_matched_plays"] == 0
    assert eff["total_epa"] == 0


def test_shared_name_key_is_split_by_team(monkeypatch):
    a = _contract("Jon Harlow", team="ZZZ", pos="HC", ctype="coach")
    b = _contract("Jim Harlow", team="YYY", pos="HC", ctype="coach")
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [a, b])
    plays = [_play(rush="J.Harlow", epa=0.2, posteam="ZZZ"), _play(rush="J.Harlow", epa=0.7, posteam="YYY")]
    assert ct.calculate_contract_performance_efficiency(a, plays, 2025)["total_epa"] == pytest.approx(0.2)
    assert ct.calculate_contract_performance_efficiency(b, plays, 2025)["total_epa"] == pytest.approx(0.7)


def test_blank_or_non_numeric_epa_does_not_crash():
    c = _contract("Quincy Testarro")
    plays = [_play(qb="Q.Testarro", epa=""), _play(qb="Q.Testarro", epa=None), _play(qb="Q.Testarro", epa=0.2)]
    eff = ct.calculate_contract_performance_efficiency(c, plays, 2025)
    assert eff["epa_matched_plays"] == 3
    assert eff["total_epa"] == pytest.approx(0.2)


def test_dossier_shows_epa_when_names_match(monkeypatch):
    c = _contract("Quincy Testarro")
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [c])
    out = cli.strip_ansi(ct.render_player_contract_view("Quincy Testarro", plays=[_play(qb="Q.Testarro", epa=0.8)], season=2025))
    assert "+0.8 EPA" in out
    assert "EPA unavailable" not in out


def test_dossier_warns_instead_of_silently_omitting_when_no_name_matches(monkeypatch):
    c = _contract("Quincy Testarro")
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [c])
    out = cli.strip_ansi(ct.render_player_contract_view("Quincy Testarro", plays=[_play(qb="N.Nobody", epa=0.8)], season=2025))
    assert "EPA unavailable" in out
