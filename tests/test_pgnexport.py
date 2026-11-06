import io

import chess
import chess.engine
import chess.pgn
import pytest

from uciboard import pgnexport
from uciboard.api import Api
from test_api_evolution import SCHOLARS, settings, wait_done, wait_for  # noqa: F401


def parse(text):
    return chess.pgn.read_game(io.StringIO(text))


def test_without_an_analysis_the_game_and_its_tactics_are_written(tmp_path):
    api = Api(settings(tmp_path))
    api.load_pgn("1. e4 e5 2. Nf3 d6 3. Nc3 Nf6 *")
    out = api.export_pgn()
    assert out["analysed"] is False
    g = parse(out["pgn"])
    assert [m.uci() for m in g.mainline_moves()] == ["e2e4", "e7e5", "g1f3", "d7d6", "b1c3", "g8f6"]
    assert g.headers["Annotator"] == "uciboard"


def test_a_fork_is_named_and_its_targets_circled():
    # 1. Nc7+ forks king e8 and rook a8
    fen = "r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1"
    g = parse(pgnexport.annotated_pgn(fen, ["d5c7"], {}))
    node = g.next()
    assert "fork" in node.comment
    assert {a.tail for a in node.arrows()} == {chess.E8, chess.A8}
    assert g.headers["FEN"] == fen


def test_an_ordinary_move_gets_no_comment():
    g = parse(pgnexport.annotated_pgn(chess.STARTING_FEN, ["e2e4"], {}))
    assert g.next().comment == ""


def test_scores_and_the_preferred_move_come_from_the_analysis():
    fake = {
        "nodes": [
            {"id": 0, "main": 0, "cp": 0, "mate_in": None, "fen": chess.STARTING_FEN, "event": ""},
            {"id": 1, "main": 1, "cp": -20, "mate_in": None, "fen": "x", "event": ""},        # 1. a3
            {"id": 2, "main": None, "cp": 60, "mate_in": None, "fen": "x", "event": ""},      # 1. e4 would be +0.60
        ],
        "edges": [
            {"s": 0, "t": 1, "actual": True, "collapsed": False, "back": False, "uci": "a2a3"},
            {"s": 0, "t": 2, "actual": False, "collapsed": False, "back": False, "uci": "e2e4"},
        ],
    }
    g = parse(pgnexport.annotated_pgn(chess.STARTING_FEN, ["a2a3"], {}, fake))
    node = g.next()
    assert node.eval().white().score() == -20
    assert "Engine preferred e4" in node.comment and "+0.60" in node.comment
    assert [(a.tail, a.head) for a in node.arrows()] == [(chess.E2, chess.E4)]


def test_a_small_difference_is_not_mentioned():
    fake = {
        "nodes": [
            {"id": 0, "main": 0, "cp": 0, "mate_in": None, "fen": chess.STARTING_FEN, "event": ""},
            {"id": 1, "main": 1, "cp": 10, "mate_in": None, "fen": "x", "event": ""},
            {"id": 2, "main": None, "cp": 30, "mate_in": None, "fen": "x", "event": ""},
        ],
        "edges": [
            {"s": 0, "t": 1, "actual": True, "collapsed": False, "back": False, "uci": "d2d4"},
            {"s": 0, "t": 2, "actual": False, "collapsed": False, "back": False, "uci": "e2e4"},
        ],
    }
    node = parse(pgnexport.annotated_pgn(chess.STARTING_FEN, ["d2d4"], {}, fake)).next()
    assert "preferred" not in node.comment and node.eval().white().score() == 10


@pytest.mark.engine
def test_after_an_analysis_the_export_carries_the_scores(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        api.load_pgn(SCHOLARS)
        wait_for(lambda: api.poll(0)["engine"]["state"] in ("idle", "analysing"))
        api.evolution_start({"depth": 6})
        assert wait_done(api)["state"] == "done"
        out = api.export_pgn()
        assert out["analysed"] is True
        g = parse(out["pgn"])
        nodes = list(g.mainline())
        assert nodes[0].eval() is not None                              # 1. e4 has a score
        assert nodes[-1].eval() is None and nodes[-1].move == chess.Move.from_uci("h5f7")   # the mate itself has none
        api.undo()                                                       # a different game now
        assert api.export_pgn()["analysed"] is False
    finally:
        api.shutdown()
