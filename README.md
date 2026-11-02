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
- **Controls**: Undo (Left arrow), New, Flip (F), Pause / Resume (Space), and a FEN box:
  paste a position and press Enter.

Nothing leaves your machine. No LLM, no internet.

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
| `api.py` | What the page calls: board, moves, polling of the output and summary |
| `config.py` | Where Stockfish is and how it runs |
| `app.py` | The window (pywebview) and a local static server |
| `static/` | The page: board, UCI pane, controls |

## Licence

GPL-3.0-or-later, as chessground and Stockfish are.
