// The Evolution tab: draws the graph of "Chess Evolution Visualization" (Lu, Wang, Lin; IEEE TVCG 2014)
// that Python builds (evolution.py, layout.py), and the score chart under it.
//
// Encoding, as in the paper's Fig. 3, plus colour:
//   circle  = a position of the game      square = a position the engine expects (not played)
//   ring    = whose turn it is            fill   = the side that is better / enjoys the event
//             (game positions only)
//   grey fill = tie or draw               red crown = checkmate
//   solid arrow = one move, dotted arrow = several moves shortened into one
//   thicker arrow = the better the move compared with the alternatives from the same position
// Colour (not in the paper): BLUE is the game that was played (its circles have a blue outline, its
// arrows are blue), ORANGE is everything the engine expects instead (orange squares and arrows).
// Fill and ring keep their meaning, so colour only says "played" or "alternative".
//
// Hovering an arrow draws its moves as arrows on the board (in the arrow's colour); clicking plays them.

const SVGNS = "http://www.w3.org/2000/svg";
const R_MAIN = 11;                   // circle radius (the layout reserves a 22 px node)
const H_PRED = 8;                    // half side of an expected position's square
const RING = 3.4;
const TIE_CP = 25;                   // a game position within this many centipawns is "equal"
const COL_W = 58;                    // distance between columns (layout.py)
const MIN_SCALE = 0.03, MAX_SCALE = 4;
const STEP_MS = 800;

const $ = (id) => document.getElementById(id);

function el(name, attrs, parent) {
  const e = document.createElementNS(SVGNS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.append(e);
  return e;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ nodes

const COLORS = { w: "var(--node-white)", b: "var(--node-black)", g: "var(--node-draw)" };

function nodeSpec(n) {
  const main = n.main !== null && n.main !== undefined;
  let fill = null;
  if (n.event === "mate") fill = n.turn === "w" ? "b" : "w";          // the side to move was mated
  else if (n.event === "draw") fill = "g";
  else if (n.event === "check") fill = n.check;                        // the side giving check
  else if (main) fill = n.cp == null ? "g" : n.cp > TIE_CP ? "w" : n.cp < -TIE_CP ? "b" : "g";
  return { main, turn: n.turn, fill, event: n.event, number: main ? n.main : null };
}

function crown(parent) {
  el("path", { class: "crown", d: "M-6.5 4.5 L-7.5 -4 L-3.6 0 L0 -6.5 L3.6 0 L7.5 -4 L6.5 4.5 Z" }, parent);
}

// One node at (0, 0) of its own group; the caller places the group.
function buildNode(parent, spec, title) {
  const g = el("g", { class: "n" }, parent);
  if (title) el("title", {}, g).textContent = title;
  const ring = spec.main ? COLORS[spec.turn] : "var(--c-alt)";
  const mate = spec.event === "mate";
  if (spec.main) {
    el("circle", { class: "halo", r: R_MAIN + 4 }, g);
    el("circle", { class: "shape", r: R_MAIN, style: `fill:${ring}`, stroke: "rgba(0,0,0,.45)", "stroke-width": 0.8 }, g);
    el("circle", { r: R_MAIN - RING, style: `fill:${COLORS[spec.fill || "g"]}` }, g);
    el("circle", { class: "outline", r: R_MAIN + 1.4, fill: "none", style: "stroke:var(--c-game)", "stroke-width": 2.2 }, g);
  } else {
    el("rect", { class: "halo", x: -H_PRED - 4, y: -H_PRED - 4, width: 2 * H_PRED + 8, height: 2 * H_PRED + 8, rx: 3 }, g);
    if (spec.fill) {
      el("rect", { class: "shape", x: -H_PRED, y: -H_PRED, width: 2 * H_PRED, height: 2 * H_PRED,
        style: "fill:var(--c-alt)" }, g);
      el("rect", { x: -H_PRED + 1.9, y: -H_PRED + 1.9, width: 2 * H_PRED - 3.8, height: 2 * H_PRED - 3.8,
        style: `fill:${COLORS[spec.fill]}` }, g);
    } else {          // hollow, but still easy to hit
      el("rect", { class: "shape", x: -H_PRED, y: -H_PRED, width: 2 * H_PRED, height: 2 * H_PRED,
        fill: "#000", "fill-opacity": 0.001, style: "stroke:var(--c-alt)", "stroke-width": 2 }, g);
    }
  }
  if (mate) crown(g);
  else if (spec.main && spec.number) {
    const t = el("text", { class: "num", fill: spec.fill === "b" ? "#fff" : "#111" }, g);
    t.textContent = String(spec.number);
  }
  return g;
}

// ------------------------------------------------------------------ edges

function strokeOf(w) {                // the paper's [1, 30] drawn as 1..11 px
  return 1 + (Math.min(Math.max(w, 1), 30) - 1) * (7 / 29);
}

// Path of an arrow from node a to node b (centres and radii given), and its arrowhead.
function edgeShape(a, ra, b, rb, via, sw, back) {
  const hl = Math.max(6, sw * 1.25), hw = Math.max(3.6, sw * 0.7);
  if (back) {                         // a repeated position: an arc over the top
    const h = 38 + Math.abs(b.x - a.x) * 0.15;
    const x0 = a.x, y0 = a.y - ra, x1 = b.x, y1 = b.y - rb - hl - 1;
    return {
      d: `M${x0} ${y0} C${x0} ${y0 - h} ${x1} ${y1 - h} ${x1} ${y1}`,
      head: `${x1},${b.y - rb - 1} ${x1 - hw},${y1} ${x1 + hw},${y1}`,
    };
  }
  const tip = b.x - rb - 1, end = tip - hl;
  const pts = [[a.x + ra, a.y], ...via, [end, b.y]];
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {          // horizontal tangents: a smooth S between points
    const [px, py] = pts[i - 1], [qx, qy] = pts[i], mx = (px + qx) / 2;
    d += ` C${mx} ${py} ${mx} ${qy} ${qx} ${qy}`;
  }
  return { d, head: `${tip},${b.y} ${end},${b.y - hw} ${end},${b.y + hw}` };
}

function buildEdge(parent, shape, sw, dotted, title, game = false) {
  const g = el("g", { class: "e " + (game ? "game" : "alt") + (dotted ? " dotted" : "") }, parent);
  if (title) el("title", {}, g).textContent = title;
  const line = el("path", { class: "line", d: shape.d, "stroke-width": sw }, g);
  if (dotted) line.setAttribute("stroke-dasharray", `0.01 ${(sw * 1.7 + 3.2).toFixed(1)}`);
  el("polygon", { points: shape.head }, g);
  el("path", { class: "hit", d: shape.d }, g);
  return g;
}

// ------------------------------------------------------------------ text helpers

function scoreText(n) {
  if (n.event === "mate") return "checkmate";
  if (n.event === "draw") return "draw";
  if (n.mate_in !== null && n.mate_in !== undefined) return n.mate_in >= 0 ? `#${n.mate_in}` : `-#${-n.mate_in}`;
  if (n.cp === null || n.cp === undefined) return "–";
  return `${n.cp >= 0 ? "+" : "−"}${(Math.abs(n.cp) / 100).toFixed(2)}`;
}

const lastOf = (uci) => (uci ? [uci.slice(0, 2), uci.slice(2, 4)] : null);

// ------------------------------------------------------------------ the module

export function initEvolution(ctx) {
  const api = () => ctx.api();
  const gdiv = $("evo-graph"), gsvg = $("evo-svg"), csvg = $("evo-chart");

  let data = null;                    // the graph from Python
  let byId = new Map();
  let fwd = new Map(), bwd = new Map();
  let mainId = [];                    // ply -> node id
  let nodeEls = new Map();
  let edgeEls = [];
  let selected = null;
  let lastState = null;
  let stale = false;
  let view = { scale: 1, tx: 0, ty: 0 };
  let W = 0, H = 0;
  let needHome = false;
  let stepToken = 0;
  let playing = false;                // an arrow is being played on the board
  let hovered = null;                 // the arrow whose moves are drawn on the board
  let timer = null;
  let running = false;

  // -------------------------------------------------------------- the graph

  function setData(d) {
    data = d;
    byId = new Map(d.nodes.map((n) => [n.id, n]));
    fwd = new Map(); bwd = new Map();
    mainId = [];
    for (const n of d.nodes) if (n.main !== null && n.main !== undefined) mainId[n.main] = n.id;
    d.edges.forEach((e, i) => {
      if (e.back) return;
      if (!fwd.has(e.s)) fwd.set(e.s, []);
      if (!bwd.has(e.t)) bwd.set(e.t, []);
      fwd.get(e.s).push(e.t);
      bwd.get(e.t).push(e.s);
    });
    selected = null;
    hovered = null;
    cancelSteps();
    drawGraph();
    updateStale();
    renderTitle();
    setInfo("");
    $("evo-empty").hidden = true;
    if (W > 0) home(); else needHome = true;
    drawChart();
  }

  // the moves an arrow stands for, from its source position (null for an arrow to a repeated position)
  function edgeMoves(e) {
    if (e.back) return null;
    if (e.collapsed) return e.steps;
    if (!e.uci) return null;          // a graph saved by an older version
    const b = byId.get(e.t);
    return [{ uci: e.uci, san: b.label.split(" ").pop(), fen: b.fen }];
  }

  function cancelSteps() { stepToken++; playing = false; }

  function hoverEdge(i) {
    if (drag || dragged || playing || !data) return;
    const e = data.edges[i], moves = edgeMoves(e);
    if (!moves) return;
    const a = byId.get(e.s);
    endHover();
    hovered = i;
    if (edgeEls[i]) edgeEls[i].classList.add("hover");
    const brush = e.actual ? "pg" : "pa";                // blue for the game, orange for an alternative
    ctx.preview({
      fen: a.fen, last: lastOf(a.uci),
      shapes: moves.slice(0, 16).map((m, k) => ({
        orig: m.uci.slice(0, 2), dest: m.uci.slice(2, 4), brush: `${brush}${k}`, label: { text: String(k + 1) } })),
    });
  }

  function endHover() {
    if (hovered === null) return;
    if (edgeEls[hovered]) edgeEls[hovered].classList.remove("hover");
    hovered = null;
    ctx.endPreview();
  }

  function radius(n) { return n.main !== null && n.main !== undefined ? R_MAIN : H_PRED; }

  function drawGraph() {
    gsvg.textContent = "";
    nodeEls = new Map(); edgeEls = [];
    if (!data) return;
    const eg = el("g", {}, gsvg), ng = el("g", {}, gsvg);
    // thick ones underneath thin ones, and the game's own arrows on top of everything else, so the
    // played line is never covered by the dotted alternatives that cross it (nor hidden from the mouse)
    const order = data.edges.map((e, i) => i).sort((i, j) => {
      const a = data.edges[i], b = data.edges[j];
      return (a.actual - b.actual) || (b.w - a.w);
    });
    edgeEls = new Array(data.edges.length);
    for (const i of order) {
      const e = data.edges[i], a = byId.get(e.s), b = byId.get(e.t);
      const sw = strokeOf(e.w);
      const shape = edgeShape(a, radius(a), b, radius(b), e.via, e.collapsed ? Math.min(sw, 3) : sw, e.back);
      const moves = edgeMoves(e);
      const title = moves ? `${moves.map((s) => s.san).join(" ")}  (hover to see it on the board, click to play)` : b.label;
      const g = buildEdge(eg, shape, e.back ? Math.min(sw, 2) : e.collapsed ? Math.min(sw, 3) : sw, e.collapsed,
        title, e.actual);
      g.dataset.i = i;
      if (moves) {
        g.addEventListener("pointerenter", () => hoverEdge(i));
        g.addEventListener("pointerleave", endHover);
      }
      edgeEls[i] = g;
    }
    for (const n of data.nodes) {
      const g = buildNode(ng, nodeSpec(n), `${n.label || "Start"} · ${scoreText(n)}`);
      g.setAttribute("transform", `translate(${n.x},${n.y})`);
      g.dataset.id = n.id;
      nodeEls.set(n.id, g);
    }
  }

  function applyHighlight() {
    for (const [id, g] of nodeEls) g.classList.toggle("sel", id === selected);
    for (const g of edgeEls) if (g) g.classList.remove("now");
    if (selected === null) {
      for (const g of nodeEls.values()) g.classList.remove("dim");
      for (const g of edgeEls) if (g) g.classList.remove("dim");
      return;
    }
    const keep = new Set([selected]);
    for (const adj of [fwd, bwd]) {   // everything that follows from it, and the way to it
      const stack = [selected];
      while (stack.length) {
        for (const nx of adj.get(stack.pop()) || []) if (!keep.has(nx)) { keep.add(nx); stack.push(nx); }
      }
    }
    for (const [id, g] of nodeEls) g.classList.toggle("dim", !keep.has(id));
    data.edges.forEach((e, i) => edgeEls[i] && edgeEls[i].classList.toggle("dim", !(keep.has(e.s) && keep.has(e.t))));
  }

  // -------------------------------------------------------------- pan and zoom

  function applyView() {
    if (W <= 0 || H <= 0) return;
    gsvg.setAttribute("viewBox", `${view.tx} ${view.ty} ${W / view.scale} ${H / view.scale}`);
    drawChart();
  }

  function zoomAt(f, cx = W / 2, cy = H / 2) {
    const s = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * f));
    const wx = view.tx + cx / view.scale, wy = view.ty + cy / view.scale;
    view.scale = s;
    view.tx = wx - cx / s; view.ty = wy - cy / s;
    applyView();
  }

  function fit() {
    if (!data || W <= 0) return;
    const x = data.extent, m = 28;
    const w = x.x1 - x.x0 + 2 * m, h = x.y1 - x.y0 + 2 * m;
    const s = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.min(W / w, H / h)));
    view = { scale: s, tx: x.x0 - m - (W / s - w) / 2, ty: x.y0 - m - (H / s - h) / 2 };
    applyView();
  }

  function start() {                  // the start of the game at a readable size
    if (!data || W <= 0) return;
    const x = data.extent;
    view.scale = 1;
    view.tx = x.x0 - 30;
    view.ty = -H / 2;                 // the played line runs along y = 0
    applyView();
  }

  function home() {                   // the whole graph if it fits at normal size, else its start
    if (!data) return;
    const x = data.extent;
    const fitScale = Math.min(W / (x.x1 - x.x0 + 56), H / (x.y1 - x.y0 + 56));
    if (fitScale >= 1) fit(); else start();
  }

  function reveal(n) {                // pan just enough to see a node
    if (W <= 0) return;
    const px = (n.x - view.tx) * view.scale, py = (n.y - view.ty) * view.scale;
    const m = 40;
    if (px < m || px > W - m) view.tx = n.x - (W / view.scale) / 3;
    if (py < m || py > H - m) view.ty = n.y - (H / view.scale) / 2;
    applyView();
  }

  function resized() {                // keep the centre of the view where it was
    const w = gdiv.clientWidth, h = gdiv.clientHeight;
    if (W > 0 && H > 0 && w > 0 && h > 0) {
      view.tx += (W - w) / 2 / view.scale;
      view.ty += (H - h) / 2 / view.scale;
    }
    W = w; H = h;
    if (needHome && W > 0) { needHome = false; home(); } else applyView();
    drawChart();
  }
  new ResizeObserver(resized).observe(gdiv);

  let drag = null, dragged = false;
  gdiv.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    drag = { x: ev.clientX, y: ev.clientY, tx: view.tx, ty: view.ty, id: ev.pointerId };
    dragged = false;
  });
  gdiv.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
    if (!dragged) {
      if (Math.hypot(dx, dy) < 4) return;
      dragged = true;
      try { gdiv.setPointerCapture(drag.id); } catch (e) { /* not capturable */ }
      gdiv.classList.add("dragging");
    }
    view.tx = drag.tx - dx / view.scale;
    view.ty = drag.ty - dy / view.scale;
    applyView();
  });
  const endDrag = () => {
    gdiv.classList.remove("dragging");
    drag = null;
    setTimeout(() => { dragged = false; }, 0);      // after the click that follows the pointer-up
  };
  gdiv.addEventListener("pointerup", endDrag);
  gdiv.addEventListener("pointercancel", endDrag);
  gdiv.addEventListener("wheel", (ev) => {
    if (!data) return;
    ev.preventDefault();
    const r = gdiv.getBoundingClientRect();
    zoomAt(ev.deltaY < 0 ? 1.18 : 1 / 1.18, ev.clientX - r.left, ev.clientY - r.top);
  }, { passive: false });
  gdiv.addEventListener("click", (ev) => {
    if (dragged || !data) return;
    const ne = ev.target.closest(".n");
    if (ne) { selectNode(Number(ne.dataset.id)); return; }
    const ee = ev.target.closest(".e");
    if (ee) {
      const e = data.edges[Number(ee.dataset.i)];
      if (e && edgeMoves(e)) playEdge(Number(ee.dataset.i));
    }
  });
  $("evo-zoom-in").addEventListener("click", () => zoomAt(1.3));
  $("evo-zoom-out").addEventListener("click", () => zoomAt(1 / 1.3));
  $("evo-fit").addEventListener("click", fit);
  $("evo-start").addEventListener("click", () => { if (data) start(); });

  // -------------------------------------------------------------- selecting

  const isFinal = (n) => !stale && n.main === data.moves.length;

  async function selectNode(id, opts = {}) {
    if (!data || !byId.has(id)) return;
    const n = byId.get(id);
    endHover();
    cancelSteps();
    selected = id;
    applyHighlight();
    if (opts.reveal !== false) reveal(n);
    drawChart();
    describe(n);
    const st = isFinal(n) ? await api().clear_view() : await api().view_position(n.fen, lastOf(n.uci));
    ctx.render(st);
  }

  function clearSelection() {
    if (selected === null) return;
    selected = null;
    cancelSteps();
    if (data) applyHighlight();
    drawChart();
    setInfo("");
  }

  function describe(n) {
    const who = n.turn === "w" ? "White" : "Black";
    const kind = n.main !== null && n.main !== undefined
      ? (n.main === 0 ? "the start of the game" : `the game, after ${n.label}`)
      : `a possible continuation, after ${n.label}`;
    const ev = n.event === "mate" ? " · checkmate" : n.event === "draw" ? " · draw"
      : n.event === "check" ? " · effective check" : "";
    setInfo(`${kind} · ${who} to move · ${scoreText(n)}${ev}`);
  }

  async function playEdge(i) {
    const e = data.edges[i], a = byId.get(e.s), steps = edgeMoves(e);
    endHover();                        // the board is about to change; the preview would be wrong
    const my = ++stepToken;
    playing = true;
    selected = e.s;
    applyHighlight();
    if (edgeEls[i]) edgeEls[i].classList.add("now");
    reveal(a);
    const frames = [{ fen: a.fen, last: lastOf(a.uci) },
      ...steps.map((s) => ({ fen: s.fen, last: lastOf(s.uci) }))];
    const box = $("evo-info");
    for (let k = 0; k < frames.length; k++) {
      if (my !== stepToken) return;
      box.textContent = "";
      const lead = document.createElement("span");
      lead.textContent = `${a.label || "Start"} → `;
      box.append(lead);
      steps.forEach((s, j) => {
        const sp = document.createElement("span");
        sp.className = "step" + (j === k - 1 ? " now" : "");
        sp.textContent = s.san;
        box.append(sp, " ");
      });
      const last = k === frames.length - 1;
      const target = byId.get(e.t);
      if (last) selected = e.t;        // set before the board changes: the state handler checks it
      // the end of the game itself is not "a position from the graph": give the board back
      const st = last && isFinal(target) ? await api().clear_view()
        : await api().view_position(frames[k].fen, frames[k].last);
      if (my !== stepToken) return;
      ctx.render(st);
      if (!last) await sleep(k === 0 ? STEP_MS / 2 : STEP_MS);
    }
    if (my !== stepToken) return;
    playing = false;
    selected = e.t;                   // it ends on the node the edge leads to
    applyHighlight();
    if (edgeEls[i]) edgeEls[i].classList.add("now");
    describe(byId.get(e.t));
  }

  // -------------------------------------------------------------- the score chart

  function drawChart() {
    csvg.textContent = "";
    const w = csvg.clientWidth, h = csvg.clientHeight;
    if (!data || w <= 0 || h <= 0) return;
    csvg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    const top = 17, bottom = h - 17, mid = (top + bottom) / 2, half = (bottom - top) / 2;
    const f = (cp) => Math.sign(cp) * Math.log10(1 + Math.min(Math.abs(cp), 1500) / 20);
    const Y = (cp) => mid - (f(cp) / f(1500)) * half;
    const X = (ply) => ((byId.get(mainId[ply]) || { x: ply * COL_W }).x - view.tx) * view.scale;

    for (const [pawns, text] of [[1, "1"], [3, "3"], [10, "10"]]) {
      for (const sign of [1, -1]) {
        const y = Y(sign * pawns * 100);
        el("line", { class: "grid", x1: 0, x2: w, y1: y, y2: y }, csvg);
        const t = el("text", { class: "ylab", x: 3, y: y - 2 }, csvg);
        t.textContent = (sign > 0 ? "+" : "−") + text;
      }
    }
    el("line", { class: "axis", x1: 0, x2: w, y1: mid, y2: mid }, csvg);

    const rows = data.chart;
    const bw = Math.max(3, Math.min(16, COL_W * view.scale * 0.34));
    const every = Math.max(1, Math.ceil(26 / (2 * COL_W * view.scale)));   // label every n-th move number
    const pts = [];
    for (const r of rows) {
      const x = X(r.ply);
      pts.push([x, Y(r.actual), r]);
      if (x < -20 || x > w + 20) continue;
      const side = r.white ? "w" : "b";
      if (selected !== null && byId.get(selected).main === r.ply) {
        el("rect", { class: "cur", x: x - COL_W * view.scale / 2, y: 1, width: COL_W * view.scale, height: h - 2, rx: 4 }, csvg);
      }
      const y1 = Y(r.hi), y0 = Y(r.lo);
      el("rect", { class: `band ${side}`, x: x - bw / 2, y: y1, width: bw, height: Math.max(2.5, y0 - y1), rx: 2 }, csvg);
      if (Math.ceil(r.ply / 2) % every === 0 || rows.length < 2) {
        const num = r.label.split(" ")[0];
        const t = el("text", { x, y: r.white ? 11 : h - 5 }, csvg);
        t.textContent = num;
      }
    }
    if (pts.length > 1) {
      el("path", { class: "score-line", d: "M" + pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L") }, csvg);
    }
    for (const [x, y, r] of pts) {
      if (x < -20 || x > w + 20) continue;
      const c = el("circle", { class: `dot ${r.white ? "w" : "b"}`, cx: x, cy: y, r: 4.4 }, csvg);
      el("title", {}, c).textContent =
        `${r.label} · played ${r.actual >= 0 ? "+" : "−"}${(Math.abs(r.actual) / 100).toFixed(2)}` +
        ` · alternatives ${(r.lo / 100).toFixed(2)} to ${(r.hi / 100).toFixed(2)}`;
    }
    for (const r of rows) {           // wide invisible targets, one per column
      const x = X(r.ply);
      if (x < -20 || x > w + 20) continue;
      el("rect", { class: "hit", "data-ply": r.ply, x: x - COL_W * view.scale / 2, y: 0,
        width: COL_W * view.scale, height: h }, csvg);
    }
  }

  csvg.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-ply]");
    if (t && data && mainId[Number(t.dataset.ply)] !== undefined) selectNode(mainId[Number(t.dataset.ply)]);
  });
  new ResizeObserver(drawChart).observe(csvg);

  // -------------------------------------------------------------- title, info, stale

  function setInfo(text, warn = false) {
    const box = $("evo-info");
    box.textContent = "";
    if (!text) return;
    const s = document.createElement("span");
    if (warn) s.className = "warn";
    s.textContent = text;
    box.append(s);
  }

  function sameGame(st) {
    return data.moves.length === st.moves.length && data.moves.every((m, i) => m === st.moves[i]);
  }

  function updateStale() {
    stale = !!(data && lastState && !sameGame(lastState));
    renderTitle();
  }

  function renderTitle() {
    const box = $("evo-title");
    box.textContent = "";
    if (!data) return;
    const i = data.info || {};
    const names = i.white || i.black ? `${i.white || "?"} – ${i.black || "?"}` : "";
    const stats = data.stats;
    const bits = [names, i.event, i.result && i.result !== "*" ? i.result : "", `${stats.plies} moves`,
      `${stats.shown} positions shown of ${stats.merged} found`].filter(Boolean);
    box.append(bits.join(" · "));
    if (stale) {
      const w = document.createElement("span");
      w.className = "warn";
      w.textContent = "  The board holds another game now: press Analyse game to update.";
      box.append(w);
    }
  }

  // called with every state from Python
  function onState(st) {
    lastState = st;
    if (!data) return;
    updateStale();
    if (stale) { clearSelection(); return; }
    if (selected !== null && !st.viewing && !isFinal(byId.get(selected))) clearSelection();
  }

  // -------------------------------------------------------------- running an analysis

  function setRunning(on) {
    running = on;
    $("evo-run").disabled = on;
    $("evo-pgn").disabled = on;
    $("evo-depth").disabled = on;
    $("evo-seconds").disabled = on;
    $("evo-cancel").hidden = !on;
    $("evo-progress").hidden = !on;
    if (!on) $("evo-cancel").disabled = false;
  }

  async function watch() {
    if (timer) return;
    setRunning(true);
    const tick = async () => {
      let st;
      try { st = await api().evolution_status(); } catch (e) { return; }
      if (st.state === "running") {
        $("evo-bar").max = Math.max(1, st.total);
        $("evo-bar").value = st.done;
        $("evo-progress-text").textContent =
          st.total ? `${st.message} (${st.done}/${st.total})` : st.message;
        return;
      }
      clearInterval(timer); timer = null;
      setRunning(false);
      if (st.state === "done") {
        const d = await api().evolution_result();
        if (d) setData(d);
      } else if (st.state === "cancelled") {
        setInfo("Cancelled.");
      } else if (st.state === "error") {
        setInfo(`The analysis failed: ${st.error}`, true);
      }
    };
    timer = setInterval(tick, 300);
    tick();
  }

  $("evo-run").addEventListener("click", async () => {
    const params = { depth: Number($("evo-depth").value), seconds: Number($("evo-seconds").value) };
    setInfo("");
    const r = await api().evolution_start(params);
    if (!r.started) { setInfo(r.message || "Could not start.", true); return; }
    $("evo-progress-text").textContent = "starting the engine";
    $("evo-bar").value = 0;
    watch();
  });
  $("evo-cancel").addEventListener("click", async () => {
    $("evo-cancel").disabled = true;
    await api().evolution_cancel();
  });

  // -------------------------------------------------------------- loading a game

  const dlg = $("pgn-dialog");
  $("evo-pgn").addEventListener("click", () => {
    $("pgn-msg").textContent = "";
    dlg.showModal();
    $("pgn-text").focus();
  });
  $("pgn-cancel").addEventListener("click", () => dlg.close());
  $("pgn-load").addEventListener("click", async () => {
    const st = await api().load_pgn($("pgn-text").value);
    if (st.rejected) { $("pgn-msg").textContent = st.message || "Cannot read that game."; return; }
    dlg.close();
    ctx.render(st);
    if (st.message) ctx.message(st.message);
    setInfo("Game loaded: press Analyse game.");
  });

  // -------------------------------------------------------------- the legend

  function buildLegend() {
    const grid = $("legend-grid");
    const items = [
      [(s) => buildNode(s, { main: true, turn: "b", fill: "w", number: 12 }), "A position of the game (blue outline); the number counts the moves played. Fill: the better side (here White). Ring: whose turn it is (here Black)."],
      [(s) => buildNode(s, { main: true, turn: "w", fill: "b", number: 7 }), "Black is better, White to move."],
      [(s) => buildNode(s, { main: true, turn: "w", fill: "g", number: 3 }), "Grey: about equal."],
      [(s) => buildNode(s, { main: false, fill: null }), "An orange square is a position the engine expects, not played."],
      [(s) => buildNode(s, { main: false, fill: "w", event: "check" }), "An effective check; the fill is the side giving it."],
      [(s) => buildNode(s, { main: true, turn: "b", fill: "w", event: "mate" }), "Checkmate (fill: the winner). A square with a crown is a mate the engine foresees."],
      [(s) => buildNode(s, { main: false, fill: "g", event: "draw" }), "A draw."],
      [(s) => edgeLegend(s, 4, false, true), "Blue arrow: a move of the game. The thicker, the better it was compared with the other moves from that position."],
      [(s) => edgeLegend(s, 2, false, true), "A thin blue arrow: a better move was available."],
      [(s) => edgeLegend(s, 3, false, false), "Orange arrow: a move that was not played."],
      [(s) => edgeLegend(s, 7, false, false), "A thick orange arrow: a much better move than the others from that position."],
      [(s) => edgeLegend(s, 3, true, false), "Dotted: several moves in one arrow. Hover to see them on the board, click to play them."],
    ];
    for (const [draw, text] of items) {
      const row = document.createElement("div");
      row.className = "legend-item";
      const svg = el("svg", { width: 70, height: 28, viewBox: "-35 -14 70 28" });
      const g = draw(svg);
      if (g && g.tagName === "g" && !g.classList.contains("e")) g.removeAttribute("transform");
      const span = document.createElement("span");
      span.textContent = text;
      row.append(svg, span);
      grid.append(row);
    }
  }

  function edgeLegend(svg, sw, dotted, game) {
    const shape = edgeShape({ x: -30, y: 0 }, 0, { x: 30, y: 0 }, 0, [], sw, false);
    return buildEdge(svg, shape, sw, dotted, "", game);
  }

  buildLegend();

  // -------------------------------------------------------------- start

  async function init() {
    try {
      const d = await api().evolution_defaults();
      $("evo-depth").value = d.depth;
      $("evo-seconds").value = d.seconds;
      const st = await api().evolution_status();
      if (st.state === "running") watch();
      else if (st.state === "done") {
        const r = await api().evolution_result();
        if (r) setData(r);
      }
    } catch (e) { /* the bridge is not up */ }
  }

  return {
    init,
    onState,
    show() { resized(); },
    get busy() { return running; },
  };
}
