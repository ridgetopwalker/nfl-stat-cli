"""Allowlisted engine foundation for complete game logs and stable player links."""

import math
from collections.abc import Mapping


PLAYER_ID_COLUMNS = tuple("""
passer_player_id rusher_player_id receiver_player_id player_id
kicker_player_id punter_player_id kickoff_returner_player_id punt_returner_player_id
blocked_player_id penalty_player_id interception_player_id
sack_player_id sack_player_1_id sack_player_2_id
solo_tackle_1_player_id solo_tackle_2_player_id
assist_tackle_1_player_id assist_tackle_2_player_id assist_tackle_3_player_id assist_tackle_4_player_id
tackle_with_assist_1_player_id tackle_with_assist_2_player_id
qb_hit_1_player_id qb_hit_2_player_id pass_defense_1_player_id pass_defense_2_player_id
forced_fumble_player_1_player_id forced_fumble_player_2_player_id
fumbled_1_player_id fumbled_2_player_id fumble_recovery_1_player_id fumble_recovery_2_player_id
lateral_receiver_player_id lateral_rusher_player_id lateral_returner_player_id
lateral_recovery_player_id
""".split())

FACT_COLUMNS = tuple("""
drive fixed_drive old_game_id order_sequence game_seconds_remaining time
kick_distance return_yards field_goal_result extra_point_result
field_goal_attempt extra_point_attempt kickoff_attempt punt_attempt
punt_blocked punt_inside_twenty punt_fair_catch punt_in_endzone punt_out_of_bounds punt_downed
kickoff_in_endzone kickoff_inside_twenty kickoff_fair_catch kickoff_out_of_bounds
kickoff_downed touchback lateral_return lateral_reception
lateral_rush lateral_recovery return_touchdown
""".split())
PLAYER_NAME_COLUMNS = tuple(c.replace("_id", "_name") for c in PLAYER_ID_COLUMNS if c != "player_id")
EXPLORATION_COLUMNS = PLAYER_ID_COLUMNS + PLAYER_NAME_COLUMNS + FACT_COLUMNS
ROSTER_COLUMNS = ("season", "team", "full_name", "position", "depth_chart_position", "gsis_id", "jersey_number")


def clean(value):
    """Convert absent nflverse scalars to None, preserving zero and string ids."""
    if value is None or str(value).strip().lower() in ("", "nan", "none", "<na>", "na"):
        return None
    return value.strip() if isinstance(value, str) else value


def index_rosters(rosters):
    index = {}
    for row in rosters:
        index.setdefault(row["gsis_id"], []).append(row)
    return index


def player_links(row, rosters=()):
    """One link per recorded role, keyed solely by GSIS identity."""
    links = []
    for column in PLAYER_ID_COLUMNS:
        gsis_id = clean(row.get(column))
        if gsis_id is None:
            continue
        gsis_id = str(gsis_id)
        roster_rows = rosters.get(gsis_id, ()) if isinstance(rosters, Mapping) else rosters
        candidates = [r for r in roster_rows if r.get("gsis_id") == gsis_id
                      and str(r.get("season")) == str(row.get("season"))]
        # Traded players can have several roster rows. Identity/name are shared.
        roster = next((r for r in candidates if r.get("team") == row.get("posteam")),
                      candidates[0] if candidates else {})
        name_column = column.replace("_id", "_name")
        links.append({"ref": f"player:{gsis_id}", "gsis_id": gsis_id,
                      "role": column, "name": roster.get("full_name") or clean(row.get(name_column)) or gsis_id})
    return links


def row_refs(row, rosters=()):
    game = clean(row.get("game_id"))
    play = clean(row.get("play_id"))
    links = player_links(row, rosters)
    play_ref = f"play:{game}:{play}" if game is not None and play is not None else None
    game_ref = f"game:{game}" if game is not None else None
    return {"play_ref": row.get("play_ref", play_ref), "game_ref": row.get("game_ref", game_ref),
            "player_refs": list(dict.fromkeys(link["ref"] for link in links)), "players": links}


def extend_row(normalized, raw):
    for column in EXPLORATION_COLUMNS:
        value = clean(raw.get(column))
        if column in PLAYER_NAME_COLUMNS and value is None:
            continue
        if column in PLAYER_ID_COLUMNS and value is not None:
            value = str(value)
        if column in FACT_COLUMNS and column not in ("time", "old_game_id", "field_goal_result", "extra_point_result"):
            value = _number(value)
        normalized[column] = value
    normalized["play_kind"] = clean(raw.get("play_type")) or "untyped"
    for column in ("kick_distance", "return_yards", "touchback", "punt_blocked"):
        normalized[column + "_known"] = int(_number(normalized.get(column)) is not None)
    normalized["punt_net_yards"] = None
    if all(normalized[column + "_known"] for column in ("kick_distance", "return_yards", "touchback")):
        normalized["punt_net_yards"] = (float(normalized["kick_distance"]) - float(normalized["return_yards"])
                                        - 20 * float(normalized["touchback"]))
    normalized.update(row_refs(normalized))
    if clean(raw.get("play_id")) is None:
        normalized["play_ref"] = None
    if clean(raw.get("game_id")) is None:
        normalized["play_ref"] = None
        normalized["game_ref"] = None
    return normalized


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def order_game_log(rows):
    """Use numeric play_id within each game, with stable source order for ties.

    play_id is the source event sequence. order_sequence is retained as metadata.
    Missing play ids follow identified events in their original input order.
    Clock corrections and untimed events make remaining-time sorting unsuitable.
    """
    return sorted(rows, key=lambda row: (str(row.get("game_id") or ""),
                                        _number(row.get("play_id")) is None,
                                        _number(row.get("play_id")) or 0))


def normalize_rosters(rows):
    """Keep only approved attributes. Preserve team-season rows for traded players."""
    result = []
    for raw in rows:
        row = {column: clean(raw.get(column)) for column in ROSTER_COLUMNS}
        if row["gsis_id"]:
            row["gsis_id"] = str(row["gsis_id"])
            season = _number(row["season"])
            row["season"] = int(season) if season is not None else None
            result.append(row)
    return result
