"""The detectors on positions built by hand. Each test pins down a case where the obvious
shortcut (count attackers against defenders, trust is_pinned for every pin, call any piece
that attacks two things a fork, count material in a line that stops mid-exchange) is wrong."""

import chess

from uciboard import tactics


def sq(name):
    return chess.parse_square(name)


def loose(fen):
    return {f["square"]: f for f in tactics.loose_pieces(chess.Board(fen))}


# ------------------------------------------------------------------ exchanges

def test_an_undefended_piece_attacked_is_loose_and_it_is_the_movers_chance():
    found = loose("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    assert found["d5"]["gain"] == 9 and found["d5"]["now"] is True and found["d5"]["taker"] == "d1"


def test_a_pawn_attacking_a_defended_queen_wins_it_although_attackers_do_not_outnumber_defenders():
    board = chess.Board("3rk3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    attackers = len(board.attackers(chess.WHITE, sq("d5")))
    defenders = len(board.attackers(chess.BLACK, sq("d5")))
    assert attackers == 1 and defenders == 1                      # the counting rule says "fine"
    assert tactics.exchange(board, sq("d5"), chess.WHITE) == 8    # a queen for a pawn


def test_an_even_trade_is_not_loose():
    # Nxd5 cxd5 and Nxc3 bxc3 each trade a knight for a knight
    assert loose("4k3/8/2p5/3n4/8/2N5/1P6/4K3 w - - 0 1") == {}


def test_a_rook_behind_a_rook_can_make_a_king_defence_worthless():
    # Rxd2 and the king may not recapture: the other rook on the file covers d2
    found = loose("3rk3/8/8/3r4/8/8/3R4/4K3 w - - 0 1")
    assert found["d2"]["gain"] == 5


def test_the_queen_does_not_take_a_pawn_that_is_defended_by_a_pawn():
    board = chess.Board("4k3/8/2p5/3p4/8/8/8/3QK3 w - - 0 1")
    assert tactics.exchange(board, sq("d5"), chess.WHITE) == 0


def test_a_rook_behind_a_rook_joins_the_exchange():
    with_battery = chess.Board("3rk3/8/8/3p4/8/8/3R4/3RK3 w - - 0 1")
    alone = chess.Board("3rk3/8/8/3p4/8/8/3R4/4K3 w - - 0 1")
    assert tactics.exchange(with_battery, sq("d5"), chess.WHITE) == 1
    assert tactics.exchange(alone, sq("d5"), chess.WHITE) == 0


def test_a_pinned_defender_does_not_defend():
    pinned = chess.Board("7k/8/5n2/3pB3/8/8/8/3RK3 w - - 0 1")       # Nf6 pinned to Kh8 by Be5
    free = chess.Board("k7/8/5n2/3pB3/8/8/8/3RK3 w - - 0 1")
    assert pinned.is_pinned(chess.BLACK, sq("f6"))
    assert tactics.exchange(pinned, sq("d5"), chess.WHITE) == 1
    assert tactics.exchange(free, sq("d5"), chess.WHITE) == 0


def test_the_king_cannot_take_a_defended_piece_and_can_take_a_free_one():
    defended = chess.Board("8/8/8/8/8/3k4/3q4/3RK3 b - - 0 1")
    # white rook d1 is defended by the king; the queen cannot win it, the king certainly cannot
    assert tactics.exchange(defended, sq("d1"), chess.BLACK) == 0
    free = chess.Board("8/8/8/8/8/8/3k4/3R3K b - - 0 1")
    assert tactics.exchange(free, sq("d1"), chess.BLACK) == 5      # Kxd1: nothing guards the rook


def test_nothing_to_capture_and_the_king_are_zero():
    board = chess.Board()
    assert tactics.exchange(board, sq("e4"), chess.WHITE) == 0
    assert tactics.exchange(board, sq("e1"), chess.BLACK) == 0


def test_the_starting_position_has_nothing_loose_nothing_pinned():
    out = tactics.analyse(chess.Board())
    assert out["loose"] == [] and out["pins"] == []
    assert out["defenders"] == {"removable": [], "overloaded": []}


# ------------------------------------------------------------- pins and skewers

def pins(fen):
    return tactics.pins_and_skewers(chess.Board(fen))


def test_an_absolute_pin_agrees_with_python_chess():
    fen = "7k/8/5n2/3pB3/8/8/8/3RK3 w - - 0 1"
    found = [p for p in pins(fen) if p["absolute"]]
    assert [(p["slider"], p["front"], p["back"]) for p in found] == [("e5", "f6", "h8")]
    assert chess.Board(fen).is_pinned(chess.BLACK, sq("f6"))


def test_a_relative_pin_is_found_although_is_pinned_cannot_see_it():
    fen = "4k3/3q4/2n5/1B6/8/8/8/4K3 w - - 0 1"
    board = chess.Board(fen)
    assert not board.is_pinned(chess.BLACK, sq("c6"))              # not pinned to the king
    (p,) = pins(fen)
    assert (p["kind"], p["absolute"], p["slider"], p["front"], p["back"]) == ("pin", False, "b5", "c6", "d7")


def test_a_skewer_has_the_valuable_piece_in_front():
    (p,) = [x for x in pins("n3k3/8/8/q7/8/8/8/RK6 w - - 0 1") if x["slider"] == "a1"]
    assert (p["kind"], p["front"], p["back"]) == ("skewer", "a5", "a8")


def test_a_rook_behind_the_queen_defends_it_so_there_is_no_skewer_only_a_loose_rook():
    fen = "r3k3/8/8/q7/8/8/8/RK6 w - - 0 1"
    assert [x for x in pins(fen) if x["slider"] == "a1"] == []
    assert loose(fen)["a1"]["gain"] == 5


def test_a_pinning_piece_that_just_gets_taken_is_not_reported():
    # the same skewer, but the rook is undefended: Qxa1 wins it first
    assert [x for x in pins("n3k3/8/8/q7/8/8/8/R3K3 w - - 0 1") if x["slider"] == "a1"] == []


def test_equal_value_behind_is_neither_pin_nor_skewer():
    # Bb2 hits Bd4 with a knight behind it on the diagonal: 3 against 3
    assert [p for p in pins("4k3/8/5n2/8/3b4/8/1B6/K7 w - - 0 1") if p["slider"] == "b2"] == []


# ------------------------------------------------------------------ lines

def themes(fen, *moves):
    return tactics.line_themes(chess.Board(fen), list(moves))


def tags(result, ply):
    return [t["tag"] for t in result["plies"][ply]["tags"]]


def test_a_knight_fork_of_king_and_rook():
    r = themes("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1", "d5c7")
    (fork,) = [t for t in r["plies"][0]["tags"] if t["tag"] == "fork"]
    assert sorted(fork["squares"]) == ["a8", "e8"]


def test_the_same_fork_by_a_piece_that_can_be_taken_is_not_one():
    r = themes("r1q1k3/8/8/3N4/8/8/8/4K3 w - - 0 1", "d5c7")
    assert "fork" not in tags(r, 0)


def test_attacking_two_defended_pieces_of_equal_value_is_not_a_fork():
    # the knight hits a defended knight and a defended bishop: it only offers trades
    r = themes("4k3/8/2p1p3/3b1n2/8/4N3/8/4K3 w - - 0 1", "e3d5")
    assert "fork" not in tags(r, 0)


def test_a_discovered_check_is_not_a_direct_check():
    r = themes("4k3/8/8/8/4B3/8/8/4R1K1 w - - 0 1", "e4f5")
    assert tags(r, 0) == ["discovered check"]


def test_a_double_check():
    r = themes("4k3/8/8/8/4B3/8/8/4R1K1 w - - 0 1", "e4c6")
    assert tags(r, 0) == ["double check"]


def test_a_direct_check_is_not_labelled():
    r = themes("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a8")
    assert tags(r, 0) == []


def test_a_rook_check_next_to_the_king_that_can_take_it_is_a_sacrifice():
    assert tags(themes("4k3/8/8/8/8/8/8/4RK2 w - - 0 1", "e1e7"), 0) == ["sacrifice"]


def test_a_castling_check_is_not_taken_for_a_discovered_one():
    r = themes("5k2/8/8/8/8/8/8/R3K3 w Q - 0 1", "e1c1")
    assert "discovered check" not in tags(r, 0)


def test_mate_is_named():
    r = themes("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1", "a1a8")
    assert tags(r, 0) == ["mate"]


def test_a_sacrifice_loses_material_for_nothing_immediate_a_trade_does_not():
    r = themes("3rk3/8/8/3p4/8/8/8/3QK3 w - - 0 1", "d1d5")
    (sac,) = [t for t in r["plies"][0]["tags"] if t["tag"] == "sacrifice"]
    assert sac["pawns"] == 8
    assert "sacrifice" not in tags(themes("3rk3/8/8/3r4/8/8/3R4/4K3 w - - 0 1", "d2d5"), 0)


def test_a_line_that_stops_in_the_middle_of_an_exchange_shows_no_gain():
    board_fen = "3rk3/8/8/3p4/8/8/8/3QK3 w - - 0 1"
    cut = themes(board_fen, "d1d5")                                # Qxd5 and the line ends: Rxd5 is coming
    assert cut["material"] == {"net": 0, "plies": 0, "white": True}
    full = themes(board_fen, "d1d5", "d8d5")
    assert full["material"] == {"net": -8, "plies": 2, "white": True}


def test_a_free_piece_counts_once_the_line_has_settled():
    r = themes("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", "d1d5")
    assert r["material"] == {"net": 9, "plies": 1, "white": True}


def test_material_is_counted_for_the_side_that_moves_first():
    r = themes("4k3/8/8/3q4/8/8/8/3RK3 b - - 0 1", "e8f8", "d1d5")
    assert r["material"]["white"] is False and r["material"]["net"] == -9


def test_a_line_stops_at_the_first_illegal_move():
    r = themes(chess.STARTING_FEN, "e2e4", "e2e4", "e7e5")
    assert len(r["plies"]) == 1
    assert themes(chess.STARTING_FEN, "zzzz")["plies"] == []


# ------------------------------------------------------------- random games

def random_positions(games=25, plies=70, seed=7):
    import random
    rng = random.Random(seed)
    for _ in range(games):
        board = chess.Board()
        moves = []
        for _ in range(plies):
            legal = list(board.legal_moves)
            if not legal:
                break
            move = rng.choice(legal)
            board.push(move)
            moves.append(move.uci())
            yield board.copy(), moves[-12:]


def test_the_detectors_never_fail_and_agree_with_python_chess_on_random_positions():
    seen = 0
    for board, _ in random_positions():
        out = tactics.analyse(board)
        for p in out["pins"]:
            if p["absolute"]:
                front = chess.parse_square(p["front"])
                assert board.is_pinned(board.piece_at(front).color, front)
                assert chess.parse_square(p["back"]) == board.king(board.piece_at(front).color)
        for item in out["loose"]:
            s = chess.parse_square(item["square"])
            piece = board.piece_at(s)
            assert piece and piece.piece_type != chess.KING and item["gain"] > 0
            assert board.attackers(not piece.color, s)             # something really attacks it
            assert tactics.exchange(board, s, not piece.color) == item["gain"]
        seen += 1
    assert seen > 500


def test_line_themes_on_random_lines_is_well_formed():
    import random
    rng = random.Random(3)
    for _ in range(60):
        board = chess.Board()
        for _ in range(rng.randrange(0, 40)):
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(rng.choice(legal))
        line, probe = [], board.copy()
        for _ in range(8):
            legal = list(probe.legal_moves)
            if not legal:
                break
            mv = rng.choice(legal)
            line.append(mv.uci())
            probe.push(mv)
        r = tactics.line_themes(board, line)
        assert len(r["plies"]) == len(line)
        assert 0 <= r["material"]["plies"] <= len(line)


# ------------------------------------------------------- defenders, king zones, safe squares

RUY = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"


def test_the_only_defender_of_an_attacked_pawn_that_can_be_traded_off_is_removable():
    (r,) = tactics.defenders(chess.Board(RUY))["removable"]
    assert (r["defender"], r["defends"], r["taker"], r["white"]) == ("c6", ["e5"], "b5", False)
    assert "only defender of pawn e5" in r["text"] and "can trade it off" in r["text"]


def test_a_defender_that_costs_the_taker_more_is_not_removable():
    # Qa4 also hits the knight, but Qxc6 dxc6 gives a queen for a knight
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/Q3P3/5N2/PPPP1PPP/RNB1KB1R b KQkq - 0 1"
    assert tactics.defenders(chess.Board(fen))["removable"] == []


def test_a_piece_with_two_defenders_has_no_only_defender():
    fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    board = chess.Board(fen)
    board.set_piece_at(chess.parse_square("d6"), chess.Piece(chess.PAWN, chess.BLACK))   # now d6 guards e5 too
    assert tactics.defenders(board)["removable"] == []


def test_a_piece_defended_only_by_its_king_is_not_a_defender_pair():
    board = chess.Board("4k3/4p3/8/8/8/8/8/K3R3 w - - 0 1")      # Re1 attacks e7, only the king guards it
    assert tactics.exchange(board, sq("e7"), chess.WHITE) == 0     # Rxe7+ Kxe7: not loose
    assert tactics.defenders(board) == {"removable": [], "overloaded": []}


def test_a_rook_guarding_two_attacked_pieces_is_overloaded():
    fen = "1n1r2k1/8/8/3p4/5B2/8/8/K2R4 w - - 0 1"
    (o,) = tactics.defenders(chess.Board(fen))["overloaded"]
    assert o["defender"] == "d8" and sorted(o["defends"]) == ["b8", "d5"] and o["white"] is False
    assert "only defender of" in o["text"]


def test_a_skewer_against_a_defended_pawn_is_not_reported_but_a_loose_one_is():
    assert tactics.pins_and_skewers(chess.Board(RUY)) == []                        # d7 is defended: nothing to win
    assert [x for x in pins("n3k3/8/8/q7/8/8/8/RK6 w - - 0 1") if x["slider"] == "a1"]   # a8 is not


def test_king_zones_see_through_the_king_and_leave_out_its_own_pieces():
    z = tactics.king_zones(chess.Board("R5k1/5ppp/8/8/8/8/8/4K3 b - - 0 1"))["black"]
    assert z["king"] == "g8" and z["check"] is True
    assert sorted(z["danger"]) == ["f8", "h8"] and z["escape"] == []               # h8 is hit through the king
    z = tactics.king_zones(chess.Board(RUY))["black"]
    assert z["escape"] == ["e7"] and z["danger"] == []


def test_safe_squares_count_what_the_move_takes():
    board = chess.Board("4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1")
    out = tactics.safe_squares(board, sq("c3"))
    assert out["e4"] is False                                      # the d5 pawn takes it
    assert out["d5"] is True and out["b5"] is True                 # takes an undefended pawn / quiet
    defended = chess.Board("4k3/8/4p3/3p4/8/2N5/8/4K3 w - - 0 1")
    assert tactics.safe_squares(defended, sq("c3"))["d5"] is False  # a pawn for a knight
    assert tactics.safe_squares(board, sq("d5")) == {}             # not the mover's piece
