"""
Pawn structure and files, from the position alone (python-chess only, no engine).

  * open file: no pawn of either side on it.
  * half-open file for a side: none of that side's pawns on it, at least one of the other side's
    (the side's rooks can press on that pawn). A file with only one colour's pawns is half-open
    for the other colour.
  * doubled pawns: two or more pawns of one colour on a file.
  * isolated pawn: no pawn of the same colour on either neighbouring file.

These are facts about the position, not judgements: a doubled or isolated pawn can be fine
(it may guard something, or the open file may be what the position wants).
"""

from __future__ import annotations

import chess

FILES = "abcdefgh"


def _side(colour: bool) -> str:
    return "white" if colour == chess.WHITE else "black"


def analyse(board: chess.Board) -> dict:
    pawns = {c: board.pieces(chess.PAWN, c) for c in (chess.WHITE, chess.BLACK)}
    count = {c: [0] * 8 for c in pawns}
    for c, squares in pawns.items():
        for sq in squares:
            count[c][chess.square_file(sq)] += 1

    files, lines = [], []
    kinds: dict = {"open": [], "half-w": [], "half-b": []}
    for f in range(8):
        w, b = count[chess.WHITE][f], count[chess.BLACK][f]
        if not w and not b:
            files.append({"file": FILES[f], "kind": "open"})
            kinds["open"].append(FILES[f])
        elif not w:
            files.append({"file": FILES[f], "kind": "half", "white": True})
            kinds["half-w"].append(FILES[f])
        elif not b:
            files.append({"file": FILES[f], "kind": "half", "white": False})
            kinds["half-b"].append(FILES[f])
    if kinds["open"]:
        lines.append({"kind": "open", "text": "open file" + ("s" if len(kinds["open"]) > 1 else "")
                      + ": " + ", ".join(kinds["open"])})
    for key, who, other in (("half-w", "White", "Black"), ("half-b", "Black", "White")):
        if kinds[key]:
            lines.append({"kind": "half", "text": f"half-open for {who} (only {other} has a pawn there): "
                          + ", ".join(kinds[key])})

    weak = []
    for c in (chess.WHITE, chess.BLACK):
        for f in range(8):
            n = count[c][f]
            if n >= 2:
                sqs = sorted((chess.square_name(s) for s in pawns[c] if chess.square_file(s) == f),
                             key=lambda s: int(s[1]))
                weak.append({"kind": "doubled", "white": c == chess.WHITE, "squares": sqs,
                             "text": f"doubled {_side(c)} pawns on the {FILES[f]}-file ({', '.join(sqs)})"})
            if n and not any(0 <= g < 8 and count[c][g] for g in (f - 1, f + 1)):
                for s in pawns[c]:
                    if chess.square_file(s) == f:
                        name = chess.square_name(s)
                        weak.append({"kind": "isolated", "white": c == chess.WHITE, "squares": [name],
                                     "text": f"isolated {_side(c)} pawn {name}"})
    weak.sort(key=lambda w: (w["kind"] != "isolated", w["squares"][0]))
    return {"files": files, "pawns": weak, "found": lines + weak}
