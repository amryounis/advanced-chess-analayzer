import io

import chess
import chess.pgn
import pytest

from uciboard import pgnexport, quality
from uciboard.api import Api
from test_api_evolution import SCHOLARS, settings, wait_done, wait_for  # noqa: F401


def row(ply, white, lo, hi, actual):
    return {"ply": ply, "white": white, "lo": lo, "hi": hi, "actual": actual}


def test_the_winning_chances_curve():
    assert quality.win_percent(0) == pytest.approx(50)
    assert quality.win_percent(100) == pytest.approx(59.1, abs=0.1)
    assert quality.win_percent(5000) == quality.win_percent(1000)        # clipped: a mate is not infinitely better


@pytest.mark.parametrize("white,lo,hi,actual,mark", [
    (True, 0, 50, 45, ""),               # about as good as the best
    (True, 0, 30, 41, ""),               # better than every alternative found: loses nothing
    (True, 0, 50, -60, "?!"),            # from +0.50 to -0.60: about 11 points
    (True, 0, 50, -250, "?"),
    (True, 0, 100, -600, "??"),
    (False, -50, 0, 150, "?!"),          # Black: best left White at -0.50, the move played gives White +1.50
    (False, 300, 400, 900, "?"),         # already losing, then losing more
])
def test_marks(white, lo, hi, actual, mark):
    got = quality.classify([row(1, white, lo, hi, actual)])[0]
    assert got["mark"] == mark, got


def test_the_same_loss_counts_for_less_when_already_winning():
    equal = quality.classify([row(1, True, 0, 0, -200)])[0]["drop"]
    winning = quality.classify([row(1, True, 800, 800, 600)])[0]["drop"]
    assert equal > 3 * winning and quality.classify([row(1, True, 800, 800, 600)])[0]["mark"] == ""


def test_counts_and_marks_for_a_game():
    chart = [row(1, True, 0, 50, 45), row(2, False, -50, 0, 150), row(3, True, 0, 100, -600)]
    rows = quality.classify(chart)
    assert quality.counts(rows) == {"w": {"?!": 0, "?": 0, "??": 1}, "b": {"?!": 1, "?": 0, "??": 0}}
    assert quality.marks_for(["e4", "e5", "Qh5", "Nc6"], chart) == ["", "?!", "??", ""]


def test_nags_in_the_pgn():
    fake = {
        "nodes": [{"id": 0, "main": 0, "cp": 0, "mate_in": None, "fen": chess.STARTING_FEN, "event": ""},
                  {"id": 1, "main": 1, "cp": -250, "mate_in": None, "fen": "x", "event": ""}],
        "edges": [],
        "chart": [row(1, True, 0, 50, -250)],
    }
    g = chess.pgn.read_game(io.StringIO(pgnexport.annotated_pgn(chess.STARTING_FEN, ["f2f3"], {}, fake)))
    assert g.next().nags == {chess.pgn.NAG_MISTAKE}


@pytest.mark.engine
def test_the_state_and_result_carry_the_marks(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        api.load_pgn(SCHOLARS)
        assert api.state()["marks"] == []                                  # nothing analysed yet
        wait_for(lambda: api.poll(0)["engine"]["state"] in ("idle", "analysing"))
        api.evolution_start({"depth": 6})
        assert wait_done(api)["state"] == "done"
        data = api.evolution_result()
        assert len(data["quality"]["rows"]) == len(data["chart"]) == 7
        assert set(data["quality"]["counts"]) == {"w", "b"}
        marks = api.state()["marks"]
        assert len(marks) == 7 and marks[-1] == ""                         # one per move
        api.undo()
        assert api.state()["marks"] == []                                  # another game now
    finally:
        api.shutdown()
