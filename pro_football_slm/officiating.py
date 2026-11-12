"""nflverse officiating allowlists, cached loaders, joins and first-penalty reports."""
from collections import Counter
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request
from .exploration import clean

OFFICIAL_COLUMNS = tuple("game_id game_key official_id name position jersey_number season week season_type".split())
SCHEDULE_COLUMNS = tuple("game_id old_game_id gsis season week game_type home_team away_team referee gameday weekday gametime home_score away_score".split())
PENALTY_COLUMNS = tuple("game_id old_game_id play_id season week home_team away_team penalty penalty_player_id penalty_player_name penalty_type penalty_team penalty_yards down ydstogo desc".split())
URLS = {
    "officials": "https://github.com/nflverse/nflverse-data/releases/download/officials/officials.parquet",
    "schedules": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
}

def normalize(rows, columns, season):
    result = []
    for raw in rows:
        if clean(raw.get("season")) is not None and int(raw["season"]) != int(season):
            continue
        row = {k: clean(raw.get("official_name") if k == "name" and "official_name" in raw else raw.get(k)) for k in columns}
        row["season"] = int(season)
        for key in ("official_id", "game_id", "old_game_id", "gsis"):
            if row.get(key) is not None:
                row[key] = str(row[key]).removesuffix(".0")
        result.append(row)
    return result

def load_table(kind, season, cache_dir, ttl=86400, *, fixture_dir=None, max_bytes=64000000):
    """Read only approved columns; atomically cache sanitized season rows like PBP.

    Fixed nflverse URLs only. Fixtures never trigger a network request.
    """
    columns = {"officials": OFFICIAL_COLUMNS, "schedules": SCHEDULE_COLUMNS, "pbp": PENALTY_COLUMNS}[kind]
    if fixture_dir is not None:
        path = Path(fixture_dir) / f"{kind}_{int(season)}.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return normalize(payload.get("rows", []) if isinstance(payload, dict) else payload, columns, season)
    path = Path(cache_dir) / f"{kind}_{int(season)}.json"
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return normalize(json.loads(path.read_text(encoding="utf-8")), columns, season)
    url = f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{int(season)}.parquet" if kind == "pbp" else URLS[kind]
    opener = urllib.request.build_opener(_NflverseRedirect())
    with opener.open(url, timeout=30) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("nflverse asset exceeds size cap")
    if kind in ("officials", "pbp"):
        import pyarrow.parquet as pq
        stream = io.BytesIO(data)
        names = pq.read_schema(stream).names
        stream.seek(0)
        raw = pq.read_table(stream, columns=[c for c in columns if c in names] + (["official_name"] if "official_name" in names else [])).to_pylist()
    else:
        raw = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    rows = normalize(raw, columns, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(rows, output)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return rows

POSITIONS = {"r": "referee", "referee": "referee", "u": "umpire", "umpire": "umpire",
    "dj": "down judge", "hl": "down judge", "head linesman": "down judge", "down judge": "down judge",
    "lj": "line judge", "line judge": "line judge", "fj": "field judge", "field judge": "field judge",
    "sj": "side judge", "side judge": "side judge", "bj": "back judge", "back judge": "back judge"}

def person_name(value):
    return " ".join(str(value or "").lower().replace("ronald", "ron").split())

class _NflverseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "raw.githubusercontent.com"):
            raise ValueError("non-nflverse redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Officiating:
    def __init__(self, plays, officials, schedules, season):
        self.season = int(season)
        self.plays = plays
        self.officials = normalize(officials, OFFICIAL_COLUMNS, season)
        self.schedules = normalize(schedules, SCHEDULE_COLUMNS, season)
        self.games = {r["game_id"]: dict(r) for r in self.schedules if r.get("game_id")}
        for row in plays:
            game = self.games.setdefault(row["game_id"], {k: row.get(k) for k in SCHEDULE_COLUMNS})
            if row.get("old_game_id"):
                game["old_game_id"] = str(row["old_game_id"]).removesuffix(".0")
        known_chiefs = {}
        for o in self.officials:
            if POSITIONS.get(str(o.get("position") or "").lower()) == "referee" and o.get("official_id"):
                known_chiefs.setdefault(person_name(o.get("name")), {})[o["official_id"]] = o
        self.crews = {}
        self.conflicts = []
        for gid, game in self.games.items():
            keys = {str(v) for v in (gid, game.get("old_game_id"), game.get("gsis")) if v}
            crew = [{**o, "role": POSITIONS.get(str(o.get("position") or "").lower(), "alternate")}
                    for o in self.officials if o.get("game_id") in keys]
            chief = next((o for o in crew if o["role"] == "referee"), None)
            fallback = game.get("referee")
            if chief and fallback and person_name(chief.get("name")) != person_name(fallback):
                self.conflicts.append(gid)
            if chief is None and fallback:
                matches = known_chiefs.get(person_name(fallback), {})
                if len(matches) == 1:
                    chief = next(iter(matches.values()))
            # Fallback identities require a unique match to an officials-table person.
            self.crews[gid] = {"officials": crew, "chief": chief,
                "chiefName": chief.get("name") if chief else fallback,
                "source": "officials" if any(o["role"] == "referee" for o in crew) else "schedules" if fallback else None}

    def availability(self):
        covered = [g for g, c in self.crews.items() if c["officials"]]
        weeks = [int(self.games[g].get("week") or 0) for g in covered]
        return {"crew": "complete" if covered and len(covered) == len(self.games) else "partial" if covered else "unavailable",
            "through": f"{self.season} week {max(weeks)}" if weeks else None,
            "gamesCovered": len(covered), "gamesInSeason": len(self.games),
            "chiefGamesCovered": sum(bool(c["chiefName"]) for c in self.crews.values())}

    def penalties(self, *, player=None, team=None, type=None, crew=None, game=None):
        rows = []
        for p in self.plays:
            if not p.get("penalty_type") and p.get("penalty") not in (1, True, "1"):
                continue
            c = self.crews.get(p["game_id"], {})
            if player and player not in (p.get("penalty_player_id"), p.get("penalty_player_name")):
                continue
            if team and p.get("penalty_team") != team or type and p.get("penalty_type") != type:
                continue
            if game and p["game_id"] != game:
                continue
            if crew and crew not in (c.get("chiefName"), (c.get("chief") or {}).get("official_id")):
                continue
            description = p.get("desc") or p.get("description") or ""
            rows.append({**{k: p.get(k) for k in ("game_id", "play_id", "season", "week", "penalty_type", "penalty_team", "penalty_player_id", "penalty_player_name", "penalty_yards", "down", "ydstogo")},
                "description": description, "playerLabel": p.get("penalty_player_name") or "team foul, no player recorded",
                "recordingNote": "first penalty recorded", "enforcement": "unknown; recorded flags include possible declined or offsetting penalties",
                "crewChief": c.get("chiefName"), "crewChiefId": (c.get("chief") or {}).get("official_id")})
        return rows

    def profile(self, official_id):
        assignments = [g for g, c in self.crews.items() if any(o.get("official_id") == official_id for o in c["officials"])]
        games = [g for g, c in self.crews.items() if (c.get("chief") or {}).get("official_id") == official_id]
        # Rates use games with recorded PBP, including zero-penalty games.
        played = {p["game_id"] for p in self.plays}
        denominator = len(played.intersection(games))
        flags = self.penalties()
        selected = [r for r in flags if r["game_id"] in games]
        counts = Counter(r["penalty_type"] for r in selected)
        league = Counter(r["penalty_type"] for r in flags)
        return {"assignments": sorted(set(assignments + games)), "games": games, "gamesOfficiated": len(games), "gamesWithPbp": denominator,
            "rates": [{"type": t, "count": counts[t], "games": denominator,
                       "perGame": counts[t] / denominator if denominator else None,
                       "leagueCount": league[t], "leagueGames": len(played),
                       "leaguePerGame": league[t] / len(played) if played else None} for t in sorted(league, key=str)],
            "players": dict(Counter(r["penalty_player_id"] or "team foul, no player recorded" for r in selected)),
            "teams": dict(Counter(r["penalty_team"] for r in selected)),
            "wording": "games officiated by crew chief; no individual flag attribution"}

    def answer(self, kind, value=None, **filters):
        view = {"type": kind}
        if kind == "crew":
            view.update(self.crews.get(value, {"officials": [], "chief": None, "chiefName": None, "source": None}))
            view["message"] = "crew available" if view["officials"] else "crew not yet available"
            rows = view["officials"]
        elif kind == "ref":
            view.update(self.profile(value))
            rows = view["rates"]
        elif kind == "schedule":
            rows = [r for r in self.schedules if value in (r.get("home_team"), r.get("away_team"))]
            played = {p["game_id"] for p in self.plays}
            rows = [{**r, "playLogAvailable": r["game_id"] in played} for r in sorted(rows, key=lambda r: int(r.get("week") or 0))]
            regular = [r for r in rows if r.get("game_type") == "REG"]
            expected_games = 17 if self.season >= 2021 else 16
            view["byeWeeks"] = sorted(set(range(1, expected_games + 2)) - {int(r["week"]) for r in regular}) if len(regular) == expected_games else []
            view["byeAvailability"] = "available" if len(regular) == expected_games else "complete regular-season schedule required"
        else:
            rows = self.penalties(**filters)
        view["rows"] = rows
        view["availability"] = self.availability()
        columns = list(dict.fromkeys(key for row in rows for key in row))
        text = kind.upper() + "\n" + view.get("message", "") + "\n"
        text += " | ".join(columns) + "\n"
        text += "\n".join(" | ".join(str(row.get(key, "")) for key in columns) for row in rows)
        text += "\nGames covered: " + str(view["availability"]["gamesCovered"]) + "/" + str(view["availability"]["gamesInSeason"])
        text += "\nAvailable through: " + str(view["availability"]["through"] or "not yet available")
        text = text.encode("ascii", "backslashreplace").decode("ascii")
        return {"rows": rows, "view": view, "text": text, "availability": self.availability()}


def command(line, season, cache_dir, *, fixture_dir=None):
    """Run public slash commands without starting an interactive loop."""
    import argparse
    import shlex
    parser = argparse.ArgumentParser(prog="officiating", exit_on_error=False)
    parser.add_argument("kind", choices=("crew", "ref", "penalties"))
    parser.add_argument("value", nargs="?")
    for name in ("player", "team", "type", "crew"):
        parser.add_argument("--" + name)
    parser.add_argument("--season", type=int, default=season)
    tokens = shlex.split(line)
    tokens[0] = tokens[0].lstrip("/")
    args = parser.parse_args(tokens)
    graph = Officiating(load_table("pbp", args.season, cache_dir, fixture_dir=fixture_dir),
        load_table("officials", args.season, cache_dir, fixture_dir=fixture_dir),
        load_table("schedules", args.season, cache_dir, fixture_dir=fixture_dir), args.season)
    value = args.value
    if args.kind == "crew" and value is None:
        if len(graph.games) != 1:
            raise ValueError("specify a game id")
        value = next(iter(graph.games))
    if args.kind == "ref":
        ids = {o["official_id"] for o in graph.officials if o.get("official_id") and
               (o["official_id"] == value or person_name(o.get("name")) == person_name(value))}
        if len(ids) != 1:
            raise ValueError("referee name missing or ambiguous; use official id")
        value = ids.pop()
    return graph.answer(args.kind, value, **{k: getattr(args, k) for k in ("player", "team", "type", "crew")})
