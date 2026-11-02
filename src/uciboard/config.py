"""
Settings: where Stockfish lives and how it is run.

The Stockfish path is looked up in this order (first one set wins):
  1. --stockfish PATH on the command line
  2. the environment variable UCIBOARD_STOCKFISH_PATH
  3. uciboard's own config file
       (Windows: %APPDATA%\\uciboard\\config.toml, elsewhere: ~/.config/uciboard/config.toml)
  4. chesscoach's config file, so the engine you already set up there is reused
       (Windows: %APPDATA%\\chesscoach\\config.toml, elsewhere: ~/.config/chesscoach/config.toml)
  5. "stockfish" on the PATH

A path that is set but points nowhere is an error; it never silently falls
through to the next source.

Other settings (all optional) go in uciboard's config file:
    threads = 4        # search threads
    hash_mb = 512      # transposition table size
    multipv = 1        # lines shown at once
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class ConfigError(Exception):
    """A setting is wrong or the engine cannot be found."""


@dataclass
class Settings:
    stockfish_path: str = ""
    threads: int = 1
    hash_mb: int = 512
    multipv: int = 1
    source: str = "defaults"        # where the Stockfish path came from (info only)

    def uci_options(self) -> dict:
        return {"Threads": self.threads, "Hash": self.hash_mb, "MultiPV": self.multipv}

    def require_stockfish(self) -> str:
        if not self.stockfish_path:
            raise ConfigError(
                "No Stockfish found. Set stockfish_path in "
                f"{user_config_path()} (or in chesscoach's config), set "
                "UCIBOARD_STOCKFISH_PATH, or start with --stockfish PATH.")
        if not os.path.isfile(self.stockfish_path):
            raise ConfigError(
                f"Stockfish not found at {self.stockfish_path} (from {self.source}).")
        return self.stockfish_path


def _config_home() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def user_config_path() -> Path:
    return _config_home() / "uciboard" / "config.toml"


def chesscoach_config_path() -> Path:
    return _config_home() / "chesscoach" / "config.toml"


def _read(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Cannot read {path}: {e}") from e


def _int(name: str, value, low: int, high: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a whole number, not {value!r}") from None
    return max(low, min(high, v))


def default_threads() -> int:
    """Half the logical cores, at least one: leaves the machine usable while analysing."""
    return max(1, (os.cpu_count() or 2) // 2)


def load_settings(stockfish: Optional[str] = None, own_config: Optional[Path] = None,
                  chesscoach_config: Optional[Path] = None) -> Settings:
    s = Settings(threads=default_threads())

    own = Path(own_config) if own_config else user_config_path()
    data = _read(own) if own.exists() else {}
    unknown = set(data) - {"stockfish_path", "threads", "hash_mb", "multipv"}
    if unknown:
        raise ConfigError(f"Unknown setting(s) in {own}: {', '.join(sorted(unknown))}")
    if "threads" in data:
        s.threads = _int("threads", data["threads"], 1, 1024)
    if "hash_mb" in data:
        s.hash_mb = _int("hash_mb", data["hash_mb"], 1, 1_000_000)
    if "multipv" in data:
        s.multipv = _int("multipv", data["multipv"], 1, 20)

    if stockfish:
        s.stockfish_path, s.source = stockfish, "--stockfish"
    elif os.environ.get("UCIBOARD_STOCKFISH_PATH"):
        s.stockfish_path, s.source = os.environ["UCIBOARD_STOCKFISH_PATH"], "UCIBOARD_STOCKFISH_PATH"
    elif data.get("stockfish_path"):
        s.stockfish_path, s.source = str(data["stockfish_path"]), str(own)
    else:
        cc = Path(chesscoach_config) if chesscoach_config else chesscoach_config_path()
        cc_path = ""
        if cc.exists():
            try:
                cc_path = str(_read(cc).get("stockfish_path", "") or "")
            except ConfigError:
                cc_path = ""        # chesscoach's file is not ours to complain about
        if cc_path:
            s.stockfish_path, s.source = cc_path, f"chesscoach config ({cc})"
        else:
            found = shutil.which("stockfish")
            if found:
                s.stockfish_path, s.source = found, "PATH"
    return s
