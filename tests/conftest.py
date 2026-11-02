import os
import shutil
import time

import pytest


def find_stockfish() -> str:
    return (os.environ.get("UCIBOARD_STOCKFISH_PATH") or shutil.which("stockfish")
            or ("/usr/games/stockfish" if os.path.exists("/usr/games/stockfish") else ""))


@pytest.fixture
def stockfish():
    path = find_stockfish()
    if not path:
        pytest.skip("no Stockfish found (set UCIBOARD_STOCKFISH_PATH)")
    return path


def wait_for(predicate, timeout=15.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out waiting for the condition")
