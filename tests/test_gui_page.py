"""
Drive the real page in a headless browser with a real Stockfish behind it.

pywebview is replaced by a tiny bridge: the page's `window.pywebview.api.<name>(...)`
becomes a POST to this test server, which calls the same Api object the desktop
window would. Everything else (page, chessground, polling) is the real thing.
"""

import json
import os
import shutil
import threading
import functools
import http.server

import pytest

from uciboard import config
from uciboard.api import Api
from uciboard.app import STATIC

playwright_sync = pytest.importorskip("playwright.sync_api")

BRIDGE = """
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) =>
  fetch('/rpc/' + name, { method: 'POST', body: JSON.stringify(args) }).then(r => r.json()) }) };
"""


def make_handler(api):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]
            length = int(self.headers.get("Content-Length", 0))
            args = json.loads(self.rfile.read(length) or "[]")
            if name.startswith("_") or not callable(getattr(api, name, None)):
                self.send_error(404)
                return
            body = json.dumps(getattr(api, name)(*args)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return functools.partial(Handler, directory=str(STATIC))


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            exe = (os.environ.get("UCIBOARD_TEST_CHROME") or shutil.which("google-chrome")
                   or shutil.which("chromium") or shutil.which("chromium-browser"))
            if not exe:
                pytest.skip("no browser for playwright (playwright install chromium)")
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def make_page(browser):
    opened = []

    def make(api):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        page = browser.new_page(viewport={"width": 1240, "height": 820})
        page.add_init_script(BRIDGE)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
        opened.append((page, server, api))
        return page, errors

    yield make
    for page, server, api in opened:
        page.close()
        server.shutdown()
        api.shutdown()


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
    return Api(config.load_settings(stockfish=stockfish))


@pytest.mark.engine
def test_engine_starts_and_streams_uci_output(make_page, stockfish):
    page, errors = make_page(engine_api(stockfish))
    page.wait_for_selector("#engine[data-state=analysing]")
    assert "Stockfish" in page.inner_text("#engine-text")
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
    page.wait_for_selector("#engine[data-state=paused]")
    assert page.inner_text("#btn-pause") == "Resume"
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


@pytest.mark.engine
def test_screenshot(make_page, stockfish, tmp_path):
    page, _ = make_page(engine_api(stockfish))
    page.wait_for_function("document.getElementById('eval').textContent !== '–'")
    for a, b in [("e2", "e4"), ("e7", "e5"), ("g1", "f3")]:
        drag(page, a, b)
        page.wait_for_timeout(200)
    page.wait_for_function("document.getElementById('depth').textContent.includes('depth 1')")
    page.wait_for_timeout(800)
    out = os.environ.get("UCIBOARD_SCREENSHOT")
    if out:
        page.screenshot(path=out)
