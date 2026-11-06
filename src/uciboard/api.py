"""
The bridge between the page and the engine (exposed to JavaScript by pywebview).

Everything the page can call is a public method here; all state lives in
underscore attributes so pywebview does not try to expose it.

The page polls `poll(cursor)` a few times a second: new UCI lines plus the
latest summary of the search. Nothing is pushed into the page.
"""

from __future__ import annotations

import io
import json
import threading
import traceback
from typing import Optional

import chess
import chess.pgn

from . import __version__, config, evolution, pgnexport, posgraph, quality, structure, tactics
from .layout import layout as run_layout
from .uci import EngineError, UciEngine, parse_info

MAX_LINES = 20000            # kept in memory; the oldest half is dropped beyond this
POLL_BATCH = 2000            # most lines handed to the page in one poll
PV_MOVES = 10                # moves of the engine's best line kept (the page draws as many as you pick)


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
        self._view: Optional[chess.Board] = None     # a position being looked at, not part of the game
        self._view_last: Optional[list] = None
        self._ply: Optional[int] = None              # how many moves of the game are on the board; None = all
        self._info: dict = {}                        # who played, from a loaded PGN
        self._evo_lock = threading.Lock()
        self._theme_cache: dict = {}
        self._evo_thread: Optional[threading.Thread] = None
        self._evo_cancel = threading.Event()
        self._evo_searcher = None
        self._evo_busy = False                       # the job has the machine: live analysis waits
        self._evo_status: dict = {"state": "idle", "done": 0, "total": 0, "message": "", "error": ""}
        self._evo_result: Optional[dict] = None

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
        self.evolution_cancel()
        thread = self._evo_thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            engine, self._engine = self._engine, None
        if engine:
            engine.quit()

    def _cursor(self) -> int:
        """How many moves of the game are on the board."""
        total = len(self._board.move_stack)
        return total if self._ply is None else max(0, min(self._ply, total))

    def _game_board(self) -> chess.Board:
        """The game as far as the cursor (the whole game unless someone stepped back)."""
        n = self._cursor()
        if n == len(self._board.move_stack):
            return self._board
        b = self._board.copy(stack=True)
        while len(b.move_stack) > n:
            b.pop()
        return b

    def _shown(self) -> chess.Board:
        """The position on the board: the game up to the cursor, or one being looked at."""
        return self._view if self._view is not None else self._game_board()

    def _restart_analysis(self) -> None:
        # called with the lock held
        engine = self._engine
        if not engine or not engine.alive:
            return
        shown = self._shown()
        if self._evo_busy or shown.is_game_over(claim_draw=False) or self._paused:
            engine.stop()                  # no search: nothing to show for this position
            with self._buf_lock:
                self._summary = {}
            return
        fen = shown.fen()
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
            pv_san, pv_uci, arrows = [], [], []
            try:
                for uci in info.get("pv", [])[:PV_MOVES]:
                    move = chess.Move.from_uci(uci)
                    if move not in board.legal_moves:
                        break              # not a move of this position: the line ends here
                    arrows.append({"orig": chess.square_name(move.from_square),
                                   "dest": chess.square_name(move.to_square),
                                   "white": board.turn == chess.WHITE})
                    pv_san.append(board.san(move))
                    pv_uci.append(uci)
                    board.push(move)
            except ValueError:
                pass                       # an unreadable move ends the line shown
            self._summary = {
                "depth": info.get("depth", 0), "seldepth": info.get("seldepth", 0),
                "score": score_text(info["score"], white),
                "bound": info.get("bound", ""), "nps": info.get("nps", 0),
                "nodes": info.get("nodes", 0), "time": info.get("time", 0),
                "pv": pv_san, "pv_uci": pv_uci, "arrows": arrows, "fen": tag,
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
        if summary.get("pv_uci"):
            summary["themes"] = self._themes(summary["fen"], summary["pv_uci"])
        return {"lines": chunk, "cursor": new_cursor, "summary": summary,
                "engine": self._engine_state(engine)}

    def _themes(self, fen: str, pv: list):
        """What the moves of the engine's line do (fork, discovered check, ...), worked out
        from the geometry of the position; remembered, because the page asks every few moments."""
        key = (fen, tuple(pv))
        if key not in self._theme_cache:
            try:
                found = tactics.line_themes(chess.Board(fen), pv)
            except Exception:                          # noqa: BLE001 - a label is never worth a crash
                found = None
            if len(self._theme_cache) > 64:
                self._theme_cache.clear()
            self._theme_cache[key] = found
        return self._theme_cache[key]

    def _engine_state(self, engine) -> dict:
        if engine is None:
            return {"state": "none", "name": "", "error": self._error}
        if not engine.alive:
            return {"state": "exited", "name": engine.name, "error": self._error}
        if self._evo_busy:
            state = "busy"
        elif self._shown().is_game_over(claim_draw=False):
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
        shown = self._shown()
        at = self._game_board()
        replay = chess.Board(self._root_fen)
        sans = []
        for move in board.move_stack:
            sans.append(replay.san(move))
            replay.push(move)
        dests: dict = {}
        if self._view is None:                      # nothing can be played while looking at a position
            for move in at.legal_moves:
                dests.setdefault(chess.square_name(move.from_square), []).append(
                    chess.square_name(move.to_square))
        if self._view is not None:
            last = self._view_last
        elif at.move_stack:
            mv = at.peek()
            last = [chess.square_name(mv.from_square), chess.square_name(mv.to_square)]
        else:
            last = None
        root = chess.Board(self._root_fen)
        return {
            "version": __version__,
            "fen": shown.fen(),
            "game_fen": board.fen(),
            "viewing": self._view is not None,
            "turn": "white" if shown.turn == chess.WHITE else "black",
            "dests": {k: sorted(set(v)) for k, v in dests.items()},
            "last": last,
            "check": shown.is_check(),
            "moves": sans,
            "ply": self._cursor(),
            "marks": self._marks(sans),
            "first_move_number": root.fullmove_number,
            "first_is_black": root.turn == chess.BLACK,
            "over": self._result_text(shown),
            "info": dict(self._info),
            "tactics": self._tactics(shown),
            "control": posgraph.control_map(shown),
            "structure": structure.analyse(shown),
        }

    def _marks(self, sans: list) -> list:
        """Inaccuracy / mistake / blunder marks for the game's moves, if the analysis is of this game."""
        evo = self._evo_result
        if not evo or evo.get("start_fen") != self._root_fen or evo.get("moves") != sans:
            return []
        return quality.marks_for(sans, evo["chart"])

    @staticmethod
    def _tactics(board: chess.Board) -> dict:
        try:
            return tactics.analyse(board)
        except Exception:                              # noqa: BLE001 - overlays are optional
            return {"loose": [], "pins": []}

    @staticmethod
    def _result_text(b: chess.Board) -> str:
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
            piece = self._game_board().piece_at(frm)
            return bool(piece and piece.piece_type == chess.PAWN
                        and chess.square_rank(to) in (0, 7)
                        and chess.Move(frm, to, chess.QUEEN) in self._game_board().legal_moves)

    def move(self, orig: str, dest: str, promotion: Optional[str] = None) -> dict:
        """Play a move for whoever is to move. An illegal move changes nothing."""
        with self._lock:
            if self._view is not None:
                return {**self._state(), "rejected": True,
                        "message": "You are looking at a position from the graph. Go back to the game to move."}
            try:
                promo = chess.Piece.from_symbol(promotion.lower()).piece_type if promotion else None
                move = chess.Move(chess.parse_square(orig), chess.parse_square(dest), promo)
            except ValueError:
                return {**self._state(), "rejected": True}
            at = self._game_board()
            if move not in at.legal_moves:
                return {**self._state(), "rejected": True}
            n = self._cursor()
            if n < len(self._board.move_stack):
                if self._board.move_stack[n] == move:      # the game's own next move: just step on
                    self._ply = n + 1
                    self._restart_analysis()
                    return self._state()
                del_to = n                                 # a different move: the rest of the game goes
                while len(self._board.move_stack) > del_to:
                    self._board.pop()
            self._board.push(move)
            self._ply = None
            self._restart_analysis()
            return self._state()

    def undo(self) -> dict:
        """Take back the move on the board; the moves after it (if someone stepped back) go too."""
        with self._lock:
            self._view = None
            n = self._cursor()
            if n:
                while len(self._board.move_stack) > n - 1:
                    self._board.pop()
                self._ply = None
            self._restart_analysis()
            return self._state()

    def goto_ply(self, ply: int) -> dict:
        """Show the game after `ply` moves (0 is the start). The moves stay: this is only looking."""
        with self._lock:
            try:
                n = int(ply)
            except (TypeError, ValueError):
                return {**self._state(), "rejected": True}
            total = len(self._board.move_stack)
            n = max(0, min(n, total))
            self._view, self._view_last = None, None
            self._ply = None if n == total else n
            self._restart_analysis()
            return self._state()

    def step(self, delta: int) -> dict:
        """One move back or forward from where the board is."""
        with self._lock:
            try:
                d = int(delta)
            except (TypeError, ValueError):
                return {**self._state(), "rejected": True}
            n = self._cursor() + d
        return self.goto_ply(n)

    def reset(self) -> dict:
        with self._lock:
            self._view, self._info, self._ply = None, {}, None
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
            self._view, self._info, self._ply = None, {}, None
            self._board = board
            self._root_fen = board.fen()
            self._restart_analysis()
            return self._state()

    # --------------------------------------------------------- games and views

    def load_pgn(self, text: str) -> dict:
        """Put the main line of a pasted PGN on the board (the game to analyse)."""
        try:
            game = chess.pgn.read_game(io.StringIO(text or ""))
        except (ValueError, KeyError) as e:
            return {**self.state(), "rejected": True, "message": f"Cannot read that PGN: {e}"}
        if game is None:
            return {**self.state(), "rejected": True, "message": "No game found in that text."}
        variant = game.headers.get("Variant", "Standard")
        if variant.lower() not in ("standard", "chess", ""):
            return {**self.state(), "rejected": True,
                    "message": f"Only standard chess is supported (this is {variant})."}
        start = game.board()
        board = start.copy()
        for move in game.mainline_moves():
            board.push(move)
        if not board.move_stack:
            message = str(game.errors[0]) if game.errors else "That game has no moves."
            return {**self.state(), "rejected": True, "message": message}
        h = game.headers
        info = {"white": h.get("White", ""), "black": h.get("Black", ""), "event": h.get("Event", ""),
                "date": h.get("Date", ""), "result": h.get("Result", "")}
        with self._lock:
            self._view, self._ply = None, None
            self._board, self._root_fen = board, start.fen()
            self._info = {k: v for k, v in info.items() if v.strip("?. ")}    # drop "?" placeholders
            self._restart_analysis()
            st = self._state()
        if game.errors:
            st["message"] = f"The game was read up to an illegal move ({game.errors[0]})."
        return st

    def export_pgn(self) -> dict:
        """The game as PGN, with the Evolution analysis in the comments if it is for this game."""
        with self._lock:
            start_fen = self._root_fen
            moves = [m.uci() for m in self._board.move_stack]
            info = dict(self._info)
            evo = self._evo_result
        if not moves:
            return {"rejected": True, "message": "There is no game to export yet."}
        sans, b = [], chess.Board(start_fen)
        for u in moves:
            m = chess.Move.from_uci(u)
            sans.append(b.san(m))
            b.push(m)
        analysed = bool(evo and evo.get("start_fen") == start_fen and evo.get("moves") == sans)
        if not info.get("result"):
            info["result"] = {"1-0": "1-0", "0-1": "0-1", "1/2-1/2": "1/2-1/2"}.get(b.result(), "*")
        text = pgnexport.annotated_pgn(start_fen, moves, info, evo if analysed else None)
        return {"pgn": text, "analysed": analysed}

    def view_position(self, fen: str, last: Optional[list] = None) -> dict:
        """Look at another position (a node of the graph) without touching the game."""
        try:
            board = chess.Board(fen)
        except ValueError:
            return {**self.state(), "rejected": True, "message": "Not a valid position."}
        if not board.is_valid():
            return {**self.state(), "rejected": True, "message": "That position is not legal."}
        try:
            ok = isinstance(last, list) and len(last) == 2 and all(
                isinstance(q, str) and chess.parse_square(q) >= 0 for q in last)
        except ValueError:
            ok = False
        if not ok:
            last = None
        with self._lock:
            self._view, self._view_last = board, last
            self._restart_analysis()
            return self._state()

    def clear_view(self) -> dict:
        with self._lock:
            self._view, self._view_last = None, None
            self._restart_analysis()
            return self._state()

    # ------------------------------------------------------------ evolution

    def evolution_start(self, params: Optional[dict] = None) -> dict:
        """Analyse the game on the board for the evolution graph (runs in the background)."""
        with self._lock:
            if self._evo_thread and self._evo_thread.is_alive():
                return {"started": False, "message": "An analysis is already running."}
            if not self._board.move_stack:
                return {"started": False, "message": "Play some moves or load a PGN first."}
            try:
                path = self._settings.require_stockfish()
            except config.ConfigError as e:
                return {"started": False, "message": str(e)}
            s = self._settings
            wanted = evolution.Params(depth=s.evo_depth, lines=s.evo_lines, seconds=s.evo_seconds,
                                      check_depth=s.evo_check_depth)
            for key, value in (params or {}).items():
                if key in ("depth", "lines", "seconds", "check_depth", "check_tolerance", "max_plies"):
                    try:
                        setattr(wanted, key, type(getattr(wanted, key))(value))
                    except (TypeError, ValueError):
                        return {"started": False, "message": f"{key} must be a number."}
            wanted.clamp()
            start_fen = self._root_fen
            moves = [m.uci() for m in self._board.move_stack]
            info = dict(self._info)
            self._evo_cancel = threading.Event()
            self._evo_busy = True
            if self._engine and self._engine.alive:
                self._engine.stop()                       # the job needs the machine
            with self._buf_lock:
                self._summary = {}
            self._set_evo(state="running", done=0, total=0, message="starting the engine", error="")
            self._evo_result = None
            self._evo_thread = threading.Thread(
                target=self._run_evolution, args=(path, start_fen, moves, wanted, info), daemon=True)
            self._evo_thread.start()
        return {"started": True}

    def evolution_defaults(self) -> dict:
        s = self._settings
        return {"depth": s.evo_depth, "seconds": s.evo_seconds, "lines": s.evo_lines,
                "check_depth": s.evo_check_depth}

    def evolution_status(self) -> dict:
        with self._evo_lock:
            return dict(self._evo_status)

    def evolution_result(self) -> Optional[dict]:
        return self._evo_result

    def evolution_cancel(self) -> dict:
        self._evo_cancel.set()
        searcher = self._evo_searcher
        if searcher is not None:
            searcher.abort()
        return self.evolution_status()

    def _set_evo(self, **changes) -> None:
        with self._evo_lock:
            self._evo_status.update(changes)

    def _run_evolution(self, path: str, start_fen: str, moves: list, params, info: dict) -> None:
        cache_file = config.cache_path(self._settings) / (
            evolution.cache_key(start_fen, moves, params) + ".json")
        try:
            data = None
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if data is not None:
                self._set_evo(message="from the saved analysis")
            else:
                with evolution.UciSearcher(path, self._settings.uci_options()) as searcher:
                    self._evo_searcher = searcher
                    evo = evolution.build(
                        start_fen, moves, searcher, params,
                        progress=lambda done, total, msg: self._set_evo(done=done, total=total, message=msg),
                        cancel=self._evo_cancel)
                self._set_evo(message="laying out the graph")
                ranks = {n.id: n.rank for n in evo.nodes}
                main = {n.id for n in evo.nodes if n.main is not None}
                laid = run_layout(ranks, main, [(e.src, e.dst, e.actual) for e in evo.edges])
                data = evo.to_json(laid)
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(data), encoding="utf-8")
                except OSError:
                    pass                                   # not being able to save is not an error
            data["info"] = info
            # not kept with the saved graph: it costs nothing to work out, and saved graphs made
            # before the measures existed get them too
            data["metrics"] = posgraph.game_metrics(data["start_fen"], data["moves"])
            data["metric_names"] = posgraph.METRICS
            rows = quality.classify(data["chart"])
            data["quality"] = {"rows": rows, "counts": quality.counts(rows)}
            self._evo_result = data
            self._set_evo(state="done", message="done")
        except evolution.Cancelled:
            self._set_evo(state="cancelled", message="cancelled")
        except Exception as e:                             # noqa: BLE001 - shown to the user
            self._note(f"! evolution: {traceback.format_exc(limit=3)}")
            self._set_evo(state="error", error=str(e) or e.__class__.__name__)
        finally:
            self._evo_searcher = None
            with self._lock:
                self._evo_busy = False
                self._restart_analysis()
