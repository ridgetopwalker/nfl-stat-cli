"""
Data attribution and license metadata for the CLI.

Everything user-facing about *where the numbers came from* lives here so the
credit, license link, changes-made note, exports and ``about`` all stay in sync:

* nflverse data (play-by-play etc.) is CC BY 4.0 -> credit, license link, a
  changes-made note, and no implied endorsement.
* FTN charting data (``load_ftn_charting``) is CC BY-SA 4.0 -> extra credit
  line, shown ONLY when that dataset is actually loaded.
* The sportsdataverse-py fallback and the bundled sample rows are NOT nflverse
  and are never labelled as such.

The product name is a single constant so a later rebrand is one edit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# The one place the product name lives (used by every footer / export / about text).
PRODUCT_NAME = "nfl-stat-cli"

NFLVERSE_URL = "https://github.com/nflverse/nflverse-data"
CC_BY_NAME = "CC BY 4.0"
CC_BY_ID = "CC-BY-4.0"
CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"
FTN_NAME = "FTN Data via nflverse"
FTN_URL = "https://ftndata.com"
CC_BY_SA_NAME = "CC BY-SA 4.0"
CC_BY_SA_ID = "CC-BY-SA-4.0"
CC_BY_SA_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

# Source kinds: what actually produced the rows behind a result.
SOURCE_NFLVERSE = "nflverse"
SOURCE_SPORTSDATAVERSE = "sportsdataverse"
SOURCE_SAMPLE = "sample"

# Dataset ids that can be registered as "actually loaded" for the active source.
DATASET_PBP = "pbp"
DATASET_FTN = "ftn_charting"

CHANGES_NOTE = "filtered, aggregated, and derived statistics"

# --- Source labels (what ``last_source_used`` reports) ---------------------------------
LABEL_NFLREADPY = "nflreadpy (Python)"
LABEL_NFL_DATA_PY = "nfl_data_py (Python)"
LABEL_SPORTSDATAVERSE = "sportsdataverse-py (Python, not nflverse)"
LABEL_NFLREADR = "nflverse / nflreadr (R)"
LABEL_SAMPLE = "built-in sample data (not nflverse)"
LABEL_PYTHON_UNIDENTIFIED = "python data backend (unidentified)"  # classified as not-nflverse: no credit claimed

# --- NOTICE (repo-root NOTICE must equal ``render_notice()``) --------------------------
_NOTICE_HEAD = (
    "This software is MIT-licensed (see LICENSE). The MIT license covers the code only.\n"
    "\n"
    f"NFL play-by-play and related data come from nflverse ({NFLVERSE_URL}), licensed under the "
    f"Creative Commons Attribution 4.0 International License ({CC_BY_NAME}, {CC_BY_URL}).\n"
    "Changes: we filter, aggregate, and compute derived statistics and model outputs from that data. "
    "Results are not the original nflverse data.\n"
)
_NOTICE_FTN = (
    f"Charting data: {FTN_NAME} ({FTN_URL}), licensed {CC_BY_SA_NAME} ({CC_BY_SA_URL}). "
    "Derived charting data we share is released under the same license.\n"
)
_NOTICE_TAIL = (
    "This project is not affiliated with or endorsed by nflverse, FTN, the NFL, or any team.\n"
    "Contract and coaching-staff tables are compiled by RidgetopWalker LLC from public reports, "
    "are approximate, and may be out of date. sportsdataverse-py is MIT-licensed; data it fetches "
    "comes from third-party sources and is not nflverse data.\n"
)

README_LICENSE_LINE = (
    f"Code: MIT (see LICENSE). Data: nflverse ({NFLVERSE_URL}), {CC_BY_NAME} ({CC_BY_URL}); "
    "we aggregate and derive statistics from it. "
    "Optional Python backend: sportsdataverse-py (https://github.com/sportsdataverse/sportsdataverse-py, MIT). "
    "Contract and coaching-staff tables are compiled by us from public reports. See NOTICE. "
    "Not affiliated with or endorsed by the NFL, nflverse, sportsdataverse, Over The Cap, or Spotrac."
)


def render_notice(ftn: bool = False) -> str:
    """Return the NOTICE text; the FTN credit paragraph is included only when ``ftn`` is true."""
    return _NOTICE_HEAD + (_NOTICE_FTN if ftn else "") + _NOTICE_TAIL


class DataSource:
    """What produced the rows behind the current results (kind + label + loaded datasets)."""

    def __init__(self, kind: str = SOURCE_SAMPLE, label: str = LABEL_SAMPLE,
                 datasets: Optional[List[str]] = None) -> None:
        self.kind = kind
        self.label = label
        self.datasets: List[str] = list(datasets) if datasets else []
        self.loaded = False  # True once a data bridge has reported a source

    @property
    def ftn_loaded(self) -> bool:
        return DATASET_FTN in self.datasets and self.kind == SOURCE_NFLVERSE


def classify_source(label: Optional[str]) -> str:
    """Map a ``last_source_used`` label to a source kind. Anything unrecognised is NOT nflverse."""
    low = (label or "").lower()
    if not low or "sample" in low or "built-in" in low or "offline" in low or "demo" in low:
        return SOURCE_SAMPLE
    if "sportsdataverse" in low or "sdv" in low:
        return SOURCE_SPORTSDATAVERSE
    if "nflreadpy" in low or "nfl_data_py" in low or "nflreadr" in low or "nflverse" in low:
        return SOURCE_NFLVERSE
    return SOURCE_SAMPLE


# Process-wide "active" source, updated whenever the data bridge reports a new source.
# Single-user CLI state; web callers should pass an explicit ``DataSource`` instead.
_ACTIVE = DataSource()


def active_source() -> DataSource:
    return _ACTIVE


def set_active_source(label: Optional[str], datasets: Optional[List[str]] = None) -> DataSource:
    """Record the backend that really produced the rows (called by ``NFLDataBridge``)."""
    global _ACTIVE
    kind = classify_source(label)
    ds = list(datasets) if datasets is not None else ([DATASET_PBP] if kind != SOURCE_SAMPLE else [])
    # Keep optional datasets (FTN) registered earlier in the session while the same kind stays active.
    if datasets is None and kind == _ACTIVE.kind and DATASET_FTN in _ACTIVE.datasets:
        ds.append(DATASET_FTN)
    _ACTIVE = DataSource(kind, label or LABEL_SAMPLE, ds)
    _ACTIVE.loaded = True
    return _ACTIVE


def register_loaded_dataset(dataset: str) -> None:
    """Record that an additional dataset (e.g. ``ftn_charting``) was really loaded."""
    if dataset not in _ACTIVE.datasets:
        _ACTIVE.datasets.append(dataset)


def reset_active_source() -> None:
    global _ACTIVE
    _ACTIVE = DataSource()


# --- CLI footers -----------------------------------------------------------------------

def footer_text(source: Optional[DataSource] = None) -> str:
    """One-line footer for results, chosen by what actually produced them."""
    src = source or _ACTIVE
    if src.kind == SOURCE_SAMPLE:
        return "Sample data (bundled demo rows, not nflverse)"
    if src.kind == SOURCE_SPORTSDATAVERSE:
        return "Data: sportsdataverse-py (not nflverse; its own terms apply) · derived/aggregated by " + PRODUCT_NAME
    text = f"Data: nflverse ({CC_BY_NAME}) · {CC_BY_URL.split('://', 1)[1].rstrip('/')} · derived/aggregated by {PRODUCT_NAME}"
    if src.ftn_loaded:
        text += f"\nCharting: {FTN_NAME} ({CC_BY_SA_NAME}) · {CC_BY_SA_URL.split('://', 1)[1].rstrip('/')}"
    return text


# --- Export metadata -------------------------------------------------------------------

def csv_comment_lines(source: Optional[DataSource] = None) -> List[str]:
    """Leading ``#`` comment line(s) for CSV exports."""
    src = source or _ACTIVE
    if src.kind == SOURCE_SAMPLE:
        return [f"# Data: sample data (bundled demo rows, not nflverse) ; generated by {PRODUCT_NAME}"]
    if src.kind == SOURCE_SPORTSDATAVERSE:
        return [f"# Data: sportsdataverse-py (MIT library; fetched data is third-party, not nflverse) ; derived/aggregated by {PRODUCT_NAME}"]
    lines = [
        f"# Data: nflverse ({NFLVERSE_URL}), {CC_BY_NAME} {CC_BY_URL} ; "
        f"derived/aggregated by {PRODUCT_NAME} ; not endorsed by NFL or nflverse"
    ]
    if src.ftn_loaded:
        lines.append(
            f"# Charting data: {FTN_NAME} ({FTN_URL}), {CC_BY_SA_NAME} {CC_BY_SA_URL} ; "
            "derived charting data is shared under the same license"
        )
    return lines


def json_license_block(source: Optional[DataSource] = None) -> Dict[str, Any]:
    """Top-level ``license`` object for JSON exports."""
    src = source or _ACTIVE
    if src.kind == SOURCE_SAMPLE:
        return {"source": "sample", "note": "bundled demo rows, not nflverse", "generated_by": PRODUCT_NAME}
    if src.kind == SOURCE_SPORTSDATAVERSE:
        return {"source": "sportsdataverse-py", "note": "MIT library; fetched data is third-party, not nflverse",
                "changes": CHANGES_NOTE, "generated_by": PRODUCT_NAME}
    block: Dict[str, Any] = {
        "source": "nflverse",
        "source_url": NFLVERSE_URL,
        "license": CC_BY_ID,
        "license_url": CC_BY_URL,
        "changes": CHANGES_NOTE,
        "generated_by": PRODUCT_NAME,
        "endorsement": "not endorsed by the NFL or nflverse",
    }
    if src.ftn_loaded:
        block["ftn"] = {
            "source": FTN_NAME,
            "source_url": FTN_URL,
            "license": CC_BY_SA_ID,
            "license_url": CC_BY_SA_URL,
            "note": "derived charting data is shared under the same license",
        }
    return block


def text_footer_lines(source: Optional[DataSource] = None) -> List[str]:
    """Footer lines appended to plain-text exports."""
    return footer_text(source).split("\n")


# --- about / --about -------------------------------------------------------------------

def about_text(source: Optional[DataSource] = None) -> str:
    """Full NOTICE (FTN paragraph only if FTN is loaded) plus a note about the active source."""
    src = source or _ACTIVE
    parts = [render_notice(ftn=src.ftn_loaded).rstrip("\n")]
    if not src.loaded:
        return parts[0]
    parts.append("")
    if src.kind == SOURCE_SAMPLE:
        parts.append("Current data: sample data (bundled demo rows, not nflverse).")
    elif src.kind == SOURCE_SPORTSDATAVERSE:
        parts.append("Current data: sportsdataverse-py backend. That data is not nflverse and is not covered "
                     "by the nflverse notice above; check its own terms before redistributing.")
    else:
        parts.append(f"Current data: {src.label}.")
    return "\n".join(parts)


# Slash commands whose output is built from the loaded play-by-play rows (these get the data footer).
# An allowlist on purpose: static/bundled data (coaches, contracts, payrolls) is not nflverse and must
# not be credited as such; a new command gets no footer until it is added here.
DATA_SLASH_COMMANDS = frozenset({
    "/stat", "/leaderboard", "/team", "/team-stats", "/team-drilldown", "/player", "/player-stats",
    "/player-drilldown", "/play", "/diagram", "/field", "/games", "/game", "/matchup", "/matchups",
    "/boxscore", "/pbp", "/fantasy", "/fant", "/fp", "/sportsbook", "/odds", "/handicap", "/lines",
    "/betting", "/projections", "/projection", "/model", "/query", "/filter", "/page", "/stat-page", "/example", "/examples", "/ex", "/qb-wins",
    "/screen-pass", "/play-efficiency",
})

# Natural-language intents whose answer is built from play-by-play rows.
DATA_INTENTS = frozenset({
    "stat_query", "specific_play", "qb_wins_report", "team_drilldown", "player_drilldown",
    "fantasy_report", "sportsbook_report", "dataset_info", "stat_page", "create_stat",
})


def wants_footer(cmd_token: str) -> bool:
    return cmd_token.lower() in DATA_SLASH_COMMANDS


def wants_footer_for_intent(parsed: Optional[Dict[str, Any]]) -> bool:
    """True when a parsed natural-language query was answered from play-by-play rows."""
    parsed = parsed or {}
    intent = parsed.get("intent")
    if intent in DATA_INTENTS:
        return True
    # Contract answers are bundled third-party data, except the per-player view that adds nflverse EPA.
    return intent == "contract_report" and parsed.get("subquery") == "player"


