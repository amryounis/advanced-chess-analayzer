# uciboard

A small desktop chess board that runs a UCI engine (Stockfish) in **infinite analysis**
and shows the engine's raw output beside the board.

Move pieces for both sides; every move restarts the analysis on the new position, and
it keeps going until you move again, pause it, or the game ends.

- **Board**: [chessground](https://github.com/lichess-org/chessground) (the Lichess board,
  vendored, works offline), legal moves only, promotion chooser, castling, en passant.
- **UCI output pane**: every line Stockfish prints, plus the commands sent to it
  (`position fen …`, `go infinite`, `stop`). *Follow* keeps the newest line in view;
  scrolling up stops following.
- **Summary**: evaluation (always from White's side), depth, speed and the best line in SAN.
- **Best line as arrows**: the engine's best line is drawn on the board, numbered in play order,
  White's moves in blue and Black's in orange, fading for later moves. The *Arrows* picker
  sets how many moves are drawn (default 4, i.e. two for each side; 0 turns them off), and the
  second picker draws both sides, White only or Black only (the count is of the line's moves, so
  "White only" with 8 shows White's first four; the numbers keep their place in the line).
  Arrows only ever show a line for the position on the board.
- **Controls**: Undo (Left arrow), New, Flip (F), Pause / Resume (Space), and a FEN box:
  paste a position and press Enter.

- **Tactics**: pieces that can be won, pins and skewers drawn on the board, and labels (fork,
  discovered or double check, sacrifice) on the moves of the engine's line. See below.
- **Evolution tab**: the graph of [Chess Evolution Visualization](https://doi.org/10.1109/TVCG.2014.2299803)
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

## Evolution tab

Play a game (or press **Load PGN…** and paste one), open the **Evolution** tab and press
**Analyse game**. Stockfish searches every position of the game for its best continuations;
the graph shows where the moves played could have led.

How to read it (the *How to read it* box under the graph has the same legend):

- **Circle** = a position of the game, numbered by moves played. **Square** = a position the
  engine expects, not played (hollow unless it carries an event).
- **Ring** = whose turn it is (game positions). **Fill** = the better side, grey when equal or drawn.
  A **red crown** is checkmate; an *effective* check (see below) fills the node with the side giving it.
- **Solid arrow** = one move, **dotted arrow** = several moves shortened into one: click it and the
  moves are played on the board one after the other.
- **Thicker arrow** = a better move compared with the alternatives from the same position
  (thickness is only comparable between arrows leaving the same position).
- **Score chart** under the graph, aligned with its columns: the dot is the score of the move
  actually played, the translucent bar is the range of scores the engine's alternatives would have
  given at that move (log scale, White's point of view; White's move numbers above, Black's below).
  Click a column to jump to that move.
- **Click a node** to put its position on the board (a banner says you are looking at a position
  from the graph; the engine analyses it; Esc or *Back to the game* returns). Everything not
  connected to the node fades. Drag to pan, wheel or +/− to zoom, *Fit* and *Start* to reset the view.

Settings on the tab: **Depth** and **Seconds** (the most time spent on one position). The paper
uses depth 20, which can take many minutes for a long game; the default is 16. On a two-core test
machine a 12-move game took about 40 seconds at the defaults. Finished analyses are kept (see
`cache_dir`) and reused when the same game is analysed again with the same settings. The live
analysis of the board pauses while the job runs and resumes afterwards; *Cancel* stops it quickly.

More settings in uciboard's config file:

```toml
evo_depth = 16         # search depth per position (the paper: 20)
evo_lines = 9          # sequences asked for at each position (the paper: 9)
evo_seconds = 20       # most time on one position
evo_check_depth = 10   # depth of the quick searches that judge a check
cache_dir = ""         # where finished analyses are kept (default: beside the config file)
```

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
| `evolution.py` | The paper's pipeline: sequences, decision tree, merging, shortening, events, edge thickness, score chart |
| `layout.py` | Equation (1): columns, virtual nodes, ordering and vertical positions |
| `config.py` | Where Stockfish is and how it runs |
| `app.py` | The window (pywebview) and a local static server |
| `static/` | The page: board, UCI pane, controls; `evo.js` draws the graph and the score chart |

## Licence

GPL-3.0-or-later, as chessground and Stockfish are.
