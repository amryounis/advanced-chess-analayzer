import pytest

from uciboard import config


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("UCIBOARD_STOCKFISH_PATH", raising=False)
    monkeypatch.setenv("PATH", "")          # so nothing is found on the PATH unless a test adds it


def test_reuses_the_chesscoach_stockfish(tmp_path):
    cc = _write(tmp_path / "cc" / "config.toml", 'stockfish_path = "C:/engines/sf.exe"\ndepth = 18\n')
    s = config.load_settings(own_config=tmp_path / "none.toml", chesscoach_config=cc)
    assert s.stockfish_path == "C:/engines/sf.exe"
    assert "chesscoach" in s.source


def test_own_config_beats_chesscoach(tmp_path):
    own = _write(tmp_path / "own.toml", 'stockfish_path = "/mine/sf"\nthreads = 3\nhash_mb = 256\n')
    cc = _write(tmp_path / "cc.toml", 'stockfish_path = "/theirs/sf"\n')
    s = config.load_settings(own_config=own, chesscoach_config=cc)
    assert (s.stockfish_path, s.threads, s.hash_mb) == ("/mine/sf", 3, 256)


def test_env_and_flag_order(tmp_path, monkeypatch):
    own = _write(tmp_path / "own.toml", 'stockfish_path = "/mine/sf"\n')
    monkeypatch.setenv("UCIBOARD_STOCKFISH_PATH", "/env/sf")
    assert config.load_settings(own_config=own).stockfish_path == "/env/sf"
    assert config.load_settings(stockfish="/flag/sf", own_config=own).stockfish_path == "/flag/sf"


def test_a_broken_chesscoach_file_is_ignored(tmp_path):
    cc = _write(tmp_path / "cc.toml", "this is = not [valid")
    s = config.load_settings(own_config=tmp_path / "none.toml", chesscoach_config=cc)
    assert s.stockfish_path == ""


def test_own_config_errors_are_reported(tmp_path):
    with pytest.raises(config.ConfigError):
        config.load_settings(own_config=_write(tmp_path / "a.toml", "bogus = 1\n"))
    with pytest.raises(config.ConfigError):
        config.load_settings(own_config=_write(tmp_path / "b.toml", 'threads = "many"\n'))


def test_a_path_that_points_nowhere_is_an_error_not_a_fallthrough(tmp_path):
    s = config.load_settings(stockfish=str(tmp_path / "missing.exe"),
                             own_config=tmp_path / "none.toml")
    with pytest.raises(config.ConfigError, match="not found"):
        s.require_stockfish()
    with pytest.raises(config.ConfigError, match="No Stockfish"):
        config.Settings().require_stockfish()
