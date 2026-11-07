"""
Drive the real page in a headless browser with a real Stockfish behind it.

pywebview is replaced by a tiny bridge: the page's `window.pywebview.api.<name>(...)`
becomes a POST to this test server, which calls the same Api object the desktop
window would. Everything else (page, chessground, polling) is the real thing.
"""

import os

import pytest

from uciboard import config
from uciboard.api import Api


def square_center(page, square, flipped=False):
    box = page.locator("#board").bounding_box()
    file = "abcdefgh".index(square[0])
    rank = int(square[1]) - 1
    col, row = (7 - file, rank) if flipped else (file, 7 - rank)
    s = box["width"] / 8
    return box["x"] + (col + .5) * s, box["y"] + (row + .5) * s


def drag(page, a, b):
    x1, y1 = square_center(page, a)
    x2, y2 = square_center(page, b)
    page.mouse.move(x1, y1)
    page.mouse.down()
    page.mouse.move((x1 + x2) / 2, (y1 + y2) / 2, steps=4)
    page.mouse.move(x2, y2, steps=4)
    page.mouse.up()


def engine_api(stockfish):
    return Api(config.load_settings(stockfish=stockfish, analyse=True))


@pytest.mark.engine
def test_engine_starts_and_streams_uci_output(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    assert "Stockfish" in page.inner_text("#engine-text")
    page.check("#uci-raw")                                        # the raw log, not the table
    page.wait_for_function("document.querySelectorAll('#pane .l').length > 8")
    text = page.inner_text("#pane")
    assert "> uci" in text and "uciok" in text and "> go infinite" in text
    assert "info depth" in text
    page.wait_for_function("document.getElementById('eval').textContent !== '–'")
    assert page.inner_text("#depth").startswith("depth ")
    assert page.inner_text("#pv").startswith("1.")
    assert errors == []


@pytest.mark.engine
def test_moving_a_piece_restarts_the_analysis_on_the_new_position(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    page.wait_for_function("document.getElementById('eval').textContent !== '–'")

    drag(page, "e2", "e4")
    page.wait_for_function("document.getElementById('moves').textContent.includes('e4')")
    assert page.input_value("#fen").startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b")
    # the engine was told about the new position, and is now analysing it for Black
    page.wait_for_function(
        "document.getElementById('pane').textContent.includes('position fen rnbqkbnr/pppppppp/8/8/4P3')")
    page.wait_for_function("document.getElementById('pv').textContent.startsWith('1…')")

    drag(page, "e7", "e5")
    page.wait_for_function("document.getElementById('moves').textContent.includes('e5')")
    page.wait_for_function("document.getElementById('pv').textContent.startsWith('2.')")
    assert page.inner_text("#engine-text").endswith("analysing")
    assert errors == []


@pytest.mark.engine
def test_an_illegal_drag_changes_nothing(make_page, stockfish):
    api = engine_api(stockfish)
    page, _ = make_page(api)
    page.wait_for_selector("#engine[data-state=analysing]")
    drag(page, "e2", "e5")
    page.wait_for_timeout(400)
    assert api.state()["moves"] == []
    # chessground keeps one hidden "ghost" piece in the DOM for dragging; it is not a piece
    assert page.locator("#board piece:not(.ghost)").count() == 32
    assert page.locator("#board piece.ghost").evaluate("e => getComputedStyle(e).visibility") == "hidden"
    assert page.locator("#board piece.pawn.white:not(.ghost)").count() == 8


@pytest.mark.engine
def test_promotion_asks_which_piece(make_page, stockfish):
    api = engine_api(stockfish)
    page, errors = make_page(api)
    page.wait_for_selector("#engine[data-state=analysing]")
    page.fill("#fen", "8/P6k/8/8/8/8/8/K7 w - - 0 1")
    page.press("#fen", "Enter")
    page.wait_for_function("document.querySelector('#board piece.pawn') !== null")
    drag(page, "a7", "a8")
    page.wait_for_selector("#promo:not([hidden])")
    page.click("#promo button[data-p=n]")
    page.wait_for_function("document.getElementById('moves').textContent.includes('a8=N')")
    assert api.state()["moves"] == ["a8=N"]
    assert errors == []


@pytest.mark.engine
def test_controls_undo_flip_pause_resume(make_page, stockfish):
    api = engine_api(stockfish)
    page, _ = make_page(api)
    page.wait_for_selector("#engine[data-state=analysing]")
    drag(page, "d2", "d4")
    page.wait_for_function("document.getElementById('moves').textContent.includes('d4')")

    page.click("#btn-undo")
    page.wait_for_function("document.getElementById('moves').textContent.trim() === ''")
    assert api.state()["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")

    page.click("#btn-flip")
    assert page.locator("#board.orientation-black").count() == 1
    page.keyboard.press("f")
    assert page.locator("#board.orientation-white").count() == 1

    page.click("#btn-pause")
    page.wait_for_selector("#engine[data-state=off]")
    assert page.inner_text("#btn-pause") == "Analyse"
    page.wait_for_function("document.getElementById('pane').textContent.includes('bestmove')")
    page.click("#btn-pause")
    page.wait_for_selector("#engine[data-state=analysing]")


@pytest.mark.engine
def test_checkmate_ends_the_analysis(make_page, stockfish):
    page, _ = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    for a, b in [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]:
        drag(page, a, b)
        page.wait_for_timeout(150)
    page.wait_for_selector("#engine[data-state=idle]")
    assert "Checkmate" in page.inner_text("#msg")


@pytest.mark.engine
def test_scrolling_up_stops_following_and_ticking_follow_returns_to_the_end(make_page, stockfish):
    page, _ = make_page(engine_api(stockfish))
    page.check("#uci-raw")
    page.wait_for_function("document.querySelectorAll('#pane .l').length > 40")
    assert page.is_checked("#follow")
    page.evaluate("document.getElementById('pane').scrollTop = 0")
    page.wait_for_function("!document.getElementById('follow').checked")
    page.check("#follow")
    page.wait_for_function(
        "(() => { const p = document.getElementById('pane');"
        " return p.scrollHeight - p.scrollTop - p.clientHeight < 40; })()")


@pytest.mark.engine
def test_the_pane_keeps_a_bounded_number_of_lines(make_page, stockfish):
    page, _ = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    page.evaluate("""() => { const p = document.getElementById('pane');
      for (let i = 0; i < 3000; i++) { const d = document.createElement('div'); d.className = 'l'; p.append(d); } }""")
    page.wait_for_function("document.querySelectorAll('#pane .l').length <= 1500 + 400")


def test_no_engine_shows_why_and_the_board_still_works(make_page, tmp_path):
    api = Api(config.Settings(stockfish_path=str(tmp_path / "missing.exe"), source="test"))
    page, errors = make_page(api)
    page.wait_for_selector("#engine[data-state=none]")
    page.wait_for_function("document.getElementById('msg').textContent.includes('not found')")
    drag(page, "e2", "e4")
    page.wait_for_function("document.getElementById('moves').textContent.includes('e4')")
    assert errors == []


ARROWS = "document.querySelectorAll('#board .cg-shapes line')"
ONLY = ("((colour, n) => { const a = [...document.querySelectorAll('#board .cg-shapes line')];"
        " return a.length === n && a.every(l => l.getAttribute('stroke').toLowerCase() === colour); })")


def arrow_strokes(page):
    return page.evaluate(f"[...{ARROWS}].map(l => l.getAttribute('stroke').toLowerCase())")


@pytest.mark.engine
def test_best_line_is_drawn_as_arrows_four_by_default(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_function(f"{ARROWS}.length === 4")
    strokes = arrow_strokes(page)
    assert sorted(strokes) == ["#3f6fc4"] * 2 + ["#d06a1f"] * 2    # two for White, two for Black
    # the line under the board marks the same four moves in full, and the rest dimmed
    page.wait_for_function("document.querySelectorAll('#pv .w:not(.far), #pv .b:not(.far)').length === 4")
    assert page.input_value("#arrows") == "4"
    assert errors == []


@pytest.mark.engine
def test_the_arrow_picker_and_the_arrows_following_the_position(make_page, stockfish):
    page, _ = make_page(engine_api(stockfish))
    page.wait_for_function(f"{ARROWS}.length === 4")

    page.select_option("#arrows", "2")
    page.wait_for_function(f"{ARROWS}.length === 2")
    page.select_option("#arrows", "0")
    page.wait_for_function(f"{ARROWS}.length === 0")
    page.select_option("#arrows", "6")
    page.wait_for_function(f"{ARROWS}.length === 6")

    # a move: the old position's arrows go, the new line's arrows come, now starting with Black
    page.select_option("#arrows", "4")
    page.wait_for_function(f"{ARROWS}.length === 4")
    drag(page, "e2", "e4")
    page.wait_for_function("document.getElementById('pv').textContent.startsWith('1…')")
    page.wait_for_function(f"{ARROWS}.length === 4")
    strokes = arrow_strokes(page)
    assert sorted(strokes) == ["#3f6fc4"] * 2 + ["#d06a1f"] * 2

    # the choice is remembered by the page
    assert page.evaluate("localStorage.getItem('arrows')") == "4"


@pytest.mark.engine
def test_screenshot(make_page, stockfish):
    page, _ = make_page(engine_api(stockfish))
    page.wait_for_function(f"{ARROWS}.length === 4")
    page.wait_for_function("parseInt(document.getElementById('depth').textContent.split(' ')[1]) >= 18")
    out = os.environ.get("UCIBOARD_SCREENSHOT")
    if out:
        page.screenshot(path=os.path.join(out, "board.png") if os.path.isdir(out) else out)


@pytest.mark.engine
def test_arrows_for_one_side_only(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_function(f"{ARROWS}.length === 4")
    page.select_option("#arrows", "6")
    page.select_option("#arrow-side", "white")
    page.wait_for_function(f"{ONLY}('#3f6fc4', 3)")             # the shapes are redrawn a frame later
    assert set(arrow_strokes(page)) == {"#3f6fc4"}
    labels = page.evaluate("[...document.querySelectorAll('#board svg text')].map(t => t.textContent)")
    assert sorted(labels) == ["1", "3", "5"]                          # the place in the line is kept
    # the line under the board marks only White's moves in full
    page.wait_for_function("document.querySelectorAll('#pv .w:not(.far)').length === 3")
    assert page.locator("#pv .b:not(.far)").count() == 0

    page.select_option("#arrow-side", "black")
    page.wait_for_function(f"{ONLY}('#d06a1f', 3)")
    assert set(arrow_strokes(page)) == {"#d06a1f"}

    page.select_option("#arrow-side", "both")
    page.wait_for_function(f"{ARROWS}.length === 6")

    # the choice is remembered, and follows the position after a move (Black is to move, so its arrow is first)
    page.select_option("#arrow-side", "black")
    page.reload()
    page.wait_for_selector("#engine[data-state=analysing]")
    assert page.input_value("#arrow-side") == "black"
    assert errors == []


@pytest.mark.engine
def test_the_uci_table_has_one_row_per_depth_newest_first(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    page.wait_for_function("document.querySelectorAll('#uci-table .ur').length >= 6")
    assert page.is_hidden("#pane") and page.is_visible("#uci-table")
    first = page.evaluate("""() => [...document.querySelectorAll('#uci-table .ur')].map(r =>
        Number(r.querySelector('.d').textContent.split('/')[0]))""")
    assert first == sorted(first, reverse=True) and first[0] >= 6               # deepest on top
    row = page.locator("#uci-table .ur").first
    assert "-" in row.locator(".ln").inner_text()                               # long notation: e2-e4
    assert row.locator(".v").inner_text()[0] in "+-#≥≤"
    assert ":" in row.locator(".t").inner_text()
    page.wait_for_function("document.getElementById('u-nodes').textContent.length > 0")
    assert "Stockfish" in page.inner_text("#u-name") and "MB" in page.inner_text("#u-name")
    assert page.inner_text("#u-nps").strip() and page.inner_text("#u-threads").strip()
    page.check("#uci-raw")                                                      # and the log is one click away
    assert page.is_visible("#pane") and page.is_hidden("#uci-table") and page.is_visible("#follow")
    page.uncheck("#uci-raw")
    assert page.is_hidden("#follow")
    assert not errors, errors


@pytest.mark.engine
def test_the_table_starts_again_for_another_position(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_function("document.querySelectorAll('#uci-table .ur').length >= 8")
    drag(page, "e2", "e4")
    page.wait_for_function("document.querySelectorAll('#uci-table .ur').length > 0 && "
                           "document.querySelector('#uci-table .ur .ln').textContent.split(' ')[0].match(/^[a-hNBRQK]/) "
                           "&& document.getElementById('board').dataset.fen.includes('4P3')")
    page.wait_for_function("""() => { const ds = [...document.querySelectorAll('#uci-table .ur .d')]
        .map(d => Number(d.textContent.split('/')[0])); return ds.length > 0 && ds.length < 40 &&
        ds.every((d, i) => i === 0 || d <= ds[i - 1]); }""")
    assert not errors, errors


@pytest.mark.engine
def test_the_page_starts_with_analysis_off_and_the_button_turns_it_on(make_page, stockfish):
    api = Api(config.load_settings(stockfish=stockfish))              # the default: off
    page, errors = make_page(api)
    page.wait_for_selector("#engine[data-state=off]")
    assert page.inner_text("#btn-pause") == "Analyse"
    assert "off" in page.inner_text("#engine-text")
    assert "Press Analyse" in page.inner_text("#line-note")
    page.keyboard.press("Space")                                      # the same switch as the button
    page.wait_for_selector("#engine[data-state=analysing]")
    assert page.inner_text("#btn-pause") == "Stop"
    page.click("#btn-pause")
    page.wait_for_selector("#engine[data-state=off]")
    assert page.inner_text("#btn-pause") == "Analyse"
    assert not errors, errors
