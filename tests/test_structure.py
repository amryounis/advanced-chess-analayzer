import chess

from uciboard import structure


def texts(fen):
    return [f["text"] for f in structure.analyse(chess.Board(fen))["found"]]


def test_the_start_has_no_structure_to_report():
    r = structure.analyse(chess.Board())
    assert r["found"] == [] and r["files"] == [] and r["pawns"] == []


def test_open_and_half_open_files():
    r = structure.analyse(chess.Board("4k3/p1p5/8/8/8/2P5/2P1P3/4K3 w - - 0 1"))
    kinds = {f["file"]: (f["kind"], f.get("white")) for f in r["files"]}
    assert kinds["b"] == ("open", None) and kinds["a"] == ("half", True)    # only Black has an a-pawn
    assert kinds["e"] == ("half", False)                                    # only White has an e-pawn
    assert "c" not in kinds                                                 # both have c-pawns
    t = [f["text"] for f in r["found"]]
    assert t[0].startswith("open files: b, d, f, g, h")
    assert any(x.startswith("half-open for White") and x.endswith(": a") for x in t)


def test_doubled_and_isolated_pawns():
    t = texts("4k3/p1p5/8/8/8/2P5/2P1P3/4K3 w - - 0 1")
    assert "doubled white pawns on the c-file (c2, c3)" in t
    assert "isolated black pawn a7" in t and "isolated white pawn e2" in t


def test_a_pawn_with_a_neighbour_is_not_isolated():
    t = texts("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1")
    assert not [x for x in t if x.startswith("isolated")]
    assert not [x for x in t if x.startswith("doubled")]
