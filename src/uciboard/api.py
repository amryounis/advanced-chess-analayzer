"""
The bridge between the page and the engine (exposed to JavaScript by pywebview).

Everything the page can call is a public method here; all state lives in
underscore attributes so pywebview does not try to expose it.

The page polls `poll(cursor)` a few times a second: new UCI lines plus the
latest summary of the search. Nothing is pushed into the page.
"""

from __future__ import annotations

import threading
from typing import Optional

import chess

from . import __version__, config
from .uci import EngineError, UciEngine, parse_info

MAX_LINES = 20000            # kept in memory; the oldest half is dropped beyond this
POLL_BATCH = 2000            # most lines handed to the page in one poll
PV_MOVES = 10                # moves of the best line shown in the summary


def score_text(score: Optional[dict], white_to_move: bool) -> str:
    """'+0.35', '-1.20', '#5' (White mates in 5) or '-#3', from White's point of view."""
    if not score:
        return ""
    sign = 1 if white_to_move else -1
    if "mate" in score:
        m = score["mate"] * sign
        if m == 0:
            return "#0"
        return f"#{m}" if m > 0 else f"-#{-m}"
    cp = score["cp"] * sign
    return f"{cp / 100:+.2f}"


class Api:
    def __init__(self, settings: Optional[config.Settings] = None):
        self._settings = settings or config.Settings()
        self._board = chess.Board()
        self._root_fen = self._board.fen()
        self._engine: Optional[UciEngine] = None
        self._error = ""                     # why there is no engine, if there is none
        self._paused = False
        self._lock = threading.RLock()       # board + engine control
        self._buf_lock = threading.Lock()    # output lines + summary (the reader thread)
        self._lines: list = []
        self._offset = 0                     # sequence number of _lines[0]
        self._summary: dict = {}

    # ------------------------------------------------------------- engine

    def start(self) -> dict:
        """Start the engine and begin analysing the current position."""
        with self._lock:
            if self._engine is None:
                try:
                    path = self._settings.require_stockfish()
                    engine = UciEngine(path, on_line=self._on_line,
                                       options=self._settings.uci_options())
                    engine.start()
                    self._engine, self._error = engine, ""
                except (config.ConfigError, EngineError) as e:
                    self._error = str(e)
                    self._note(f"! {e}")
            self._restart_analysis()
            return self._state()

    def pause(self) -> dict:
        with self._lock:
            self._paused = True
            if self._engine and self._engine.alive:
                self._engine.stop()
            return self._state()

    def resume(self) -> dict:
        with self._lock:
            self._paused = False
            self._restart_analysis()
            return self._state()

    def shutdown(self, *_args) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
        if engine:
            engine.quit()

    def _restart_analysis(self) -> None:
        # called with the lock held
        engine = self._engine
        if not engine or not engine.alive:
            return
        if self._board.is_game_over(claim_draw=False) or self._paused:
            engine.stop()                  # no search: nothing to show for this position
            with self._buf_lock:
                self._summary = {}
            return
        fen = self._board.fen()
        try:
            engine.analyze(fen, tag=fen)
        except EngineError as e:
            self._error = str(e)
        # Cleared after analyze(): until then the engine may still be printing
        # for the old position, and that must not outlive this call.
        with self._buf_lock:
            self._summary = {}

    # ------------------------------------------------------------- output

    def _note(self, text: str) -> None:
        with self._buf_lock:
            self._append("sys", text)

    def _append(self, kind: str, text: str) -> None:
        # called with _buf_lock held
        self._lines.append({"k": kind, "t": text})
        if len(self._lines) > MAX_LINES:
            drop = MAX_LINES // 2
            del self._lines[:drop]
            self._offset += drop

    def _on_line(self, kind: str, text: str, tag) -> None:
        """Runs on the engine's reader thread (and on ours for sent commands)."""
        with self._buf_lock:
            self._append(kind, text)
            if kind != "out" or not tag:
                return
            info = parse_info(text)
            if not info or "score" not in info or info.get("multipv", 1) != 1:
                return
            try:
                board = chess.Board(tag)
            except ValueError:
                return
            white = board.turn == chess.WHITE
            pv_san = []
            try:
                for uci in info.get("pv", [])[:PV_MOVES]:
                    move = chess.Move.from_uci(uci)
                    pv_san.append(board.san(move))
                    board.push(move)
            except ValueError:
                pass                       # an unreadable move ends the line shown
            self._summary = {
                "depth": info.get("depth", 0), "seldepth": info.get("seldepth", 0),
                "score": score_text(info["score"], white),
                "bound": info.get("bound", ""), "nps": info.get("nps", 0),
                "nodes": info.get("nodes", 0), "time": info.get("time", 0),
                "pv": pv_san,
                "move_number": chess.Board(tag).fullmove_number, "white": white,
            }

    def poll(self, cursor: int = 0) -> dict:
        """New output lines since `cursor`, plus the engine's state and summary."""
        engine = self._engine
        with self._buf_lock:
            start = max(0, cursor - self._offset)
            chunk = self._lines[start:start + POLL_BATCH]
            new_cursor = self._offset + start + len(chunk)
            summary = dict(self._summary)
        return {"lines": chunk, "cursor": new_cursor, "summary": summary,
                "engine": self._engine_state(engine)}

    def _engine_state(self, engine) -> dict:
        if engine is None:
            return {"state": "none", "name": "", "error": self._error}
        if not engine.alive:
            return {"state": "exited", "name": engine.name, "error": self._error}
        if self._board.is_game_over(claim_draw=False):
            state = "idle"
        elif self._paused:
            state = "paused"
        else:
            state = "analysing"
        return {"state": state, "name": engine.name, "error": self._error}

    # -------------------------------------------------------------- board

    def state(self) -> dict:
        with self._lock:
            return self._state()

    def _state(self) -> dict:
        board = self._board
        replay = chess.Board(self._root_fen)
        sans = []
        for move in board.move_stack:
            sans.append(replay.san(move))
            replay.push(move)
        dests: dict = {}
        for move in board.legal_moves:
            dests.setdefault(chess.square_name(move.from_square), []).append(
                chess.square_name(move.to_square))
        last = board.peek() if board.move_stack else None
        return {
            "version": __version__,
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "dests": {k: sorted(set(v)) for k, v in dests.items()},
            "last": ([chess.square_name(last.from_square), chess.square_name(last.to_square)]
                     if last else None),
            "check": board.is_check(),
            "moves": sans,
            "first_move_number": chess.Board(self._root_fen).fullmove_number,
            "first_is_black": chess.Board(self._root_fen).turn == chess.BLACK,
            "over": self._result_text(),
        }

    def _result_text(self) -> str:
        b = self._board
        if b.is_checkmate():
            return "Checkmate. " + ("Black" if b.turn == chess.WHITE else "White") + " wins."
        if b.is_stalemate():
            return "Stalemate."
        if b.is_insufficient_material():
            return "Draw: insufficient material."
        if b.is_seventyfive_moves():
            return "Draw: seventy-five-move rule."
        if b.is_fivefold_repetition():
            return "Draw: fivefold repetition."
        return ""

    def needs_promotion(self, orig: str, dest: str) -> bool:
        with self._lock:
            try:
                frm, to = chess.parse_square(orig), chess.parse_square(dest)
            except ValueError:
                return False
            piece = self._board.piece_at(frm)
            return bool(piece and piece.piece_type == chess.PAWN
                        and chess.square_rank(to) in (0, 7)
                        and chess.Move(frm, to, chess.QUEEN) in self._board.legal_moves)

    def move(self, orig: str, dest: str, promotion: Optional[str] = None) -> dict:
        """Play a move for whoever is to move. An illegal move changes nothing."""
        with self._lock:
            try:
                promo = chess.Piece.from_symbol(promotion.lower()).piece_type if promotion else None
                move = chess.Move(chess.parse_square(orig), chess.parse_square(dest), promo)
            except ValueError:
                return {**self._state(), "rejected": True}
            if move not in self._board.legal_moves:
                return {**self._state(), "rejected": True}
            self._board.push(move)
            self._restart_analysis()
            return self._state()

    def undo(self) -> dict:
        with self._lock:
            if self._board.move_stack:
                self._board.pop()
                self._restart_analysis()
            return self._state()

    def reset(self) -> dict:
        with self._lock:
            self._board = chess.Board()
            self._root_fen = self._board.fen()
            self._restart_analysis()
            return self._state()

    def set_position(self, fen: str) -> dict:
        """Start again from a FEN (the board is set up, the move list restarts)."""
        with self._lock:
            try:
                board = chess.Board(fen.strip())
            except ValueError as e:
                return {**self._state(), "rejected": True, "message": str(e)}
            if not board.is_valid():
                return {**self._state(), "rejected": True,
                        "message": "That position is not legal."}
            self._board = board
            self._root_fen = board.fen()
            self._restart_analysis()
            return self._state()
