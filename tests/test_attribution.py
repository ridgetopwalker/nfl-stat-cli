"""Issue #12: nflverse CC BY attribution, accurate source labels, and license metadata in exports."""
import csv
import io
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import nfl_stat_cli as cli
from nfl_stat_cli import attribution as attr

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_source():
    attr.reset_active_source()
    yield
    attr.reset_active_source()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _env(home):
    env = dict(os.environ)
    env.update({"HOME": str(home), "USERPROFILE": str(home), "NFL_STAT_SLM_MODEL": "off"})
    return env


def _run(home, *args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "nfl_stat_cli", *args],
        input=stdin, capture_output=True, text=True, env=_env(home), cwd=str(ROOT), timeout=120,
    )


# --- NOTICE / README ---------------------------------------------------------------------

def test_notice_file_matches_generated_text_and_required_credit():
    text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert text == attr.render_notice()
    assert "https://github.com/nflverse/nflverse-data" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text
    assert "CC BY 4.0" in text
    assert "Changes:" in text and "derived statistics" in text
    assert "not affiliated with or endorsed by" in text
    assert "MIT" in text and "code only" in text
    # FTN paragraph only appears when FTN data is loaded
    assert "CC BY-SA 4.0" not in text
    ftn = attr.render_notice(ftn=True)
    assert "FTN Data via nflverse" in ftn and "https://creativecommons.org/licenses/by-sa/4.0/" in ftn


def test_readme_license_section_carries_attribution():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert attr.README_LICENSE_LINE in readme
    assert "See NOTICE" in readme
    assert "CC BY 4.0" in readme


def test_notice_is_tracked_and_not_excluded_from_the_sdist():
    """setuptools ships NOTICE* by default (checked by building the sdist); guard against ignoring/excluding it."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(l.strip().lstrip("/").upper() in ("NOTICE", "NOTICE*") for l in gitignore)
    manifest_path = ROOT / "MANIFEST.in"
    manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    assert not re.search(r"^(?:global-)?(?:exclude|prune)\s+.*NOTICE", manifest, re.M)


# --- product name is a single constant -----------------------------------------------------

def test_product_name_is_the_only_hardcoded_brand_in_attribution_text():
    """The product name's value appears once (its definition), so a rebrand is a one-line edit."""
    src = Path(attr.__file__).read_text(encoding="utf-8")
    hits = [ln for ln in src.splitlines() if attr.PRODUCT_NAME.lower() in ln.lower()]
    assert len(hits) == 1 and hits[0].startswith("PRODUCT_NAME = "), hits
    # and no other spelling of the old brand is hard-coded in the credit text
    assert not [ln for ln in src.splitlines() if re.search(r"nfl[-_ ]stat", ln, re.I) and not ln.startswith("PRODUCT_NAME = ")]


def test_changing_product_name_changes_every_user_facing_credit(monkeypatch):
    monkeypatch.setattr(attr, "PRODUCT_NAME", "Zed Product")
    attr.set_active_source(attr.LABEL_NFLREADPY)
    assert "Zed Product" in attr.footer_text()
    assert "Zed Product" in attr.csv_comment_lines()[0]
    assert attr.json_license_block()["generated_by"] == "Zed Product"
    attr.set_active_source(attr.LABEL_SAMPLE)
    assert "Zed Product" in attr.csv_comment_lines()[0]


# --- source classification and bridge labels -----------------------------------------------

@pytest.mark.parametrize("label,kind", [
    (attr.LABEL_NFLREADPY, "nflverse"),
    (attr.LABEL_NFL_DATA_PY, "nflverse"),
    (attr.LABEL_NFLREADR, "nflverse"),
    (attr.LABEL_SPORTSDATAVERSE, "sportsdataverse"),
    (attr.LABEL_SAMPLE, "sample"),
    ("built-in nflverse/sdv offline dataset", "sample"),   # the old mislabel is never treated as nflverse
    ("SAMPLE DATA - built-in demo plays, NOT live NFL data", "sample"),
    ("", "sample"),
    (None, "sample"),
    ("something unknown", "sample"),
])
def test_classify_source(label, kind):
    assert attr.classify_source(label) == kind


def _fake_df(rows):
    class DF:
        def to_pandas(self):
            return self

        def to_dict(self, orient="records"):
            return [dict(r) for r in rows]

    return DF()


def _live_rows():
    return [{
        "posteam": "KC", "defteam": "BUF", "season": 2025, "week": 1, "game_id": "2025_01_BUF_KC",
        "play_id": 1, "pass_attempt": 1, "play_type": "pass", "qtr": 1, "yards_gained": 7, "epa": 0.2,
        "home_score": 7, "away_score": 0, "passer_player_name": "P.Mahomes",
    }]


def _install_backends(monkeypatch, working):
    """Make only the named python backends importable, each returning one live-looking row."""
    rows = _live_rows()
    for name in ("nflreadpy", "nfl_data_py", "sportsdataverse", "sportsdataverse.nfl"):
        monkeypatch.setitem(sys.modules, name, None)  # None -> ImportError on import
    if "nflreadpy" in working:
        m = types.ModuleType("nflreadpy")
        m.load_pbp = lambda seasons=None: _fake_df(rows)
        monkeypatch.setitem(sys.modules, "nflreadpy", m)
    if "nfl_data_py" in working:
        m = types.ModuleType("nfl_data_py")
        m.import_pbp_data = lambda seasons, downcast=True: _fake_df(rows)
        monkeypatch.setitem(sys.modules, "nfl_data_py", m)
    if "sportsdataverse" in working:
        parent = types.ModuleType("sportsdataverse")
        child = types.ModuleType("sportsdataverse.nfl")
        child.load_nfl_pbp = lambda seasons=None, return_as_pandas=True: _fake_df(rows)
        parent.nfl = child
        monkeypatch.setitem(sys.modules, "sportsdataverse", parent)
        monkeypatch.setitem(sys.modules, "sportsdataverse.nfl", child)


@pytest.mark.parametrize("working,label,kind", [
    (("nflreadpy", "nfl_data_py", "sportsdataverse"), attr.LABEL_NFLREADPY, "nflverse"),
    (("nfl_data_py", "sportsdataverse"), attr.LABEL_NFL_DATA_PY, "nflverse"),
    (("sportsdataverse",), attr.LABEL_SPORTSDATAVERSE, "sportsdataverse"),
])
def test_last_source_used_reports_the_backend_that_really_loaded(tmp_path, monkeypatch, working, label, kind):
    _install_backends(monkeypatch, working)
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="python")
    rows = bridge.load_pbp([2025])
    assert rows and rows[0]["posteam"] == "KC"
    assert bridge.last_source_used == label
    assert bridge.last_source_kind == kind
    assert attr.active_source().kind == kind
    if kind == "sportsdataverse":
        assert "nflverse" in label and "not nflverse" in label
        assert "CC BY" not in attr.footer_text()


def test_sample_fallback_never_claims_nflverse(tmp_path, monkeypatch):
    _install_backends(monkeypatch, ())
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="python")
    assert bridge.last_source_kind == "sample"          # before any load
    rows = bridge.load_pbp([2025])
    assert rows
    assert bridge.last_source_used == attr.LABEL_SAMPLE
    assert bridge.last_source_kind == "sample"
    assert attr.footer_text() == "Sample data (bundled demo rows, not nflverse)"
    for text in (bridge.last_source_used, attr.footer_text(), *attr.csv_comment_lines(),
                 json.dumps(attr.json_license_block())):
        assert "CC BY" not in text and "CC-BY" not in text
        assert "nflverse" not in text.replace("not nflverse", "")


def test_r_backend_is_labelled_nflverse(tmp_path, monkeypatch):
    _install_backends(monkeypatch, ())
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="r")
    monkeypatch.setattr(bridge, "_try_nflverse_r", lambda seasons, spinner=None: bridge._normalize_dataframe(_fake_df(_live_rows())))
    assert bridge.load_pbp([2025])
    assert bridge.last_source_used == attr.LABEL_NFLREADR and bridge.last_source_kind == "nflverse"


# --- footer text ---------------------------------------------------------------------------

def test_nflverse_footer_matches_the_lawyer_wording():
    attr.set_active_source(attr.LABEL_NFLREADPY)
    assert attr.footer_text() == (
        f"Data: nflverse (CC BY 4.0) · creativecommons.org/licenses/by/4.0 · derived/aggregated by {attr.PRODUCT_NAME}"
    )


def test_ftn_footer_only_when_ftn_dataset_registered():
    attr.set_active_source(attr.LABEL_NFLREADPY)
    assert "FTN" not in attr.footer_text()
    attr.register_loaded_dataset(attr.DATASET_FTN)
    foot = attr.footer_text()
    assert "FTN Data via nflverse" in foot and "CC BY-SA 4.0" in foot
    # a later pbp reload keeps the FTN credit while the same backend stays active
    attr.set_active_source(attr.LABEL_NFLREADPY)
    assert "FTN" in attr.footer_text()
    # ...but sample data never carries FTN credit even if something registered it
    attr.set_active_source(attr.LABEL_SAMPLE)
    attr.register_loaded_dataset(attr.DATASET_FTN)
    assert "FTN" not in attr.footer_text()
    assert "FTN" not in "\n".join(attr.csv_comment_lines())
    assert "ftn" not in attr.json_license_block()


# --- CLI output ----------------------------------------------------------------------------

def test_cli_stat_output_ends_with_sample_footer_and_no_nflverse_claim(tmp_path, isolated_home):
    res = _run(isolated_home, "stat", "yards_per_play", "--engine", "offline", "--season", "2025", "--no-color")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "Sample data (bundled demo rows, not nflverse)" in out
    assert "Data: nflverse (CC BY 4.0)" not in out
    assert "built-in nflverse" not in out
    assert out.rstrip().splitlines()[-1].strip() == "Sample data (bundled demo rows, not nflverse)"


def test_cli_ask_prints_footer_but_ambiguous_does_not(tmp_path, isolated_home):
    amb_parsed = cli.NaturalLanguageStatAssistant.interpret_query(
        "tell me something unrelated 2024 AFC Chiefs", engine=cli.StatEngine(storage_dir=tmp_path), slm_model="off")
    assert amb_parsed["intent"] == "ambiguous"
    ok = _run(isolated_home, "ask", "who has the most passing yards", "--engine", "offline", "--season", "2025",
              "--no-color", "--slm-model", "off")
    assert ok.returncode == 0, ok.stderr
    assert "Sample data (bundled demo rows, not nflverse)" in ok.stdout
    amb = _run(isolated_home, "ask", "tell me something unrelated 2024 AFC Chiefs", "--engine", "offline",
               "--no-color", "--slm-model", "off")
    assert amb.returncode == 0, amb.stderr
    assert "Sample data (bundled" not in amb.stdout


def test_cli_footer_nflverse_path(tmp_path, monkeypatch, isolated_home, capsys):
    _install_backends(monkeypatch, ("nflreadpy",))
    # one KC play in 2025 is enough for `stat` to render
    rc = cli.main(["stat", "yards_per_play", "--engine", "python", "--season", "2025"])
    out = cli.strip_ansi(capsys.readouterr().out)
    assert rc == 0
    assert f"Data: nflverse (CC BY 4.0) · creativecommons.org/licenses/by/4.0 · derived/aggregated by {attr.PRODUCT_NAME}" in out
    assert "Sample data" not in out
    assert "nflreadpy (Python)" in out   # banner line reports the real backend


def test_about_flag_and_subcommand_print_notice(isolated_home):
    for args in (("--about",), ("about",)):
        res = _run(isolated_home, *args)
        assert res.returncode == 0, res.stderr
        assert attr.render_notice().strip() in res.stdout
        assert "CC BY 4.0" in res.stdout
        assert "FTN Data via nflverse" not in res.stdout


def test_about_adds_ftn_paragraph_only_when_loaded():
    attr.set_active_source(attr.LABEL_NFLREADPY)
    assert "CC BY-SA" not in attr.about_text()
    attr.register_loaded_dataset(attr.DATASET_FTN)
    assert "FTN Data via nflverse" in attr.about_text()
    assert "CC BY-SA 4.0" in attr.about_text()


def test_about_for_sportsdataverse_says_not_nflverse():
    attr.set_active_source(attr.LABEL_SPORTSDATAVERSE)
    assert "not nflverse" in attr.about_text()


def test_tui_about_and_footer_and_unknown_command(isolated_home):
    stdin = "\n".join(["/about", "who has the most passing yards", "/bogus", "/camera sideline", "quit"]) + "\n"
    res = _run(isolated_home, "tui", "--engine", "offline", "--season", "2025", "--no-color", "--slm-model", "off", stdin=stdin)
    assert res.returncode == 0, res.stderr
    out = cli.strip_ansi(res.stdout)
    assert attr.render_notice().strip() in out
    assert out.count("Sample data (bundled demo rows, not nflverse)") == 1  # only after the stat answer
    assert "Unknown command `/bogus`" in out


# --- exports -------------------------------------------------------------------------------

@pytest.fixture
def records(monkeypatch):
    monkeypatch.setattr(cli, "LAST_RENDERED_TABLE", None)
    monkeypatch.setattr(cli, "LAST_RAW_OUTPUT", "")
    monkeypatch.setattr(cli, "LAST_RESULT_RECORDS", [{"team": "KC", "epa": 0.2}, {"team": "BUF", "epa": 0.1}])


def test_csv_export_first_line_is_the_license_comment_and_parses(tmp_path, records):
    attr.set_active_source(attr.LABEL_NFLREADPY)
    ok, _ = cli.export_last_result(tmp_path / "out.csv")
    assert ok
    lines = (tmp_path / "out.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == (
        "# Data: nflverse (https://github.com/nflverse/nflverse-data), CC BY 4.0 "
        f"https://creativecommons.org/licenses/by/4.0/ ; derived/aggregated by {attr.PRODUCT_NAME} ; "
        "not endorsed by NFL or nflverse"
    )
    assert lines[1] == "team,epa"
    parsed = list(csv.reader(l for l in lines if not l.startswith("#")))
    assert parsed == [["team", "epa"], ["KC", "0.2"], ["BUF", "0.1"]]
    assert not any("FTN" in l for l in lines)


def test_json_export_has_license_block(tmp_path, records):
    attr.set_active_source(attr.LABEL_NFLREADR)
    ok, _ = cli.export_last_result(tmp_path / "out.json")
    assert ok
    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    lic = data["license"]
    assert lic["source"] == "nflverse"
    assert lic["source_url"] == "https://github.com/nflverse/nflverse-data"
    assert lic["license"] == "CC-BY-4.0"
    assert lic["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert lic["changes"] == "filtered, aggregated, and derived statistics"
    assert "ftn" not in lic
    assert data["records"][0]["team"] == "KC"


def test_exports_add_ftn_only_when_ftn_loaded(tmp_path, records):
    attr.set_active_source(attr.LABEL_NFLREADPY)
    attr.register_loaded_dataset(attr.DATASET_FTN)
    cli.export_last_result(tmp_path / "f.csv")
    cli.export_last_result(tmp_path / "f.json")
    lines = (tmp_path / "f.csv").read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith("# Charting data: FTN Data via nflverse (https://ftndata.com), CC BY-SA 4.0 https://creativecommons.org/licenses/by-sa/4.0/")
    assert lines[2] == "team,epa"
    ftn = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))["license"]["ftn"]
    assert ftn["license"] == "CC-BY-SA-4.0" and ftn["source_url"] == "https://ftndata.com"


@pytest.mark.parametrize("label", [attr.LABEL_SAMPLE, attr.LABEL_SPORTSDATAVERSE])
def test_non_nflverse_exports_never_claim_cc_by(tmp_path, records, label):
    attr.set_active_source(label)
    cli.export_last_result(tmp_path / "x.csv")
    cli.export_last_result(tmp_path / "x.json")
    cli.export_last_result(tmp_path / "x.txt")
    for name in ("x.csv", "x.json", "x.txt"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "not nflverse" in text
        assert "CC BY" not in text and "CC-BY" not in text
        assert "creativecommons.org/licenses/by/4.0" not in text


def test_table_and_text_exports_carry_credit(tmp_path, monkeypatch):
    attr.set_active_source(attr.LABEL_NFLREADPY)
    monkeypatch.setattr(cli, "LAST_RESULT_RECORDS", None)
    monkeypatch.setattr(cli, "LAST_RENDERED_TABLE", {"title": "T", "headers": ["a", "b"], "rows": [["1", "2"]]})
    cli.export_last_result(tmp_path / "t.csv")
    cli.export_last_result(tmp_path / "t.json")
    assert (tmp_path / "t.csv").read_text(encoding="utf-8").startswith("# Data: nflverse")
    assert json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))["license"]["license"] == "CC-BY-4.0"
    monkeypatch.setattr(cli, "LAST_RENDERED_TABLE", None)
    monkeypatch.setattr(cli, "LAST_RAW_OUTPUT", "some text output")
    cli.export_last_result(tmp_path / "t.txt")
    cli.export_last_result(tmp_path / "t2.csv")
    cli.export_last_result(tmp_path / "t2.json")
    assert "Data: nflverse (CC BY 4.0)" in (tmp_path / "t.txt").read_text(encoding="utf-8")
    assert (tmp_path / "t2.csv").read_text(encoding="utf-8").startswith("# Data: nflverse")
    assert "license" in json.loads((tmp_path / "t2.json").read_text(encoding="utf-8"))


# --- datasets gate -------------------------------------------------------------------------

def _loader_calls():
    py = (ROOT / "nfl_stat_cli" / "__init__.py").read_text(encoding="utf-8")
    r = (ROOT / "nfl_stat_cli" / "nflverse_bridge.R").read_text(encoding="utf-8")
    calls = set(re.findall(r"\b(?:nfl|nfl_data|sdv_nfl)\.(\w+)\(", py))
    calls |= set(re.findall(r"nflreadr::(\w+)", r))
    calls |= set(re.findall(r'"pbp <- (\w+)\(', py))
    return calls


def test_only_reviewed_nflverse_datasets_are_loaded():
    """Attribution gate: adding a loader (FTN/NGS/PFR/ESPN/...) must come with a license review."""
    assert _loader_calls() == {"load_pbp", "import_pbp_data", "load_nfl_pbp", "load_teams"}
    forbidden = re.compile(r"ftn_charting|\b(?:load|import)_(?:ftn|nextgen|ngs|pfr|espn)\w*", re.I)
    for f in (ROOT / "nfl_stat_cli").rglob("*.py"):
        if f.name == "attribution.py":
            continue
        assert not forbidden.search(f.read_text(encoding="utf-8")), f.name


def test_no_ftn_dataset_is_loaded_by_the_bridge(tmp_path, monkeypatch):
    _install_backends(monkeypatch, ("nflreadpy",))
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "cache", engine="python")
    bridge.load_pbp([2025])
    assert attr.DATASET_FTN not in attr.active_source().datasets
    assert attr.active_source().datasets == [attr.DATASET_PBP]


def test_about_without_a_loaded_source_is_just_the_notice():
    assert attr.about_text() == attr.render_notice().rstrip("\n")
    attr.set_active_source(attr.LABEL_SAMPLE)
    assert "Current data: sample data" in attr.about_text()


def test_footer_allowlist_excludes_bundled_non_nflverse_data():
    assert attr.wants_footer("/stat") and attr.wants_footer("/FANTASY")
    assert attr.wants_footer("/projections") and attr.wants_footer("/sportsbook")
    for cmd in ("/coaches", "/contract", "/payroll", "/help", "/about", "/export", "/bogus", "/camera"):
        assert not attr.wants_footer(cmd), cmd
    assert attr.wants_footer_for_intent({"intent": "stat_query"})
    assert attr.wants_footer_for_intent({"intent": "contract_report", "subquery": "player"})
    for parsed in ({"intent": "contract_report", "subquery": "team"}, {"intent": "coaching_staff"},
                   {"intent": "ambiguous"}, {"intent": "export_data"}, {}, None):
        assert not attr.wants_footer_for_intent(parsed), parsed


def test_constructing_a_bridge_does_not_overwrite_the_active_source(tmp_path):
    attr.set_active_source(attr.LABEL_NFLREADPY)
    attr.register_loaded_dataset(attr.DATASET_FTN)
    cli.NFLDataBridge(cache_dir=tmp_path / "c2", engine="offline")   # e.g. a helper or failed reload
    assert attr.active_source().kind == "nflverse" and attr.DATASET_FTN in attr.active_source().datasets


def test_unidentified_python_backend_is_not_credited_as_nflverse():
    assert attr.classify_source(attr.LABEL_PYTHON_UNIDENTIFIED) == "sample"
