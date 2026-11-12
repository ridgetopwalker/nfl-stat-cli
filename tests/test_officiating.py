"""Synthetic officials and first-recorded penalty fixtures only."""
import io
import json
import pytest
from pro_football_slm.officiating import (Officiating, load_table, normalize, command,
    OFFICIAL_COLUMNS, SCHEDULE_COLUMNS)

G = "2024_01_BAL_KC"

def fixture(season=2024, week=1, game=G):
    plays = [dict(game_id=game, old_game_id="synthetic-old", season=season, week=week,
        play_id=1, penalty=1, penalty_type="False Start", penalty_player_id="dummy-player",
        penalty_player_name="E.Player", penalty_team="KC", penalty_yards=0,
        desc="Synthetic PENALTY declined; PENALTY offsetting")]
    officials = [dict(game_id="synthetic-old", official_id="dummy-chief", official_name="Example Chief",
        position="Referee", jersey_number=99, season=season),
        dict(game_id="synthetic-old", official_id="dummy-dj", name="Example Judge", position="Head Linesman", season=season),
        dict(game_id="synthetic-old", official_id="dummy-alt", name="Example Alternate", position="AL", season=season)]
    schedules = [dict(game_id=game, season=season, week=week, referee="Different Chief", home_team="KC", away_team="BAL")]
    return plays, officials, schedules

def test_officials_win_join_and_positions():
    graph = Officiating(*fixture(), 2024)
    crew = graph.answer("crew", G)
    assert graph.conflicts == [G]
    assert crew["view"]["chiefName"] == "Example Chief"
    assert crew["rows"][0]["official_id"] == "dummy-chief"
    assert [r["role"] for r in crew["rows"]] == ["referee", "down judge", "alternate"]
    assert "flag attribution" in graph.profile("dummy-chief")["wording"]

def test_penalties_filters_and_conservative_enforcement():
    plays, officials, schedules = fixture()
    plays += [dict(plays[0], play_id=2, penalty_player_id=None, penalty_player_name=None)]
    graph = Officiating(plays, officials, schedules, 2024)
    flags = graph.penalties(player="dummy-player", team="KC", type="False Start", crew="dummy-chief")
    assert len(flags) == 1 and flags[0]["penalty_yards"] == 0
    assert flags[0]["recordingNote"] == "first penalty recorded"
    assert "unknown" in flags[0]["enforcement"]
    assert graph.penalties()[1]["playerLabel"] == "team foul, no player recorded"
    assert graph.penalties(crew="Different Chief") == []

def test_three_games_2024_week1_week6_gap():
    old = Officiating(*fixture(), 2024)
    plays, officials, schedules = fixture(2026, 1, "2026_01_BAL_KC")
    future = "2026_06_BAL_KC"
    schedules.append(dict(game_id=future, season=2026, week=6, home_team="KC", away_team="BAL"))
    graph = Officiating(plays, officials, schedules, 2026)
    gap = graph.answer("crew", future)
    assert old.availability()["gamesCovered"] == 1
    assert gap["view"]["message"] == "crew not yet available"
    assert gap["availability"] == dict(crew="partial", through="2026 week 1", gamesCovered=1, gamesInSeason=2, chiefGamesCovered=1)
    assert len(graph.answer("schedule", "KC")["rows"]) == 2

def test_synthetic_282_of_285_agreement_three_conflicts():
    officials = [dict(game_id=str(i), official_id=f"dummy-{i}", name=f"Example {i}", position="R", season=2024) for i in range(285)]
    schedules = [dict(game_id=str(i), referee=f"Example {i}" if i < 282 else "Conflict", season=2024) for i in range(285)]
    graph = Officiating([], officials, schedules, 2024)
    assert len(graph.conflicts) == 3
    assert (len(graph.games) - len(graph.conflicts)) / len(graph.games) == 282 / 285

def test_rates_include_zero_flag_games_and_league_denominator():
    plays, officials, schedules = fixture()
    plays.append(dict(game_id="2024_02_BAL_KC", season=2024, penalty=0))
    schedules.append(dict(game_id="2024_02_BAL_KC", season=2024, week=2))
    graph = Officiating(plays, officials, schedules, 2024)
    rate = graph.profile("dummy-chief")["rates"][0]
    assert rate["games"] == 1 and rate["leagueGames"] == 2
    assert rate["perGame"] == 1 and rate["leaguePerGame"] == .5

def test_allowlists_exclude_betting_and_roster_private_fields(tmp_path):
    excluded = dict(home_moneyline=1, away_moneyline=1, spread_line=1, total_line=1, odds=1, headshot_url="excluded", birth_date="excluded")
    for kind, columns in (("officials", OFFICIAL_COLUMNS), ("schedules", SCHEDULE_COLUMNS)):
        (tmp_path / f"{kind}_2024.json").write_text(json.dumps([dict(season=2024, **excluded)]))
        row = load_table(kind, 2024, tmp_path, fixture_dir=tmp_path)[0]
        assert set(row) <= set(columns)
        assert not set(row).intersection(excluded)
    assert load_table("officials", 2026, tmp_path, fixture_dir=tmp_path) == []

def test_public_commands_return_rows_and_ascii(tmp_path):
    for kind, rows in zip(("pbp", "officials", "schedules"), fixture()):
        (tmp_path / f"{kind}_2024.json").write_text(json.dumps(rows))
    for line in (f"/crew {G}", '/ref "Example Chief"', '/penalties --player dummy-player --team KC --type "False Start" --crew dummy-chief --season 2024'):
        answer = command(line, 2024, tmp_path, fixture_dir=tmp_path)
        assert answer["rows"]
        assert answer["text"].isascii()

def test_loader_caches_only_allowlisted_columns(tmp_path, monkeypatch):
    import pro_football_slm.officiating as module
    class Opener:
        calls = 0
        def open(self, url, timeout):
            self.calls += 1
            return io.BytesIO(b"game_id,season,week,home_team,away_team,spread_line\n2024_01_BAL_KC,2024,1,KC,BAL,123\n")
    opener = Opener()
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: opener)
    first = load_table("schedules", 2024, tmp_path)
    assert first == load_table("schedules", 2024, tmp_path)
    assert opener.calls == 1
    assert "spread_line" not in (tmp_path / "schedules_2024.json").read_text()


def test_schedule_fallback_keeps_official_id_and_rates():
    plays, officials, schedules = fixture()
    next_game = "2024_02_BAL_KC"
    schedules.append(dict(game_id=next_game, season=2024, week=2, referee="Example Chief"))
    plays.append(dict(game_id=next_game, penalty=0))
    graph = Officiating(plays, officials, schedules, 2024)
    assert graph.crews[next_game]["source"] == "schedules"
    assert graph.crews[next_game]["officials"] == []
    assert graph.crews[next_game]["chief"]["official_id"] == "dummy-chief"
    assert graph.profile("dummy-chief")["gamesOfficiated"] == 2
    assert graph.profile("dummy-chief")["rates"][0]["perGame"] == .5

def test_byes_require_complete_regular_schedule():
    schedules = [dict(game_id=f"2026_{w:02d}_BAL_KC", season=2026, week=w, game_type="REG", home_team="KC", away_team="BAL") for w in range(1,19) if w != 6]
    answer = Officiating([], [], schedules, 2026).answer("schedule", "KC")
    assert answer["view"]["byeWeeks"] == [6]
    assert all(not row["playLogAvailable"] for row in answer["rows"])
    assert Officiating([], [], schedules[:1], 2026).answer("schedule", "KC")["view"]["byeWeeks"] == []

def test_parquet_official_name_alias_and_size_limit(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pro_football_slm.officiating as module
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([dict(game_id="dummy-game", official_id="dummy-id", official_name="Example Chief", position="R", season=2024, spread_line=999)]), buffer)
    class Opener:
        def open(self, url, timeout):
            return io.BytesIO(buffer.getvalue())
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: Opener())
    row = load_table("officials", 2024, tmp_path)[0]
    assert row["name"] == "Example Chief" and "spread_line" not in row
    with pytest.raises(ValueError, match="size cap"):
        load_table("officials", 2026, tmp_path, max_bytes=1)

def test_cli_parser_registers_officiating_commands():
    import pro_football_slm as cli
    for tokens in (("crew", G), ("ref", "Example Chief"), ("penalties", "--player", "dummy-player", "--type", "False Start", "--crew", "dummy-chief", "--season", "2026")):
        args = cli.build_arg_parser().parse_args(tokens)
        assert args.command == tokens[0]


def test_non_chief_official_has_assignments_only():
    graph = Officiating(*fixture(), 2024)
    answer = graph.answer("ref", "dummy-dj")
    assert answer["view"]["rates"] == []
    assert answer["view"]["gamesOfficiated"] == 0
    assert answer["rows"] == [{"game_id": G}]
    assert G in answer["text"]


@pytest.mark.parametrize("ending", ["declined", "offsetting"])
def test_game_log_and_cli_preserve_raw_penalty_fields(tmp_path, ending):
    from pro_football_slm import NFLDataBridge
    plays, officials, schedules = fixture()
    plays[0].update(penalty_team=None, penalty_player_name=None, penalty_player_id=None,
                    posteam="KC", defteam="BAL",
                    desc=f"Synthetic completion for 12 yards. PENALTY on KC-E.Player, Holding {ending}")
    normalized = NFLDataBridge(cache_dir=tmp_path / "cache", engine="offline").normalize_game_log(plays)
    rows = Officiating(normalized, officials, schedules, 2024).penalties()
    for kind, data in (("pbp", plays), ("officials", officials), ("schedules", schedules)):
        (tmp_path / f"{kind}_2024.json").write_text(json.dumps(data), encoding="utf-8")
    public = command("/penalties --season 2024", 2024, tmp_path, fixture_dir=tmp_path)
    for key in ("penalty_yards", "penalty_team", "penalty_player_id", "penalty_player_name", "penalty_type"):
        assert rows[0][key] == plays[0][key]
        assert public["rows"][0][key] == plays[0][key]


def test_assignment_only_profile_copy():
    graph = Officiating(*fixture(), 2024)
    profile = graph.profile("dummy-dj")
    assert profile["assignmentCount"] == 1
    assert profile["profileKind"] == "assignments"
    assert "crew chief" not in profile["wording"]
    assert profile["rates"] == []
    assert "Assignment count: 1" in graph.answer("ref", "dummy-dj")["text"]
