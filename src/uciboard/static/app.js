import { Chessground } from "./vendor/chessground.min.js";

const $ = (id) => document.getElementById(id);
const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const MAX_DOM_LINES = 1500;          // lines kept in the pane; the engine's full output stays in Python
const POLL_MS = 150;

let api = null;
let cursor = 0;
let paused = false;
let current = null;                  // the last state from Python
let orientation = "white";

const board = Chessground($("board"), {
  fen: START,
  coordinates: true,
  animation: { duration: 150 },
  movable: { free: false, color: undefined, showDests: true, events: { after: onUserMove } },
  premovable: { enabled: false },
  highlight: { lastMove: true, check: true },
});

// ------------------------------------------------------------------ board

function render(st) {
  current = st;
  board.set({
    fen: st.fen,
    turnColor: st.turn,
    check: st.check,
    lastMove: st.last,
    movable: {
      color: st.over ? undefined : st.turn,
      dests: new Map(Object.entries(st.dests)),
    },
  });
  $("version").textContent = st.version;
  document.title = `uciboard ${st.version}`;
  if (document.activeElement !== $("fen")) $("fen").value = st.fen;
  renderMoves(st);
  setMessage(st.over || "");
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

// ------------------------------------------------------------ the summary

function fmt(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} Gn`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} Mn`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kn`;
  return `${n} n`;
}

function renderSummary(s) {
  if (!s || !s.depth) {
    $("eval").textContent = "–";
    $("depth").textContent = "";
    $("nps").textContent = "";
    $("pv").textContent = "";
    return;
  }
  const bound = s.bound === "lower" ? "≥ " : s.bound === "upper" ? "≤ " : "";
  $("eval").textContent = bound + s.score;
  $("depth").textContent = `depth ${s.depth}/${s.seldepth}`;
  $("nps").textContent = s.nps ? `${fmt(s.nps)}/s` : "";
  // The best line with move numbers, starting from the side to move.
  let n = s.move_number, white = s.white, out = [];
  s.pv.forEach((san, i) => {
    if (white) out.push(`${n}.`);
    else if (i === 0) out.push(`${n}…`);
    out.push(san);
    if (!white) n += 1;
    white = !white;
  });
  $("pv").textContent = out.join(" ");
}

const STATE_TEXT = { analysing: "analysing", paused: "paused", idle: "game over",
                     none: "no engine", exited: "engine stopped" };

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

$("fen").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter") return;
  const st = await api.set_position($("fen").value);
  if (st.rejected) { setMessage(st.message || "Not a valid position."); return; }
  $("fen").blur();                     // blur puts the current FEN back in the field
  render(st);
});
$("fen").addEventListener("blur", () => { if (current) $("fen").value = current.fen; });

window.addEventListener("keydown", (e) => {
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
  poll();
  setInterval(poll, POLL_MS);
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
