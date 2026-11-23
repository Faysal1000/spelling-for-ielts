#!/usr/bin/env python3
"""Local preview server that behaves like Vercel for this site.

It sends the headers from vercel.json (Content-Security-Policy and the rest) and supports
clean URLs (/privacy serves privacy.html), so problems show up locally before deploying.

    python3 tools/serve.py            # http://127.0.0.1:8765
    python3 tools/serve.py 9000
"""
import http.server
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, "vercel.json"), encoding="utf-8"))


def to_regex(source):
    # Vercel's path-to-regexp patterns used here are simple groups like /(css|js)/(.*)
    return re.compile("^" + source + "$")


RULES = [(to_regex(rule["source"]), rule["headers"]) for rule in CONFIG.get("headers", [])]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def translate_path(self, path):
        full = super().translate_path(path)
        if CONFIG.get("cleanUrls") and not os.path.exists(full) and os.path.exists(full + ".html"):
            return full + ".html"
        return full

    def end_headers(self):
        path = self.path.split("?", 1)[0]
        for pattern, headers in RULES:
            if pattern.match(path):
                for h in headers:
                    self.send_header(h["key"], h["value"])
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        page = os.path.join(ROOT, "404.html")
        if code == 404 and os.path.exists(page):
            body = open(page, "rb").read()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().send_error(code, message, explain)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Serving {ROOT} on http://127.0.0.1:{port}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
