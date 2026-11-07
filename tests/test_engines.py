"""The list of engines, and the live analysis and the Evolution job each using their own."""

import shutil

import chess
import pytest

from uciboard import config, engines
from uciboard.api import Api
from uciboard.uci import EngineError

from conftest import wait_for


# ------------------------------------------------------------------ options as text

def test_options_are_read_one_per_line():
    text = "Threads=4\n\n# a comment\n WeightsFile = C:/nets/BT4.pb.gz \nSyzygyPath=D:/tb"
    assert engines.parse_options(text) == {"Threads": "4", "WeightsFile": "C:/nets/BT4.pb.gz",
                                           "SyzygyPath": "D:/tb"}
    assert engines.parse_options(engines.options_text({"Hash": "64", "Backend": "cuda-fp16"})) == {
        "Hash": "64", "Backend": "cuda-fp16"}
    assert engines.parse_options("   \n") == {}


@pytest.mark.parametrize("text", ["Threads 4", "=4", "Hash=1\noops"])
def test_a_line_that_is_not_an_option_is_an_error_not_silently_ignored(text):
    with pytest.raises(ValueError, match="Name=value"):
        engines.parse_options(text)


# ------------------------------------------------------------------ the registry

def test_the_default_is_listed_first_and_chosen_until_told_otherwise():
    r = engines.Registry("/usr/bin/stockfish")
    assert [e.id for e in r.all()] == ["default"]
    assert r.resolve("live").id == r.resolve("evolution").id == "default"
    assert engines.Registry("").resolve("live") is None            # nothing set up


def test_added_engines_get_unique_names_and_ids():
    r = engines.Registry("/usr/bin/stockfish")
    a = r.add("C:/engines/lc0.exe", "Lc0")
    b = r.add("D:/other/lc0.exe", "Lc0")
    c = r.add("D:/x/Some Engine.exe", "")
    assert (a.id, b.id, c.id) == ("e1", "e2", "e3")
    assert (a.name, b.name, c.name) == ("Lc0", "Lc0 (2)", "Some Engine")
    r.remove("e2")
    assert r.add("E:/y.exe", "Y").id == "e4"                        # new ids follow the highest in use
    assert len({e.id for e in r.all()}) == len(r.all())


def test_the_two_jobs_choose_separately_and_removal_falls_back_to_the_default():
    r = engines.Registry("/usr/bin/stockfish")
    lc0 = r.add("C:/lc0.exe", "Lc0")
    r.choose("live", lc0.id)
    assert (r.resolve("live").id, r.resolve("evolution").id) == (lc0.id, "default")
    r.choose("evolution", lc0.id)
    r.remove(lc0.id)
    assert (r.resolve("live").id, r.resolve("evolution").id) == ("default", "default")
    with pytest.raises(KeyError):
        r.choose("live", "nope")
    with pytest.raises(KeyError):
        r.choose("sideways", "default")


def test_a_chosen_engine_that_has_gone_falls_back_to_what_there_is():
    r = engines.Registry("")                                       # no default found
    e = r.add("C:/lc0.exe", "Lc0")
    r.choose("live", e.id)
    r.added.clear()
    assert r.resolve("live") is None
    r.default_path = "/usr/bin/stockfish"
    assert r.resolve("live").id == "default"


def test_updating_checks_the_name_and_cannot_touch_the_default():
    r = engines.Registry("/usr/bin/stockfish")
    a, b = r.add("a.exe", "A"), r.add("b.exe", "B")
    r.update(a.id, "Alpha", {"Threads": "2"})
    assert r.get(a.id).name == "Alpha" and r.get(a.id).options == {"Threads": "2"}
    with pytest.raises(ValueError, match="already an engine called"):
        r.update(b.id, "Alpha", {})
    with pytest.raises(KeyError):
        r.update("default", "X", {})


def test_the_list_and_the_choices_are_kept_between_runs(tmp_path):
    file = tmp_path / "sub" / "engines.json"
    r = engines.Registry("/usr/bin/stockfish", file=file)
    e = r.add("C:/lc0.exe", "Lc0")
    r.update(e.id, "Lc0", {"WeightsFile": "C:/n.pb.gz"})
    r.choose("evolution", e.id)
    again = engines.Registry("/usr/bin/stockfish", file=file)
    (got,) = again.added
    assert (got.id, got.name, got.path, got.options) == (e.id, "Lc0", "C:/lc0.exe", {"WeightsFile": "C:/n.pb.gz"})
    assert again.choice == {"live": "default", "evolution": e.id}


def test_a_damaged_file_is_ignored_and_reported(tmp_path):
    file = tmp_path / "engines.json"
    file.write_text("{ not json", encoding="utf-8")
    r = engines.Registry("/usr/bin/stockfish", file=file)
    assert r.added == [] and "Cannot read" in r.error
    assert [e.id for e in r.all()] == ["default"]                  # still usable
    file.write_text('{"engines": [{"id": "e1"}]}', encoding="utf-8")   # valid JSON, wrong shape
    assert "Cannot read" in engines.Registry("/usr/bin/stockfish", file=file).error


# ------------------------------------------------------------------ probing a program

@pytest.mark.engine
def test_probe_reads_the_engine_name(stockfish):
    assert engines.probe(stockfish).startswith("Stockfish")


def test_probe_refuses_a_missing_file_and_a_program_that_is_not_an_engine(tmp_path):
    with pytest.raises(EngineError, match="No file"):
        engines.probe(str(tmp_path / "nothing.exe"))
    cat = shutil.which("cat")
    if cat is None:
        pytest.skip("needs a program that answers nothing")
    with pytest.raises(EngineError, match="did not answer"):
        engines.probe(cat, timeout=1.0)


# ------------------------------------------------------------------ the Api

def make_api(tmp_path, stockfish, analyse=True):
    s = config.load_settings(stockfish=stockfish, own_config=tmp_path / "none.toml", analyse=analyse)
    s.cache_dir = str(tmp_path / "cache")
    s.threads, s.evo_depth, s.evo_seconds, s.evo_check_depth = 1, 5, 4.0, 4
    return Api(s)


@pytest.mark.engine
def test_the_list_can_be_edited_through_the_api(stockfish, tmp_path):
    api = make_api(tmp_path, stockfish, analyse=False)
    try:
        before = api.engines()
        assert [e["id"] for e in before["engines"]] == ["default"] and before["live"] == "default"
        r = api.add_engine(stockfish, "Second")
        assert r["ok"] and r["added"] == "e1" and [e["name"] for e in r["engines"]][-1] == "Second"
        assert api.add_engine(str(tmp_path / "nope.exe"))["ok"] is False
        assert api.update_engine("e1", "Second", "Hash 16")["ok"] is False        # not Name=value
        assert api.update_engine("e1", "Second", "Hash=16")["engines"][-1]["options"] == "Hash=16"
        assert api.update_engine("default", "x", "")["ok"] is False
        assert api.remove_engine("default")["ok"] is False
        assert api.choose_engine("live", "zzz")["ok"] is False
        assert api.remove_engine("e1")["ok"] and [e["id"] for e in api.engines()["engines"]] == ["default"]
        assert (tmp_path / "engines.json").exists()                           # kept for next time
    finally:
        api.shutdown()


@pytest.mark.engine
def test_choosing_the_live_engine_restarts_it_and_keeps_analysis_off_or_on(stockfish, tmp_path):
    api = make_api(tmp_path, stockfish)
    try:
        api.start()
        assert api.poll(0)["engine"]["id"] == "default"
        api.add_engine(stockfish, "Second")
        api.update_engine("e1", "Second", "Threads=2\nHash=32")
        r = api.choose_engine("live", "e1")
        assert r["ok"] and r["live"] == "e1" and r["evolution"] == "default"       # the jobs are separate
        wait_for(lambda: (p := api.poll(0))["engine"]["id"] == "e1" and p["engine"]["state"] == "analysing")
        wait_for(lambda: api.poll(0)["summary"].get("depth", 0) >= 4)
        stats = api.poll(0)["uci"]["stats"]
        assert (stats["threads"], stats["hash_mb"]) == ("2", "32")                 # this engine's own options
        api.pause()
        api.choose_engine("live", "default")                                       # switching keeps it stopped
        wait_for(lambda: api.poll(0)["engine"]["id"] == "default")
        assert api.poll(0)["engine"]["state"] == "off"
        stats = api.poll(0)["uci"]["stats"]
        assert stats["threads"] == 1
    finally:
        api.shutdown()


@pytest.mark.engine
def test_evolution_uses_its_own_engine_and_keeps_its_results_apart(stockfish, tmp_path):
    api = make_api(tmp_path, stockfish)
    try:
        api.add_engine(stockfish, "Second")
        api.choose_engine("evolution", "e1")
        assert api.engines()["live"] == "default"                                  # live is untouched
        api.move("e2", "e4")
        api.move("e7", "e5")

        def run():
            assert api.evolution_start({"depth": 4, "lines": 4, "check_depth": 3, "seconds": 3})["started"]
            status = wait_for(lambda: (s := api.evolution_status())["state"] != "running" and s, 90)
            assert status["state"] == "done", status
            return api.evolution_result()

        assert run()["engine"] == "Second"
        api.choose_engine("evolution", "default")
        assert run()["engine"] == "Stockfish (auto)"
        assert len(list((tmp_path / "cache").glob("*.json"))) == 2                 # one analysis per engine
        api.choose_engine("evolution", "e1")
        assert run()["engine"] == "Second"
        assert len(list((tmp_path / "cache").glob("*.json"))) == 2                 # the first was reused
    finally:
        api.shutdown()


def test_evolution_with_a_chosen_engine_that_has_gone_says_so(tmp_path):
    s = config.load_settings(own_config=tmp_path / "none.toml")
    s.stockfish_path = ""
    api = Api(s)
    api._registry.add(str(tmp_path / "gone.exe"), "Gone")
    api.choose_engine("evolution", "e1")
    api.move("e2", "e4")
    msg = api.evolution_start()["message"]
    assert "Gone" in msg and "no program" in msg


def test_the_default_engine_keeps_the_old_cache_key():
    from uciboard.evolution import Params, cache_key
    p = Params()
    assert cache_key(chess.STARTING_FEN, ["e2e4"], p, "") == cache_key(chess.STARTING_FEN, ["e2e4"], p)
    assert cache_key(chess.STARTING_FEN, ["e2e4"], p, "lc0|{}") != cache_key(chess.STARTING_FEN, ["e2e4"], p)
