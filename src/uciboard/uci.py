"""
A small UCI engine driver.

Runs the engine as a child process, keeps every line it prints, and runs
infinite searches that can be moved to a new position at any moment.

Moving on: when the position changes the old search is told to `stop`, the
new `position` / `go infinite` follow straight away, and everything the
engine prints until the old search's `bestmove` is dropped, so output from
the old position never shows up under the new one.
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Callable, Optional

# on_line(kind, text, tag):  kind "out" = a line from the engine, "in" = a command
# we sent, "sys" = a note from us. tag is whatever analyze() was given for the
# search that line belongs to (None for lines outside a search).
LineCallback = Callable[[str, str, object], None]


class EngineError(Exception):
    """The engine could not be started, or stopped answering."""


class UciEngine:
    def __init__(self, path: str, on_line: Optional[LineCallback] = None,
                 options: Optional[dict] = None, startup_timeout: float = 20.0):
        self.path = path
        self.on_line = on_line or (lambda kind, text, tag: None)
        self.options = dict(options or {})
        self.startup_timeout = startup_timeout
        self.name = ""
        self.option_names: set = set()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._uciok = threading.Event()
        self._readyok = threading.Event()
        self._stale = 0              # bestmoves still owed by searches we abandoned
        self._searching = False      # a search is running (or stopping) on the engine
        self._stopping = False       # ... and we have already sent it `stop`
        self._tag: object = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._proc = subprocess.Popen(
                [self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                encoding="utf-8", errors="replace", creationflags=flags,
                # Run beside the engine so it finds its network file (NNUE)
                cwd=os.path.dirname(os.path.abspath(self.path)) or None)
        except OSError as e:
            raise EngineError(f"Cannot start {self.path}: {e}") from e
        threading.Thread(target=self._read_loop, daemon=True).start()

        self._send("uci")
        if not self._uciok.wait(self.startup_timeout):
            self.quit()
            raise EngineError(f"{self.path} did not answer `uci`. Is it a UCI engine?")
        for name, value in self.options.items():
            if name in self.option_names:
                self._send(f"setoption name {name} value {value}")
        self._readyok.clear()
        self._send("isready")
        if not self._readyok.wait(self.startup_timeout):
            self.quit()
            raise EngineError(f"{self.path} did not become ready.")

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def searching(self) -> bool:
        return self._searching

    def quit(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    self._send("quit")
                except EngineError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        finally:
            for stream in (proc.stdin, proc.stdout):
                try:
                    stream.close()
                except Exception:
                    pass

    # ------------------------------------------------------------- searching

    def analyze(self, fen: str, tag: object = None) -> None:
        """Search `fen` until told otherwise, dropping whatever the old search prints."""
        with self._lock:
            self._abandon()
            self._tag = tag
            self._send(f"position fen {fen}")
            self._send("go infinite")
            self._searching, self._stopping = True, False

    def stop(self) -> None:
        """Stop searching; the engine's final `bestmove` is still shown."""
        with self._lock:
            if self._searching and not self._stopping:
                self._send("stop")
                self._stopping = True

    def _abandon(self) -> None:
        # called with the lock held
        if not self._searching:
            return
        if not self._stopping:
            self._send("stop")
        self._stale += 1
        self._searching, self._stopping = False, False

    # --------------------------------------------------------------- plumbing

    def _send(self, command: str) -> None:
        with self._lock:
            if not self.alive:
                raise EngineError("The engine is not running.")
            try:
                self._proc.stdin.write(command + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise EngineError(f"Lost the engine while sending {command!r}: {e}") from e
            tag = self._tag
        self.on_line("in", command, tag)

    def _read_loop(self) -> None:
        proc = self._proc
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                head = line.split(None, 1)[0]
                if head == "id" and line.startswith("id name "):
                    self.name = line[len("id name "):].strip()
                elif head == "option":
                    parts = line.split()
                    if "name" in parts:
                        i = parts.index("name") + 1
                        j = parts.index("type") if "type" in parts else len(parts)
                        self.option_names.add(" ".join(parts[i:j]))
                with self._lock:
                    if head == "uciok":
                        self._uciok.set()
                    elif head == "readyok":
                        self._readyok.set()
                    if self._stale > 0:
                        if head == "bestmove":
                            self._stale -= 1
                        continue                    # the abandoned search's output
                    if head == "bestmove":
                        self._searching = self._stopping = False
                    tag = self._tag
                self.on_line("out", line, tag)
        except (OSError, ValueError):
            pass
        code = proc.poll()
        if code is None:
            try:
                code = proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                code = None
        with self._lock:
            self._searching = self._stopping = False
        self.on_line("sys", f"engine exited{'' if code is None else f' (code {code})'}", None)


def parse_info(line: str) -> Optional[dict]:
    """Pick the useful numbers out of an `info ...` line (None for other lines).

    Score is from the side to move's point of view, as the engine sends it:
    {"cp": 35} or {"mate": -3}. `bound` is "lower" / "upper" when the engine
    says the score is only a bound.
    """
    parts = line.split()
    if not parts or parts[0] != "info" or "string" in parts[:2]:
        return None
    out: dict = {}
    i = 1
    n = len(parts)
    while i < n:
        key = parts[i]
        if key in ("depth", "seldepth", "multipv", "nodes", "nps", "time", "hashfull", "tbhits"):
            try:
                out[key] = int(parts[i + 1])
            except (IndexError, ValueError):
                pass
            i += 2
        elif key == "score":
            try:
                kind, val = parts[i + 1], int(parts[i + 2])
            except (IndexError, ValueError):
                i += 1
                continue
            out["score"] = {kind: val} if kind in ("cp", "mate") else None
            i += 3
            if i < n and parts[i] in ("lowerbound", "upperbound"):
                out["bound"] = parts[i][:-5]
                i += 1
        elif key == "pv":
            out["pv"] = parts[i + 1:]
            break
        elif key == "wdl":
            i += 4                                  # wdl <win> <draw> <loss>
        elif key in ("currmove", "currmovenumber"):
            i += 2
        elif key in ("refutation", "currline"):
            break                                   # move lists we do not use
        else:
            i += 1
    return out
