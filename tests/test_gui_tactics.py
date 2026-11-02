"""Loose pieces, pins and the labels on the engine's line, in the real page."""

import os

import pytest

from uciboard import config
from uciboard.api import Api

pytestmark = pytest.mark.engine


def page_with(make_page, stockfish, fen):
    s = config.load_settings(stockfish=stockfish)
    api = Api(s)
    api.set_position(fen)
    page, errors = make_page(api)
    page.wait_for_selector("#engine[data-state=analysing]")
    return page, errors


def test_a_loose_piece_is_listed_and_ringed_and_the_toggle_hides_both(make_page, stockfish):
    page, errors = page_with(make_page, stockfish, "4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    page.wait_for_selector("#tactics li.t-loose.now")
    assert "black queen d5" in page.inner_text("#tactics")
    page.wait_for_function("document.querySelectorAll('.cg-shapes circle').length >= 1")
    page.uncheck("#show-loose")
    page.wait_for_function("document.querySelectorAll('.cg-shapes circle').length === 0")
    assert page.locator("#tactics li").count() == 0
    page.check("#show-loose")
    page.wait_for_selector("#tactics li.t-loose")
    assert not errors, errors


def test_a_pin_is_listed(make_page, stockfish):
    page, errors = page_with(make_page, stockfish, "4k3/3q4/2n5/1B6/8/8/8/4K3 w - - 0 1")
    page.wait_for_selector("#tactics li.t-pin")
    assert "white bishop b5 pins black knight c6 to queen d7" in page.inner_text("#tactics")
    page.uncheck("#show-pins")
    page.wait_for_function("document.querySelectorAll('#tactics li.t-pin').length === 0")
    assert not errors, errors


def test_the_engines_line_is_labelled_where_it_forks(make_page, stockfish):
    # Nc7+ forks the king and the queen (the queen on a8 also attacks the knight, so it has to move)
    page, errors = page_with(make_page, stockfish, "q3k3/8/8/3N4/8/8/8/4K2R w - - 0 1")
    page.wait_for_function("document.getElementById('pv').textContent.includes('Nc7+ fork')", timeout=30000)
    assert "attacks" in page.get_attribute("#pv .tag", "title")
    assert not errors, errors


def test_a_quiet_start_shows_nothing_extra(make_page, stockfish):
    page, errors = page_with(make_page, stockfish, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    page.wait_for_selector("#pv span")
    assert page.locator("#tactics li").count() == 0
    assert page.locator("#pv .tag").count() == 0
    assert not errors, errors


def test_screenshot_for_a_look(make_page, stockfish):
    out = os.environ.get("UCIBOARD_SCREENSHOT")
    if not out:
        pytest.skip("set UCIBOARD_SCREENSHOT to a directory")
    page, _ = page_with(make_page, stockfish,
                        "r1bq1rk1/ppp2ppp/2n2n2/3pp3/1b1P4/2NBPN2/PPP2PPP/R1BQ1RK1 w - - 0 7")
    page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(out, "tactics.png"))
