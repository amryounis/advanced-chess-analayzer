import time

import chess
import pytest

from uciboard import config
from uciboard.api import Api

from conftest import wait_for

SCHOLARS = """[Event "Casual"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0
"""

FIVE_PLIES = "1. e4 e5 2. Nf3 Nc6 3. Bb5 *"


def settings(tmp_path, stockfish=""):
    s = config.load_settings(stockfish=stockfish or None, own_config=tmp_path / "none.toml")
    s.cache_dir = str(tmp_path / "cache")
    s.evo_depth, s.evo_seconds, s.evo_check_depth = 6, 5.0, 5
    return s


# ------------------------------------------------------------------ PGN and views

def test_a_pgn_becomes_the_game(tmp_path):
    api = Api(settings(tmp_path))
    st = api.load_pgn(SCHOLARS)
    assert not st.get("rejected")
    assert st["moves"] == ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    assert st["over"].startswith("Checkmate") and "White" in st["over"]
    assert st["info"] == {"white": "Alice", "black": "Bob", "event": "Casual", "result": "1-0"}


def test_a_pgn_with_a_starting_position_and_black_to_move(tmp_path):
    api = Api(settings(tmp_path))
    pgn = '[FEN "4k3/8/8/8/8/8/4P3/4K3 b - - 0 7"]\n[SetUp "1"]\n\n7... Kd7 8. e4 *'
    st = api.load_pgn(pgn)
    assert st["moves"] == ["Kd7", "e4"] and st["first_is_black"] and st["first_move_number"] == 7


@pytest.mark.parametrize("text", ["", "hello there", "1. Ke4 e5"])
def test_bad_pgn_is_refused_and_the_board_is_left_alone(tmp_path, text):
    api = Api(settings(tmp_path))
    api.move("d2", "d4")
    st = api.load_pgn(text)
    assert st["rejected"] is True and st["message"]
    assert api.state()["moves"] == ["d4"]


def test_an_illegal_move_in_a_pgn_keeps_what_came_before(tmp_path):
    api = Api(settings(tmp_path))
    st = api.load_pgn("1. e4 e5 2. Nf3 Nf9 3. Bc4 *")
    assert st["moves"] == ["e4", "e5", "Nf3"] and "illegal" in st["message"]


def test_looking_at_a_position_does_not_touch_the_game(tmp_path):
    api = Api(settings(tmp_path))
    api.move("e2", "e4")
    game = api.state()["fen"]
    other = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 3"
    st = api.view_position(other, ["g1", "f3"])
    assert st["viewing"] and st["fen"] == other and st["last"] == ["g1", "f3"]
    assert st["game_fen"] == game and st["dests"] == {} and st["moves"] == ["e4"]
    bad = api.move("e7", "e5")
    assert bad["rejected"] and "go back" in bad["message"].lower()
    back = api.clear_view()
    assert not back["viewing"] and back["fen"] == game and back["dests"]
    assert api.view_position("nonsense")["rejected"]
    assert api.view_position("8/8/8/8/8/8/8/8 w - - 0 1")["rejected"]


def test_changing_the_game_ends_a_view(tmp_path):
    api = Api(settings(tmp_path))
    api.view_position("4k3/8/8/8/8/8/8/4K2R w - - 0 1")
    assert not api.undo()["viewing"]
    api.view_position("4k3/8/8/8/8/8/8/4K2R w - - 0 1")
    assert not api.reset()["viewing"]
    api.view_position("4k3/8/8/8/8/8/8/4K2R w - - 0 1")
    assert not api.load_pgn(FIVE_PLIES)["viewing"]


@pytest.mark.engine
def test_the_engine_follows_the_viewed_position(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        other = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 3"
        api.view_position(other)
        p = wait_for(lambda: (q := api.poll(0))["summary"].get("fen") == other and q)
        assert p["summary"]["white"] is False
        api.clear_view()
        wait_for(lambda: api.poll(0)["summary"].get("fen") == chess.STARTING_FEN)
    finally:
        api.shutdown()


# ------------------------------------------------------------------ the job

def test_evolution_needs_a_game_and_an_engine(tmp_path):
    api = Api(settings(tmp_path))
    assert "moves" in api.evolution_start()["message"]
    api.move("e2", "e4")
    assert "No Stockfish" in api.evolution_start()["message"]
    assert api.evolution_status()["state"] == "idle" and api.evolution_result() is None


def wait_done(api, timeout=60):
    return wait_for(lambda: (s := api.evolution_status())["state"] not in ("running",) and s, timeout)


@pytest.mark.engine
def test_the_job_produces_the_graph_and_gives_the_engine_back(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        api.load_pgn(SCHOLARS)
        wait_for(lambda: api.poll(0)["engine"]["state"] in ("idle", "analysing"))
        assert api.evolution_start({"depth": 6})["started"]
        assert api.evolution_start()["started"] is False                  # one at a time
        assert api.poll(0)["engine"]["state"] == "busy"                   # the live analysis waits
        status = wait_done(api)
        assert status["state"] == "done", status
        data = api.evolution_result()
        assert data["moves"][-1] == "Qxf7#" and data["info"]["white"] == "Alice"
        mains = sorted((n for n in data["nodes"] if n["main"] is not None), key=lambda n: n["main"])
        assert [n["main"] for n in mains] == list(range(8))
        assert mains[-1]["event"] == "mate" and mains[-1]["cp"] == 30000   # White mated Black
        assert all(abs(n["y"]) < 0.5 for n in mains)
        assert len(data["chart"]) == 7 and data["stats"]["shown"] <= data["stats"]["merged"]
        assert len(data["metrics"]) == 8 and "defensiveness" in data["metric_names"]   # one per position
        assert data["metrics"][-1]["b"]["material"] == 38 and data["metrics"][0]["w"]["material"] == 39
        ids = {n["id"] for n in data["nodes"]}
        assert all(e["s"] in ids and e["t"] in ids for e in data["edges"])
        assert any(e["actual"] for e in data["edges"]) and all(e["w"] >= 1 for e in data["edges"])
        # the live analysis is back (the game is over, so the engine just waits)
        wait_for(lambda: api.poll(0)["engine"]["state"] == "idle")
    finally:
        api.shutdown()


@pytest.mark.engine
def test_the_live_analysis_resumes_after_the_job(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        api.load_pgn(FIVE_PLIES)
        api.evolution_start({"depth": 5, "lines": 5})
        assert wait_done(api)["state"] == "done"
        wait_for(lambda: api.poll(0)["engine"]["state"] == "analysing")
        fen = api.state()["fen"]
        wait_for(lambda: api.poll(0)["summary"].get("fen") == fen)
    finally:
        api.shutdown()


@pytest.mark.engine
def test_a_finished_analysis_is_kept_and_reused(stockfish, tmp_path):
    s = settings(tmp_path, stockfish)
    api = Api(s)
    try:
        api.load_pgn(FIVE_PLIES)
        api.evolution_start({"depth": 5})
        assert wait_done(api)["state"] == "done"
        first = api.evolution_result()
        assert list((tmp_path / "cache").glob("*.json"))
        t = time.time()
        api.evolution_start({"depth": 5})
        status = wait_done(api)
        assert status["state"] == "done" and status["message"] == "done"
        assert time.time() - t < 3
        assert api.evolution_result()["nodes"] == first["nodes"]
        api.evolution_start({"depth": 6})                                  # other settings: new analysis
        wait_done(api)
        assert len(list((tmp_path / "cache").glob("*.json"))) == 2
    finally:
        api.shutdown()


@pytest.mark.engine
def test_cancel_stops_the_job_quickly_and_keeps_nothing(stockfish, tmp_path):
    s = settings(tmp_path, stockfish)
    api = Api(s)
    try:
        api.start()
        api.load_pgn("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *")
        api.evolution_start({"depth": 24, "seconds": 30})
        wait_for(lambda: api.evolution_status()["done"] >= 0 and api.evolution_status()["total"] > 0)
        t = time.time()
        api.evolution_cancel()
        status = wait_done(api, 15)
        assert status["state"] == "cancelled" and time.time() - t < 10
        assert api.evolution_result() is None
        assert not list((tmp_path / "cache").glob("*.json"))
        wait_for(lambda: api.poll(0)["engine"]["state"] == "analysing")   # live analysis is back
    finally:
        api.shutdown()


@pytest.mark.engine
def test_settings_are_clamped(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.load_pgn(FIVE_PLIES)
        assert api.evolution_start({"depth": "many"})["started"] is False
        assert api.evolution_start({"depth": 3, "lines": 99, "seconds": 0})["started"]
        wait_done(api)
        p = api.evolution_result()["params"]
        assert p["lines"] == 12 and p["seconds"] == 0.2 and p["depth"] == 3
    finally:
        api.shutdown()
