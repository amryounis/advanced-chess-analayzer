"""
How good each move of the game was, from the Evolution analysis (no extra search).

For every move the analysis has the engine's score for the move played (`actual`) and the range of
scores of the best alternatives it compared (`lo` .. `hi`, from White's side). The mover's best
alternative is `hi` for White and `lo` for Black. The move is judged by how much it dropped the mover's
chance of winning, using the winning-chances curve Lichess publishes for its own move
classification:

    win%(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)        (cp clipped to +-1000)

    drop of  10 points or more:  inaccuracy  (?!)
    drop of  20 points or more:  mistake     (?)
    drop of  30 points or more:  blunder     (??)

Judging by winning chances rather than centipawns means that giving up two pawns when already
winning by a rook counts for little, and the same loss in an equal position counts for a lot.

What this is not: a verdict. The scores come from the depth the analysis ran at, and the best
alternative is the best of the lines the analysis kept, not of every legal move. A move whose score
is better than every alternative the analysis found loses nothing. Nothing is marked "good" or
"best": only the moves that gave something away.
"""

from __future__ import annotations

import math

K = 0.00368208
CLIP = 1000
LIMITS = (("??", 30.0), ("?", 20.0), ("?!", 10.0))       # checked in this order
NAMES = {"?!": "inaccuracy", "?": "mistake", "??": "blunder"}


def win_percent(cp: float) -> float:
    cp = max(-CLIP, min(CLIP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-K * cp)) - 1)


def classify(chart: list) -> list:
    """One entry per chart row: {"ply", "white", "drop", "mark"} (mark is "" for a move that is fine)."""
    out = []
    for row in chart:
        white = bool(row["white"])
        best = row["hi"] if white else row["lo"]
        played = row["actual"]
        sign = 1 if white else -1
        drop = max(0.0, win_percent(sign * best) - win_percent(sign * played))
        mark = next((m for m, limit in LIMITS if drop >= limit), "")
        out.append({"ply": row["ply"], "white": white, "drop": round(drop, 1), "mark": mark})
    return out


def counts(rows: list) -> dict:
    """{"w": {"?!": n, "?": n, "??": n}, "b": {...}}"""
    out = {"w": {m: 0 for m, _ in LIMITS}, "b": {m: 0 for m, _ in LIMITS}}
    for r in rows:
        if r["mark"]:
            out["w" if r["white"] else "b"][r["mark"]] += 1
    return out


def marks_for(moves_san: list, chart: list) -> list:
    """The mark of every move of the game, in move order ("" where fine or not analysed)."""
    by_ply = {r["ply"]: r["mark"] for r in classify(chart)}
    return [by_ply.get(i + 1, "") for i in range(len(moves_san))]
