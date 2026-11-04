"""Positional chess graphs and their measures (ChessY, Rudolph-Lilith 2019)."""

import chess
import pytest

from uciboard import posgraph as pg
from uciboard.api import Api

START = chess.Board()


def sq(name):
    return chess.parse_square(name)


def test_the_start_is_symmetric_and_the_numbers_are_the_ones_you_can_count():
    m = pg.position_metrics(START)
    assert m["w"] == m["b"]
    assert m["w"]["control"] == pytest.approx(16 / 48)     # ranks 3 and 4 out of the 48 open squares
    assert m["w"]["mobility"] == pytest.approx(16 / 32)    # out of the 32 empty squares
    assert m["w"]["offensiveness"] == 0                    # nothing can take anything yet
    assert m["w"]["defensiveness"] == 8                    # the eight back-rank pieces guard something
    assert m["w"]["material"] == 39


def test_legal_moves_are_edges_and_so_are_guarded_pieces():
    es = pg.edges(START, chess.WHITE)
    assert (sq("e2"), sq("e4")) in es                      # the double step
    assert (sq("g1"), sq("f3")) in es
    assert (sq("d1"), sq("e1")) in es                      # the queen guards the king: a defence edge
    assert (sq("e2"), sq("d3")) not in es                  # a pawn does not move diagonally to nothing
    assert len(es) == 20 + sum(
        chess.popcount(START.attacks_mask(s) & START.occupied_co[chess.WHITE])
        for s in chess.scan_forward(START.occupied_co[chess.WHITE]))


def test_a_pinned_piece_has_no_edges():
    b = chess.Board("4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1")
    es = pg.edges(b, chess.WHITE)
    assert not [e for e in es if e[0] == sq("e2")]         # the knight cannot move
    assert (sq("e1"), sq("e2")) in es                      # but the king guards it


def test_offensiveness_counts_pieces_that_can_take_something():
    b = chess.Board("4k3/8/8/8/p7/8/8/R3K3 w - - 0 1")
    assert pg.measures(b, chess.WHITE)["offensiveness"] == 1       # the rook takes a4
    assert pg.measures(b, chess.BLACK)["offensiveness"] == 0


def test_the_side_not_to_move_still_has_edges_and_en_passant_is_for_the_mover():
    b = chess.Board("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
    assert (sq("e5"), sq("d6")) in pg.edges(b, chess.WHITE)        # en passant
    assert (sq("d8"), sq("d7")) in pg.edges(b, chess.BLACK)        # the queen's step to the vacated d7
    assert pg.edges(b, chess.BLACK)                                # Black has edges though it is not to move


def test_a_game_gives_one_row_per_position_and_stops_at_a_bad_move():
    rows = pg.game_metrics(chess.STARTING_FEN, ["e4", "e5", "Nf3"])
    assert len(rows) == 4
    assert set(rows[0]) == {"w", "b"} and set(rows[0]["w"]) == set(pg.METRICS)
    assert rows[3]["w"]["material"] == 39
    assert len(pg.game_metrics(chess.STARTING_FEN, ["e4", "Zz9", "e5"])) == 2


def test_material_falls_when_a_piece_is_taken():
    rows = pg.game_metrics(chess.STARTING_FEN, ["e4", "d5", "exd5"])
    assert rows[3]["b"]["material"] == 38 and rows[3]["w"]["material"] == 39


def test_the_heat_map_counts_attackers_net():
    heat = pg.control_map(START)
    assert heat["c3"] == 3 and heat["a3"] == 2                      # b2, d2, b1 / b2, b1
    assert heat["c6"] == -3
    assert "e4" not in heat                                         # nobody attacks it yet


def test_the_state_carries_the_heat_map():
    api = Api()
    st = api.state()
    assert st["control"]["c3"] == 3
