"""
Positional chess graphs and their measures, after M. Rudolph-Lilith, "ChessY: A Mathematica toolbox
for the generation, visualization and analysis of positional chess graphs", SoftwareX 9 (2019).

The graph of a position: one node per square, one directed edge for every move a piece can make
(the paper: "all potential moves which the pieces ... can legally perform"). Both colours have
edges in every position, whoever is to move. Measures, per colour (the paper's "state"):

  control         unique targeted squares that are empty or hold an enemy piece, as a fraction of
                  the squares that are empty or hold an enemy piece
  mobility        unique targeted empty squares, as a fraction of the empty squares
  connectedness   edges, as a fraction of the edges of a fully connected graph on 64 squares
  offensiveness   pieces with an edge to an enemy piece (a count, as in the paper)
  defensiveness   pieces with an edge to a piece of their own colour (a count, as in the paper)
  reach           unique targeted squares per piece (the paper's "average node reach")

plus `material` (pawn 1, knight and bishop 3, rook 5, queen 9), which the paper's author found to
go with winning together with connectivity ("retention of more and higher-value pieces in
conjunction with ... a high potential connectivity").

Where this reads the paper (it is a short software note and leaves some things open):

  * A piece cannot move onto a piece of its own colour, yet defensiveness counts edges to them.
    So the graph also has a "defence" edge from a piece to every own piece it guards, and
    connectedness and reach count those edges too. Control and mobility do not depend on them.
  * The side not to move has no check to answer, so its edges are the moves it would have if it
    were to move (a pinned piece still only moves along its pin). En passant belongs to the side
    to move only. Castling is an edge of the king.
  * "Control" and "mobility" are fractions of the squares they could apply to, which is how the
    definitions read; the paper gives no denominators.
  * Dominance is left out: its definition in the paper is garbled.
"""

from __future__ import annotations

import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
FULL = 64 * 63                              # edges of a fully connected directed graph on 64 nodes
METRICS = ["control", "mobility", "connectedness", "offensiveness", "defensiveness", "reach", "material"]


def edges(board: chess.Board, colour: bool) -> set:
    """The edges (source, target) of `colour`: its legal moves, and the own pieces it guards."""
    b = board.copy(stack=False)
    b.turn = colour
    if colour != board.turn:
        b.ep_square = None
    out = {(m.from_square, m.to_square) for m in b.legal_moves}
    own = board.occupied_co[colour]
    for sq in chess.scan_forward(own):
        for t in chess.scan_forward(board.attacks_mask(sq) & own):
            out.add((sq, t))
    return out


def measures(board: chess.Board, colour: bool, es: set | None = None) -> dict:
    es = edges(board, colour) if es is None else es
    own, enemy = board.occupied_co[colour], board.occupied_co[not colour]
    empty = ~board.occupied & chess.BB_ALL
    targets = 0
    off, dfn = set(), set()
    for s, t in es:
        targets |= chess.BB_SQUARES[t]
        if enemy & chess.BB_SQUARES[t]:
            off.add(s)
        elif own & chess.BB_SQUARES[t]:
            dfn.add(s)
    hit = targets & (empty | enemy)
    open_n = chess.popcount(empty | enemy)
    pieces = chess.popcount(own)
    material = sum(VALUE[p.piece_type] for p in board.piece_map().values() if p.color == colour)
    return {
        "control": chess.popcount(hit) / open_n if open_n else 0.0,
        "mobility": chess.popcount(targets & empty) / chess.popcount(empty) if empty else 0.0,
        "connectedness": len(es) / FULL,
        "offensiveness": len(off),
        "defensiveness": len(dfn),
        "reach": chess.popcount(targets) / pieces if pieces else 0.0,
        "material": material,
    }


def position_metrics(board: chess.Board) -> dict:
    return {"w": measures(board, chess.WHITE), "b": measures(board, chess.BLACK)}


def game_metrics(start_fen: str, san_moves: list) -> list:
    """The measures of every position of a game, the starting position first. Rounded for the page."""
    b = chess.Board(start_fen)
    rows = [position_metrics(b)]
    for san in san_moves:
        try:
            b.push_san(san)
        except ValueError:
            break
        rows.append(position_metrics(b))
    return [{side: {k: round(v, 4) for k, v in m.items()} for side, m in row.items()} for row in rows]


def control_map(board: chess.Board) -> dict:
    """For the board's heat map: per square, White's attackers minus Black's (only squares where it
    is not zero). This counts what attacks a square, pawns' diagonals included, even when nothing
    stands there to be taken, so it is not the paper's `control`, which only counts squares a
    piece could move to."""
    out = {}
    for sq in chess.SQUARES:
        net = len(board.attackers(chess.WHITE, sq)) - len(board.attackers(chess.BLACK, sq))
        if net:
            out[chess.square_name(sq)] = net
    return out
