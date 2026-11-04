"""
Chess evolution graph, after Lu, Wang and Lin, "Chess Evolution Visualization",
IEEE Trans. Visualization and Computer Graphics 20(5), 2014.

The pipeline (section numbers are the paper's):

  3.1  For every position of the game the engine gives its best move sequences. Which
       ones are kept depends on how good the player's actual move was: if it is the
       n-th best, keep the best four when n <= 4, the best n when 4 < n <= 8, and the
       best eight plus the sequence holding the player's move when n >= 9.
       The sequences are laid into one tree; identical positions are merged
       (hash table), and chains of positions with nothing happening on them are
       shortened to a single edge. Positions that carry an event (a draw, an effective
       check, a checkmate), the player's own positions, branching points and the
       neighbours of event positions are kept.
  3.2  Edge thickness from equation (2): how much better a move is than the worst
       alternative from the same position, on a log scale, normalised per position.
  3.3  A score chart: for each move the engine's score band over the kept sequences
       and the score of the move actually played.

The layout (equation 1) is in layout.py.

Choices the paper leaves open, and what is done here:
  * "Effective check": a check after which the checking side is not worse off. Judged by two
    quick searches (the position before and the position after the check, one ply apart in
    depth so both see the same horizon): effective when the checker's score after is at
    least its score before (check_tolerance centipawns of slack, default none).
  * Scores are centipawns from White's side; a mate in m counts as 30000 - m.
  * A node's score comes from the analysis that reached it in the fewest plies (it was
    searched deepest from there); positions of the game itself use their own analysis.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import threading
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Protocol

import chess

from .uci import EngineError, UciEngine, parse_info

MATE_CP = 30000
MIN_SELECTED = 4             # n <= 4: the best four sequences
MAX_SELECTED = 8             # n >= 9: the best eight plus the player's own
THICKNESS_MAX = 30.0         # edge thickness, normalised per position into [1, 30] (paper)


class Cancelled(Exception):
    """The job was cancelled."""


@dataclass
class Params:
    depth: int = 16              # paper: 20 (grandmaster level, ten moves ahead)
    lines: int = 9               # sequences asked for, enough to rank the player's move (paper: 9)
    seconds: float = 20.0        # most time on one position, whatever the depth
    check_depth: int = 10        # depth of the two quick searches that judge a check
    check_tolerance: int = 0     # centipawns
    max_plies: int = 0           # longest sequence kept; 0 = as long as the engine's depth

    def clamp(self) -> "Params":
        self.depth = max(1, min(60, int(self.depth)))
        self.lines = max(MIN_SELECTED, min(12, int(self.lines)))
        self.seconds = max(0.2, min(600.0, float(self.seconds)))
        self.check_depth = max(1, min(40, int(self.check_depth)))
        self.check_tolerance = max(0, min(500, int(self.check_tolerance)))
        self.max_plies = max(0, min(80, int(self.max_plies)))
        return self

    @property
    def plies(self) -> int:
        return self.max_plies or self.depth


@dataclass
class Line:
    """One candidate sequence from the engine."""
    rank: int                    # 1 = best
    depth: int
    cp: int                      # score for the side to move at the root (mate folded in)
    pv: list
    mate: Optional[int] = None   # mate in m for the side to move (negative: it gets mated)


class Searcher(Protocol):
    def search(self, fen: str, depth: int, multipv: int, seconds: float,
               searchmoves: Optional[list] = None) -> list: ...
    def abort(self) -> None: ...


def score_cp(score: dict) -> int:
    if "mate" in score:
        m = score["mate"]
        return (MATE_CP - abs(m)) * (1 if m > 0 else -1) if m != 0 else -MATE_CP
    return int(score["cp"])


class UciSearcher:
    """Bounded searches on a Stockfish of its own (the live analysis keeps its engine)."""

    def __init__(self, path: str, options: Optional[dict] = None):
        self._engine = UciEngine(path, on_line=self._on_line, options=options)
        self._lock = threading.Lock()
        self._tag: object = None
        self._done = threading.Event()
        self._lines: dict = {}
        self._bounds: dict = {}
        self._aborted = False

    def __enter__(self) -> "UciSearcher":
        self._engine.start()
        return self

    def __exit__(self, *exc) -> None:
        self._engine.quit()

    def abort(self) -> None:
        self._aborted = True
        try:
            self._engine.stop()
        except EngineError:
            pass
        self._done.set()

    def _on_line(self, kind: str, text: str, tag) -> None:
        if kind == "sys":
            self._done.set()                      # the engine died: do not wait for it
            return
        if kind != "out" or tag is None or tag is not self._tag:
            return
        if text.startswith("bestmove"):
            self._done.set()
            return
        info = parse_info(text)
        if not info or not info.get("pv") or not info.get("score"):
            return
        line = Line(rank=info.get("multipv", 1), depth=info.get("depth", 0),
                    cp=score_cp(info["score"]), pv=info["pv"],
                    mate=info["score"].get("mate"))
        with self._lock:
            target = self._bounds if info.get("bound") else self._lines
            old = target.get(line.rank)
            if old is None or line.depth >= old.depth:
                target[line.rank] = line

    def search(self, fen: str, depth: int, multipv: int, seconds: float,
               searchmoves: Optional[list] = None) -> list:
        if self._aborted:
            raise Cancelled()
        tag = object()
        with self._lock:
            self._tag = tag
            self._lines, self._bounds = {}, {}
        self._done.clear()
        self._engine.set_option("MultiPV", multipv)
        limits = f"depth {depth} movetime {int(seconds * 1000)}"
        if searchmoves:
            limits += " searchmoves " + " ".join(searchmoves)
        self._engine.analyze(fen, tag=tag, limits=limits)
        if not self._done.wait(seconds + 60):
            self._engine.stop()
            raise EngineError("The engine did not finish a search in time.")
        if self._aborted:
            raise Cancelled()
        if not self._engine.alive:
            raise EngineError("The engine stopped during the analysis.")
        with self._lock:
            found = dict(self._bounds)
            found.update(self._lines)             # exact scores win over bounds
            return [found[k] for k in sorted(found)]


# --------------------------------------------------------------------------- the graph

@dataclass
class Node:
    id: int
    key: str
    fen: str
    rank: int                    # column: moves from the start of the game (shortest route)
    main: Optional[int]          # ply of the game it is, when the player reached it
    turn: str                    # side to move: "w" or "b"
    label: str                   # the move that led here, e.g. "12... Nf6"
    uci: str = ""                # that move
    check: str = ""              # who gave check: "w", "b" or ""
    mate: bool = False
    draw: bool = False
    effective: bool = False      # the check is an effective one
    cp: int = 0                  # score from White's side
    mate_in: Optional[int] = None    # White's mate in m (negative: Black mates), if mating
    eval_dist: int = 10 ** 6     # plies from the analysis root the score was taken at
    parent_fen: str = ""         # a position it was reached from (for judging a check)

    @property
    def event(self) -> str:
        if self.mate:
            return "mate"
        if self.draw:
            return "draw"
        if self.check and self.effective:
            return "check"
        return ""


@dataclass
class Edge:
    src: int
    dst: int
    uci: str
    san: str
    actual: bool = False         # the player's own move
    score: int = 0               # White's score of the line this move was found in
    score_dist: int = 10 ** 6    # plies from the analysis root that score was taken at
    width: float = 1.0           # thickness in [1, 30]
    steps: list = field(default_factory=list)    # collapsed chains: [{uci, san, fen}, ...]

    @property
    def collapsed(self) -> bool:
        return len(self.steps) > 1


def move_label(board_before: chess.Board, san: str) -> str:
    n = board_before.fullmove_number
    return f"{n}. {san}" if board_before.turn == chess.WHITE else f"{n}... {san}"


def white_view(cp: int, turn_is_white: bool) -> int:
    return cp if turn_is_white else -cp


def select_lines(lines: list, played: Optional[str]) -> tuple:
    """The paper's rule for which sequences to keep (3.1).

    Returns (kept, player_rank, need_player_line). player_rank is where the player's
    move stands among `lines` (None if it is not among them); need_player_line says the
    sequence holding the player's move still has to be searched for separately."""
    rank = None
    if played:
        for ln in lines:
            if ln.pv and ln.pv[0] == played:
                rank = ln.rank
                break
    if rank is not None and rank <= MIN_SELECTED:
        return lines[:MIN_SELECTED], rank, False
    if rank is not None and rank <= MAX_SELECTED:
        return lines[:rank], rank, False
    if rank is not None:                              # ninth or worse, but among the lines
        return lines[:MAX_SELECTED] + [ln for ln in lines if ln.rank == rank], rank, False
    if played is None:                                # no move was played from here
        return lines[:MIN_SELECTED], None, False
    return lines[:MAX_SELECTED], None, True


@dataclass
class Evolution:
    """The finished graph, as the page needs it."""
    start_fen: str
    moves: list                  # SAN of the game
    params: Params
    nodes: list                  # list[Node], after shortening
    edges: list                  # list[Edge], after shortening
    chart: list                  # one dict per ply
    stats: dict

    def to_json(self, layout: dict) -> dict:
        pos = layout["pos"]
        routes = layout["routes"]            # one per edge, in order
        nodes = []
        for n in self.nodes:
            x, y = pos[n.id]
            nodes.append({
                "id": n.id, "x": round(x, 1), "y": round(y, 1), "rank": n.rank, "main": n.main,
                "turn": n.turn, "label": n.label, "uci": n.uci, "fen": n.fen, "check": n.check,
                "event": n.event, "cp": n.cp, "mate_in": n.mate_in})
        edges = []
        for e, r in zip(self.edges, routes):
            edges.append({
                "s": e.src, "t": e.dst, "w": round(e.width, 2), "actual": e.actual,
                "collapsed": e.collapsed, "back": r["back"], "uci": e.uci,
                "via": [[round(px, 1), round(py, 1)] for px, py in r["via"]],
                "steps": e.steps if e.collapsed else []})
        return {"start_fen": self.start_fen, "moves": self.moves, "params": asdict(self.params),
                "nodes": nodes, "edges": edges, "chart": self.chart, "stats": self.stats,
                "extent": layout["extent"]}


GRAPH_VERSION = 2            # what the saved graphs contain; a new version leaves older files unused


def cache_key(start_fen: str, moves: list, params: Params) -> str:
    blob = json.dumps([GRAPH_VERSION, start_fen, moves, asdict(params)], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:20]


Progress = Callable[[int, int, str], None]


def build(start_fen: str, moves_uci: list, searcher: Searcher, params: Params,
          progress: Optional[Progress] = None,
          cancel: Optional[threading.Event] = None) -> Evolution:
    params = params.clamp()
    report = progress or (lambda done, total, msg: None)

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    # ---- the game itself
    board = chess.Board(start_fen)
    boards = [board.copy()]
    sans, labels = [], []
    for uci in moves_uci:
        mv = chess.Move.from_uci(uci)
        if mv not in board.legal_moves:
            raise ValueError(f"Illegal move {uci} in the game")
        san = board.san(mv)
        labels.append(move_label(board, san))
        sans.append(san)
        board.push(mv)
        boards.append(board.copy())
    n_pos = len(boards)

    nodes: dict = {}                       # key -> Node
    by_id: list = []
    edges: dict = {}                       # (src, dst) -> Edge
    visited = 0                           # positions walked, before identical ones are merged

    def new_node(key: str, b: chess.Board, rank: int, main: Optional[int], label: str,
                 uci: str, parent_fen: str) -> Node:
        mover_white = b.turn == chess.BLACK          # who has just moved
        node = Node(id=len(by_id), key=key, fen=b.fen(), rank=rank, main=main,
                    turn="w" if b.turn == chess.WHITE else "b", label=label, uci=uci,
                    parent_fen=parent_fen)
        if uci:
            node.check = ("w" if mover_white else "b") if b.is_check() else ""
        node.mate = b.is_checkmate()
        node.draw = (not node.mate) and (b.is_stalemate() or b.is_insufficient_material()
                                         or b.is_seventyfive_moves() or b.is_fivefold_repetition()
                                         or b.can_claim_draw())
        by_id.append(node)
        return node

    # the player's positions: a repeated position of the game is kept as a node of its own
    main_nodes = []
    for ply, b in enumerate(boards):
        key = b.epd()
        if key in nodes:
            key = f"{key}#{ply}"
        node = new_node(key, b, ply, ply, "start" if ply == 0 else labels[ply - 1],
                        moves_uci[ply - 1] if ply else "",
                        boards[ply - 1].fen() if ply else "")
        nodes[key] = node
        main_nodes.append(node)
    for ply in range(1, n_pos):
        edges[(main_nodes[ply - 1].id, main_nodes[ply].id)] = Edge(
            main_nodes[ply - 1].id, main_nodes[ply].id, moves_uci[ply - 1], sans[ply - 1],
            actual=True)

    chart = []
    todo = [i for i in range(n_pos) if not boards[i].is_game_over(claim_draw=False)]
    total = len(todo)
    done = 0

    def set_eval(node: Node, cp_white: int, mate_white: Optional[int], dist: int) -> None:
        if dist < node.eval_dist:
            node.cp, node.mate_in, node.eval_dist = cp_white, mate_white, dist

    for ply in range(n_pos):
        b = boards[ply]
        node = main_nodes[ply]
        if ply not in todo:
            # a finished game: mate is a win for the side that did not have to move
            set_eval(node, (MATE_CP if b.turn == chess.BLACK else -MATE_CP) if node.mate else 0,
                     None, 0)
            continue
        check_cancel()
        report(done, total, f"analysing position {done + 1} of {total}")
        lines = searcher.search(b.fen(), params.depth, params.lines, params.seconds)
        if not lines:
            done += 1
            continue
        played = moves_uci[ply] if ply < len(moves_uci) else None
        kept, rank, need_player = select_lines(lines, played)
        if need_player:
            extra = searcher.search(b.fen(), params.depth, 1, params.seconds, [played])
            if extra:
                extra[0].rank = 0
                kept = kept + extra[:1]
                rank = None
        white_turn = b.turn == chess.WHITE
        top = lines[0]
        set_eval(node, white_view(top.cp, white_turn),
                 None if top.mate is None else white_view(top.mate, white_turn), 0)

        for ln in kept:
            parent = node
            walk = b.copy()
            for t, uci in enumerate(ln.pv[:params.plies], start=1):
                mv = chess.Move.from_uci(uci)
                if mv not in walk.legal_moves:
                    break
                san = walk.san(mv)
                label = move_label(walk, san)
                before_fen = walk.fen()
                walk.push(mv)
                key = walk.epd()
                child = nodes.get(key)
                visited += 1
                if child is None:
                    child = new_node(key, walk, ply + t, None, label, uci, before_fen)
                    nodes[key] = child
                set_eval(child, white_view(ln.cp, white_turn),
                         None if ln.mate is None else white_view(ln.mate, white_turn), t)
                edge = edges.get((parent.id, child.id))
                if edge is None:
                    edge = edges[(parent.id, child.id)] = Edge(parent.id, child.id, uci, san)
                # What an edge is worth comes from the analysis that compared it with its
                # siblings (the nearest one to its source), not from the next position's own.
                if t < edge.score_dist:
                    edge.score, edge.score_dist = white_view(ln.cp, white_turn), t
                parent = child
                if child.mate or child.draw:
                    break
        # the chart: the band of the kept sequences, and the move actually played
        if ply < len(moves_uci):
            scores = [white_view(ln.cp, white_turn) for ln in kept]
            chart.append({"ply": ply + 1, "label": labels[ply], "white": white_turn,
                          "lo": min(scores), "hi": max(scores), "rank": rank, "actual": None})
        done += 1

    # the score of the move played is the score of the position it led to
    for row in chart:
        row["actual"] = main_nodes[row["ply"]].cp

    # ---- columns: moves from the start of the game, by the shortest route
    out_edges: dict = {}
    in_edges: dict = {}
    for (s, d), e in edges.items():
        out_edges.setdefault(s, []).append(e)
        in_edges.setdefault(d, []).append(e)
    heap = [(n.rank, n.id) for n in main_nodes]
    heapq.heapify(heap)
    dist = {n.id: n.rank for n in main_nodes}
    while heap:
        r, u = heapq.heappop(heap)
        if r > dist.get(u, 10 ** 9):
            continue
        for e in out_edges.get(u, []):
            v = e.dst
            if by_id[v].main is None and r + 1 < dist.get(v, 10 ** 9):
                dist[v] = r + 1
                heapq.heappush(heap, (r + 1, v))
    for n in by_id:
        n.rank = dist.get(n.id, n.rank)

    # ---- which checks are effective (they come out of searches, so cancel is honoured)
    check_nodes = [n for n in by_id if n.check and not n.mate and n.parent_fen]
    cache: dict = {}

    def quick(fen: str, depth: int) -> int:
        k = (fen, depth)
        if k not in cache:
            lines = searcher.search(fen, depth, 1, params.seconds)
            cache[k] = lines[0].cp if lines else 0
        return cache[k]

    for i, n in enumerate(check_nodes):
        check_cancel()
        report(done, total + len(check_nodes), f"judging checks {i + 1} of {len(check_nodes)}")
        before = quick(n.parent_fen, params.check_depth)                 # checker to move
        after = -quick(n.fen, max(1, params.check_depth - 1))            # seen from the checker
        n.effective = after >= before - params.check_tolerance
        done += 1

    # ---- edge thickness, equation (2), per position
    for s, outs in out_edges.items():
        mover_white = by_id[s].turn == "w"
        deltas = [(e.score if mover_white else -e.score) for e in outs]
        lo = min(deltas)
        raw = []
        for d in deltas:
            # equation (2); a gap under a few centipawns would give less than the minimum alpha = 1
            raw.append(max(1.0, math.log(max(d - lo, 1)) ** 2) if d > lo else 1.0)
        top = max(raw)
        for e, r in zip(outs, raw):
            e.width = 1.0 if top <= 1.0 else 1.0 + (THICKNESS_MAX - 1.0) * (r - 1.0) / (top - 1.0)
    width_of = {(e.src, e.dst): e.width for e in edges.values()}

    # ---- shortening
    keep = set()
    for n in by_id:
        if n.main is not None or n.event:
            keep.add(n.id)
        elif len(out_edges.get(n.id, [])) != 1 or len(in_edges.get(n.id, [])) != 1:
            keep.add(n.id)
    for n in list(by_id):
        if n.event:                                   # the neighbours of event positions stay
            for e in in_edges.get(n.id, []):
                keep.add(e.src)
            for e in out_edges.get(n.id, []):
                keep.add(e.dst)
    short_edges = []
    for n in by_id:
        if n.id not in keep:
            continue
        for e in out_edges.get(n.id, []):
            steps = [{"uci": e.uci, "san": e.san, "fen": by_id[e.dst].fen}]
            cur, seen = e.dst, {n.id}
            while cur not in keep and cur not in seen:
                seen.add(cur)
                nxt = out_edges[cur][0]
                steps.append({"uci": nxt.uci, "san": nxt.san, "fen": by_id[nxt.dst].fen})
                cur = nxt.dst
            if cur not in keep:
                continue                              # a loop with no way out: nothing to show
            short_edges.append(Edge(n.id, cur, e.uci, e.san, actual=e.actual,
                                    width=width_of[(e.src, e.dst)],
                                    steps=steps if len(steps) > 1 else []))
    kept_nodes = [n for n in by_id if n.id in keep]

    stats = {"walked": visited, "merged": len(by_id), "shown": len(kept_nodes),
             "edges": len(short_edges), "plies": n_pos - 1}
    return Evolution(start_fen=start_fen, moves=sans, params=params, nodes=kept_nodes,
                     edges=short_edges, chart=chart, stats=stats)
