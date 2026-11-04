import { Chessground } from "./vendor/chessground.min.js";
import { initEvolution } from "./evo.js";

const $ = (id) => document.getElementById(id);
const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const MAX_DOM_LINES = 1500;          // lines kept in the pane; the engine's full output stays in Python
const POLL_MS = 150;

let api = null;
let cursor = 0;
let paused = false;
let current = null;                  // the last state from Python
let orientation = "white";
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
  return brushes;
}

const board = Chessground($("board"), {
  fen: START,
  coordinates: true,
  animation: { duration: 150 },
  movable: { free: false, color: undefined, showDests: true, events: { after: onUserMove } },
  premovable: { enabled: false },
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
const show = { loose: true, pins: true, heat: false };
for (const k of Object.keys(show)) {
  try {
    const v = localStorage.getItem("show-" + k);
    if (v !== null) show[k] = v === "1";
  } catch (e) { /* storage off */ }
  $("show-" + k).checked = show[k];
}

// ------------------------------------------------------------------ board

function render(st) {
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
    m.className = "mv" + (i === st.moves.length - 1 ? " cur" : "");
    m.textContent = san;
    box.append(m);
    if (!whiteToMove) num += 1;
    whiteToMove = !whiteToMove;
  });
  box.scrollTop = box.scrollHeight;
}

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

function drawShapes() {
  drawHeat();
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
    $("line-note").textContent = "";
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

const STATE_TEXT = { analysing: "analysing", paused: "paused", idle: "game over",
                     busy: "analysing the whole game", none: "no engine", exited: "engine stopped" };

function renderEngine(e) {
  $("engine").dataset.state = e.state;
  $("engine-text").textContent = e.name ? `${e.name} · ${STATE_TEXT[e.state]}` : STATE_TEXT[e.state];
  if (e.error && (e.state === "none" || e.state === "exited")) setMessage(e.error);
}

let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const r = await api.poll(cursor);
    cursor = r.cursor;
    appendLines(r.lines);
    renderSummary(r.summary);
    renderEngine(r.engine);
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
$("btn-pause").addEventListener("click", async () => {
  paused = !paused;
  $("btn-pause").textContent = paused ? "Resume" : "Pause";
  $("btn-pause").setAttribute("aria-pressed", String(paused));
  await act(paused ? api.pause : api.resume);
});

$("btn-back").addEventListener("click", () => act(api.clear_view));

// ------------------------------------------------------------------- tabs

function showTab(name) {
  for (const b of document.querySelectorAll(".tabs [role=tab]")) {
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
  }
  $("pane").hidden = name !== "uci";
  $("evo").hidden = name !== "evo";
  document.querySelector(".pane-head").dataset.tab = name;
  if (name === "evo" && evo) evo.show();
  else if (name === "uci" && $("follow").checked) pane.scrollTop = pane.scrollHeight;
}
for (const b of document.querySelectorAll(".tabs [role=tab]")) {
  b.addEventListener("click", () => showTab(b.dataset.tab));
}

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
  if (e.key === "ArrowLeft") { e.preventDefault(); $("btn-undo").click(); }
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
  poll();
  setInterval(poll, POLL_MS);
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
