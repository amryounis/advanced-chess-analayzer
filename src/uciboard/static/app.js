import { Chessground } from "./vendor/chessground.min.js";
import { initEvolution } from "./evo.js";
import { initEngines } from "./engines.js";

const $ = (id) => document.getElementById(id);
const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const MAX_DOM_LINES = 1500;          // lines kept in the pane; the engine's full output stays in Python
const POLL_MS = 150;

let api = null;
let cursor = 0;
let engineOn = false;                // is the live analysis switched on?
let current = null;                  // the last state from Python
let orientation = "white";
let engines = null;                  // the engine pickers and their dialog (engines.js)
let evo = null;                      // the Evolution tab (evo.js), set up in init()

// One brush per side per move of the best line: the first is the boldest, later ones fade,
// so the order reads at a glance. White's moves are blue, Black's orange (as in the line below).
const ARROW_COLOR = { w: "#3f6fc4", b: "#d06a1f" };
function arrowBrushes() {
  const brushes = {};
  for (let i = 0; i < 10; i++) {
    for (const side of ["w", "b"]) {
      brushes[`${side}${i}`] = { key: `${side}${i}`, color: ARROW_COLOR[side],
        opacity: Math.max(0.4, 0.9 - i * 0.07), lineWidth: Math.max(6, 11 - i * 0.6) };
    }
  }
  // an arrow of the Evolution graph shown on the board: blue is the game, orange an alternative,
  // fading with the move's place in the line
  for (let i = 0; i < 16; i++) {
    const fade = { opacity: Math.max(0.5, 0.95 - i * 0.04), lineWidth: Math.max(6, 11 - i * 0.35) };
    brushes[`pg${i}`] = { key: `pg${i}`, color: "#2f6fe0", ...fade };
    brushes[`pa${i}`] = { key: `pa${i}`, color: "#e8821a", ...fade };
  }
  // what the geometry of the position says (not the engine): pieces that can be won, pins, skewers
  brushes.loose = { key: "loose", color: "#d62f2f", opacity: 0.85, lineWidth: 6 };
  brushes.loose2 = { key: "loose2", color: "#d4a017", opacity: 0.85, lineWidth: 5 };
  brushes.pin = { key: "pin", color: "#8a4fc7", opacity: 0.75, lineWidth: 6 };
  brushes.skewer = { key: "skewer", color: "#1fa39a", opacity: 0.75, lineWidth: 6 };
  brushes.removable = { key: "removable", color: "#c0692b", opacity: 0.8, lineWidth: 5 };
  brushes.overload = { key: "overload", color: "#d63c8c", opacity: 0.8, lineWidth: 5 };
  return brushes;
}

const board = Chessground($("board"), {
  fen: START,
  coordinates: true,
  animation: { duration: 150 },
  movable: { free: false, color: undefined, showDests: true, events: { after: onUserMove } },
  premovable: { enabled: false },
  events: { select: (key) => onSelect(key), unselect: () => clearSafe() },
  highlight: { lastMove: true, check: true },
  drawable: { enabled: true, visible: true, brushes: arrowBrushes() },
});

// How many moves of the engine's best line to draw (a setting kept in this browser).
let arrowCount = 4;
try {
  const saved = localStorage.getItem("arrows");
  if (saved !== null && !Number.isNaN(Number(saved))) arrowCount = Number(saved);
} catch (e) { /* storage off */ }
$("arrows").value = String(arrowCount);
if ($("arrows").value !== String(arrowCount)) { arrowCount = 4; $("arrows").value = "4"; }
// Which side's moves of the line are drawn: "both", "white" or "black" (also kept in this browser).
let arrowSide = "both";
try {
  const side = localStorage.getItem("arrow-side");
  if (side === "white" || side === "black") arrowSide = side;
} catch (e) { /* storage off */ }
$("arrow-side").value = arrowSide;
const drawnSide = (white) => arrowSide === "both" || (arrowSide === "white") === white;
let lastSummary = null;
let arrowKey = "";
const show = { loose: true, pins: true, defenders: true, king: false, safe: true, heat: false, structure: false };
for (const k of Object.keys(show)) {
  try {
    const v = localStorage.getItem("show-" + k);
    if (v !== null) show[k] = v === "1";
  } catch (e) { /* storage off */ }
  $("show-" + k).checked = show[k];
}

// ------------------------------------------------------------------ board

function render(st) {
  if (!current || current.fen !== st.fen) clearSafe();
  current = st;
  board.set({
    fen: st.fen,
    turnColor: st.turn,
    check: st.check,
    lastMove: st.last,
    movable: {
      color: st.over || st.viewing ? undefined : st.turn,
      dests: new Map(Object.entries(st.dests)),
    },
  });
  $("viewbar").hidden = !st.viewing;
  $("board").dataset.fen = st.fen;     // what the board shows (the page's tests and bug reports read it)
  $("version").textContent = st.version;
  document.title = `uciboard ${st.version}`;
  if (document.activeElement !== $("fen")) $("fen").value = st.fen;
  renderMoves(st);
  setMessage(st.over || "");
  renderTactics(st);
  drawShapes();                        // arrows of a line for another position are removed
  if (evo) evo.onState(st);
}

function renderMoves(st) {
  const box = $("moves");
  box.textContent = "";
  let num = st.first_move_number;
  let whiteToMove = !st.first_is_black;
  st.moves.forEach((san, i) => {
    if (whiteToMove) {
      const n = document.createElement("span");
      n.className = "no";
      n.textContent = `${num}.`;
      box.append(n);
    } else if (i === 0) {
      const n = document.createElement("span");
      n.className = "no";
      n.textContent = `${num}…`;
      box.append(n);
    }
    const m = document.createElement("span");
    m.className = "mv" + (i === st.ply - 1 ? " cur" : "") + (i >= st.ply ? " later" : "");
    const mark = (st.marks && st.marks[i]) || "";
    m.textContent = san;
    if (mark) {
      const q = document.createElement("span");
      q.className = "q";
      q.textContent = mark;
      m.append(q);
      m.classList.add(mark === "?!" ? "q1" : mark === "?" ? "q2" : "q3");
    }
    m.dataset.ply = String(i + 1);
    m.title = "Show the position after this move";
    box.append(m);
    if (!whiteToMove) num += 1;
    whiteToMove = !whiteToMove;
  });
  const cur = box.querySelector(".cur");
  if (cur) cur.scrollIntoView({ block: "nearest" });
  else box.scrollTop = st.ply ? box.scrollHeight : 0;
  const total = st.moves.length;
  $("nav-start").disabled = $("nav-prev").disabled = st.ply === 0;
  $("nav-next").disabled = $("nav-end").disabled = st.ply >= total;
  $("nav-pos").textContent = total ? `move ${st.ply} of ${total}` : "";
}

$("moves").addEventListener("click", (e) => {
  const m = e.target.closest(".mv");
  if (m) act(api.goto_ply, Number(m.dataset.ply));
});
$("nav-start").addEventListener("click", () => act(api.goto_ply, 0));
$("nav-prev").addEventListener("click", () => act(api.step, -1));
$("nav-next").addEventListener("click", () => act(api.step, 1));
$("nav-end").addEventListener("click", () => act(api.goto_ply, 1e6));

function setMessage(text) {
  $("msg").textContent = text;
}

async function onUserMove(orig, dest) {
  let promotion = null;
  if (await api.needs_promotion(orig, dest)) promotion = await askPromotion();
  const st = await api.move(orig, dest, promotion);
  render(st);                          // also puts the board back if the move was refused
  if (st.rejected) setMessage("That move is not legal.");
}

function askPromotion() {
  return new Promise((resolve) => {
    const box = $("promo");
    box.hidden = false;
    const done = (p) => { box.hidden = true; box.onclick = null; resolve(p); };
    box.onclick = (e) => {
      const b = e.target.closest("button[data-p]");
      if (b) done(b.dataset.p);
      else if (e.target === box) done("q");        // a click outside: queen
    };
  });
}

function setOrientation(o) {
  orientation = o;
  board.set({ orientation: o });
  drawHeat();
  drawStructure();
}

// ------------------------------------------------------------- UCI output

const pane = $("pane");

function lineClass(l) {
  if (l.k === "in") return "l in";
  if (l.k === "sys") return "l sys";
  if (l.t.startsWith("bestmove")) return "l best";
  if (l.t.startsWith("info string")) return "l str";
  return "l";
}

function appendLines(lines) {
  if (!lines.length) return;
  const frag = document.createDocumentFragment();
  for (const l of lines) {
    const d = document.createElement("div");
    d.className = lineClass(l);
    d.textContent = (l.k === "in" ? "> " : l.k === "sys" ? "# " : "") + l.t;
    d.title = l.t;
    frag.append(d);
  }
  pane.append(frag);
  while (pane.childElementCount > MAX_DOM_LINES) pane.firstElementChild.remove();
  if ($("follow").checked) pane.scrollTop = pane.scrollHeight;
}

// Scrolling up by hand stops following; ticking Follow jumps back to the end.
pane.addEventListener("scroll", () => {
  const atEnd = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
  if (!atEnd && $("follow").checked) $("follow").checked = false;
});
$("follow").addEventListener("change", () => {
  if ($("follow").checked) pane.scrollTop = pane.scrollHeight;
});
$("btn-clear").addEventListener("click", () => { pane.textContent = ""; });

// ------------------------------------------------------- the best line, as arrows

// Hovering an arrow of the Evolution graph: the board shows the arrow's starting position with
// the arrow's moves drawn on it, and goes back to what it showed when the pointer leaves.
let previewing = false;

function preview({ fen, last, shapes }) {
  previewing = true;
  $("board").dataset.fen = fen;
  board.set({ fen, lastMove: last || undefined, check: false, animation: { enabled: false } });
  board.setAutoShapes(shapes);
}

function endPreview() {
  if (!previewing) return;
  previewing = false;
  arrowKey = "";                       // the engine's arrows must be put back
  if (current) render(current);
  board.set({ animation: { enabled: true } });
}

// Everything drawn on the board: the first `arrowCount` moves of the engine's line, but only while
// the line belongs to the position on the board (right after a move the engine is still on the
// old one), and what the geometry says about the position (loose pieces, pins), which always does.
function tacticShapes() {
  const t = current && current.tactics;
  const shapes = [];
  if (!t) return shapes;
  if (show.loose) {
    for (const f of t.loose) {
      shapes.push({ orig: f.square, brush: f.now ? "loose" : "loose2", label: { text: `+${f.gain}` } });
    }
  }
  if (show.pins) {
    for (const p of t.pins) {
      shapes.push({ orig: p.slider, dest: p.back, brush: p.kind === "skewer" ? "skewer" : "pin" });
    }
  }
  if (show.defenders && t.defenders) {
    // a ring on the defender and an arrow to each piece it guards
    for (const [list, brush] of [[t.defenders.removable, "removable"], [t.defenders.overloaded, "overload"]]) {
      for (const r of list) {
        shapes.push({ orig: r.defender, brush });
        for (const d of r.defends) shapes.push({ orig: r.defender, dest: d, brush });
      }
    }
  }
  return shapes;
}

// The square-control heat map: a grid laid over the board, teal where White attacks a square more
// often than Black, rose where Black does; the stronger the colour, the bigger the difference.
let heatKey = "";
function drawHeat() {
  const key = previewing || !show.heat || !current ? "" : JSON.stringify([current.control, orientation]);
  if (key === heatKey) return;
  heatKey = key;
  let grid = $("board").querySelector(".heat");
  if (!key) { if (grid) grid.hidden = true; return; }
  if (!grid) {
    grid = document.createElement("div");
    grid.className = "heat";
    for (let i = 0; i < 64; i++) grid.append(document.createElement("i"));
    $("board").append(grid);
  }
  grid.hidden = false;
  const cells = grid.children;
  for (let i = 0; i < 64; i++) {
    const col = i % 8, row = Math.floor(i / 8);               // screen position, top left first
    const file = orientation === "white" ? col : 7 - col;
    const rank = orientation === "white" ? 7 - row : row;
    const net = current.control[String.fromCharCode(97 + file) + (rank + 1)] || 0;
    cells[i].className = net > 0 ? "w" : net < 0 ? "b" : "";
    cells[i].style.setProperty("--k", String(Math.min(Math.abs(net), 4) / 4));
    cells[i].title = net ? `${net > 0 ? "White" : "Black"} +${Math.abs(net)}` : "";
  }
}

// The name of the square under cell i of an overlay grid (screen position, top left first).
function cellName(i) {
  const col = i % 8, row = Math.floor(i / 8);
  const file = orientation === "white" ? col : 7 - col;
  const rank = orientation === "white" ? 7 - row : row;
  return String.fromCharCode(97 + file) + (rank + 1);
}

function overlayGrid(cls, key) {
  let grid = $("board").querySelector("." + cls);
  if (!key) { if (grid) grid.hidden = true; return null; }
  if (!grid) {
    grid = document.createElement("div");
    grid.className = cls;
    for (let i = 0; i < 64; i++) grid.append(document.createElement("i"));
    $("board").append(grid);
  }
  grid.hidden = false;
  return grid;
}

// King safety: red on the squares next to a king that the other side attacks, a green dot on those it could step to.
let zoneKey = "";
function drawKing() {
  const t = current && current.tactics;
  const key = previewing || !show.king || !t || !t.kings ? "" : JSON.stringify([t.kings, orientation]);
  if (key === zoneKey) return;
  zoneKey = key;
  const grid = overlayGrid("zones", key);
  if (!grid) return;
  const kind = {};
  for (const z of Object.values(t.kings)) {
    for (const s of z.danger) kind[s] = "danger";
    for (const s of z.escape) kind[s] = "escape";
  }
  for (let i = 0; i < 64; i++) grid.children[i].className = kind[cellName(i)] || "";
}

// Safe squares: after picking a piece up, where it can go. Green: safe, or the move wins material;
// red: the piece can be won there. Asked of Python once per selection.
let safeMarks = null, safeKey = "";
function clearSafe() {
  safeMarks = null;
  drawSafe();
}
async function onSelect(key) {
  if (!show.safe || previewing || !current || current.viewing || current.over
      || !current.dests || !current.dests[key]) { clearSafe(); return; }
  const r = await api.safe_squares(key);
  if (board.state.selected !== key) return;       // the user has moved on already
  safeMarks = r.squares;
  drawSafe();
}
// Putting a piece down by clicking it again, or dropping it off the board, deselects it without an
// event of its own: so look whenever a pointer is released.
$("board").addEventListener("pointerup", () => setTimeout(() => {
  if (safeMarks && !board.state.selected) clearSafe();
}, 60));
function drawSafe() {
  const key = previewing || !show.safe || !safeMarks ? "" : JSON.stringify([safeMarks, orientation]);
  if (key === safeKey) return;
  safeKey = key;
  const grid = overlayGrid("safe", key);
  if (!grid) return;
  for (let i = 0; i < 64; i++) {
    const v = safeMarks[cellName(i)];
    grid.children[i].className = v === undefined ? "" : v ? "ok" : "bad";
  }
}

// Files and pawn structure: gold stripes on open (strong) and half-open (light) files, a dashed box
// round doubled pawns and a solid one round isolated pawns.
let structKey = "";
function drawStructure() {
  const key = previewing || !show.structure || !current || !current.structure
    ? "" : JSON.stringify([current.structure, orientation]);
  if (key === structKey) return;
  structKey = key;
  let grid = $("board").querySelector(".struct");
  if (!key) { if (grid) grid.hidden = true; return; }
  if (!grid) {
    grid = document.createElement("div");
    grid.className = "struct";
    for (let i = 0; i < 64; i++) grid.append(document.createElement("i"));
    $("board").append(grid);
  }
  grid.hidden = false;
  const st = current.structure;
  const fileKind = {};
  for (const f of st.files) fileKind[f.file] = f.kind;
  const mark = {};
  for (const p of st.pawns) for (const sq of p.squares) (mark[sq] = mark[sq] || new Set()).add(p.kind);
  for (let i = 0; i < 64; i++) {
    const col = i % 8, row = Math.floor(i / 8);
    const file = orientation === "white" ? col : 7 - col;
    const rank = orientation === "white" ? 7 - row : row;
    const name = String.fromCharCode(97 + file) + (rank + 1);
    const cls = [];
    if (fileKind[String.fromCharCode(97 + file)]) cls.push("f-" + fileKind[String.fromCharCode(97 + file)]);
    if (mark[name]) for (const k of mark[name]) cls.push("p-" + k);
    grid.children[i].className = cls.join(" ");
  }
}

function drawShapes() {
  drawHeat();
  drawStructure();
  drawKing();
  drawSafe();
  if (previewing) return;              // an Evolution arrow is being shown: nothing else on the board
  const s = lastSummary;
  let shapes = tacticShapes();
  if (s && s.arrows && current && s.fen === current.fen && arrowCount > 0) {
    // the number is the move's place in the line, so with one side only it reads 1, 3, 5 (or 2, 4, 6)
    s.arrows.slice(0, arrowCount).forEach((a, i) => {
      if (!drawnSide(a.white)) return;
      shapes.push({ orig: a.orig, dest: a.dest, brush: `${a.white ? "w" : "b"}${i}`,
        label: { text: String(i + 1) } });
    });
  }
  const key = JSON.stringify(shapes);
  if (key === arrowKey) return;        // nothing changed: do not redraw on every poll
  arrowKey = key;
  board.setAutoShapes(shapes);
}

// The same findings in words, under the line.
function renderTactics(st) {
  const box = $("tactics");
  box.textContent = "";
  const t = st.tactics;
  if (!t) return;
  const add = (cls, text) => {
    const li = document.createElement("li");
    li.className = cls;
    li.textContent = text;
    box.append(li);
  };
  if (show.loose) for (const f of t.loose) add(f.now ? "t-loose now" : "t-loose", f.text);
  if (show.pins) for (const p of t.pins) add(p.kind === "skewer" ? "t-skewer" : "t-pin", p.text);
  if (show.defenders && t.defenders) {
    for (const r of t.defenders.removable) add("t-removable", r.text);
    for (const o of t.defenders.overloaded) add("t-overload", o.text);
  }
  if (show.king && t.kings) {
    for (const side of ["white", "black"]) {
      const z = t.kings[side];
      if (!z) continue;
      add("t-king", `${side} king ${z.king}: ` + (z.escape.length
        ? `can step to ${z.escape.join(", ")}` : "has no square to step to") + (z.check ? " (in check)" : ""));
    }
  }
  if (show.structure && st.structure) for (const f of st.structure.found) add("t-struct", f.text);
}

for (const k of Object.keys(show)) {
  $("show-" + k).addEventListener("change", () => {
    show[k] = $("show-" + k).checked;
    try { localStorage.setItem("show-" + k, show[k] ? "1" : "0"); } catch (e) { /* storage off */ }
    if (current) renderTactics(current);
    drawShapes();
  });
}

$("arrow-side").addEventListener("change", () => {
  arrowSide = $("arrow-side").value;
  try { localStorage.setItem("arrow-side", arrowSide); } catch (e) { /* storage off */ }
  drawShapes();
  renderSummary(lastSummary);
});

$("arrows").addEventListener("change", () => {
  arrowCount = Number($("arrows").value);
  try { localStorage.setItem("arrows", String(arrowCount)); } catch (e) { /* storage off */ }
  drawShapes();
  renderSummary(lastSummary);
});

// ------------------------------------------------------------ the summary

function fmt(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} Gn`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} Mn`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kn`;
  return `${n} n`;
}

function renderSummary(s) {
  lastSummary = s && s.depth ? s : null;
  drawShapes();
  if (!s || !s.depth) {
    $("eval").textContent = "–";
    $("depth").textContent = "";
    $("nps").textContent = "";
    $("pv").textContent = "";
    $("line-note").textContent = !engineOn && !(current && current.over)
      ? "Analysis is off, so the engine is idle. Press Analyse (or Space) to start it." : "";
    return;
  }
  const bound = s.bound === "lower" ? "≥ " : s.bound === "upper" ? "≤ " : "";
  $("eval").textContent = bound + s.score;
  $("depth").textContent = `depth ${s.depth}/${s.seldepth}`;
  $("nps").textContent = s.nps ? `${fmt(s.nps)}/s` : "";
  // The best line with move numbers, starting from the side to move. The moves drawn as
  // arrows are in the side's colour; the rest of the line is dimmed.
  const pv = $("pv");
  pv.textContent = "";
  let n = s.move_number, white = s.white;
  s.pv.forEach((san, i) => {
    const add = (cls, text) => {
      const e = document.createElement("span");
      e.className = cls;
      e.textContent = text + " ";
      pv.append(e);
    };
    if (white) add("no", `${n}.`);
    else if (i === 0) add("no", `${n}…`);
    add((white ? "w" : "b") + (i < arrowCount && drawnSide(white) ? "" : " far"), san);
    for (const t of (s.themes && s.themes.plies[i] ? s.themes.plies[i].tags : [])) {
      const label = TAG_TEXT[t.tag];
      if (!label) continue;
      const e = document.createElement("span");
      e.className = "tag";
      e.textContent = label;
      e.title = tagTitle(t);
      pv.append(e, " ");
    }
    if (!white) n += 1;
    white = !white;
  });
  const m = s.themes && s.themes.material;
  $("line-note").textContent = m && m.plies > 0 && m.net !== 0
    ? `Material once the line settles (move ${m.plies}): ${(m.net > 0) === m.white ? "White" : "Black"} +${Math.abs(m.net)}`
    : "";
}

// Labels on the moves of the engine's line. Checks, captures and promotions are already in the move's
// own notation (+ x =), so only what the notation does not say is added.
const TAG_TEXT = { fork: "fork", "discovered check": "disc+", "double check": "dbl+", sacrifice: "sac" };

function tagTitle(t) {
  if (t.tag === "fork") return `Fork: attacks ${t.squares.join(" and ")}, and cannot simply be taken`;
  if (t.tag === "sacrifice") return `Gives up about ${t.pawns} pawns' worth of material on the spot`;
  if (t.tag === "discovered check") return "Discovered check: a piece behind the moved one gives the check";
  return "Double check: the king can only move";
}

const STATE_TEXT = { analysing: "analysing", off: "analysis off", idle: "game over",
                     busy: "analysing the whole game", none: "no engine", exited: "engine stopped" };

function renderEngine(e) {
  engineOn = !!e.on;
  const b = $("btn-pause");
  b.textContent = engineOn ? "Stop" : "Analyse";
  b.setAttribute("aria-pressed", String(engineOn));
  b.classList.toggle("primary", !engineOn && e.state !== "none" && e.state !== "exited");
  $("engine").dataset.state = e.state;
  $("uci").dataset.state = e.state;
  const mb = $("u-name").dataset.mb;
  $("u-name").textContent = e.name ? (mb ? `${e.name} · ${mb}` : e.name) : "–";
  $("engine-text").textContent = e.name ? `${e.name} · ${STATE_TEXT[e.state]}` : STATE_TEXT[e.state];
  if (e.error && (e.state === "none" || e.state === "exited")) setMessage(e.error);
}

// ------------------------------------------------ the UCI table (after Arena's engine window)

const uciTable = $("uci-table");
let rowCursor = 0, rowEpoch = -1;
const MAX_ROWS_DOM = 200;
const nfmt = new Intl.NumberFormat("en-US");
const kfmt = (n) => (n < 1000 ? String(n) : `${nfmt.format(Math.round(n / 1000))}k`);
const clock = (ms) => {
  const t = Math.floor(ms / 1000);
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
};

function rowElement(r) {
  const d = document.createElement("div");
  d.className = "ur";
  const cell = (cls, text) => {
    const c = document.createElement("span");
    c.className = cls;
    c.textContent = text;
    d.append(c);
    return c;
  };
  cell("d", `${r.depth}/${r.seldepth}`);
  cell("t", clock(r.time));
  cell("n", kfmt(r.nodes));
  cell("s", kfmt(r.nps));
  const bound = r.bound === "lower" ? "≥" : r.bound === "upper" ? "≤" : "";
  cell("v" + (r.score.includes("#") ? " mate" : ""), bound + r.score);
  const pv = cell("ln", r.pv);
  pv.title = r.pv;
  return d;
}

function applyUci(u) {
  if (!u) return;
  if (u.reset) { uciTable.textContent = ""; rowCursor = 0; }
  rowEpoch = u.epoch;
  if (u.rows.length) {
    const frag = document.createDocumentFragment();
    for (const r of u.rows) frag.prepend(rowElement(r));       // newest on top
    uciTable.prepend(frag);
    while (uciTable.childElementCount > MAX_ROWS_DOM) uciTable.lastElementChild.remove();
    rowCursor = u.rows[u.rows.length - 1].n;
  }
  const st = u.stats || {};
  $("u-threads").textContent = st.threads ? String(st.threads) : "";
  $("u-move").textContent = st.currmove ? `${st.currmove} (${st.currnum}/${st.total_moves || "?"})` : "";
  $("u-nodes").textContent = st.nodes ? nfmt.format(st.nodes) : "";
  $("u-nps").textContent = st.nps ? kfmt(st.nps) : "";
  $("u-hash").textContent = st.hashfull !== undefined ? `${Math.round(st.hashfull / 10)}%` : "";
  const mb = st.hash_mb ? `${st.hash_mb} MB` : "";
  $("u-name").dataset.mb = mb;
}

let rawMode = false;
try { rawMode = localStorage.getItem("uci-raw") === "1"; } catch (e) { /* storage off */ }
function showRaw(on) {
  rawMode = on;
  $("uci-raw").checked = on;
  uciTable.hidden = on;
  $("pane").hidden = !on;
  $("raw-tools").hidden = !on;
  if (on && $("follow").checked) pane.scrollTop = pane.scrollHeight;
}
$("uci-raw").addEventListener("change", () => {
  showRaw($("uci-raw").checked);
  try { localStorage.setItem("uci-raw", rawMode ? "1" : "0"); } catch (e) { /* storage off */ }
});
showRaw(rawMode);

let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const r = await api.poll(cursor, rowCursor, rowEpoch);
    cursor = r.cursor;
    appendLines(r.lines);
    applyUci(r.uci);
    renderEngine(r.engine);
    renderSummary(r.summary);
  } catch (e) {
    /* the window is closing, or the bridge is not up yet */
  } finally {
    polling = false;
  }
}

// --------------------------------------------------------------- controls

async function act(fn, ...args) {
  render(await fn.apply(api, args));
}

$("btn-undo").addEventListener("click", () => act(api.undo));
$("btn-reset").addEventListener("click", () => act(api.reset));
$("btn-flip").addEventListener("click", () => setOrientation(orientation === "white" ? "black" : "white"));
// ---- init-time hookup of the engine list is in init(); a change of the live engine restarts it
$("btn-pause").addEventListener("click", async () => {
  await act(engineOn ? api.pause : api.resume);
  poll();
});

$("btn-back").addEventListener("click", () => act(api.clear_view));

$("fen").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter") return;
  const st = await api.set_position($("fen").value);
  if (st.rejected) { setMessage(st.message || "Not a valid position."); return; }
  $("fen").blur();                     // blur puts the current FEN back in the field
  render(st);
});
$("fen").addEventListener("blur", () => { if (current) $("fen").value = current.fen; });

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && current && current.viewing && !$("pgn-dialog").open) {
    e.preventDefault();
    $("btn-back").click();
    return;
  }
  if (e.target.tagName === "INPUT" && e.target.type !== "checkbox") return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); $("nav-prev").click(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); $("nav-next").click(); }
  else if (e.key === "Home") { e.preventDefault(); $("nav-start").click(); }
  else if (e.key === "End") { e.preventDefault(); $("nav-end").click(); }
  else if (e.key === "f" || e.key === "F") $("btn-flip").click();
  else if (e.key === " " && e.target.tagName !== "BUTTON") { e.preventDefault(); $("btn-pause").click(); }
});

// ------------------------------------------------------------------ start

async function init() {
  api = window.pywebview.api;
  render(await api.state());
  render(await api.start());           // starts Stockfish and the first analysis
  evo = initEvolution({
    api: () => api,
    render,
    message: setMessage,
    preview,
    endPreview,
  });
  evo.onState(current);
  evo.init();
  evo.show();
  engines = initEngines({ api: () => api, onLiveChanged: () => poll() });
  await engines.refresh();
  poll();
  setInterval(poll, POLL_MS);
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
