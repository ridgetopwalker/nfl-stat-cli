"""Issue #27: coach pay must not be folded into the team cap total (synthetic contracts only)."""
import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import contracts as ct


def _rec(name, pos, ctype, apy, cap):
    return ct.ContractRecord(name, "ZZZ", pos, ctype, apy * 4, apy, apy * 2, 4, 2024, 2028, cap, "")


@pytest.fixture
def synthetic_team(monkeypatch):
    records = [
        _rec("Alpha Player", "QB", "player", 10.0, 5.0),
        _rec("Bravo Player", "WR", "player", 20.0, 8.0),
        _rec("Charlie Coach", "HC", "coach", 25.0, 25.0),
        # A different team that must never leak into ZZZ totals
        ct.ContractRecord("Delta Player", "YYY", "QB", "player", 400.0, 100.0, 100.0, 4, 2024, 2028, 90.0, ""),
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
