import time

import chess
import pytest

from uciboard import config
from uciboard.api import Api, score_text

from conftest import wait_for


def test_score_text_is_from_whites_point_of_view():
    assert score_text({"cp": 35}, True) == "+0.35"
    assert score_text({"cp": 35}, False) == "-0.35"      # good for Black to move = bad for White
    assert score_text({"mate": 5}, True) == "#5"
    assert score_text({"mate": 5}, False) == "-#5"
    assert score_text({"mate": -2}, True) == "-#2"
    assert score_text(None, True) == ""


def test_board_moves_without_an_engine():
    api = Api(config.Settings())                          # no Stockfish configured
    st = api.state()
    assert st["turn"] == "white" and st["dests"]["e2"] == ["e3", "e4"]
    st = api.move("e2", "e4")
    assert st["turn"] == "black" and st["moves"] == ["e4"] and st["last"] == ["e2", "e4"]
    bad = api.move("e7", "e3")
    assert bad["rejected"] and bad["moves"] == ["e4"]
    assert api.move("zz", "e3")["rejected"]
    assert api.undo()["moves"] == [] and api.undo()["moves"] == []     # a second undo is harmless
    assert api.state()["fen"] == chess.STARTING_FEN


def test_no_engine_is_reported_not_raised():
    api = Api(config.Settings())
    api.start()
    p = api.poll(0)
    assert p["engine"]["state"] == "none" and "No Stockfish" in p["engine"]["error"]
    assert any("No Stockfish" in l["t"] for l in p["lines"])


def test_promotion_and_special_moves():
    api = Api(config.Settings())
    api.set_position("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert api.needs_promotion("a7", "a8") is True
    assert api.needs_promotion("a1", "a2") is False
    assert api.move("a7", "a8")["rejected"]               # a promotion needs a piece
    st = api.move("a7", "a8", "n")
    assert st["moves"] == ["a8=N"]
    api.set_position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert "g1" in api.state()["dests"]["e1"]             # castling is offered as a king move
    assert api.move("e1", "g1")["moves"] == ["O-O"]
    api.set_position("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    assert api.move("e5", "d6")["moves"] == ["exd6"]      # en passant


def test_set_position_validates():
    api = Api(config.Settings())
    assert api.set_position("not a fen")["rejected"]
    assert api.set_position("8/8/8/8/8/8/8/8 w - - 0 1")["rejected"]       # no kings
    assert api.state()["fen"] == chess.STARTING_FEN
    st = api.set_position("4k3/8/8/8/8/8/8/4K2R b K - 3 20")
    assert st["first_is_black"] and st["first_move_number"] == 20
    assert api.move("e8", "e7")["moves"] == ["Ke7"]


def test_game_over_is_reported():
    api = Api(config.Settings())
    for orig, dest in [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]:
        st = api.move(orig, dest)
    assert st["over"].startswith("Checkmate") and "Black" in st["over"] and st["dests"] == {}


@pytest.mark.engine
def test_the_engine_follows_the_board(stockfish):
    api = Api(config.load_settings(stockfish=stockfish, analyse=True))
    try:
        api.start()
        cursor = 0
        seen = []

        def drain():
            nonlocal cursor
            p = api.poll(cursor)
            cursor = p["cursor"]
            seen.extend(l["t"] for l in p["lines"])
            return p

        p = wait_for(lambda: (q := drain())["summary"].get("depth", 0) >= 8 and q)
        assert p["engine"]["state"] == "analysing" and "Stockfish" in p["engine"]["name"]
        assert p["summary"]["white"] is True and p["summary"]["pv"]
        assert "position fen " + chess.STARTING_FEN in seen      # the commands sent are shown too
        assert "go infinite" in seen

        api.move("e2", "e4")
        api.move("e7", "e5")
        fen = api.state()["fen"]
        wait_for(lambda: (drain(), f"position fen {fen}" in seen)[1])
        p = wait_for(lambda: (q := drain())["summary"].get("depth", 0) >= 8 and q)
        assert p["summary"]["move_number"] == 2 and p["summary"]["white"] is True

        api.pause()
        wait_for(lambda: (drain(), any(t.startswith("bestmove") for t in seen))[1])
        assert drain()["engine"]["state"] == "off"
        api.resume()
        wait_for(lambda: drain()["engine"]["state"] == "analysing")
    finally:
        api.shutdown()


@pytest.mark.engine
def test_the_engine_stays_idle_until_analysis_is_switched_on(stockfish):
    api = Api(config.load_settings(stockfish=stockfish))              # the default: off
    try:
        api.start()
        e = api.poll(0)["engine"]
        assert e["state"] == "off" and e["on"] is False
        api.move("e2", "e4")
        api.move("e7", "e5")
        time.sleep(1.0)                                               # a search would have printed by now
        p = api.poll(0)
        assert p["engine"]["state"] == "off" and p["summary"] == {} and p["uci"]["rows"] == []
        assert not any(l["t"].startswith(("go ", "info ")) for l in p["lines"])
        api.resume()                                                  # the Analyse button
        wait_for(lambda: api.poll(0)["summary"].get("depth", 0) >= 6)
        assert api.poll(0)["engine"]["on"] is True
        api.pause()                                                   # the Stop button
        assert api.poll(0)["engine"]["state"] == "off"
        api.move("g1", "f3")                                          # moving does not wake it
        time.sleep(0.5)
        assert api.poll(0)["engine"]["state"] == "off"
    finally:
        api.shutdown()


@pytest.mark.engine
def test_a_checkmated_position_stops_the_search(stockfish):
    api = Api(config.load_settings(stockfish=stockfish, analyse=True))
    try:
        api.start()
        for orig, dest in [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]:
            api.move(orig, dest)
        p = wait_for(lambda: (q := api.poll(0))["engine"]["state"] == "idle" and q)
        assert p["summary"] == {}
    finally:
        api.shutdown()


def test_a_bad_engine_path_is_reported(tmp_path):
    api = Api(config.Settings(stockfish_path=str(tmp_path / "missing"), source="test"))
    api.start()
    assert "not found" in api.poll(0)["engine"]["error"]
    assert api.move("e2", "e4")["moves"] == ["e4"]        # the board still works


@pytest.mark.engine
def test_the_summary_carries_the_best_line_as_arrows(stockfish):
    api = Api(config.load_settings(stockfish=stockfish, analyse=True))
    try:
        api.start()
        p = wait_for(lambda: (q := api.poll(0))["summary"].get("depth", 0) >= 10 and q)
        s = p["summary"]
        assert s["fen"] == chess.STARTING_FEN
        assert len(s["arrows"]) == len(s["pv"]) >= 4
        # White moves first, then the sides alternate, and every arrow is a legal move in turn
        assert [a["white"] for a in s["arrows"]] == [i % 2 == 0 for i in range(len(s["arrows"]))]
        board = chess.Board()
        for a, san in zip(s["arrows"], s["pv"]):
            move = chess.Move(chess.parse_square(a["orig"]), chess.parse_square(a["dest"]))
            assert board.san(move) == san
            board.push(move)
        # after a move the summary belongs to the new position (and says so)
        api.move("e2", "e4")
        fen = api.state()["fen"]
        s = wait_for(lambda: (q := api.poll(0)["summary"]).get("fen") == fen and q)
        assert s["arrows"][0]["white"] is False
    finally:
        api.shutdown()


def test_state_carries_what_the_geometry_says_about_the_shown_position(tmp_path):
    api = Api(config.load_settings(own_config=tmp_path / "none.toml"))
    t = api.state()["tactics"]
    assert t["loose"] == [] and t["pins"] == [] and t["defenders"] == {"removable": [], "overloaded": []}
    assert t["kings"]["white"]["king"] == "e1" and t["kings"]["black"]["king"] == "e8"
    api.set_position("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    loose = api.state()["tactics"]["loose"]
    assert [(f["square"], f["gain"], f["now"]) for f in loose] == [("d5", 9, True)]
    api.view_position("7k/8/5n2/3pB3/8/8/8/3RK3 w - - 0 1")           # overlays follow what is shown
    assert any(p["absolute"] for p in api.state()["tactics"]["pins"])


def test_line_themes_are_added_to_the_summary_and_remembered(tmp_path):
    api = Api(config.load_settings(own_config=tmp_path / "none.toml"))
    fen = "r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1"
    api._summary = {"pv_uci": ["d5c7"], "fen": fen}
    first = api.poll(0)["summary"]["themes"]
    assert [t["tag"] for t in first["plies"][0]["tags"]] == ["fork"]
    assert api.poll(0)["summary"]["themes"] is first                 # computed once
    api._summary = {"pv_uci": [], "fen": fen}
    assert "themes" not in api.poll(0)["summary"]


def test_safe_squares_come_from_the_game_on_the_board():
    api = Api(config.Settings())
    api.set_position("4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1")
    r = api.safe_squares("c3")
    assert r["square"] == "c3" and r["squares"]["e4"] is False and r["squares"]["b5"] is True
    assert api.safe_squares("d5")["squares"] == {}               # Black's piece, White to move
    assert api.safe_squares("zz")["squares"] == {}               # not a square: no crash
