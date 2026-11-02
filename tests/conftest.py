import functools
import http.server
import json
import os
import shutil
import threading
import time

import pytest

from uciboard.app import STATIC

playwright_sync = pytest.importorskip("playwright.sync_api")


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


# ---- the page in a headless browser, with pywebview replaced by a bridge to the real Api

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


