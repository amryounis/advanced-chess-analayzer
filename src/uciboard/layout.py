"""
Graph layout, after equation (1) of the paper.

The paper hands this to Graphviz. Here it is done in plain Python so nothing has to be
installed: a layered layout whose columns are moves from the start of the game.

  * x is the column (move number). An edge that spans several columns gets a virtual node
    in each column it crosses, so nothing is drawn through other nodes and the chain can
    be bent into a smooth curve through the virtual nodes.
  * The order of the nodes in a column is chosen to keep edges from crossing (repeated
    barycentre sweeps, left to right and back).
  * y is found by minimising  sum k_ij * w_ij * |y_i - y_j|  subject to a minimum distance
    between neighbours in a column, which is equation (1):
        k_ij = 1 (both virtual), 2 (one virtual), 8 (both real)
        w_ij = 5e4 for the player's own moves, 1e4 otherwise
    The absolute value is handled by iteratively re-weighted least squares, each column
    solved exactly under its ordering constraint (weighted isotonic regression).
  * The player's line is pinned to y = 0, so the game runs along a horizontal axis with the
    alternatives spreading above and below it.

Edges that go back to an earlier or the same column (a repeated position) are not part of
the layout; they are routed as arcs by the page.
"""

from __future__ import annotations

COL_W = 58.0                 # distance between columns
NODE = 22.0                  # diameter of a position
VIRTUAL = 4.0                # a virtual node is a point
GAP = 7.0                    # d in equation (1): the space kept between neighbours
K_BOTH_VIRTUAL, K_ONE_VIRTUAL, K_BOTH_REAL = 1.0, 2.0, 8.0
W_PLAYER, W_OTHER = 5e4, 1e4
PIN = 1e9                    # how hard the player's line is held at y = 0
SWEEPS = 24
REORDER_SWEEPS = 12          # the first sweeps may change the order, the rest only polish


def _isotonic(targets: list, weights: list, gaps: list) -> list:
    """Positions y_0 < y_1 < ... with y_{i+1} - y_i >= gaps[i] closest to the targets
    in the weighted least-squares sense (pool adjacent violators)."""
    n = len(targets)
    offset = [0.0] * n
    for i in range(1, n):
        offset[i] = offset[i - 1] + gaps[i - 1]
    # blocks of (weighted mean, weight, count) on the shifted targets
    blocks: list = []
    for i in range(n):
        blocks.append([targets[i] - offset[i], weights[i], 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2, c2 = blocks.pop()
            m1, w1, c1 = blocks.pop()
            w = w1 + w2
            blocks.append([(m1 * w1 + m2 * w2) / w, w, c1 + c2])
    out: list = []
    for mean, _w, count in blocks:
        out.extend([mean] * count)
    return [out[i] + offset[i] for i in range(n)]


def layout(ranks: dict, main: set, edges: list) -> dict:
    """ranks: node id -> column. main: ids of the player's positions.
    edges: list of (src, dst, actual) in the order the caller keeps them.

    Returns {"pos": {id: (x, y)}, "routes": [one per edge: {"via": [(x, y)...], "back": bool}],
             "extent": {...}}."""
    node_ids = list(ranks)
    virtual_of: dict = {}                      # virtual id -> (edge index, column)
    nxt = (max(node_ids) + 1) if node_ids else 0
    col: dict = dict(ranks)                    # every layered node: its column
    layered: list = []                         # (a, b, k, w) consecutive-column edges
    chains: dict = {}                          # edge index -> [virtual ids]
    back: set = set()
    for i, (s, d, actual) in enumerate(edges):
        w = W_PLAYER if actual else W_OTHER
        if ranks[d] <= ranks[s]:
            back.add(i)
            continue
        prev, chain = s, []
        for c in range(ranks[s] + 1, ranks[d]):
            v = nxt
            nxt += 1
            virtual_of[v] = (i, c)
            col[v] = c
            chain.append(v)
            layered.append((prev, v, K_BOTH_VIRTUAL if prev in virtual_of else K_ONE_VIRTUAL, w))
            prev = v
        layered.append((prev, d, K_ONE_VIRTUAL if prev in virtual_of else K_BOTH_REAL, w))
        chains[i] = chain

    left: dict = {}                            # node -> [(neighbour in the column before, k*w)]
    right: dict = {}
    for a, b, k, w in layered:
        left.setdefault(b, []).append((a, k * w))
        right.setdefault(a, []).append((b, k * w))

    columns: dict = {}
    for v, c in col.items():
        columns.setdefault(c, []).append(v)
    order_cols = sorted(columns)

    # ---- first order: a tree-like spread around the player's line
    slot: dict = {v: 0.0 for v in main}
    taken: dict = {}                           # parent -> children placed so far
    for s_, d_, actual in edges:
        if actual:
            taken[s_] = 1                      # the player's own move keeps the parent's line
    for c in order_cols:
        members = sorted(columns[c])
        for v in members:
            if v in slot:
                continue
            preds = left.get(v)
            if not preds:
                slot[v] = 0.0
                continue
            base = sum(slot[a] for a, _ in preds) / len(preds)
            parent = min(a for a, _ in preds)
            n = taken.get(parent, 0)
            taken[parent] = n + 1
            # the first child stays on its parent's line, the others alternate above and below
            offset = 0 if n == 0 else ((n + 1) // 2) * (1 if n % 2 else -1)
            slot[v] = base + offset
        members.sort(key=lambda v: (slot[v], 0 if v in main else 1, v))
        columns[c] = members

    def sep(a, b) -> float:
        sa = VIRTUAL if a in virtual_of else NODE
        sb = VIRTUAL if b in virtual_of else NODE
        return (sa + sb) / 2 + GAP

    y: dict = {}
    for c in order_cols:
        pos = 0.0
        for i, v in enumerate(columns[c]):
            if i:
                pos += sep(columns[c][i - 1], v)
            y[v] = pos
        shift = next((y[v] for v in columns[c] if v in main), 0.0)
        for v in columns[c]:
            y[v] -= shift

    # ---- alternate sweeps: pull each node towards its neighbours, keep the order legal
    eps = (NODE + GAP) * 0.25
    for it in range(SWEEPS):
        reorder = it < REORDER_SWEEPS
        sweep = order_cols if it % 2 == 0 else order_cols[::-1]
        for c in sweep:
            members = columns[c]
            targets, weights = [], []
            for v in members:
                num = den = 0.0
                for nb, kw in left.get(v, ()):
                    wgt = kw / max(abs(y[v] - y[nb]), eps)        # IRLS: |.| -> weighted square
                    num += wgt * y[nb]
                    den += wgt
                for nb, kw in right.get(v, ()):
                    wgt = kw / max(abs(y[v] - y[nb]), eps)
                    num += wgt * y[nb]
                    den += wgt
                if v in main:
                    den += PIN                                    # pulled to y = 0
                targets.append(num / den if den else y[v])
                weights.append(den if den else 1e-6)
            if reorder:                                          # barycentre ordering
                order = sorted(range(len(members)), key=lambda i: (targets[i], i))
                if order != list(range(len(members))):
                    members = [members[i] for i in order]
                    targets = [targets[i] for i in order]
                    weights = [weights[i] for i in order]
                    columns[c] = members
            gaps = [sep(members[i], members[i + 1]) for i in range(len(members) - 1)]
            solved = _isotonic(targets, weights, gaps)
            for v, val in zip(members, solved):
                y[v] = val

    # ---- the result
    pos = {v: (c_x(col[v]), y[v]) for v in node_ids}
    routes = []
    for i in range(len(edges)):
        if i in back:
            routes.append({"via": [], "back": True})
        else:
            routes.append({"via": [(c_x(col[v]), y[v]) for v in chains.get(i, [])], "back": False})
    ys = [y[v] for v in y]
    extent = {"x0": c_x(min(col.values())) if col else 0.0, "x1": c_x(max(col.values())) if col else 0.0,
              "y0": min(ys) if ys else 0.0, "y1": max(ys) if ys else 0.0}
    return {"pos": pos, "routes": routes, "extent": extent}


def c_x(column: int) -> float:
    return column * COL_W
