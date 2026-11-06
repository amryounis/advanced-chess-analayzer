"""
The game as a PGN that other viewers can show with the analysis in it.

Each move can carry, in the comment, what Lichess and chess.com read: `[%eval x]` (the engine's score
for the position after the move, from White's side), `[%cal ...]` (an arrow) and `[%csl ...]` (squares).
Without an Evolution analysis only the moves, the headers and the tactic names are written; with
one, the scores of the game are added, and the engine's preferred move as a green arrow when it is
clearly better than the move played.

  * Tactic names (fork, discovered check, double check, sacrifice) come from the geometry of the move
    that was played, the same rules as the engine's line in the app (tactics.line_themes). A fork gets
    its targets circled.
  * Moves that gave something away are marked ?! ? ?? (the standard symbols), by the drop in the
    mover's winning chances; see quality.py for the thresholds and what they mean.
  * "Engine preferred" is only said when the analysis compared both moves one move deep and the
    difference is at least BETTER_BY pawns, at the depth the analysis ran; it is the engine's
    opinion at that depth, not a verdict.
"""

from __future__ import annotations

import io
from typing import Optional

import chess
import chess.engine
import chess.pgn
import chess.svg

from . import quality, tactics

BETTER_BY = 0.5                  # pawns, before the engine's preferred move is mentioned


def _score(node: dict):
    if node.get("mate") or node.get("event") == "mate":
        return None
    if node.get("mate_in") is not None:
        return chess.engine.PovScore(chess.engine.Mate(node["mate_in"]), chess.WHITE)
    return chess.engine.PovScore(chess.engine.Cp(int(node["cp"])), chess.WHITE)


def _cp(node: dict, mover_white: bool) -> Optional[int]:
    if node.get("mate_in") is not None or abs(node.get("cp", 0)) >= 29000:
        return None
    return node["cp"] if mover_white else -node["cp"]


def _preferred(evo: dict, ply: int, by_id: dict, mains: dict, played_cp: Optional[int]):
    """The best other first move from the position before `ply`, if clearly better than the played one."""
    src = mains.get(ply - 1)
    if src is None or played_cp is None:
        return None
    white = ply % 2 == 1
    best = None
    for e in evo["edges"]:
        if e["s"] != src["id"] or e["actual"] or e["collapsed"] or e["back"] or not e.get("uci"):
            continue
        cp = _cp(by_id[e["t"]], white)
        if cp is not None and (best is None or cp > best[0]):
            best = (cp, e["uci"])
    if best and best[0] - played_cp >= BETTER_BY * 100:
        return best
    return None


def annotated_pgn(start_fen: str, uci_moves: list, info: dict, evo: Optional[dict] = None) -> str:
    start = chess.Board(start_fen)
    game = chess.pgn.Game()
    for key, name in (("event", "Event"), ("white", "White"), ("black", "Black"),
                      ("date", "Date"), ("result", "Result")):
        if info.get(key):
            game.headers[name] = info[key]
    if start_fen != chess.STARTING_FEN:
        game.setup(start)
    game.headers["Annotator"] = "uciboard"

    by_id, mains, marks = {}, {}, {}
    if evo:
        marks = {r["ply"]: r["mark"] for r in quality.classify(evo.get("chart", []))}
        by_id = {n["id"]: n for n in evo["nodes"]}
        mains = {n["main"]: n for n in evo["nodes"] if n["main"] is not None}

    board, node = start.copy(), game
    for ply, uci in enumerate(uci_moves, start=1):
        move = chess.Move.from_uci(uci)
        mover = board.turn
        themes = tactics.line_themes(board, [uci])["plies"]
        tags = themes[0]["tags"] if themes else []
        board.push(move)
        node = node.add_variation(move)

        words, arrows, squares = [], [], []
        nag = {"?!": chess.pgn.NAG_DUBIOUS_MOVE, "?": chess.pgn.NAG_MISTAKE, "??": chess.pgn.NAG_BLUNDER}.get(marks.get(ply, ""))
        if nag:
            node.nags.add(nag)
        main = mains.get(ply)
        if main is not None:
            score = _score(main)
            if score is not None:
                node.set_eval(score)
            pref = _preferred(evo, ply, by_id, mains, _cp(main, mover == chess.WHITE))
            if pref:
                pm = chess.Move.from_uci(pref[1])
                arrows.append(chess.svg.Arrow(pm.from_square, pm.to_square, color="green"))
                words.append(f"Engine preferred {chess.Board(mains[ply - 1]['fen']).san(pm)} "
                             f"({pref[0] / 100:+.2f} for the mover against "
                             f"{_cp(main, mover == chess.WHITE) / 100:+.2f})")
        for t in tags:
            if t["tag"] == "mate":
                continue
            words.append(t["tag"] + (f" (loses {t['pawns']} pawns' worth if taken)" if t["tag"] == "sacrifice" else ""))
            if t["tag"] == "fork":
                squares += [chess.svg.Arrow(chess.parse_square(s), chess.parse_square(s), color="red")
                            for s in t["squares"]]
        if arrows or squares:
            node.set_arrows(arrows + squares)
        if words:
            node.comment = (node.comment + " " if node.comment else "") + "; ".join(words)

    out = io.StringIO()
    game.accept(chess.pgn.FileExporter(out))
    return out.getvalue()
