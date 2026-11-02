"""The Evolution tab in the real page: load a game, analyse it, read the graph, look at positions."""

import os

import pytest

from uciboard import config
from uciboard.api import Api

pytestmark = pytest.mark.engine

SCHOLARS = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"


def quick_api(stockfish, tmp_path):
    s = config.load_settings(stockfish=stockfish, own_config=tmp_path / "none.toml")
    s.cache_dir = str(tmp_path / "cache")
    s.evo_depth, s.evo_seconds, s.evo_check_depth = 6, 5.0, 5
    return Api(s)


def ready(page):
    page.wait_for_selector("#engine[data-state=analysing]")      # the page is wired up


def analyse(page, pgn=SCHOLARS):
    ready(page)
    page.click("#tab-evo")
    page.click("#evo-pgn")
    page.fill("#pgn-text", pgn)
    page.click("#pgn-load")
    page.wait_for_selector("#pgn-dialog", state="hidden")
    page.click("#evo-run")
    page.wait_for_selector("#evo-svg .n", timeout=60000)


def test_the_graph_appears_and_can_be_read(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    analyse(page)
    assert page.locator("#evo-svg .n").count() >= 8                  # the game alone has 8 positions
    assert page.locator("#evo-svg .n circle.shape").count() == 8     # circles: played; squares: expected
    assert page.locator("#evo-svg .crown").count() >= 1              # the mate
    assert page.locator("#evo-svg .e").count() >= 7
    assert "Alice" not in page.inner_text("#evo-title")              # this PGN has no names
    assert "7 moves" in page.inner_text("#evo-title")
    assert page.locator("#evo-chart .dot").count() == 7
    assert page.locator("#evo-chart .band").count() == 7
    assert page.locator("#legend-grid .legend-item").count() >= 8
    assert page.is_hidden("#evo-progress")
    assert not errors, errors


def test_clicking_a_position_shows_it_and_back_returns(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    analyse(page)
    final_fen = page.input_value("#fen")
    # the position after 1. e4 (the game's second node)
    page.locator("#evo-svg .n").nth(0).wait_for()
    ids = page.evaluate("[...document.querySelectorAll('#evo-svg .n')].map(g => g.dataset.id)")
    first_main = page.evaluate("""() => {
        const g = [...document.querySelectorAll('#evo-svg .n')].find(g => g.querySelector('text.num') && g.querySelector('text.num').textContent === '1');
        g.dispatchEvent(new MouseEvent('click', {bubbles: true})); return g.dataset.id; }""")
    page.wait_for_selector("#viewbar:not([hidden])")
    assert page.input_value("#fen") != final_fen
    assert page.input_value("#fen").startswith("rnbqkbnr/pppppppp/8/8/4P3")
    assert page.locator("#evo-svg .n.sel").count() == 1
    assert page.locator("#evo-svg .dim").count() > 0                 # others fade
    assert "e4" in page.inner_text("#evo-info")
    # nothing can be played while looking at a position
    assert page.evaluate("document.querySelectorAll('cg-board piece').length") == 32
    page.keyboard.press("Escape")
    page.wait_for_selector("#viewbar", state="hidden")
    assert page.input_value("#fen") == final_fen
    assert page.locator("#evo-svg .n.sel").count() == 0
    assert page.locator("#evo-svg .dim").count() == 0
    assert ids and first_main is not None
    assert not errors, errors


def test_clicking_the_chart_selects_a_move(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    analyse(page)
    page.locator("#evo-chart .hit[data-ply='3']").dispatch_event("click")
    page.wait_for_selector("#viewbar:not([hidden])")
    assert "Bc4" in page.inner_text("#evo-info")
    assert page.locator("#evo-chart .cur").count() == 1
    assert not errors, errors


def test_an_old_graph_says_so_when_the_game_changes(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    analyse(page)
    page.click("#btn-undo")
    page.wait_for_function("document.getElementById('evo-title').textContent.includes('another game')")
    page.click("#tab-uci")
    assert page.is_hidden("#evo")
    assert not errors, errors


def test_a_bad_pgn_is_explained_in_the_dialog(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    ready(page)
    page.click("#tab-evo")
    page.click("#evo-pgn")
    page.fill("#pgn-text", "not a game")
    page.click("#pgn-load")
    page.wait_for_function("document.getElementById('pgn-msg').textContent.length > 0")
    assert page.is_visible("#pgn-dialog")
    assert not errors, errors


def test_cancel_leaves_no_graph(make_page, stockfish, tmp_path):
    page, errors = make_page(quick_api(stockfish, tmp_path))
    ready(page)
    page.click("#tab-evo")
    page.click("#evo-pgn")
    page.fill("#pgn-text", "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *")
    page.click("#pgn-load")
    page.fill("#evo-depth", "24")
    page.fill("#evo-seconds", "30")
    page.click("#evo-run")
    page.wait_for_selector("#evo-cancel:not([hidden])")
    page.click("#evo-cancel")
    page.wait_for_selector("#evo-cancel", state="hidden", timeout=20000)
    assert page.locator("#evo-svg .n").count() == 0
    assert "Cancelled" in page.inner_text("#evo-info")
    assert not errors, errors


def test_screenshot_for_a_look(make_page, stockfish, tmp_path):
    out = os.environ.get("UCIBOARD_SCREENSHOT")
    if not out:
        pytest.skip("set UCIBOARD_SCREENSHOT to a directory")
    page, _ = make_page(quick_api(stockfish, tmp_path))
    analyse(page, "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 *")
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(out, "evolution.png"))
