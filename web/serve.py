"""Dev static server for the web client with HTTP caching disabled.

Plain `python3 -m http.server` sends no Cache-Control headers, so browsers
heuristically cache the JS modules — meaning an already-open tab keeps
running stale code after every change until a manual hard refresh. That
made a shipped fix look like a no-op during playtesting. Serving everything
with `Cache-Control: no-store` guarantees a normal reload always fetches
the current files.

Serves the repo root (so /web/... and /assets/... both resolve).
Usage: python3 web/serve.py [port]   (default 5500)
"""

import functools
import http.server
import os
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5500
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    handler = functools.partial(NoCacheHandler, directory=repo_root)
    server = http.server.ThreadingHTTPServer(("", port), handler)
    print(f"serving {repo_root} on http://127.0.0.1:{port} (caching disabled)")
    server.serve_forever()


if __name__ == "__main__":
    main()
