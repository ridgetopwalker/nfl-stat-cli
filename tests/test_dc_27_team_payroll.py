"""Issue #27: coach pay must not be folded into the team cap total (synthetic contracts only)."""
import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import contracts as ct


def _rec(name, pos, ctype, apy, cap):
    return ct.ContractRecord(
        name=name, team="ZZZ", position=pos, contract_type=ctype, total_value_m=apy * 4, apy_m=apy,
        guaranteed_m=apy * 2, years=4, signed_year=2024, free_agent_year=2028, cap_hit_current_m=cap,
    )


@pytest.fixture
def synthetic_team(monkeypatch):
    records = [
        _rec("Alpha Player", "QB", "player", 10.0, 5.0),
        _rec("Bravo Player", "WR", "player", 20.0, 8.0),
        _rec("Charlie Coach", "HC", "coach", 25.0, 25.0),
        # A different team that must never leak into ZZZ totals
        ct.ContractRecord(
            name="Delta Player", team="YYY", position="QB", contract_type="player", total_value_m=400.0,
            apy_m=100.0, guaranteed_m=100.0, years=4, signed_year=2024, free_agent_year=2028, cap_hit_current_m=90.0,
        ),
    ]
    monkeypatch.setattr(ct, "NFL_CONTRACTS", records)
    return records


def test_payroll_view_total_excludes_coach_pay(synthetic_team):
    out = cli.strip_ansi(ct.render_team_payroll_view("ZZZ"))
    # Player APY 10+20 = 30.00 and cap 5+8 = 13.00; coach 25 would make 55.00 / 38.00
    assert "$30.00M" in out
    assert "$13.00M" in out
    assert "$55.00M" not in out
    assert "$38.00M" not in out


def test_payroll_view_does_not_call_a_partial_catalog_total_committed(synthetic_team):
    out = cli.strip_ansi(ct.render_team_payroll_view("ZZZ"))
    assert "TOTAL COMMITTED" not in out
    assert "CATALOGED PLAYER TOTAL" in out
    assert "partial" in out.lower()
    # Coach is still listed, and the view says it is separate
    assert "Charlie Coach" in out
    assert "not included" in out.lower()


def test_payroll_totals_helper_keeps_player_and_coach_apart(synthetic_team):
    totals = ct.compute_team_payroll_totals("zzz")
    assert totals["player_count"] == 2
    assert totals["coach_count"] == 1
    assert totals["player_apy_m"] == pytest.approx(30.0)
    assert totals["player_cap_hit_m"] == pytest.approx(13.0)
    assert totals["coach_apy_m"] == pytest.approx(25.0)


def test_payroll_view_coach_only_team_has_no_player_total(monkeypatch):
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [_rec("Charlie Coach", "HC", "coach", 25.0, 25.0)])
    out = cli.strip_ansi(ct.render_team_payroll_view("ZZZ"))
    assert "CATALOGED PLAYER TOTAL" not in out
    assert "TOTAL COMMITTED" not in out
    assert "Charlie Coach" in out
    assert "cataloged player contract" not in out


def test_payroll_view_still_lists_unknown_contract_types(monkeypatch):
    odd = _rec("Echo Exec", "GM", "executive", 4.0, 1.0)
    monkeypatch.setattr(ct, "NFL_CONTRACTS", [_rec("Alpha Player", "QB", "player", 10.0, 5.0), odd])
    out = cli.strip_ansi(ct.render_team_payroll_view("ZZZ"))
    assert "Echo Exec" in out
