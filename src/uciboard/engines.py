"""
The engines uciboard can use, and which one does which job.

Two jobs pick an engine separately: the **live** analysis of the board, and the **evolution**
(the game analysis behind the graph). Both choose from the same list: the Stockfish that uciboard
finds by itself (`default`, see config.py) and any engine you add. Added engines, their options and
the two choices are kept in `engines.json` beside the config file.

An engine's options are sent to it after `uci`, but only those it reports having, so a setting like
`Hash` is simply skipped by an engine without it. Lc0 for instance needs `WeightsFile` and
usually `Backend`; they go in the engine's options like any other.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .uci import EngineError, UciEngine

ROLES = ("live", "evolution")
DEFAULT = "default"


@dataclass
class Entry:
    id: str
    name: str
    path: str
    options: dict = field(default_factory=dict)     # option name -> value, as text

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT


def parse_options(text: str) -> dict:
    """`Name=value` lines to a dict. Blank lines and lines starting with # are skipped; a line
    without `=` is an error (it is most likely a typo, and would otherwise be ignored silently)."""
    out: dict = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"line {n}: write each option as Name=value (not {line!r})")
        out[name.strip()] = value.strip()
    return out


def options_text(options: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in options.items())


def probe(path: str, timeout: float = 20.0) -> str:
    """Start the program, ask it `uci`, and return its name; raises EngineError when it is not a UCI
    engine. It is not asked to get ready, so an engine that loads a big network does not wait for it."""
    if not os.path.isfile(path):
        raise EngineError(f"No file at {path}")
    engine = UciEngine(path, startup_timeout=timeout)
    try:
        engine.start(ready=False)
        return engine.name or Path(path).stem
    finally:
        engine.quit()


class Registry:
    """The default engine (found by config.py), the added ones, and the two choices."""

    def __init__(self, default_path: str = "", default_source: str = "", file: Optional[Path] = None):
        self.default_path = default_path
        self.default_source = default_source
        self.file = Path(file) if file else None
        self.added: list = []
        self.choice = {role: DEFAULT for role in ROLES}
        self.error = ""
        self.load()

    # ------------------------------------------------------------ reading

    def all(self) -> list:
        out = []
        if self.default_path:
            out.append(Entry(DEFAULT, "Stockfish (auto)", self.default_path))
        return out + list(self.added)

    def get(self, engine_id: str) -> Optional[Entry]:
        return next((e for e in self.all() if e.id == engine_id), None)

    def resolve(self, role: str) -> Optional[Entry]:
        """The engine chosen for `role`; the default when the choice is gone; None when nothing is set up."""
        found = self.get(self.choice.get(role, DEFAULT))
        if found is not None:
            return found
        everything = self.all()
        return everything[0] if everything else None

    # ------------------------------------------------------------ changing

    def add(self, path: str, name: str) -> Entry:
        taken = {e.name for e in self.all()}
        base, n = name.strip() or Path(path).stem, 2
        unique = base
        while unique in taken:
            unique, n = f"{base} ({n})", n + 1
        ids = [int(m.group(1)) for e in self.added if (m := re.fullmatch(r"e(\d+)", e.id))]
        entry = Entry(f"e{max(ids, default=0) + 1}", unique, path)
        self.added.append(entry)
        self.save()
        return entry

    def update(self, engine_id: str, name: str, options: dict) -> Entry:
        entry = next((e for e in self.added if e.id == engine_id), None)
        if entry is None:
            raise KeyError(engine_id)
        others = {e.name for e in self.all() if e.id != engine_id}
        name = name.strip() or entry.name
        if name in others:
            raise ValueError(f"There is already an engine called {name!r}.")
        entry.name, entry.options = name, dict(options)
        self.save()
        return entry

    def remove(self, engine_id: str) -> None:
        self.added = [e for e in self.added if e.id != engine_id]
        for role, chosen in self.choice.items():
            if chosen == engine_id:
                self.choice[role] = DEFAULT
        self.save()

    def choose(self, role: str, engine_id: str) -> None:
        if role not in ROLES:
            raise KeyError(role)
        if self.get(engine_id) is None:
            raise KeyError(engine_id)
        self.choice[role] = engine_id
        self.save()

    # ------------------------------------------------------------ the file

    def load(self) -> None:
        if self.file is None or not self.file.exists():
            return
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            self.added = [Entry(str(e["id"]), str(e["name"]), str(e["path"]),
                                {str(k): str(v) for k, v in dict(e.get("options", {})).items()})
                          for e in data.get("engines", [])]
            for role in ROLES:
                chosen = data.get("choice", {}).get(role)
                if isinstance(chosen, str):
                    self.choice[role] = chosen
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.added = []
            self.error = f"Cannot read {self.file}: {e}"

    def save(self) -> None:
        if self.file is None:
            return
        data = {"version": 1,
                "engines": [{"id": e.id, "name": e.name, "path": e.path, "options": e.options}
                            for e in self.added],
                "choice": self.choice}
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.file)
        except OSError as e:
            self.error = f"Cannot save {self.file}: {e}"
