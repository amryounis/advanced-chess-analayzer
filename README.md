# uciboard

A small desktop chess board that runs a UCI engine (Stockfish) in **infinite analysis**
and shows the engine's raw output beside the board.

Move pieces for both sides; every move restarts the analysis on the new position, and
it keeps going until you move again, pause it, or the game ends.

- **Board**: [chessground](https://github.com/lichess-org/chessground) (the Lichess board,
  vendored, works offline), legal moves only, promotion chooser, castling, en passant.
- **UCI output**: every line Stockfish prints, plus the commands sent to it
  (`position fen …`, `go infinite`, `stop`), in a strip of five lines (four in a short window) at
  the bottom of the right column. One log line is one row; hover it for the whole line, scroll
  for older ones. *Follow* keeps the newest line in view; scrolling up stops following.
- **Summary**: evaluation (always from White's side), depth, speed and the best line in SAN.
- **Best line as arrows**: the engine's best line is drawn on the board, numbered in play order,
  White's moves in blue and Black's in orange, fading for later moves. The *Arrows* picker
  sets how many moves are drawn (default 4, i.e. two for each side; 0 turns them off), and the
  second picker draws both sides, White only or Black only (the count is of the line's moves, so
  "White only" with 8 shows White's first four; the numbers keep their place in the line).
  Arrows only ever show a line for the position on the board.
- **Controls**: Undo, New, Flip (F), Pause / Resume (Space), and a FEN box:
  paste a position and press Enter.
- **Moving through the game**: the arrows under the board (or Left / Right, Home / End) step back
  and forward, and clicking a move in the list jumps to it. The later moves stay in the list,
  greyed, and the engine analyses the position you are on. Playing the game's own next move steps
  on; playing a different move from an earlier position replaces the rest of the game. *Undo*
  takes back the move on the board, and the moves after it if you had stepped back.

- **Tactics**: pieces that can be won, pins and skewers drawn on the board, and labels (fork,
  discovered or double check, sacrifice) on the moves of the engine's line. See below.
- **Pawn structure** (off by default): open and half-open files (gold stripes), doubled pawns
  (dashed box) and isolated pawns (solid box), listed under the line. Plain facts about the
  position: a doubled or isolated pawn can be fine, and an open file may be just what the position
  wants.
- **Positional graph measures**: the position as a graph of its 64 squares and their moves, after
  [ChessY](https://doi.org/10.1016/j.softx.2018.12.004) (Rudolph-Lilith, SoftwareX 2019): a
  square-control heat map on the board, and control, mobility, offensiveness, defensiveness and
  more for both sides along the game, under the Evolution score chart. See below.
- **Evolution**: the graph of [Chess Evolution Visualization](https://doi.org/10.1109/TVCG.2014.2299803)
  (Lu, Wang, Lin; IEEE TVCG 2014) for the game on the board. See below.

Nothing leaves your machine. No LLM, no internet.

## Tactics

Two layers, kept apart so you can tell what Stockfish thinks from what is simply geometry.

**The position on the board** (no engine, instant; the *Show on the board* boxes toggle them):

- **Loose pieces**: a ring with the material the other side wins (`+3` is a knight's worth), listed
  below the line. Red means it is their move, yellow means they would have to be allowed to.
  This is decided by a *static exchange evaluation*, not by counting attackers against defenders:
  both sides capture on the square cheapest-first, pieces behind a capturer join in (x-rays), either
  side may stop, a pinned piece may only capture along its pin, and a king only takes an unguarded
  piece. So a pawn attacking a queen that is defended once is flagged (it wins the queen for a pawn),
  and an even trade is not.
- **Square control** (off by default): every square tinted teal where White has more attackers than
  Black, rose where Black has, stronger with the difference; hover a square for the numbers.
  It counts attackers, so a pawn's diagonal counts even on an empty square, which is not what the
  ChessY *control* measure counts (see *Positional graph measures*).
- **Pins and skewers**: purple (pin, absolute or to something worth more) and teal (skewer) arrows
  from the pinning piece to the piece behind. python-chess's own `is_pinned` only knows pins to the
  king, so the others are found by looking along the line. A pin is not reported if the pinning
  piece itself can simply be won. A skewer against the king is a check and is not listed.

**The engine's line** (the moves Stockfish chose, named by geometry): `fork` (two targets that are
the king, worth more than the forker, or undefended, and the forker cannot be taken profitably),
`disc+` (discovered check), `dbl+` (double check), `sac` (the moved piece can be won for more
than the move took). Checks, captures and promotions are already in the move notation. Under the
line, the **net material** is given only up to the last position where nothing is left to take for free: a
line cut off in the middle of an exchange would otherwise show a capture that is about to be
recaptured as a gain.

Limits: a king already in check from another piece, overloaded defenders and promotion or en passant
inside an exchange are not modelled; material is counted pawn 1, minor piece 3, rook 5, queen 9. These
are descriptions of the position, not evaluations of it: a "loose" piece can still be the right
thing to leave.

## Evolution

Play a game (or press **Load PGN…** and paste one), press
**Analyse game**. Stockfish searches every position of the game for its best continuations;
the graph shows where the moves played could have led.

How to read it (the *How to read it* box under the graph has the same legend):

- **Colour**: **blue** is the game that was played (arrows, the outline of its circles, the score
  line), **orange** is everything the engine suggests instead (arrows, squares, the range bars).
  Blue arrows are drawn on top of orange ones.
- **Circle** = a position of the game, numbered by moves played. **Square** = a position the
  engine expects, not played (orange outline; filled when it carries an event).
- **Ring** = whose turn it is (game positions). **Fill** = the better side, grey when equal or drawn.
  A **red crown** is checkmate; an *effective* check (see below) fills the node with the side giving it.
- **Solid arrow** = one move, **dotted arrow** = several moves shortened into one.
- **Hover an arrow** and its moves are drawn on the board as numbered arrows (blue for the game,
  orange for an alternative), starting from the position the arrow leaves; the board's own
  engine arrows are hidden meanwhile. **Click an arrow** and its moves are played on the board one
  after the other. (An arrow back to a position already shown has no moves to preview or play.)
- **Thicker arrow** = a better move compared with the alternatives from the same position
  (thickness is only comparable between arrows leaving the same position).
- **Score chart** under the graph, aligned with its columns: the dot is the score of the move
  actually played, the translucent bar is the range of scores the engine's alternatives would have
  given at that move (log scale, White's point of view; White's move numbers above, Black's below).
  Click a column to jump to that move.
- **Click a node** to put its position on the board (a banner says you are looking at a position
  from the graph; the engine analyses it; Esc or *Back to the game* returns). Everything not
  connected to the node fades. Drag to pan, wheel or +/− to zoom, *Fit* and *Start* to reset the view.

Settings in the toolbar: **Depth** and **Seconds** (the most time spent on one position). The paper
uses depth 20, which can take many minutes for a long game; the default is 16. On a two-core test
machine a 12-move game took about 40 seconds at the defaults. Finished analyses are kept (see
`cache_dir`) and reused when the same game is analysed again with the same settings (a release that changes what a saved graph contains, like 0.5.0, analyses the game again once). The live
analysis of the board pauses while the job runs and resumes afterwards; *Cancel* stops it quickly.

More settings in uciboard's config file:

```toml
evo_depth = 16         # search depth per position (the paper: 20)
evo_lines = 9          # sequences asked for at each position (the paper: 9)
evo_seconds = 20       # most time on one position
evo_check_depth = 10   # depth of the quick searches that judge a check
cache_dir = ""         # where finished analyses are kept (default: beside the config file)
```

### Move quality

After an analysis, the moves that gave something away are marked in the move list, in the PGN
export (as the standard `?!`, `?`, `??` symbols) and counted per side under the graph's title.
A move is judged by how much it dropped the mover's chance of winning, using the winning-chances
curve Lichess publishes: `win% = 50 + 50 · (2 / (1 + e^(−0.00368208 · cp)) − 1)`, scores clipped to
±10 pawns. A drop of 10 points is an inaccuracy (`?!`), 20 a mistake (`?`), 30 a blunder (`??`).
Using winning chances means two pawns given up while a rook ahead count for little, and the same
loss in an equal position counts for a lot.

What it is not: a verdict. The scores are from the depth the analysis ran at, and "best" is the best
of the lines the analysis kept for that position, not of every legal move; a move scoring better
than all of them loses nothing. Nothing is marked "good" or "best". It uses what the Evolution
analysis already found, so there is no extra search.

### Exporting the game

*Export PGN…* in the Evolution toolbar shows the game as a PGN you can copy into Lichess or chess.com.
Each move carries what those sites read from the comments: `[%eval]` (the engine's score after the
move, White's side), a green arrow when the analysis found a move at least half a pawn better
(only moves compared one move deep, at the depth the analysis ran, so it is the engine's opinion
at that depth, not a verdict), and the tactic names of the move that was played (fork with its
targets circled, discovered or double check, sacrifice). Without an analysis for this game you get
the moves and the tactic names only.

### Positional graph measures (ChessY)

Under the score chart, a second chart plots one measure for White (teal) and Black (rose) after
every move of the game, in the same columns as the graph and the score chart; click a column to
jump to that position. Pick the measure from the list. They come from the positional chess graph
of ChessY: a node for each square, an edge for each move a piece can make (the side not to move
is treated as if it were to move; pins are respected):

| Measure | Meaning |
| --- | --- |
| Control | squares the side can move to that are empty or hold an enemy piece, as a share of those squares |
| Mobility | empty squares the side can move to, as a share of the empty squares |
| Connectedness | moves and guarded pieces, as a share of a fully connected graph (64 × 63) |
| Offensiveness | pieces that can capture an enemy piece (a count) |
| Defensiveness | pieces that guard a piece of their own colour (a count) |
| Reach | different squares the side's pieces reach, per piece |
| Material | pawn 1, knight and bishop 3, rook 5, queen 9 (not in the paper; its author found keeping more and higher-value pieces together with high connectivity goes with winning) |

How the paper was read: it is a short software note, and I filled these gaps myself. A piece cannot
move onto its own piece, yet *defensiveness* counts edges to own pieces, so guarded pieces are
added as edges (they count towards connectedness and reach, not towards control or mobility).
The paper gives no denominators for control and mobility; the shares above are the natural ones.
*Dominance* is left out because its definition in the paper is garbled. The measures describe the
position; they are not an evaluation. They are worked out when a graph is loaded and are not kept
in the saved analysis.

### Where this differs from the paper

- **Layout**: the paper hands equation (1) to Graphviz. Here it is solved in plain Python
  (`layout.py`) with the paper's weights, so nothing has to be installed. Columns are moves
  from the start of the game and the played line is pinned to a horizontal axis. The result looks
  like the paper's figures but is not Graphviz's output.
- **"Effective check"**: the paper does not define it precisely. Here a check counts as effective
  when the checking side is not worse off afterwards: two quick searches (the position before the
  check, and the position after it, one ply shallower) are compared, and the check is effective if
  the checker's score after is at least its score before (`check_tolerance`, 0 by default, allows
  some slack). Treat the check highlighting as an interpretation.
- **Edge thickness** follows equation (2) with a = 1 and the [1, 30] normalisation, drawn as 1–8 px.
- Search depth and time defaults are lower than the paper's (see above).

## Install

Python 3.10 or newer.

```
pip install -e ".[gui]"
uciboard-app
```

`uciboard-app` opens the window without a console. `uciboard` (or `python -m uciboard`) does
the same from a terminal.

## Which Stockfish

By default uciboard **reuses the Stockfish you already set up for chesscoach**: it reads
`stockfish_path` from `%APPDATA%\chesscoach\config.toml`. Check what it found with:

```
uciboard --where
```

The path is taken from the first of these that is set:

1. `--stockfish PATH`
2. the environment variable `UCIBOARD_STOCKFISH_PATH`
3. uciboard's own `%APPDATA%\uciboard\config.toml` (elsewhere `~/.config/uciboard/config.toml`)
4. chesscoach's `config.toml`
5. `stockfish` on the PATH

A path that is set but wrong is reported as an error in the window; it never silently falls
through to the next one. The board still works without an engine.

Optional settings in uciboard's own config file:

```toml
stockfish_path = "C:/engines/stockfish/stockfish.exe"
threads = 6        # default: half the logical cores
hash_mb = 512      # default 512
multipv = 1        # lines the engine searches at once (the summary shows line 1)
```

## Development

```
pip install -e ".[gui,dev]"
pytest
```

Tests that need an engine run against the Stockfish found by the rules above and are
skipped when there is none. The browser tests also need `playwright install chromium`
(or a Chrome on the machine; set `UCIBOARD_TEST_CHROME` to its path).

## Layout

| File | What it does |
| --- | --- |
| `uci.py` | Drives the engine process; infinite search that can jump to a new position, and drops the old search's output when it does |
| `api.py` | What the page calls: board, moves, polling of the output, summary and the best line's arrows; PGN loading, viewing a position, the Evolution job |
| `tactics.py` | Exchange evaluation, loose pieces, pins and skewers, and the labels and net material of an engine line (python-chess only) |
| `structure.py` | Open and half-open files, doubled and isolated pawns |
| `quality.py` | Inaccuracy, mistake and blunder marks from the analysis |
| `pgnexport.py` | The game as a PGN with the analysis in the comments |
| `posgraph.py` | The positional chess graph of a position (ChessY): edges, the measures, and the heat map's control counts |
| `evolution.py` | The paper's pipeline: sequences, decision tree, merging, shortening, events, edge thickness, score chart |
| `layout.py` | Equation (1): columns, virtual nodes, ordering and vertical positions |
| `config.py` | Where Stockfish is and how it runs |
| `app.py` | The window (pywebview) and a local static server |
| `static/` | The page: board, moves, the line and overlays, the Evolution graph, the UCI strip; `evo.js` draws the graph and the score chart |

## Licence

GPL-3.0-or-later, as chessground and Stockfish are.
