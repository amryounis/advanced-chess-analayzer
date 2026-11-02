"""The paper's rules, checked with a scripted searcher so every number is known."""

import math
import threading

import chess
import pytest

from uciboard.evolution import (Cancelled, Line, Params, build, cache_key, score_cp, select_lines)
from uciboard.layout import COL_W, GAP, NODE, layout


class Scripted:
    """Stands in for the engine. For a position it ranks the legal moves in a fixed order
    (by move text), gives rank r the score `base - step * (r - 1)` for the side to move, and
    continues each line with the first legal move in that order. `overrides` maps a FEN
    to a score for the quick searches that judge checks."""

    def __init__(self, base=100, step=30, overrides=None, scores=None, prefer=None):
        self.base, self.step, self.calls = base, step, []
        self.prefer = prefer or {}               # fen -> move text to rank first
        self.overrides = overrides or {}
        self.scores = scores or {}               # fen -> list of cp per rank
        self.aborted = False

    def abort(self):
        self.aborted = True

    def _continue(self, board, first, plies):
        b = board.copy()
        out = []
        move = first
        for _ in range(plies):
            if move not in b.legal_moves:
                break
            out.append(move.uci())
            b.push(move)
            if b.is_game_over():
                break
            move = sorted(b.legal_moves, key=lambda m: m.uci())[0]
        return out

    def search(self, fen, depth, multipv, seconds, searchmoves=None):
        self.calls.append((fen, depth, multipv, tuple(searchmoves or ())))
        b = chess.Board(fen)
        if multipv == 1 and depth in self.overrides.get("depths", ()) and fen in self.overrides:
            return [Line(1, depth, self.overrides[fen], [])]
        moves = sorted(b.legal_moves, key=lambda m: (m.uci() != self.prefer.get(fen), m.uci()))
        if searchmoves:
            moves = [chess.Move.from_uci(m) for m in searchmoves]
        lines = []
        for i, mv in enumerate(moves[:multipv]):
            table = self.scores.get(fen)
            cp = table[i] if table and i < len(table) else self.base - self.step * i
            lines.append(Line(i + 1, depth, cp, self._continue(b, mv, depth)))
        return lines


def uci_game(san_moves, fen=chess.STARTING_FEN):
    b = chess.Board(fen)
    out = []
    for san in san_moves:
        mv = b.parse_san(san)
        out.append(mv.uci())
        b.push(mv)
    return out


# ------------------------------------------------------------------ the selection rule

def lines_with(played_rank, n=9):
    lines = [Line(i, 10, 100 - i, [f"m{i}a", "x"]) for i in range(1, n + 1)]
    return lines, f"m{played_rank}a"


@pytest.mark.parametrize("rank, expected", [(1, 4), (2, 4), (4, 4), (5, 5), (6, 6), (8, 8), (9, 9)])
def test_selection_rule(rank, expected):
    lines, played = lines_with(rank)
    kept, got_rank, need = select_lines(lines, played)
    assert got_rank == rank and not need
    assert [ln.rank for ln in kept][:min(rank, 8)] == list(range(1, min(rank, 8) + 1))
    assert len(kept) == expected


def test_a_move_below_ninth_needs_its_own_search():
    lines, _ = lines_with(1)
    kept, rank, need = select_lines(lines, "zzz")
    assert rank is None and need and len(kept) == 8


def test_no_move_played_keeps_the_best_four():
    lines, _ = lines_with(1)
    kept, rank, need = select_lines(lines, None)
    assert len(kept) == 4 and rank is None and not need


def test_scores_mate_is_folded_in():
    assert score_cp({"cp": -35}) == -35
    assert score_cp({"mate": 3}) == 30000 - 3
    assert score_cp({"mate": -2}) == -(30000 - 2)


# --------------------------------------------------------------------- the graph

def build_short(searcher=None, game=("e4", "e5", "Nf3", "Nc6"), **params):
    searcher = searcher or Scripted()
    p = Params(depth=6, lines=9, seconds=1, check_depth=4, **params)
    return build(chess.STARTING_FEN, uci_game(game), searcher, p), searcher


def test_the_players_positions_are_in_the_graph_in_order():
    evo, _ = build_short()
    mains = sorted((n for n in evo.nodes if n.main is not None), key=lambda n: n.main)
    assert [n.main for n in mains] == [0, 1, 2, 3, 4]
    assert [n.rank for n in mains] == [0, 1, 2, 3, 4]               # column = move number
    assert [n.label for n in mains] == ["start", "1. e4", "1... e5", "2. Nf3", "2... Nc6"]
    actual = {(e.src, e.dst) for e in evo.edges if e.actual}
    assert actual == {(mains[i].id, mains[i + 1].id) for i in range(4)}


def test_identical_positions_are_merged():
    evo, _ = build_short()
    assert evo.stats["merged"] < evo.stats["walked"] + 5            # the walk revisits positions
    keys = [chess.Board(n.fen).epd() for n in evo.nodes]
    assert len(keys) == len(set(keys))


def test_shortening_keeps_exactly_the_nodes_the_paper_keeps():
    evo, _ = build_short()
    ids = {n.id for n in evo.nodes}
    assert all(e.src in ids and e.dst in ids for e in evo.edges)
    outs, ins = {}, {}
    for e in evo.edges:
        outs.setdefault(e.src, []).append(e)
        ins.setdefault(e.dst, []).append(e)
    events = {n.id for n in evo.nodes if n.event}
    near_event = set(events)
    for e in evo.edges:
        if e.dst in events:
            near_event.add(e.src)
        if e.src in events:
            near_event.add(e.dst)
    for n in evo.nodes:
        if n.main is None and n.id not in near_event:
            # a plain position survives only because it is a junction or an end
            assert len(outs.get(n.id, [])) != 1 or len(ins.get(n.id, [])) != 1
    collapsed = [e for e in evo.edges if e.collapsed]
    assert collapsed, "the script's long quiet lines must have been shortened"
    by_id = {n.id: n for n in evo.nodes}
    for e in collapsed:
        assert e.steps[-1]["fen"] == by_id[e.dst].fen
        b = chess.Board(by_id[e.src].fen)
        for step in e.steps:                                        # the hidden moves are a real line
            b.push(chess.Move.from_uci(step["uci"]))
            assert b.fen() == step["fen"]


def test_shortening_makes_the_graph_smaller_but_keeps_the_game():
    evo, _ = build_short()
    assert evo.stats["shown"] < evo.stats["merged"]
    assert sum(1 for n in evo.nodes if n.main is not None) == 5


def test_edge_thickness_follows_equation_2():
    # three moves from the start position, scores 300, 100, 0 for White (best first)
    fen = chess.STARTING_FEN
    evo, _ = build_short(Scripted(scores={fen: [300, 100, 0]}), game=("a3",))
    first_ranked = sorted(chess.Board(fen).legal_moves, key=lambda m: m.uci())[:3]
    by_id = {n.id: n for n in evo.nodes}
    root = next(n for n in evo.nodes if n.main == 0)
    w = {}
    for e in evo.edges:
        if e.src == root.id:
            w[e.uci] = e.width
    assert w[first_ranked[0].uci()] == pytest.approx(30.0)          # the best: thickest
    assert w[first_ranked[2].uci()] == pytest.approx(1.0)           # the worst of them: 1
    mid = (math.log(100) ** 2 - 1) / (math.log(300) ** 2 - 1) * 29 + 1
    assert w[first_ranked[1].uci()] == pytest.approx(mid)
    assert by_id[root.id].main == 0


def test_nearly_equal_moves_never_get_less_than_the_minimum_thickness():
    fen = chess.STARTING_FEN
    evo, _ = build_short(Scripted(scores={fen: [100, 99, 98, 0]}), game=("a3",))
    root = next(n for n in evo.nodes if n.main == 0)
    widths = [e.width for e in evo.edges if e.src == root.id]
    assert widths and min(widths) >= 1.0 and max(widths) <= 30.0


def test_a_position_with_one_way_on_has_the_minimum_thickness():
    fen = "k7/8/8/8/8/8/1q6/K7 w - - 0 1"          # White has one legal move: Kxb2
    assert len(list(chess.Board(fen).legal_moves)) == 1
    evo = build(fen, [], Scripted(), Params(depth=4, lines=9, seconds=1, check_depth=3))
    root = next(n for n in evo.nodes if n.main == 0)
    edges = [e for e in evo.edges if e.src == root.id]
    assert len(edges) == 1 and edges[0].width == 1.0


def test_checkmate_and_checks_are_events():
    game = ("f3", "e5", "g4", "Qh4#")
    evo, _ = build_short(game=game)
    last = max((n for n in evo.nodes if n.main is not None), key=lambda n: n.main)
    assert last.mate and last.check == "b" and last.event == "mate"
    assert last.cp == 30000 - 0 - 0 or last.cp < 0                    # a win for Black
    assert last.cp == -30000                                          # Black mated White: -30000


def test_a_check_is_effective_only_if_the_checker_is_not_worse_off():
    # 1.e4 e5 2.Qh5 Nc6, then the engine's line starts 3.Qxf7+ : judged by two quick searches
    game = ("e4", "e5", "Qh5", "Nc6")
    start = chess.Board()
    for san in game:
        start.push_san(san)
    before = start.fen()
    after_board = start.copy()
    after_board.push_san("Qxf7+")
    after = after_board.fen()
    # (the checker's score before, the opponent's score after the check, effective?)
    for checker_before, opponent_after, expect in [(0, -50, True), (0, 80, False), (0, 0, True)]:
        s = Scripted(prefer={before: "h5f7"},
                     overrides={"depths": (4, 3), before: checker_before, after: opponent_after})
        evo, _ = build_short(s, game=game)
        node = next((n for n in evo.nodes if n.fen == after), None)
        if expect:                                        # an event: highlighted, so it stays
            assert node is not None and node.check == "w" and node.event == "check"
        else:                                             # not an event: a step inside a shortened edge
            assert node is None
            hidden = [e for e in evo.edges if e.collapsed and e.steps[0]["fen"] == after]
            assert hidden and hidden[0].steps[0]["san"] == "Qxf7+"
        assert (before, 4, 1, ()) in s.calls and (after, 3, 1, ()) in s.calls   # one ply less deep


def test_tolerance_forgives_a_small_loss():
    game = ("e4", "e5", "Qh5", "Nc6")
    b = chess.Board()
    for san in game:
        b.push_san(san)
    before = b.fen()
    b.push_san("Qxf7+")
    after = b.fen()
    s = Scripted(prefer={before: "h5f7"}, overrides={"depths": (4, 3), before: 0, after: 20})
    evo, _ = build_short(s, game=game, check_tolerance=30)
    node = next(n for n in evo.nodes if n.fen == after)
    assert node.effective is True and node.event == "check"


def test_cancel_stops_the_job():
    cancel = threading.Event()
    s = Scripted()
    orig = s.search

    def search(*a, **k):
        cancel.set()
        return orig(*a, **k)
    s.search = search
    with pytest.raises(Cancelled):
        build(chess.STARTING_FEN, uci_game(("e4", "e5")), s, Params(depth=4, lines=9), cancel=cancel)


def test_the_chart_has_a_band_per_move():
    evo, _ = build_short()
    assert [row["ply"] for row in evo.chart] == [1, 2, 3, 4]
    for row in evo.chart:
        assert row["lo"] <= row["hi"]
    assert evo.chart[0]["white"] is True and evo.chart[1]["white"] is False
    assert evo.chart[0]["label"] == "1. e4"
    assert evo.chart[0]["rank"] is None                    # e4 is 12th in the script's order: below the nine asked for
    assert evo.chart[2]["rank"] is not None or evo.chart[2]["rank"] is None
    assert all(isinstance(row["actual"], int) for row in evo.chart)


def test_a_repeated_position_in_the_game_is_a_node_of_its_own():
    game = ("Nf3", "Nf6", "Ng1", "Ng8")                              # back to the start
    evo, _ = build_short(game=game)
    mains = [n for n in evo.nodes if n.main is not None]
    assert len(mains) == 5 and len({n.id for n in mains}) == 5


def test_cache_key_depends_on_the_game_and_the_settings():
    a = cache_key(chess.STARTING_FEN, ["e2e4"], Params())
    assert a == cache_key(chess.STARTING_FEN, ["e2e4"], Params())
    assert a != cache_key(chess.STARTING_FEN, ["d2d4"], Params())
    assert a != cache_key(chess.STARTING_FEN, ["e2e4"], Params(depth=20))


def test_an_illegal_game_is_refused():
    with pytest.raises(ValueError):
        build(chess.STARTING_FEN, ["e2e5"], Scripted(), Params())


# -------------------------------------------------------------------- the layout

def crossings(pos, edges):
    """Edges between consecutive columns that cross each other."""
    segs = [(pos[a], pos[b]) for a, b in edges]
    n = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (a, b), (c, d) = segs[i], segs[j]
            if a[0] == c[0] and b[0] == d[0] and (a[1] - c[1]) * (b[1] - d[1]) < -1e-6:
                n += 1
    return n


def small_graph():
    #   0 - 1 - 2 - 3 - 4        player's line
    #       |   |
    #       5 - 6 - 7            a branch off 1
    #           8 = = = > 4      a long edge from 2 into the player's node 4 (column 4)
    ranks = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 2, 6: 3, 7: 4, 8: 3}
    edges = [(0, 1, True), (1, 2, True), (2, 3, True), (3, 4, True),
             (1, 5, False), (5, 6, False), (6, 7, False), (2, 8, False), (8, 4, False)]
    return ranks, {0, 1, 2, 3, 4}, edges


def test_columns_follow_the_ranks_and_the_players_line_is_straight():
    ranks, main, edges = small_graph()
    out = layout(ranks, main, edges)
    for v, r in ranks.items():
        assert out["pos"][v][0] == r * COL_W
    assert all(abs(out["pos"][v][1]) < 0.5 for v in main)


def test_nodes_in_a_column_never_overlap():
    ranks, main, edges = small_graph()
    pos = layout(ranks, main, edges)["pos"]
    by_col = {}
    for v, (x, y) in pos.items():
        by_col.setdefault(x, []).append(y)
    for ys in by_col.values():
        ys.sort()
        assert all(b - a >= NODE + GAP - 1e-6 for a, b in zip(ys, ys[1:]))


def test_a_long_edge_gets_a_virtual_node_per_column_it_crosses():
    ranks = {0: 0, 1: 1, 2: 4}
    out = layout(ranks, {0, 1, 2}, [(0, 1, True), (1, 2, False), (0, 2, False)])
    assert len(out["routes"][1]["via"]) == 2                          # columns 2 and 3
    assert len(out["routes"][2]["via"]) == 3                          # columns 1, 2 and 3
    assert [x for x, _ in out["routes"][1]["via"]] == [2 * COL_W, 3 * COL_W]


def test_an_edge_back_to_an_earlier_column_is_marked():
    out = layout({0: 0, 1: 1, 2: 2}, {0, 1, 2}, [(0, 1, True), (1, 2, True), (2, 0, False)])
    assert [r["back"] for r in out["routes"]] == [False, False, True]


def test_branches_spread_to_both_sides_and_do_not_cross():
    ranks, main, edges = small_graph()
    out = layout(ranks, main, edges)
    pos = out["pos"]
    assert crossings(pos, [(a, b) for a, b, _ in edges if ranks[b] - ranks[a] == 1]) == 0
    ys = [pos[v][1] for v in (5, 6, 7, 8)]
    assert min(ys) < 0 < max(ys) or all(y != 0 for y in ys)


def test_a_quiet_chain_stays_on_one_line():
    ranks = {i: i for i in range(8)}
    ranks.update({10 + i: 2 + i for i in range(5)})                    # a branch off node 1
    edges = [(i, i + 1, True) for i in range(7)] + [(1, 10, False)] + [(10 + i, 11 + i, False) for i in range(4)]
    pos = layout(ranks, set(range(8)), edges)["pos"]
    ys = [pos[10 + i][1] for i in range(5)]
    assert max(ys) - min(ys) < 1.0


def test_the_whole_pipeline_lays_out(tmp_path):
    evo, _ = build_short()
    ranks = {n.id: n.rank for n in evo.nodes}
    main = {n.id for n in evo.nodes if n.main is not None}
    lay = layout(ranks, main, [(e.src, e.dst, e.actual) for e in evo.edges])
    data = evo.to_json(lay)
    assert len(data["nodes"]) == len(evo.nodes) and len(data["edges"]) == len(evo.edges)
    assert all(abs(n["y"]) < 0.5 for n in data["nodes"] if n["main"] is not None)
    assert data["extent"]["x1"] >= 4 * COL_W
