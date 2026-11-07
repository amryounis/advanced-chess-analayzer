"""
Desktop window: a native window (pywebview) showing the page in ./static.

The page is served by a small local HTTP server on 127.0.0.1 so ES modules
load the same way in every browser engine pywebview may use (Edge WebView2
on Windows). Nothing is reachable from other machines.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import threading
from pathlib import Path

from . import __version__, config
from .api import Api

STATIC = Path(__file__).parent / "static"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve_static(directory: Path = STATIC) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def launch(settings: config.Settings, debug: bool = False) -> None:
    try:
        import webview
    except ImportError as e:
        raise SystemExit(
            "The desktop app needs pywebview. Install it with:\n"
            '    pip install "uciboard[gui]"') from e

    server = serve_static()
    api = Api(settings)
    port = server.server_address[1]
    window = webview.create_window(
        f"uciboard {__version__}", url=f"http://127.0.0.1:{port}/index.html", js_api=api,
        width=1240, height=820, min_size=(900, 600))
    window.events.closing += api.shutdown
    try:
        webview.start(debug=debug)
    finally:
        api.shutdown()
        server.shutdown()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="uciboard", description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--stockfish", metavar="PATH", help="Stockfish executable (overrides config)")
    ap.add_argument("--analyse", action="store_true", default=None,
                    help="start analysing at once (by default the engine stays idle until you press Analyse)")
    ap.add_argument("--where", action="store_true",
                    help="print which Stockfish would be used, and from where, then exit")
    ap.add_argument("--debug", action="store_true", help="open the web inspector")
    args = ap.parse_args(argv)
    try:
        settings = config.load_settings(stockfish=args.stockfish, analyse=args.analyse)
    except config.ConfigError as e:
        raise SystemExit(str(e)) from e
    if args.where:
        print(f"stockfish_path = {settings.stockfish_path or '(none)'}   [{settings.source}]")
        print(f"threads = {settings.threads}   hash_mb = {settings.hash_mb}   "
              f"multipv = {settings.multipv}   analyse at start = {settings.analyse}")
        print(f"own config: {config.user_config_path()}")
        print(f"engine list: {settings.engines_file}")
        return
    launch(settings, debug=args.debug)
