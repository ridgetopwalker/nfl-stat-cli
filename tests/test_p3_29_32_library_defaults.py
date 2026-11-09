"""Regression tests for #29 (library default is no local-model probe) and #32 (structured results, colour not process-wide)."""
import json
import urllib.request

import pytest

import nfl_stat_cli as cli

PLAYS = cli.SAMPLE_PBP_PLAYS  # note: other tests may reload the module, so always reach classes through `cli.` at call time


@pytest.fixture
def engine(tmp_path):
    return cli.StatEngine(storage_dir=tmp_path)


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("the library default must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.delenv("NFL_STAT_SLM_MODEL", raising=False)
    return calls


# ---------------------------------------------------------------- #29

def test_interpret_query_default_does_not_probe_ollama(engine, no_network):
    parsed = cli.NaturalLanguageStatAssistant.interpret_query("epa per play", engine=engine, default_season=2024)
    assert parsed["intent"] == "stat_query" and not parsed.get("slm_model_used")
    assert no_network == []


def test_interpret_query_default_ignores_the_slm_env_var(engine, no_network, monkeypatch):
    monkeypatch.setenv("NFL_STAT_SLM_MODEL", "qwen2.5:1.5b")
    cli.NaturalLanguageStatAssistant.interpret_query("epa per play", engine=engine, default_season=2024)
    assert no_network == []


def test_explicit_auto_still_probes(engine, monkeypatch):
    seen = []
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: seen.append(requested) or None))
    cli.NaturalLanguageStatAssistant.interpret_query("epa per play", engine=engine, slm_model="auto", default_season=2024)
    assert seen == ["auto"]


def test_explicit_off_never_probes(engine, monkeypatch):
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: pytest.fail("probed")))
    cli.NaturalLanguageStatAssistant.interpret_query("epa per play", engine=engine, slm_model="off", default_season=2024)


def test_cli_ask_keeps_auto_by_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = []
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: seen.append(requested) or None))
    cli.main(["ask", "epa per play", "--season", "2024", "--engine", "offline", "--no-color"])
    assert seen and seen[0] == "auto"


def test_cli_ask_respects_slm_off(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: pytest.fail("probed")))
    cli.main(["ask", "epa per play", "--season", "2024", "--engine", "offline", "--no-color", "--slm-model", "off"])


def test_tui_defaults_to_auto_detection(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: seen.append(requested) or None))
    monkeypatch.setattr(cli, "prompt_input", lambda prompt: "/quit")
    eng = cli.StatEngine(storage_dir=tmp_path)
    bridge = cli.NFLDataBridge(cache_dir=tmp_path / "c", engine="offline")
    try:
        cli.interactive_tui(eng, bridge, slm_model=None, default_season=2024, initial_plays=list(PLAYS))
    except SystemExit:
        pass
    assert seen and seen[0] == "auto"


# ---------------------------------------------------------------- #32

def test_answer_query_returns_structured_ansi_free_result(engine, no_network):
    r = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    assert isinstance(r, cli.QueryResult)
    assert r.intent == "stat_query" and r.answered and r.stat_name == "epa_per_play"
    assert r.records and {"entity", "team", "value", "plays"} <= set(r.records[0])
    assert "best_play" not in r.records[0] and "metrics" not in r.records[0]
    assert "\x1b" not in r.text and "epa" in r.text.lower()
    assert json.loads(json.dumps(r.to_dict(), allow_nan=False))["records"] == r.records
    assert r.title and "\x1b" not in r.title


def test_answer_query_limit_and_ordering(engine):
    full = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    one = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024, limit=1)
    assert len(one.records) == 1 and one.records[0] == full.records[0]
    assert len(full.records) > 1
    values = [r["value"] for r in full.records]
    assert values == sorted(values, reverse=True)


def test_answer_query_does_not_change_process_wide_colour(engine):
    before = cli.C.snapshot()
    cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    assert cli.C.snapshot() == before
    if before["RED"]:
        assert cli.C.RED.startswith("\x1b")


def test_answer_query_ambiguous_is_unanswered(engine):
    r = cli.answer_query("blorp zzz qqq", engine, PLAYS, default_season=2024)
    assert r.intent == "ambiguous" and r.answered is False and r.records == []
    assert "\x1b" not in r.text


@pytest.mark.parametrize("query", ["delete stat yards_per_play", "export results to out_x.csv", "create stat foo = plays + 1"])
def test_answer_query_never_mutates(engine, tmp_path, monkeypatch, query):
    monkeypatch.chdir(tmp_path)
    r = cli.answer_query(query, engine, PLAYS, default_season=2024)
    assert r.intent in ("delete_stat", "export_data", "create_stat")
    assert r.answered is False and "does not" in r.text
    assert "yards_per_play" in engine.stats and "foo" not in engine.stats
    assert not list(tmp_path.glob("*.csv")) and not list(tmp_path.glob("*.json"))


def test_answer_query_does_not_prompt(engine, monkeypatch):
    monkeypatch.setattr(cli, "prompt_input", lambda *a, **k: pytest.fail("prompted"))
    cli.answer_query("show me Patrick", engine, PLAYS, default_season=2024)


def test_colour_snapshot_and_restore_roundtrip():
    saved = cli.C.snapshot()
    try:
        cli.C.disable()
        assert cli.C.RED == ""
    finally:
        cli.C.restore(saved)
    assert cli.C.snapshot() == saved


def test_main_no_color_does_not_leak_into_the_process(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    before = cli.C.snapshot()
    cli.main(["list-stats", "--no-color"])
    assert cli.C.snapshot() == before


def test_main_restores_colour_even_when_the_command_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    before = cli.C.snapshot()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "render_stats_catalog", boom)
    try:
        cli.main(["list-stats", "--no-color"])
    except BaseException:
        pass
    assert cli.C.snapshot() == before


def test_jsonable_removes_nan_and_control_characters():
    out = cli._jsonable({"a\x1b[2J": [float("nan"), float("inf"), 1.5, "x\x07y\x1b]0;t\x07z", ("t", {1})], "b": object()})
    assert json.dumps(out, allow_nan=False)
    assert out["a"][0] is None and out["a"][1] is None and out["a"][2] == 1.5
    assert "\x07" not in json.dumps(out) and "\x1b" not in json.dumps(out)


def test_answer_query_records_are_strict_json_even_with_nan_values(engine, monkeypatch):
    orig = cli.StatEngine.evaluate_stat_leaderboard

    def with_nan(self, *a, **k):
        rows = orig(self, *a, **k)
        for r in rows:
            r["value"] = float("nan")
        return rows

    monkeypatch.setattr(cli.StatEngine, "evaluate_stat_leaderboard", with_nan)
    r = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    assert r.records and all(rec["value"] is None for rec in r.records)
    json.dumps(r.to_dict(), allow_nan=False)


def test_answer_query_restores_the_last_result_globals(engine, monkeypatch):
    mine = {"title": "mine", "headers": ["h"], "rows": [["r"]]}
    monkeypatch.setattr(cli, "LAST_RENDERED_TABLE", mine)
    monkeypatch.setattr(cli, "LAST_RAW_OUTPUT", "mine")
    monkeypatch.setattr(cli, "LAST_RESULT_RECORDS", [{"mine": 1}])
    seen_during = []
    orig = cli.handle_nl_query_result

    def spy(*a, **k):
        out = orig(*a, **k)
        seen_during.append(cli.LAST_RENDERED_TABLE)
        return out

    monkeypatch.setattr(cli, "handle_nl_query_result", spy)
    cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    assert seen_during and seen_during[0] is not mine  # the renderer really did overwrite it during the call
    assert cli.LAST_RENDERED_TABLE is mine and cli.LAST_RAW_OUTPUT == "mine" and cli.LAST_RESULT_RECORDS == [{"mine": 1}]


def test_answer_query_strips_control_characters_from_user_text(engine):
    r = cli.answer_query("epa per play 2024 \x1b[31m\x07", engine, PLAYS, default_season=2024)
    blob = json.dumps(r.to_dict())
    assert "\\u001b" not in blob and "\\u0007" not in blob


@pytest.mark.parametrize("query", ["blorp zzz qqq", "show me Mahomes", "Chiefs team stats 2024", "Patrick Mahomes player stats 2024"])
def test_answer_query_never_prompts_for_any_read_intent(engine, monkeypatch, no_network, query):
    import builtins
    monkeypatch.setattr(cli, "prompt_input", lambda *a, **k: pytest.fail("prompted"))
    monkeypatch.setattr(builtins, "input", lambda *a, **k: pytest.fail("input() called"))
    r = cli.answer_query(query, engine, PLAYS, default_season=2024)
    assert isinstance(r.text, str) and r.text and r.intent


def test_model_chosen_mutating_intents_are_refused(engine, monkeypatch):
    monkeypatch.setattr(cli.NaturalLanguageStatAssistant, "detect_ollama_model", classmethod(lambda cls, requested=None: "fake-model"))
    for intent in ("delete_stat", "create_stat", "stat_page", "export_data", "export_stats"):
        monkeypatch.setattr(
            cli.NaturalLanguageStatAssistant, "query_local_slm",
            classmethod(lambda cls, q, e, m, intent=intent: {"intent": intent, "stat_name": "yards_per_play", "query": q, "target_file": "x.csv"}),
        )
        r = cli.answer_query("anything", engine, PLAYS, slm_model="auto", default_season=2024)
        assert r.answered is False and "does not" in r.text, intent
    assert "yards_per_play" in engine.stats


def test_answer_query_limit_is_applied_to_text_and_records(engine):
    full = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024)
    one = cli.answer_query("epa per play 2024", engine, PLAYS, default_season=2024, limit=1)
    assert len(one.records) == 1 and len(full.records) > 1
    assert full.records[1]["entity"] in full.text and full.records[1]["entity"] not in one.text
