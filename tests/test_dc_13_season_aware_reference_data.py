"""Issue #13: embedded coaches, contracts and positions are season-keyed and never silently reused."""
import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import contracts as ct

SNAP_COACH = getattr(cli, "COACHING_SNAPSHOT_SEASON", 2025)
SNAP_CONTRACT = getattr(ct, "CONTRACT_SNAPSHOT_SEASON", 2024)


def _row(**kw):
    base = {"posteam": "KC", "defteam": "BAL", "game_id": "2025_01_BAL_KC", "season": 2025, "week": 1,
            "play_type": "run", "rush_attempt": 1, "desc": "run"}
    base.update(kw)
    return cli.NFLDataBridge(engine="offline")._normalize_row(base, 1)


# --- coaches --------------------------------------------------------------------------------------

def test_staff_is_keyed_by_season_and_flagged_unverified():
    assert set(cli.COACHING_STAFFS_BY_SEASON) == {SNAP_COACH}
    assert cli.COACHING_STAFF_STATUS[SNAP_COACH] == "unverified"
    assert cli.get_team_coaching_staff("KC", SNAP_COACH)["hc"] == "Andy Reid"
    assert cli.get_team_coaching_staff("KC")["hc"] == "Andy Reid"  # None = latest cataloged season


@pytest.mark.parametrize("season", [SNAP_COACH - 1, SNAP_COACH + 1, 2030, 0])
def test_uncataloged_season_never_reuses_the_table(season):
    assert cli.get_team_coaching_staff("KC", season) == {}
    assert cli.get_team_head_coach("KC", season) == "Unknown Coach"
    assert cli.find_coach_team("Andy Reid", season=season) is None
    note = cli.coaching_catalog_note(season)
    assert "not cataloged" in note and str(SNAP_COACH) in note


def test_unknown_team_is_not_answered_with_another_teams_staff():
    assert cli.get_team_coaching_staff("ZZZ", SNAP_COACH) == {}
    assert cli.get_team_coaching_staff("ZZZ") == {}
    assert cli.get_team_head_coach("ZZZ") == "Unknown Coach"


def test_find_coach_team_still_works_for_the_cataloged_season():
    assert cli.find_coach_team("Andy Reid", season=SNAP_COACH)[0] == "KC"
    assert cli.find_coach_team("Andy Reid")[0] == "KC"


def test_normalized_rows_carry_coaches_only_for_a_cataloged_season():
    cataloged = _row(season=SNAP_COACH)
    assert cataloged["head_coach"] == "Andy Reid"
    other = _row(season=SNAP_COACH + 1, game_id="x")
    assert other["head_coach"] == "Unknown Coach" and other["oc"] == "" and other["dc"] == ""
    assert other["head_coach"] != "Andy Reid"


def test_staff_view_says_when_the_season_is_not_cataloged():
    out = cli.strip_ansi(cli.render_coaching_staff_view("KC", season=SNAP_COACH + 1))
    assert "not cataloged" in out and "Andy Reid" not in out
    ok = cli.strip_ansi(cli.render_coaching_staff_view("KC", season=SNAP_COACH))
    assert "Andy Reid" in ok and "unverified" in ok
    assert "No coaching staff is cataloged" in cli.strip_ansi(cli.render_coaching_staff_view("ZZZ", season=SNAP_COACH))


# --- contracts ------------------------------------------------------------------------------------

def test_contracts_are_keyed_by_season_and_flagged_unverified():
    assert set(ct.CONTRACT_SEASONS) == {SNAP_CONTRACT}
    assert ct.CONTRACT_SEASONS[SNAP_CONTRACT]["status"] == "unverified"
    assert ct.find_contract_by_name("Patrick Mahomes", season=SNAP_CONTRACT).team == "KC"
    assert ct.find_contract_by_name("Patrick Mahomes").team == "KC"


@pytest.mark.parametrize("season", [SNAP_CONTRACT - 1, SNAP_CONTRACT + 1, 2030])
def test_uncataloged_contract_season_finds_nothing(season):
    assert ct.find_contract_by_name("Patrick Mahomes", season=season) is None
    assert not ct.contract_season_cataloged(season)
    note = ct.contract_catalog_note(season)
    assert "not cataloged" in note and str(season) in note and "nothing is shown" in note


def test_contract_dossier_states_status_and_is_not_pinned_to_a_hard_coded_year():
    out = cli.strip_ansi(ct.render_player_contract_view("Patrick Mahomes", season=SNAP_CONTRACT))
    assert "unverified static snapshot" in out
    assert "season(s) remaining)" not in out and f"after the {SNAP_CONTRACT} snapshot" in out
    gone = cli.strip_ansi(ct.render_player_contract_view("Patrick Mahomes", season=SNAP_CONTRACT + 1))
    assert "not cataloged" in gone and "Average Per Year" not in gone


def _mahomes_rows(season):
    return [_row(season=season, game_id=f"{season}_01_BAL_KC", player_name="Patrick Mahomes",
                 qb_name="Patrick Mahomes", play_type="pass", pass_attempt=0, rush_attempt=0)]


def test_contract_stats_are_not_attached_to_plays_of_an_uncataloged_season(tmp_path):
    eng = cli.StatEngine(storage_dir=tmp_path)
    in_snapshot = eng._compute_base_metrics(_mahomes_rows(SNAP_CONTRACT))
    assert in_snapshot["cap_hit"] > 0 and in_snapshot["apy"] > 0
    for season in (SNAP_CONTRACT + 1, SNAP_CONTRACT - 1):
        m = eng._compute_base_metrics(_mahomes_rows(season))
        assert m["cap_hit"] == 0 and m["apy"] == 0 and m["salary"] == 0 and m["contract_value_m"] == 0


def test_query_notes_explain_missing_reference_data():
    note = cli.strip_ansi(cli._reference_data_note("cap_hit", None, SNAP_CONTRACT + 1))
    assert "not cataloged" in note
    assert cli._reference_data_note("cap_hit", None, SNAP_CONTRACT) == ""
    assert "Coaching staffs are not cataloged" in cli.strip_ansi(cli._reference_data_note("epa_per_play", "coach", SNAP_COACH + 1))
    assert cli._reference_data_note("epa_per_play", "team", SNAP_COACH + 1) == ""


# --- team codes stay compatible with the #23 matching -----------------------------------------------

def test_team_codes_are_unchanged_and_canonical():
    assert {c.team for c in ct.NFL_CONTRACTS} == {cli.resolve_team_abbr(c.team) for c in ct.NFL_CONTRACTS}
    non_canonical = [t for t in cli.NFL_COACHING_STAFFS if cli.resolve_team_abbr(t) != t]
    assert non_canonical == ["LAR"]  # the pre-existing alias row; LA is the canonical key
    assert cli.NFL_COACHING_STAFFS["LA"]["hc"] == cli.NFL_COACHING_STAFFS["LAR"]["hc"]


# --- positions ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["K.Allen", "Keenan Allen", "D.Jackson", "Some Taylor"])
def test_a_shared_surname_is_not_resolved_to_the_registry_surname_entry(name):
    assert cli.get_player_position(name) is None


def test_full_names_initials_and_bare_surnames_still_resolve():
    assert cli.get_player_position("J.Allen") == "QB"
    assert cli.get_player_position("Josh Allen") == "QB"
    assert cli.get_player_position("P.Mahomes") == "QB"
    assert cli.get_player_position("X. Worthy") == "WR"
    assert cli.get_player_position("Mahomes") == "QB"


def test_play_rows_resolve_a_shared_surname_when_the_registry_cannot():
    plays = [{"receiver_player_name": "K.Allen", "receiver_position": "WR"}]
    assert cli.get_player_position("K.Allen", plays) == "WR"
    assert cli.get_player_position("K.Allen") is None


def test_the_season_catalog_points_at_the_single_embedded_table():
    assert cli.COACHING_STAFFS_BY_SEASON[SNAP_COACH] is cli.NFL_COACHING_STAFFS


def test_query_header_carries_the_note_for_an_uncataloged_season(tmp_path):
    engine = cli.StatEngine(storage_dir=tmp_path)
    plays = [_row(season=SNAP_COACH + 1, game_id="g1")]
    parsed = {"intent": "stat_query", "query": f"epa per play by coach {SNAP_COACH + 1}", "season": SNAP_COACH + 1,
              "stat_name": "epa_per_play", "group_by": "coach"}
    out = cli.strip_ansi(cli.handle_nl_query_result(parsed, engine, plays))
    assert "Coaching staffs are not cataloged" in out
    staff = cli.strip_ansi(cli.handle_nl_query_result(
        {"intent": "coaching_staff", "query": f"kc coach {SNAP_COACH + 1}", "season": SNAP_COACH + 1, "team": "KC"},
        engine, plays))
    assert "not cataloged" in staff and "Andy Reid" not in staff
