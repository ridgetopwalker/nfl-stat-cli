"""
Pro Football SLM Player & Coach Contract Analytics Engine.
Provides contract data compiled from public reports (approximate):
- Player contracts across all positions (Quarterbacks, Skill Positions, Linemen, Defense).
- Head Coach contracts, salaries, and contract expiration horizons.
- Team payroll distributions, cap hits, guaranteed allocations, and free agency classes.
- Value & ROI analytics: Cost per EPA ($M/EPA), Cost per Fantasy Point, and Cap Efficiency.
"""

from __future__ import annotations

import difflib
import math
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ContractRecord:
    name: str
    team: str
    position: str
    contract_type: str            # 'player' or 'coach'
    total_value_m: float          # In Millions ($M)
    apy_m: float                  # Average Per Year in Millions ($M)
    guaranteed_m: float           # Total Guaranteed Money in Millions ($M)
    years: int                    # Contract Duration in Years
    signed_year: int              # Year Signed
    free_agent_year: int          # Free Agency / Expiration Year
    cap_hit_current_m: float      # Current Season Cap Hit in Millions ($M)
    notes: str = ""


# Contract figures compiled from public reports (approximate). Embedded contract rows. No upstream source, retrieval
# date or as-of date is recorded for them, so they are catalogued below as one unverified snapshot
# (see CONTRACT_SEASONS) rather than as "current" data.
NFL_CONTRACTS: List[ContractRecord] = [
    # ------------------ QUARTERBACKS ------------------
    ContractRecord("Patrick Mahomes", "KC", "QB", "player", 450.0, 45.0, 141.5, 10, 2020, 2032, 37.0, "10-yr extension, rolling guarantees & roster bonus restructuring"),
    ContractRecord("Dak Prescott", "DAL", "QB", "player", 240.0, 60.0, 231.0, 4, 2024, 2029, 44.0, "Highest APY in NFL history ($60M), no-trade & no-tag clauses"),
    ContractRecord("Joe Burrow", "CIN", "QB", "player", 275.0, 55.0, 219.0, 5, 2023, 2030, 29.7, "5-yr extension, $146.5M fully guaranteed at signing"),
    ContractRecord("Jordan Love", "GB", "QB", "player", 220.0, 55.0, 160.3, 4, 2024, 2029, 20.8, "4-yr extension tied for record $55M APY, $75M signing bonus"),
    ContractRecord("Trevor Lawrence", "JAX", "QB", "player", 275.0, 55.0, 200.0, 5, 2024, 2031, 15.0, "5-yr extension, $142M fully guaranteed at signing"),
    ContractRecord("Tua Tagovailoa", "MIA", "QB", "player", 212.4, 53.1, 167.1, 4, 2024, 2029, 13.6, "4-yr extension, $93.1M fully guaranteed at signing"),
    ContractRecord("Jared Goff", "DET", "QB", "player", 212.0, 53.0, 170.0, 4, 2024, 2029, 27.2, "4-yr extension with $73M signing bonus"),
    ContractRecord("Justin Herbert", "LAC", "QB", "player", 262.5, 52.5, 218.7, 5, 2023, 2030, 19.3, "5-yr extension, $133.7M fully guaranteed at signing"),
    ContractRecord("Lamar Jackson", "BAL", "QB", "player", 260.0, 52.0, 185.0, 5, 2023, 2028, 32.4, "5-yr extension, 2-time MVP, $135M fully guaranteed"),
    ContractRecord("Jalen Hurts", "PHI", "QB", "player", 255.0, 51.0, 179.3, 5, 2023, 2029, 13.6, "5-yr extension with first no-trade clause in Eagles history"),
    ContractRecord("Kyler Murray", "ARI", "QB", "player", 230.5, 46.1, 160.0, 5, 2022, 2029, 49.1, "5-yr extension, $103.3M fully guaranteed at signing"),
    ContractRecord("Deshaun Watson", "CLE", "QB", "player", 230.0, 46.0, 230.0, 5, 2022, 2027, 63.8, "5-yr fully guaranteed contract ($230M guaranteed)"),
    ContractRecord("Kirk Cousins", "ATL", "QB", "player", 180.0, 45.0, 100.0, 4, 2024, 2028, 25.0, "4-yr free agent contract, $90M fully guaranteed"),
    ContractRecord("Josh Allen", "BUF", "QB", "player", 258.0, 43.0, 150.0, 6, 2021, 2029, 30.3, "6-yr extension, $100M fully guaranteed at signing"),
    ContractRecord("Matthew Stafford", "LA", "QB", "player", 160.0, 40.0, 135.0, 4, 2022, 2027, 49.5, "4-yr extension after Super Bowl LVI championship"),
    ContractRecord("Daniel Jones", "NYG", "QB", "player", 160.0, 40.0, 104.0, 4, 2023, 2027, 47.9, "4-yr extension with injury guarantees"),
    ContractRecord("Aaron Rodgers", "NYJ", "QB", "player", 112.5, 37.5, 75.0, 3, 2023, 2026, 17.2, "Restructured 3-yr deal taking a $35M pay cut for cap room"),
    ContractRecord("Baker Mayfield", "TB", "QB", "player", 100.0, 33.3, 50.0, 3, 2024, 2027, 13.0, "3-yr deal after leading Bucs to division title"),
    ContractRecord("Geno Smith", "SEA", "QB", "player", 75.0, 25.0, 40.0, 3, 2023, 2026, 26.4, "3-yr incentive-laden extension"),
    ContractRecord("Caleb Williams", "CHI", "QB", "player", 39.5, 9.87, 39.5, 4, 2024, 2028, 7.2, "#1 overall pick rookie contract, 4-yr fully guaranteed + 5th yr option"),
    ContractRecord("Jayden Daniels", "WAS", "QB", "player", 37.7, 9.44, 37.7, 4, 2024, 2028, 6.9, "#2 overall pick rookie contract, 4-yr fully guaranteed + 5th yr option"),
    ContractRecord("C.J. Stroud", "HOU", "QB", "player", 36.3, 9.07, 36.3, 4, 2023, 2027, 8.2, "Rookie contract, 2023 Offensive Rookie of the Year"),
    ContractRecord("Bo Nix", "DEN", "QB", "player", 18.6, 4.65, 18.6, 4, 2024, 2028, 3.4, "1st round rookie contract, 4-yr fully guaranteed + 5th yr option"),
    ContractRecord("Brock Purdy", "SF", "QB", "player", 3.74, 0.93, 0.08, 4, 2022, 2026, 1.0, "'Mr. Irrelevant' 7th round rookie contract — highest value ROI in NFL"),

    # ------------------ RUNNING BACKS ------------------
    ContractRecord("Christian McCaffrey", "SF", "RB", "player", 38.0, 19.0, 24.0, 2, 2024, 2028, 6.7, "Highest-paid RB in NFL history ($19.0M APY)"),
    ContractRecord("Luke McCaffrey", "WAS", "WR", "player", 5.56, 1.39, 1.05, 4, 2024, 2028, 1.39, "Rookie draft contract (Round 3)"),
    ContractRecord("Jonathan Taylor", "IND", "RB", "player", 42.0, 14.0, 26.5, 3, 2023, 2027, 10.6, "3-yr extension with $19.3M fully guaranteed"),
    ContractRecord("Saquon Barkley", "PHI", "RB", "player", 37.75, 12.58, 26.0, 3, 2024, 2027, 3.8, "3-yr free agent deal with $26M guaranteed"),
    ContractRecord("Josh Jacobs", "GB", "RB", "player", 48.0, 12.0, 12.5, 4, 2024, 2028, 5.3, "4-yr free agent contract, $12.5M signing bonus"),
    ContractRecord("Alvin Kamara", "NO", "RB", "player", 24.5, 12.25, 22.2, 2, 2024, 2027, 8.1, "2-yr extension with $22.2M guaranteed"),
    ContractRecord("Derrick Henry", "BAL", "RB", "player", 16.0, 8.0, 9.0, 2, 2024, 2026, 5.1, "2-yr free agent contract, $9M fully guaranteed"),
    ContractRecord("Bijan Robinson", "ATL", "RB", "player", 21.96, 5.49, 21.96, 4, 2023, 2027, 4.9, "#8 overall pick rookie contract, 4-yr fully guaranteed"),
    ContractRecord("Jahmyr Gibbs", "DET", "RB", "player", 17.84, 4.46, 17.84, 4, 2023, 2027, 4.0, "#12 overall pick rookie contract, 4-yr fully guaranteed"),
    ContractRecord("Breece Hall", "NYJ", "RB", "player", 9.01, 2.25, 6.37, 4, 2022, 2026, 2.7, "2nd round rookie contract, 4 yrs"),
    ContractRecord("Kyren Williams", "LA", "RB", "player", 3.97, 0.99, 0.31, 4, 2022, 2026, 1.1, "5th round rookie contract, top touchdown producer"),

    # ------------------ WIDE RECEIVERS ------------------
    ContractRecord("Justin Jefferson", "MIN", "WR", "player", 140.0, 35.0, 110.0, 4, 2024, 2029, 8.6, "Highest-paid non-QB in NFL history ($35.0M APY, $110M gtd)"),
    ContractRecord("CeeDee Lamb", "DAL", "WR", "player", 136.0, 34.0, 100.0, 4, 2024, 2029, 8.8, "4-yr extension with $38M signing bonus"),
    ContractRecord("A.J. Brown", "PHI", "WR", "player", 96.0, 32.0, 84.0, 3, 2024, 2030, 11.8, "3-yr extension through 2029 season"),
    ContractRecord("Amon-Ra St. Brown", "DET", "WR", "player", 120.0, 30.0, 77.0, 4, 2024, 2029, 4.9, "4-yr extension with $34.7M fully guaranteed at signing"),
    ContractRecord("Brandon Aiyuk", "SF", "WR", "player", 120.0, 30.0, 76.0, 4, 2024, 2029, 5.7, "4-yr extension with $45M fully guaranteed"),
    ContractRecord("Tyreek Hill", "MIA", "WR", "player", 90.0, 30.0, 65.0, 3, 2024, 2027, 31.3, "Restructured 3-yr deal with $54M guaranteed"),
    ContractRecord("Jaylen Waddle", "MIA", "WR", "player", 84.75, 28.25, 76.0, 3, 2024, 2029, 8.6, "3-yr extension with $36M guaranteed"),
    ContractRecord("Davante Adams", "NYJ", "WR", "player", 140.0, 28.0, 65.67, 5, 2022, 2027, 25.3, "Acquired via trade from Raiders"),
    ContractRecord("DJ Moore", "CHI", "WR", "player", 110.0, 27.5, 82.6, 4, 2024, 2030, 20.6, "4-yr extension through 2029 season"),
    ContractRecord("Nico Collins", "HOU", "WR", "player", 72.75, 24.25, 52.0, 3, 2024, 2028, 6.6, "3-yr extension with $32.1M fully guaranteed"),
    ContractRecord("DK Metcalf", "SEA", "WR", "player", 72.0, 24.0, 58.2, 3, 2022, 2026, 24.5, "3-yr extension with $30M signing bonus"),
    ContractRecord("Ja'Marr Chase", "CIN", "WR", "player", 30.82, 7.7, 30.82, 4, 2021, 2026, 9.8, "Rookie deal + 5th yr option, pending record extension"),
    ContractRecord("Xavier Worthy", "KC", "WR", "player", 13.79, 3.45, 13.79, 4, 2024, 2028, 2.5, "#28 overall pick rookie contract, NFL combine 4.21 record"),
    ContractRecord("Rashee Rice", "KC", "WR", "player", 6.5, 1.62, 3.5, 4, 2023, 2027, 1.6, "2nd round rookie contract"),

    # ------------------ TIGHT ENDS ------------------
    ContractRecord("Travis Kelce", "KC", "WR", "player", 34.25, 17.125, 17.0, 2, 2024, 2026, 17.0, "Highest APY for a tight end in NFL history ($17.125M APY)"),
    ContractRecord("T.J. Hockenson", "MIN", "TE", "player", 66.0, 16.5, 42.5, 4, 2023, 2028, 14.0, "4-yr extension, $42.5M guaranteed"),
    ContractRecord("George Kittle", "SF", "TE", "player", 75.0, 15.0, 40.0, 5, 2020, 2026, 19.8, "5-yr extension, $30M fully guaranteed"),
    ContractRecord("Dallas Goedert", "PHI", "TE", "player", 57.0, 14.25, 35.7, 4, 2021, 2026, 9.1, "4-yr extension"),
    ContractRecord("Mark Andrews", "BAL", "TE", "player", 56.0, 14.0, 37.6, 4, 2021, 2026, 16.9, "4-yr extension with $30M fully guaranteed"),
    ContractRecord("David Njoku", "CLE", "TE", "player", 54.75, 13.69, 28.0, 4, 2022, 2026, 20.2, "4-yr contract with $17M fully guaranteed"),
    ContractRecord("Sam LaPorta", "DET", "TE", "player", 9.47, 2.37, 7.52, 4, 2023, 2027, 2.1, "2nd round rookie contract, 2023 Pro Bowler"),
    ContractRecord("Trey McBride", "ARI", "TE", "player", 6.3, 1.57, 2.8, 4, 2022, 2026, 1.8, "2nd round rookie contract"),

    # ------------------ DEFENSIVE STARS ------------------
    ContractRecord("Nick Bosa", "SF", "DEF", "player", 170.0, 34.0, 122.5, 5, 2023, 2029, 14.7, "Highest-paid defensive player in NFL history ($34.0M APY)"),
    ContractRecord("Chris Jones", "KC", "DEF", "player", 158.75, 31.75, 101.0, 5, 2024, 2029, 7.3, "Highest-paid defensive tackle in NFL history ($31.75M APY)"),
    ContractRecord("Brian Burns", "NYG", "DEF", "player", 141.0, 28.2, 87.5, 5, 2024, 2029, 15.5, "5-yr contract after trade from Carolina"),
    ContractRecord("T.J. Watt", "PIT", "DEF", "player", 112.0, 28.0, 80.0, 4, 2021, 2026, 30.4, "4-yr extension, former NFL Defensive Player of the Year"),
    ContractRecord("Christian Wilkins", "LV", "DEF", "player", 110.0, 27.5, 84.75, 4, 2024, 2028, 10.3, "4-yr free agent contract with Raiders"),
    ContractRecord("Myles Garrett", "CLE", "DEF", "player", 125.0, 25.0, 100.0, 5, 2020, 2027, 20.2, "5-yr extension, 2023 NFL Defensive Player of the Year"),
    ContractRecord("Patrick Surtain II", "DEN", "DEF", "player", 96.0, 24.0, 77.5, 4, 2024, 2030, 6.7, "Highest-paid cornerback in NFL history ($24.0M APY)"),
    ContractRecord("Jaire Alexander", "GB", "DEF", "player", 84.0, 21.0, 30.0, 4, 2022, 2027, 23.9, "4-yr extension with $30M signing bonus"),
    ContractRecord("Maxx Crosby", "LV", "DEF", "player", 94.0, 23.5, 53.0, 4, 2022, 2027, 30.4, "4-yr extension, restructured for cap relief"),
    ContractRecord("Roquan Smith", "BAL", "DEF", "player", 100.0, 20.0, 60.0, 5, 2023, 2028, 13.5, "Highest-paid off-ball linebacker in NFL history"),
    ContractRecord("Fred Warner", "SF", "DEF", "player", 95.2, 19.04, 40.5, 5, 2021, 2027, 12.3, "5-yr extension, first-team All-Pro"),
    ContractRecord("Micah Parsons", "DAL", "DEF", "player", 17.07, 4.27, 17.07, 4, 2021, 2026, 5.4, "Rookie deal + 5th yr option, pending record contract"),
    ContractRecord("Sauce Gardner", "NYJ", "DEF", "player", 33.45, 8.36, 33.45, 4, 2022, 2026, 8.9, "#4 overall pick rookie contract, 2-time first team All-Pro"),

    # ------------------ HEAD COACHES ------------------
    ContractRecord("Andy Reid", "KC", "HC", "coach", 100.0, 20.0, 100.0, 5, 2024, 2029, 20.0, "Highest-paid coach in NFL history ($20M/yr), 3x Super Bowl champion"),
    ContractRecord("Sean Payton", "DEN", "HC", "coach", 90.0, 18.0, 90.0, 5, 2023, 2028, 18.0, "5-yr deal signed after trade from Saints ($18M/yr)"),
    ContractRecord("Jim Harbaugh", "LAC", "HC", "coach", 80.0, 16.0, 80.0, 5, 2024, 2029, 16.0, "5-yr contract after winning CFP National Championship at Michigan"),
    ContractRecord("Sean McVay", "LA", "HC", "coach", 75.0, 15.0, 75.0, 5, 2022, 2028, 15.0, "5-yr extension following Super Bowl LVI win"),
    ContractRecord("Kyle Shanahan", "SF", "HC", "coach", 70.0, 14.0, 70.0, 5, 2023, 2028, 14.0, "5-yr extension through 2028 season"),
    ContractRecord("Mike Tomlin", "PIT", "HC", "coach", 37.5, 12.5, 37.5, 3, 2024, 2027, 12.5, "3-yr extension through 2027 season, never had a losing season"),
    ContractRecord("John Harbaugh", "BAL", "HC", "coach", 36.0, 12.0, 36.0, 3, 2022, 2026, 12.0, "3-yr extension, Super Bowl XLVII champion"),
    ContractRecord("Dan Campbell", "DET", "HC", "coach", 44.0, 11.0, 44.0, 4, 2024, 2028, 11.0, "4-yr extension after NFC Championship appearance"),
    ContractRecord("Kevin Stefanski", "CLE", "HC", "coach", 40.0, 10.0, 40.0, 4, 2024, 2028, 10.0, "4-yr extension, 2-time NFL Coach of the Year"),
    ContractRecord("Matt LaFleur", "GB", "HC", "coach", 36.0, 9.0, 36.0, 4, 2022, 2026, 9.0, "4-yr contract extension"),
    ContractRecord("Sean McDermott", "BUF", "HC", "coach", 36.0, 9.0, 36.0, 4, 2023, 2027, 9.0, "4-yr extension through 2027 season"),
    ContractRecord("Mike McDaniel", "MIA", "HC", "coach", 36.0, 9.0, 36.0, 4, 2024, 2028, 9.0, "Contract extension through 2028 season"),
    ContractRecord("Mike Macdonald", "SEA", "HC", "coach", 54.0, 9.0, 54.0, 6, 2024, 2030, 9.0, "6-yr contract signed in 2024"),
    ContractRecord("Raheem Morris", "ATL", "HC", "coach", 40.0, 8.0, 40.0, 5, 2024, 2029, 8.0, "5-yr contract signed in 2024"),
    ContractRecord("Dan Quinn", "WAS", "HC", "coach", 32.0, 8.0, 32.0, 4, 2024, 2028, 8.0, "4-yr contract signed in 2024"),
    ContractRecord("Kevin O'Connell", "MIN", "HC", "coach", 28.0, 7.0, 28.0, 4, 2022, 2026, 7.0, "4-yr contract"),
    ContractRecord("DeMeco Ryans", "HOU", "HC", "coach", 42.0, 7.0, 42.0, 6, 2023, 2029, 7.0, "6-yr contract signed in 2023"),
    ContractRecord("Nick Sirianni", "PHI", "HC", "coach", 35.0, 7.0, 35.0, 5, 2021, 2026, 7.0, "5-yr contract through 2025"),
    ContractRecord("Zac Taylor", "CIN", "HC", "coach", 30.0, 6.0, 30.0, 5, 2022, 2027, 6.0, "5-yr contract extension through 2026"),
    ContractRecord("Shane Steichen", "IND", "HC", "coach", 32.5, 6.5, 32.5, 5, 2023, 2028, 6.5, "5-yr contract signed in 2023"),
    ContractRecord("Dave Canales", "CAR", "HC", "coach", 36.0, 6.0, 36.0, 6, 2024, 2030, 6.0, "6-yr contract signed in 2024"),
    ContractRecord("Brian Callahan", "TEN", "HC", "coach", 30.0, 6.0, 30.0, 5, 2024, 2029, 6.0, "5-yr contract signed in 2024"),
    ContractRecord("Jerod Mayo", "NE", "HC", "coach", 24.0, 6.0, 24.0, 4, 2024, 2028, 6.0, "4-yr contract succeeding Bill Belichick"),
    ContractRecord("Todd Bowles", "TB", "HC", "coach", 25.0, 5.0, 25.0, 5, 2022, 2027, 5.0, "5-yr contract with Tampa Bay"),
    ContractRecord("Brian Daboll", "NYG", "HC", "coach", 25.0, 5.0, 25.0, 5, 2022, 2027, 5.0, "5-yr contract, 2022 Coach of the Year"),
    ContractRecord("Jonathan Gannon", "ARI", "HC", "coach", 30.0, 6.0, 30.0, 5, 2023, 2028, 6.0, "5-yr contract signed in 2023"),
    ContractRecord("Antonio Pierce", "LV", "HC", "coach", 15.0, 5.0, 15.0, 3, 2024, 2027, 5.0, "3-yr contract signed in 2024"),
]


# Season catalog. The rows carry no source and no as-of date, only each deal's signed and free-agent years, so the
# catalog is keyed by season from those terms (earliest signing year through latest free-agent year) and every
# season in it is flagged "unverified". A season outside it is NOT cataloged and is never answered from the table;
# inside it, a deal is only shown for seasons its own signed..free-agent term covers. The cap-hit column is the
# table's single "current" figure, not a per-season one.
CONTRACT_SEASONS: Dict[int, Dict[str, Any]] = {
    season: {
        "status": "unverified",
        "source": "none recorded; season derived from each row's signed/free-agent years",
    }
    for season in range(min(c.signed_year for c in NFL_CONTRACTS), max(c.free_agent_year for c in NFL_CONTRACTS) + 1)
}


def contract_in_effect(c: "ContractRecord", season: Optional[int]) -> bool:
    """True when ``season`` is None or inside the deal's own signed..free-agent term."""
    return season is None or c.signed_year <= as_season(season) <= c.free_agent_year


def as_season(value: Any) -> int:
    """A season as an int; anything missing, NaN or non-numeric is 0 (= unknown, never cataloged)."""
    try:
        return int(float(value)) if value else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def contract_season_cataloged(season: Optional[int]) -> bool:
    """True when contract rows exist for ``season``; None means "the latest cataloged season"."""
    return True if season is None else as_season(season) in CONTRACT_SEASONS


def contract_catalog_note(season: Optional[int] = None) -> str:
    """One-line statement of what the contract data can and cannot say for ``season``."""
    cataloged = sorted(CONTRACT_SEASONS)
    span = f"{cataloged[0]}-{cataloged[-1]}"
    if contract_season_cataloged(season):
        return (f"Contract data is an unverified static snapshot (seasons {span} from each deal's own term); "
                f"no source or as-of date is recorded.")
    return (f"Contract data is not cataloged for season {as_season(season)} "
            f"(cataloged: {span}, unverified); nothing is shown for it.")


def find_contract_by_name(query_name: str, season: Optional[int] = None) -> Optional[ContractRecord]:
    """
    Find a contract record by full or partial player/coach name, supporting initial abbreviations.
    With ``season`` given, a season that is not cataloged finds nothing instead of reusing the snapshot.
    (A deal's own term is checked by the caller that renders it, see ``contract_in_effect``.)
    """
    q = query_name.strip().lower()
    if not q or not contract_season_cataloged(season):
        return None

    # 1. Exact match (prefer player if both exist)
    exact_players = [c for c in NFL_CONTRACTS if c.name.lower() == q and c.contract_type == "player"]
    if exact_players:
        return exact_players[0]
    exact_all = [c for c in NFL_CONTRACTS if c.name.lower() == q]
    if exact_all:
        return exact_all[0]

    # 2. Check for initial + dot pattern (e.g. "j.taylor", "a.st. brown", "p.mahomes", "j. allen")
    dot_m = re.match(r"^([a-z])\.\s*(.+)$", q)
    if dot_m:
        init_letter = dot_m.group(1)
        rest_name = dot_m.group(2).strip()
        norm_rest = rest_name.replace(".", "").strip()
        matched_init = []
        for c in NFL_CONTRACTS:
            c_low = c.name.lower()
            c_parts = c_low.split()
            if not c_parts:
                continue
            first_init = c_parts[0][0]
            if first_init != init_letter:
                continue
            surname = " ".join(c_parts[1:])
            surname_clean = surname.replace(".", "")
            if norm_rest in (surname_clean, surname, c_parts[-1]):
                matched_init.append(c)
        if matched_init:
            players = [c for c in matched_init if c.contract_type == "player"]
            return players[0] if players else matched_init[0]

    # 3. Last name or substring match (prefer players over coaches)
    player_candidates = []
    coach_candidates = []
    for c in NFL_CONTRACTS:
        c_low = c.name.lower()
        parts = c_low.split()
        if q in c_low or c_low in q:
            if c.contract_type == "player":
                player_candidates.append(c)
            else:
                coach_candidates.append(c)
        elif any(p == q for p in parts if len(p) >= 3):
            if c.contract_type == "player":
                player_candidates.append(c)
            else:
                coach_candidates.append(c)

    if player_candidates:
        return player_candidates[0]
    if coach_candidates:
        return coach_candidates[0]

    # 4. Fuzzy match (prefer players)
    player_names = [c.name for c in NFL_CONTRACTS if c.contract_type == "player"]
    matches = difflib.get_close_matches(query_name, player_names, n=1, cutoff=0.6)
    if matches:
        return next(c for c in NFL_CONTRACTS if c.name == matches[0])
    all_names = [c.name for c in NFL_CONTRACTS]
    matches_all = difflib.get_close_matches(query_name, all_names, n=1, cutoff=0.6)
    if matches_all:
        return next(c for c in NFL_CONTRACTS if c.name == matches_all[0])
    return None


def get_contracts_by_team(team_abbr: str) -> List[ContractRecord]:
    """Retrieve all player and coach contracts for a specific team."""
    t = team_abbr.strip().upper()
    return [c for c in NFL_CONTRACTS if c.team == t]


def get_contracts_by_position(pos: str) -> List[ContractRecord]:
    """Retrieve player contracts filtered by position (e.g. QB, RB, WR, TE, DEF)."""
    p = pos.strip().upper()
    return [c for c in NFL_CONTRACTS if c.position == p and c.contract_type == "player"]


def get_all_coach_contracts() -> List[ContractRecord]:
    """Retrieve all head coach contracts sorted by APY."""
    coaches = [c for c in NFL_CONTRACTS if c.contract_type == "coach"]
    coaches.sort(key=lambda x: x.apy_m, reverse=True)
    return coaches


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_SURNAME_PARTICLES = {"st", "de", "di", "del", "la", "le", "van", "von"}
_ROI_SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}  # positions that appear in the play-by-play name fields
_PLAY_NAME_FIELDS = ("player_name", "qb_name", "rusher_player_name", "receiver_player_name")


def name_match_key(name: Any) -> Optional[Tuple[str, str]]:
    """
    Normalize a player name to (first initial, surname) so full contract names ("Patrick Mahomes",
    "C.J. Stroud", "Patrick Surtain II") match play-by-play forms ("P.Mahomes", "C.Stroud", "P.Surtain II").
    Accents are folded ("Jose"), and a leading numeric id prefix ("00-") is ignored. Returns None for blank names.
    """
    raw = unicodedata.normalize("NFKD", str(name or "").strip())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"^\d+-", "", raw)
    if not raw:
        return None
    raw = re.sub(r"\.(?=\S)", ". ", raw.replace("'", "").replace("\u2019", ""))
    tokens = [t for t in re.sub(r"[^a-z0-9\s-]", " ", raw.lower()).split() if t]
    while len(tokens) > 1 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    if not tokens:
        return None
    if len(tokens) == 1:
        return ("", tokens[0])
    surname = tokens[-1]
    if len(tokens) >= 3 and tokens[-2] in _SURNAME_PARTICLES:
        surname = f"{tokens[-2]} {tokens[-1]}"
    return (tokens[0][0], surname)


_TEAM_ALIASES = {
    "LAR": "LA", "STL": "LA", "SL": "LA", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "ARZ": "ARI",
    "SD": "LAC", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
}


def _team_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(code, code)


# Optional per-field player ids (nflverse names). The bundled data export does not carry them yet; when a row does,
# they decide whether two rows are the same player. Without them the identity is the (name key, team) pair.
_PLAY_ID_FIELDS = {
    "player_name": ("player_id",),
    "qb_name": ("passer_player_id", "qb_player_id"),
    "rusher_player_name": ("rusher_player_id",),
    "receiver_player_name": ("receiver_player_id",),
}


def _play_season(p: Dict[str, Any]) -> int:
    try:
        return int(float(p.get("season") or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _name_key_identities(plays: List[Dict[str, Any]], key: Tuple[str, str]) -> Dict[int, set]:
    """
    Distinct players that share an abbreviated name ``key`` in each season of ``plays``, by player id when the
    row has one, else by (key, team). A team-only identity is the same player as an id-bearing one on that team
    (rows with and without ids can be mixed), and a row with neither an id nor a team adds nothing.
    """
    ids: Dict[int, Dict[str, set]] = {}
    teams_without_id: Dict[int, set] = {}
    for p in plays:
        for field, id_fields in _PLAY_ID_FIELDS.items():
            val = str(p.get(field, "") or "").strip()
            if not val or name_match_key(val) != key:
                continue
            pid = next((str(p.get(i)).strip() for i in id_fields if str(p.get(i) or "").strip()), "")
            team = _team_code(p.get("posteam"))
            season = _play_season(p)
            if pid:
                ids.setdefault(season, {}).setdefault(pid, set())
                if team:
                    ids[season][pid].add(team)
            elif team:
                teams_without_id.setdefault(season, set()).add(team)
    seen: Dict[int, set] = {}
    for season in set(ids) | set(teams_without_id):
        by_id = ids.get(season, {})
        covered = set().union(*by_id.values()) if by_id else set()
        seen[season] = {("id", pid) for pid in by_id} | {
            ("name", key, t) for t in teams_without_id.get(season, set()) - covered
        }
    return seen


def _safe_epa(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0  # NaN / inf -> 0.0


def calculate_contract_performance_efficiency(
    contract: ContractRecord,
    plays: List[Dict[str, Any]],
    season: int,
) -> Dict[str, Any]:
    """
    Calculate performance ROI and cap allocation metrics:
    - Cost per EPA: APY ($M) / Total Season EPA
    - Cost per Fantasy Point: APY ($M) / Total Season Fantasy Points
    - APY per Touchdown

    Contracts carry full names while play-by-play uses abbreviated forms ("P.Mahomes"), so plays are
    matched on a normalized (first initial, surname) key. When that key belongs to exactly one player in the
    play's season (by player id if the rows carry one, else by distinct key+team pairs), it matches the contract
    on any team, so plays from before a trade count. When two or more players share it that season, the play's
    team must also be the contract's team (so namesakes are not credited).
    `epa_matched_plays` reports how many plays were matched so callers can tell "no EPA" from "no name match";
    `epa_ambiguous_key` / `epa_team_gated_plays` report plays left out because the key was ambiguous.
    """
    from .fantasy import compute_player_fantasy_profile

    p_low = contract.name.strip().lower()
    # Coaches are only matched on the exact full name: an abbreviated "J.Harbaugh" row is a player, not a coach
    c_key = name_match_key(contract.name) if contract.contract_type != "coach" else None
    c_team = _team_code(contract.team)
    identities = _name_key_identities(plays, c_key) if c_key else {}
    gated: List[Dict[str, Any]] = []

    def _play_matches(p: Dict[str, Any]) -> bool:
        rejected = False
        for field in _PLAY_NAME_FIELDS:
            val = str(p.get(field, "") or "").strip()
            if not val:
                continue
            if val.lower() == p_low:
                return True
            if c_key and name_match_key(val) == c_key:
                p_team = _team_code(p.get("posteam"))
                # a key held by one player that season is that player on any team; a shared key needs the
                # contract's team (rows without a team are accepted)
                if len(identities.get(_play_season(p), ())) <= 1 or not p_team or p_team == c_team:
                    return True
                rejected = True
        if rejected:
            gated.append(p)  # once per row, and only when no field accepted it
        return False

    p_plays = [p for p in plays if _play_matches(p)]

    tot_epa = sum(_safe_epa(p.get("epa", 0.0)) for p in p_plays)
    fprof = compute_player_fantasy_profile(contract.name, plays)
    f_pts = fprof.get("points_ppr", 0.0)

    # Cost per EPA ($k per EPA unit)
    cost_per_epa_k = round((contract.apy_m * 1000.0) / tot_epa, 1) if tot_epa > 0 else 0.0
    cost_per_fpoint_k = round((contract.apy_m * 1000.0) / f_pts, 1) if f_pts > 0 else 0.0

    return {
        "name": contract.name,
        "team": contract.team,
        "position": contract.position,
        "apy_m": contract.apy_m,
        "cap_hit_m": contract.cap_hit_current_m,
        "total_epa": round(tot_epa, 1),
        "epa_matched_plays": len(p_plays),
        "epa_ambiguous_key": any(len(v) > 1 for v in identities.values()),
        "epa_team_gated_plays": len(gated),
        "fantasy_points": round(f_pts, 1),
        "cost_per_epa_k": cost_per_epa_k,
        "cost_per_fpoint_k": cost_per_fpoint_k,
    }


def render_contracts_leaderboard_view(
    contract_type: str = "player",
    position_filter: Optional[str] = None,
    team_filter: Optional[str] = None,
    sort_by: str = "apy",
    limit: int = 15,
) -> str:
    """Render a colorized ASCII table of top NFL player or coach contracts."""
    from . import C, AsciiArtRenderer

    records = [c for c in NFL_CONTRACTS if c.contract_type == contract_type]
    if position_filter:
        pf = position_filter.strip().upper()
        records = [c for c in records if c.position == pf]
    if team_filter:
        tf = team_filter.strip().upper()
        records = [c for c in records if c.team == tf]

    sort_field = sort_by.strip().lower()
    if sort_field in ("guaranteed", "gtd", "guarantee"):
        records.sort(key=lambda x: x.guaranteed_m, reverse=True)
        sort_label = "Guaranteed $"
    elif sort_field in ("total", "value", "total_value"):
        records.sort(key=lambda x: x.total_value_m, reverse=True)
        sort_label = "Total Value"
    else:  # apy
        records.sort(key=lambda x: x.apy_m, reverse=True)
        sort_label = "APY ($M/yr)"

    display_records = records[:limit] if (limit and limit > 0) else records

    sub_parts = []
    if contract_type == "coach":
        sub_parts.append("Head Coaches")
    else:
        sub_parts.append("NFL Players")
    if position_filter:
        sub_parts.append(f"Pos: {position_filter.upper()}")
    if team_filter:
        sub_parts.append(team_filter.upper())
    sub_parts.append(f"Ranked by {sort_label}")

    title_str = f"💼 NFL Contract & Salary Leaderboard ({' • '.join(sub_parts)})"

    headers = ["Rank", "Name", "Team", "Pos", "APY ($M/yr)", "Total Value", "Guaranteed", "Yrs", "Cap Hit", "FA Year"]
    rows = []

    for idx, c in enumerate(display_records, 1):
        rows.append([
            f"#{idx}",
            f"{C.BOLD}{c.name}{C.RESET}",
            c.team,
            f"{C.CYAN}{c.position}{C.RESET}",
            f"{C.BOLD}{C.GREEN}${c.apy_m:.2f}M{C.RESET}",
            f"${c.total_value_m:.1f}M",
            f"${c.guaranteed_m:.1f}M",
            f"{c.years} yrs",
            f"${c.cap_hit_current_m:.1f}M",
            str(c.free_agent_year),
        ])

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["right", "left", "center", "center", "right", "right", "right", "center", "right", "center"],
    )
    footer = f"\n  {C.DIM}Contract figures: compiled from public reports; approximate and may be out of date. Not affiliated with Over The Cap or Spotrac.{C.RESET}"
    return f"\n{tbl}{footer}"


def render_player_contract_view(
    name: str,
    plays: Optional[List[Dict[str, Any]]] = None,
    season: Optional[int] = None,
) -> str:
    """Render a detailed contract dossier card for a specific player or coach."""
    from . import C, CURRENT_SEASON

    ref_season = as_season(season) or CURRENT_SEASON
    if season and not contract_season_cataloged(season):
        return f"\n{C.YELLOW}⚠ {contract_catalog_note(season)}{C.RESET}"
    c = find_contract_by_name(name)
    if not c:
        return f"\n{C.YELLOW}⚠ No contract record found for '{name}'. Try searching by last name (e.g. Mahomes, Jefferson, Reid).{C.RESET}"
    if not contract_in_effect(c, season):
        return (f"\n{C.YELLOW}⚠ {c.name} has no cataloged contract in effect for season {as_season(season)} "
                f"(signed {c.signed_year}, expires {c.free_agent_year}).{C.RESET}")

    lines = [
        f"\n{C.BOLD}{C.GOLD}╔══════════════════════════════════════════════════════════════════════════╗{C.RESET}",
        f"{C.BOLD}{C.GOLD}║             💼 NFL OFFICIAL CONTRACT & PAYROLL DOSSIER                   ║{C.RESET}",
        f"{C.BOLD}{C.GOLD}╚══════════════════════════════════════════════════════════════════════════╝{C.RESET}",
        f"  {C.BOLD}Entity:{C.RESET}       {C.BOLD}{c.name}{C.RESET} ({c.team} • {c.position} • {c.contract_type.upper()})",
        "",
        f"  {C.GREEN}💰 FINANCIAL COMMITMENT & APY:{C.RESET}",
        f"     • Average Per Year (APY):   {C.BOLD}{C.GREEN}${c.apy_m:.2f}M / season{C.RESET}",
        f"     • Total Contract Value:     {C.BOLD}${c.total_value_m:.2f}M{C.RESET}",
        f"     • Total Guaranteed Money:   {C.BOLD}${c.guaranteed_m:.2f}M{C.RESET} ({round((c.guaranteed_m / c.total_value_m) * 100.0, 1)}% of total)",
        f"     • Current Cap Hit:          ${c.cap_hit_current_m:.2f}M",
        "",
        f"  {C.CYAN}⏳ DURATION & FREE AGENCY HORIZON:{C.RESET}",
        f"     • Contract Length:          {c.years} Years (Signed: {c.signed_year})",
        f"     • Contract Expiration / FA: {C.BOLD}{c.free_agent_year}{C.RESET} ({max(0, c.free_agent_year - ref_season)} season(s) remaining after {ref_season})",
    ]

    if c.notes:
        lines.append(f"     • Structure Notes:          {C.DIM}{c.notes}{C.RESET}")
    lines.append(f"     • Data status:              {C.DIM}{contract_catalog_note(season)}{C.RESET}")

    if plays and season:
        eff = calculate_contract_performance_efficiency(c, plays, season)
        no_epa_match = eff["epa_matched_plays"] == 0
        if no_epa_match and c.contract_type == "player" and c.position in _ROI_SKILL_POSITIONS:
            # Say so instead of showing an empty-looking ROI card
            lines.extend([
                "",
                f"  {C.YELLOW}⚠ EPA unavailable ({season}): no play-by-play rows matched '{c.name}' (name/team mismatch, or no snaps).{C.RESET}",
            ])
        if eff["epa_team_gated_plays"]:
            lines.extend([
                "",
                f"  {C.YELLOW}⚠ ROI may be partial ({season}): the abbreviated name for '{c.name}' is shared by more than "
                f"one player, so only plays for {c.team} were counted ({eff['epa_team_gated_plays']} on other teams left out).{C.RESET}",
            ])
        if eff["total_epa"] != 0 or eff["fantasy_points"] != 0:
            cost_epa_str = f"${eff['cost_per_epa_k']}k / EPA" if eff["cost_per_epa_k"] > 0 else "N/A"
            cost_fp_str = f"${eff['cost_per_fpoint_k']}k / Pt" if eff["cost_per_fpoint_k"] > 0 else "N/A"
            epa_total_str = "unavailable (no name match)" if no_epa_match else f"{eff['total_epa']:+.1f} EPA"
            lines.extend([
                "",
                f"  {C.MAGENTA}📈 PERFORMANCE ROI & CAP EFFICIENCY ({season}):{C.RESET}",
                f"     • Total Season EPA:         {epa_total_str}",
                f"     • Season Fantasy Points:    {eff['fantasy_points']:.1f} Pts",
                f"     • Cost per EPA:             {cost_epa_str}",
                f"     • Cost per Fantasy Point:   {cost_fp_str}",
            ])

    return "\n".join(lines)


def _split_contracts(rows: List[ContractRecord]) -> Tuple[List[ContractRecord], List[ContractRecord], List[ContractRecord]]:
    """Partition contracts into (players, coaches, other); only players count toward cap totals."""
    players = [c for c in rows if str(c.contract_type).strip().lower() == "player"]
    coaches = [c for c in rows if str(c.contract_type).strip().lower() == "coach"]
    other = [c for c in rows if c not in players and c not in coaches]
    return players, coaches, other


def compute_team_payroll_totals(team_abbr: str, contracts: Optional[List[ContractRecord]] = None) -> Dict[str, Any]:
    """
    Sum cataloged contract money for one team, keeping player cap and coach pay apart.

    Only contracts of type "player" are summed into the player totals. Head-coach salaries are not
    salary-cap charges, and any other contract type is listed but also excluded from the totals.
    The catalog is partial (a curated list, not every roster contract), so the totals describe only
    cataloged players.
    """
    t = team_abbr.strip().upper()
    rows = get_contracts_by_team(t) if contracts is None else contracts
    players, coaches, other = _split_contracts(rows)
    return {
        "team": t,
        "player_count": len(players),
        "coach_count": len(coaches),
        "other_count": len(other),
        "player_apy_m": sum(c.apy_m for c in players),
        "player_cap_hit_m": sum(c.cap_hit_current_m for c in players),
        "coach_apy_m": sum(c.apy_m for c in coaches),
    }


def render_team_payroll_view(team_abbr: str) -> str:
    """Render a breakdown of a team's cataloged contracts: player subtotal, coach pay listed separately."""
    from . import C, AsciiArtRenderer

    t = team_abbr.strip().upper()
    team_contracts = get_contracts_by_team(t)
    if not team_contracts:
        return f"\n{C.YELLOW}⚠ No contracts cataloged for team '{team_abbr}'.{C.RESET}"

    totals = compute_team_payroll_totals(t, team_contracts)
    players, coaches, other = _split_contracts(team_contracts)
    players = sorted(players, key=lambda x: x.apy_m, reverse=True)
    coaches = sorted(coaches, key=lambda x: x.apy_m, reverse=True)
    other = sorted(other, key=lambda x: x.apy_m, reverse=True)

    title_str = f"🏛️ Team Contract Payroll & Cap Allocation: {t}"
    headers = ["Name", "Pos", "Type", "APY ($M)", "Total ($M)", "Guaranteed ($M)", "Yrs", "Cap Hit ($M)", "FA"]
    rows = []

    def _contract_row(c: ContractRecord, show_cap_hit: bool) -> List[str]:
        return [
            f"{C.BOLD}{c.name}{C.RESET}",
            c.position,
            str(c.contract_type).upper(),
            f"${c.apy_m:.2f}M",
            f"${c.total_value_m:.1f}M",
            f"${c.guaranteed_m:.1f}M",
            f"{c.years}y",
            f"${c.cap_hit_current_m:.1f}M" if show_cap_hit else "-",
            str(c.free_agent_year),
        ]

    def _label_row(text: str) -> List[str]:
        return [f"{C.DIM}{text}{C.RESET}"] + ["-"] * (len(headers) - 1)

    for c in players:
        rows.append(_contract_row(c, show_cap_hit=True))

    if players:
        rows.append([
            f"{C.BOLD}CATALOGED PLAYERS SUBTOTAL ({len(players)}){C.RESET}",
            "-",
            "-",
            f"{C.BOLD}{C.GREEN}${totals['player_apy_m']:.2f}M{C.RESET}",
            "-",
            "-",
            "-",
            f"{C.BOLD}${totals['player_cap_hit_m']:.2f}M{C.RESET}",
            "-",
        ])

    # Coach pay is listed for reference only: it is not a salary-cap charge and is excluded from the subtotal.
    if coaches:
        rows.append(_label_row("COACH PAY (not in subtotal)"))
        for c in coaches:
            rows.append(_contract_row(c, show_cap_hit=False))
    if other:
        rows.append(_label_row("OTHER CONTRACTS (not in subtotal)"))
        for c in other:
            rows.append(_contract_row(c, show_cap_hit=False))

    tbl = AsciiArtRenderer.render_table(
        title_str,
        headers,
        rows,
        alignments=["left", "center", "center", "right", "right", "right", "center", "right", "center"],
    )
    notes = []
    if players:
        notes.append(f"  {C.DIM}Subtotal covers only the {len(players)} cataloged player contract(s); the catalog is partial, so this is not the team's full cap commitment.{C.RESET}")
    if coaches or other:
        notes.append(f"  {C.DIM}Coach pay and other contract types are listed separately and are not included in the subtotal.{C.RESET}")
    return f"\n{tbl}\n" + "\n".join(notes)


def interactive_contracts_browser(
    plays: Optional[List[Dict[str, Any]]] = None,
    active_season: int = 2026,
) -> None:
    """Interactive drill-down menu for NFL player and coach contracts, payrolls, and ROI."""
    from . import C, prompt_input

    while True:
        print(f"\n{C.BOLD}{C.GOLD}=== 💼 NFL CONTRACT & SALARY CAP ANALYTICS ==={C.RESET}")
        print("  Select Contract Browsing Mode:")
        print(f"    [1] {C.BOLD}Highest-Paid Players{C.RESET} (Ranked by APY, Total Value, or Guarantees)")
        print(f"    [2] {C.BOLD}Filter Players by Position{C.RESET} (QB, RB, WR, TE, DEF)")
        print(f"    [3] {C.BOLD}Head Coach Contracts & Salaries{C.RESET}")
        print(f"    [4] {C.BOLD}Team Payroll & Cap Allocation{C.RESET} (Inspect any NFL team)")
        print(f"    [5] {C.BOLD}Search Player or Coach Contract Dossier{C.RESET}")
        print(f"    [q] {C.DIM}Return to main menu{C.RESET}")

        try:
            choice = prompt_input("  Choose mode [1-5, q] (default: 1): ").strip().lower() or "1"
        except (EOFError, KeyboardInterrupt):
            break

        if choice in ("q", "quit", "exit", "back"):
            break

        if choice == "1":
            try:
                sort_in = prompt_input("  Rank by [1] APY  [2] Total Value  [3] Guaranteed (default: 1): ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                continue
            sort_key = "total" if sort_in == "2" else ("guaranteed" if sort_in == "3" else "apy")
            print(render_contracts_leaderboard_view(contract_type="player", sort_by=sort_key, limit=20))
        elif choice == "2":
            try:
                pos = prompt_input("  Enter position [QB/RB/WR/TE/DEF] (default: QB): ").strip().upper() or "QB"
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_contracts_leaderboard_view(contract_type="player", position_filter=pos, limit=15))
        elif choice == "3":
            print(render_contracts_leaderboard_view(contract_type="coach", limit=20))
        elif choice == "4":
            try:
                tm = prompt_input("  Enter team abbreviation (e.g. KC, SF, PHI, DET, BAL, DAL): ").strip().upper() or "KC"
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_team_payroll_view(tm))
        elif choice == "5":
            try:
                p_in = prompt_input("  Enter player or coach name (e.g. Mahomes, Reid, Jefferson, Bosa): ").strip() or "Mahomes"
            except (EOFError, KeyboardInterrupt):
                continue
            print(render_player_contract_view(p_in, plays=plays, season=active_season))
