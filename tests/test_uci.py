import chess
import pytest

from uciboard.uci import EngineError, UciEngine, parse_info

from conftest import wait_for


def test_parse_info_reads_the_numbers():
    line = ("info depth 20 seldepth 28 multipv 1 score cp 31 nodes 1500000 nps 1200000 "
            "hashfull 12 tbhits 0 time 1250 pv e2e4 e7e5 g1f3")
    assert parse_info(line) == {
        "depth": 20, "seldepth": 28, "multipv": 1, "score": {"cp": 31}, "nodes": 1500000,
        "nps": 1200000, "hashfull": 12, "tbhits": 0, "time": 1250, "pv": ["e2e4", "e7e5", "g1f3"]}


def test_parse_info_handles_mate_bounds_and_wdl():
    assert parse_info("info depth 9 score mate -3 pv a1a2")["score"] == {"mate": -3}
    got = parse_info("info depth 9 score cp 50 lowerbound wdl 500 400 100 nodes 5 pv e2e4")
    assert got["bound"] == "lower" and got["pv"] == ["e2e4"] and got["nodes"] == 5


def test_parse_info_ignores_other_lines():
    assert parse_info("bestmove e2e4 ponder e7e5") is None
    assert parse_info("info string NNUE evaluation using nn.nnue") is None
    assert parse_info("info depth 3 currmove e2e4 currmovenumber 1") == {"depth": 3}


def test_a_missing_engine_is_a_clear_error(tmp_path):
    with pytest.raises(EngineError, match="Cannot start"):
        UciEngine(str(tmp_path / "nope")).start()


class Recorder:
    def __init__(self):
        self.items = []

    def __call__(self, kind, text, tag):
        self.items.append((kind, text, tag))

    def outs(self, tag=None):
        return [t for k, t, g in list(self.items) if k == "out" and (tag is None or g == tag)]


@pytest.mark.engine
def test_infinite_analysis_runs_until_told_to_stop(stockfish):
    rec = Recorder()
    eng = UciEngine(stockfish, on_line=rec, options={"Threads": 1, "Hash": 16})
    eng.start()
    try:
        assert "Stockfish" in eng.name
        eng.analyze(chess.STARTING_FEN, tag="start")
        deep = wait_for(lambda: [t for t in rec.outs("start") if t.startswith("info depth 1")
                                 and " pv " in t])
        assert deep
        before = len(rec.outs("start"))
        wait_for(lambda: len(rec.outs("start")) > before)          # it keeps going
        assert eng.searching
        eng.stop()
        wait_for(lambda: any(t.startswith("bestmove") for t in rec.outs("start")))
        assert not eng.searching
    finally:
        eng.quit()


@pytest.mark.engine
def test_moving_to_a_new_position_drops_the_old_searchs_output(stockfish):
    rec = Recorder()
    eng = UciEngine(stockfish, on_line=rec, options={"Threads": 1})
    eng.start()
    try:
        fens = [chess.STARTING_FEN]
        board = chess.Board()
        for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]:
            board.push_uci(uci)
            fens.append(board.fen())
        for fen in fens:
            eng.analyze(fen, tag=fen)           # switch before the engine has settled
        last = fens[-1]
        mark = len(rec.items)                   # everything from here on is after the last switch
        wait_for(lambda: any(" pv " in t for t in rec.outs(last)))
        # Each line carries the tag of the search current when it was read. After the
        # last switch no line of an abandoned search may appear, and the abandoned
        # searches' bestmoves must be swallowed.
        later = [(k, t, g) for k, t, g in rec.items[mark:] if k == "out"]
        assert later and {g for _, _, g in later} == {last}
        assert not [t for _, t, _ in later if t.startswith("bestmove")]
        # And the lines belong to the last position: the first move of the PV is legal there.
        b = chess.Board(last)
        pvs = [t.split(" pv ")[1].split()[0] for t in rec.outs(last) if " pv " in t]
        assert pvs and all(chess.Move.from_uci(m) in b.legal_moves for m in pvs)
    finally:
        eng.quit()


@pytest.mark.engine
def test_a_finished_position_ends_with_bestmove_none(stockfish):
    rec = Recorder()
    eng = UciEngine(stockfish, on_line=rec)
    eng.start()
    try:
        mate = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        eng.analyze(mate, tag="m")
        eng.stop()
        wait_for(lambda: any(t.startswith("bestmove") for t in rec.outs("m")))
    finally:
        eng.quit()


@pytest.mark.engine
def test_quit_ends_the_process(stockfish):
    eng = UciEngine(stockfish)
    eng.start()
    eng.quit()
    assert not eng.alive
