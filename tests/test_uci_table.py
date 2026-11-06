"""The depth lines and counters behind the UCI table."""

import chess
import pytest

from uciboard.api import Api, long_algebraic, long_line
from uciboard.uci import parse_info
from test_api_evolution import settings, wait_for  # noqa: F401


def test_long_algebraic_notation():
    start = chess.Board()
    assert long_line(chess.STARTING_FEN, ["e2e4", "e7e5", "g1f3", "b8c6"], 9) == "e2-e4 e7-e5 Ng1-f3 Nb8-c6"
    assert long_line(chess.STARTING_FEN, ["e2e4", "e7e5"], 1) == "e2-e4"                   # limited
    assert long_line(chess.STARTING_FEN, ["e2e4", "e7e6", "e4e5", "e9e9"], 9) == "e2-e4 e7-e6 e4-e5"   # stops at junk
    assert long_algebraic(start, chess.Move.from_uci("g1f3")) == "Ng1-f3"
    assert long_line("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 1", ["h5f7"], 1) == "Qh5xf7#"
    assert long_line("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ["e1g1", "e8c8"], 2) == "O-O O-O-O"
    assert long_line("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", ["a7a8q"], 1) == "a7-a8=Q+"
    assert long_line("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", ["e5d6"], 1) == "e5xd6"


def test_the_root_move_being_searched_is_read_from_info():
    info = parse_info("info depth 20 currmove e7e6 currmovenumber 8")
    assert info["currmove"] == "e7e6" and info["currmovenumber"] == 8


@pytest.mark.engine
def test_rows_stats_and_the_epoch(stockfish, tmp_path):
    api = Api(settings(tmp_path, stockfish))
    try:
        api.start()
        wait_for(lambda: len(api.poll(0)["uci"]["rows"]) >= 5)
        u = api.poll(0)["uci"]
        assert u["reset"] is True                                      # a page that has not seen this search
        depths = [r["depth"] for r in u["rows"]]
        assert depths == sorted(depths) and len(set(depths)) > 3       # oldest first, as sent
        r = u["rows"][-1]
        assert r["pv"].split()[0][-5:].count("-") == 1 and r["score"][0] in "+-#"
        assert u["stats"]["total_moves"] == 20 and u["stats"]["nodes"] > 0 and u["stats"]["threads"] >= 1
        again = api.poll(0, u["cursor"], u["epoch"])["uci"]            # same search: only what is new
        assert again["reset"] is False and all(x["n"] > u["cursor"] for x in again["rows"])
        api.move("e2", "e4")                                            # another position: it starts again
        wait_for(lambda: api.poll(0, u["cursor"], u["epoch"])["uci"]["reset"])
        wait_for(lambda: api.poll(0, 0, -1)["uci"]["stats"].get("total_moves") == 20)
        fresh = api.poll(0, 0, -1)["uci"]
        assert fresh["epoch"] != u["epoch"] and all(x["depth"] <= max(depths) + 12 for x in fresh["rows"])
    finally:
        api.shutdown()
