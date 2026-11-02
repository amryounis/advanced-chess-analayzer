"""
Tactical themes from the geometry of a position (python-chess only, no engine).

Two layers, kept apart on purpose:

  * analyse(board): what is true of the position on the board right now: pieces that can be
    won by an exchange, and pins / skewers. No search, so it is instant and can be wrong about
    what is *best*; it only says what the geometry allows.

  * line_themes(board, moves): labels for the moves of an engine's line (fork, discovered check,
    double check, sacrifice) and the line's net material once the exchanges in it have settled.
    The engine chose the moves; the geometry only names what they do. A label therefore means
    "this works", not just "this looks like a fork".

The rules, and what they deliberately do not claim:

  * Whether a piece is "hanging" is decided by a static exchange evaluation (exchange): both sides
    capture on the square, cheapest attacker first, x-rays included (a piece behind a capturer joins
    in once it has moved off), either side may stop, and a pinned piece may only capture along its
    pin. Counting attackers against defenders is not used: a pawn attacking a queen wins it even
    if the queen has five defenders.
  * Not modelled: a king already in check from another piece, overloaded defenders, pieces that
    can only capture by giving up something else, promotion and en passant inside an exchange.
  * A pin or skewer is only reported when the pinning piece is not itself winnable by an exchange.
  * A fork needs two targets, each the king, a more valuable piece, or an undefended piece that is
    not a pawn, and the forking piece must not be winnable by an exchange.
"""

from __future__ import annotations

import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
KING_RANK = 100                      # only to order attackers: the king captures last
NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
         chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
SACRIFICE_MIN = 2                    # pawns' worth lost for a move to be called a sacrifice


def _name(board: chess.Board, square: int, colour: bool = False) -> str:
    p = board.piece_at(square)
    who = ("white " if p.color == chess.WHITE else "black ") if colour else ""
    return f"{who}{NAMES[p.piece_type]} {chess.square_name(square)}"


# ------------------------------------------------------------------ exchanges

def _can_capture_on(board: chess.Board, colour: bool, frm: int, to: int) -> bool:
    """Is the piece on `frm` free to go to `to` (an absolute pin limits it to its pin line)?"""
    if board.king(colour) is None:
        return True
    return bool(board.pin_mask(colour, frm) & chess.BB_SQUARES[to])


def _next_attacker(board: chess.Board, colour: bool, square: int):
    """The cheapest piece of `colour` that may capture on `square`, or None."""
    best = None
    for frm in chess.scan_forward(board.attackers_mask(colour, square)):
        if not _can_capture_on(board, colour, frm, square):
            continue
        piece = board.piece_at(frm)
        if piece.piece_type == chess.KING:
            if board.attackers_mask(not colour, square):      # the king may not take a defended piece
                continue
            rank = KING_RANK
        else:
            rank = VALUE[piece.piece_type]
        if best is None or rank < best[0]:
            best = (rank, frm)
    return None if best is None else best[1]


def exchange(board: chess.Board, square: int, by: bool) -> int:
    """What the side `by` can win by starting captures on `square`, in pawns (never negative:
    it can always decline). 0 when there is nothing to capture, nothing to capture it with, or
    the exchange does not pay."""
    target = board.piece_at(square)
    if target is None or target.color == by or target.piece_type == chess.KING:
        return 0
    b = board.copy(stack=False)
    gains: list = []
    victim = VALUE[target.piece_type]
    side = by
    while True:
        frm = _next_attacker(b, side, square)
        if frm is None:
            break
        piece = b.piece_at(frm)
        gains.append(victim - gains[-1] if gains else victim)
        victim = VALUE[piece.piece_type]
        b.remove_piece_at(frm)
        b.set_piece_at(square, piece)                          # sliders behind it now see the square
        side = not side
    for d in range(len(gains) - 1, 0, -1):                     # each side stops when stopping is better
        gains[d - 1] = -max(-gains[d - 1], gains[d])
    return max(0, gains[0]) if gains else 0


# --------------------------------------------------------- the position as it is

def loose_pieces(board: chess.Board) -> list:
    """Pieces the other side can win by an exchange. `now` says it is that side's move."""
    found = []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        enemy = not piece.color
        gain = exchange(board, square, enemy)
        if gain <= 0:
            continue
        taker = _next_attacker(board, enemy, square)
        found.append({
            "kind": "loose", "square": chess.square_name(square), "piece": piece.symbol(),
            "gain": gain, "taker": chess.square_name(taker), "now": enemy == board.turn,
            "text": f"{_name(board, square, True)} can be won by {_name(board, taker)} (+{gain})"
                    + ("" if enemy == board.turn else ", if the other side lets it"),
        })
    found.sort(key=lambda f: (not f["now"], -f["gain"], f["square"]))
    return found


def _beyond(board: chess.Board, slider: int, front: int):
    """The nearest piece on the line from `slider` through `front`, past `front`; or None."""
    best = None
    for sq in chess.scan_forward(chess.ray(slider, front) & board.occupied):
        if sq in (slider, front):
            continue
        if not chess.between(slider, sq) & chess.BB_SQUARES[front]:
            continue                                           # on the near side of the front piece
        d = chess.square_distance(front, sq)
        if best is None or d < best[0]:
            best = (d, sq)
    return None if best is None else best[1]


def pins_and_skewers(board: chess.Board) -> list:
    """Absolute pins (to the king), relative pins (to something worth more) and skewers (the
    valuable piece in front, something behind it)."""
    found = []
    for colour in (chess.WHITE, chess.BLACK):
        for ptype in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for slider in board.pieces(ptype, colour):
                if exchange(board, slider, not colour) > 0:
                    continue                                   # the pinning piece would just be taken
                for front in chess.scan_forward(board.attacks_mask(slider) & board.occupied_co[not colour]):
                    fp = board.piece_at(front)
                    if fp.piece_type == chess.KING:
                        continue                               # that is a check
                    back = _beyond(board, slider, front)
                    if back is None:
                        continue
                    bp = board.piece_at(back)
                    if bp.color == colour:
                        continue
                    if bp.piece_type == chess.KING:
                        kind, absolute = "pin", True
                    elif VALUE[bp.piece_type] > VALUE[fp.piece_type]:
                        kind, absolute = "pin", False
                    elif VALUE[bp.piece_type] < VALUE[fp.piece_type]:
                        kind, absolute = "skewer", False
                    else:
                        continue
                    s, f, k = _name(board, slider, True), _name(board, front, True), _name(board, back)
                    if kind == "skewer":
                        text = f"{s} skewers {f} against {k}"
                    elif absolute:
                        text = f"{s} pins {f} to the king"
                    else:
                        text = f"{s} pins {f} to {k}"
                    found.append({
                        "kind": kind, "absolute": absolute, "slider": chess.square_name(slider),
                        "front": chess.square_name(front), "back": chess.square_name(back),
                        "white": colour == chess.WHITE, "text": text})
    found.sort(key=lambda p: (p["kind"] != "pin", not p["absolute"], p["slider"]))
    return found


def analyse(board: chess.Board) -> dict:
    return {"loose": loose_pieces(board), "pins": pins_and_skewers(board)}


# ------------------------------------------------------------- an engine's line

def _fork(board: chess.Board, to: int, mover: bool):
    """After a move to `to` by `mover`: the squares of the targets if it is a fork, else None."""
    forker = board.piece_at(to)
    if forker is None:
        return None
    targets = []
    for t in chess.scan_forward(board.attacks_mask(to) & board.occupied_co[not mover]):
        if not _can_capture_on(board, mover, to, t):
            continue                                           # a pinned forker does not attack
        tp = board.piece_at(t)
        if tp.piece_type == chess.KING:
            targets.append(t)
        elif VALUE[tp.piece_type] > VALUE[forker.piece_type]:
            targets.append(t)
        elif tp.piece_type != chess.PAWN and _next_attacker(board, not mover, t) is None:
            targets.append(t)                                  # undefended
    if len(targets) < 2 or exchange(board, to, not mover) > 0:
        return None
    return targets


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    """Material the move takes off the board (a promotion also adds the new piece)."""
    gain = 0
    if board.is_en_passant(move):
        gain = 1
    else:
        victim = board.piece_at(move.to_square)
        if victim is not None:
            gain = VALUE[victim.piece_type]
    if move.promotion:
        gain += VALUE[move.promotion] - 1
    return gain


def _settled(board: chess.Board) -> bool:
    """Nothing left to take for free: not in check and the side to move has no winning capture."""
    if board.is_check():
        return False
    for sq, piece in board.piece_map().items():
        if piece.color != board.turn and exchange(board, sq, board.turn) > 0:
            return False
    return True


def line_themes(board: chess.Board, moves: list) -> dict:
    """Name what each move of the line does, and the net material of the line once it settles.

    `moves` are UCI strings, the first one legal in `board`. The line stops at the first move
    that is not legal. Material is counted for the side that makes the first move; if the line
    ends in the middle of an exchange it is counted only up to the last settled position, so a
    capture that is about to be recaptured does not show as a gain."""
    b = board.copy(stack=False)
    first = b.turn
    plies, balance, settled_balance, settled_plies = [], 0, 0, 0
    for i, uci in enumerate(moves):
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in b.legal_moves:
            break
        mover = b.turn
        gained = _captured_value(b, move)
        castling = b.is_castling(move)
        b.push(move)
        balance += gained if mover == first else -gained
        tags = []
        if b.is_checkmate():
            tags.append({"tag": "mate"})
        else:
            checkers = b.checkers()
            if checkers and not castling:
                if len(checkers) >= 2:
                    tags.append({"tag": "double check"})
                elif not checkers & chess.BB_SQUARES[move.to_square]:
                    tags.append({"tag": "discovered check"})
            fork = _fork(b, move.to_square, mover)
            if fork:
                tags.append({"tag": "fork", "squares": [chess.square_name(s) for s in fork]})
            lost = exchange(b, move.to_square, not mover)
            if lost - gained >= SACRIFICE_MIN:
                tags.append({"tag": "sacrifice", "pawns": lost - gained})
        plies.append({"tags": tags})
        if b.is_game_over(claim_draw=False) or _settled(b):
            settled_balance, settled_plies = balance, i + 1
    return {"plies": plies,
            "material": {"net": settled_balance, "plies": settled_plies, "white": first == chess.WHITE}}
