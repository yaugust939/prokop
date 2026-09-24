#!/usr/bin/env python3
"""Локальный просмотр лендинга prokop. Без внешних зависимостей.

    python serve.py            # http://127.0.0.1:8124/site/prototype/index.html
    python serve.py 9000       # другой порт

Отдаёт корень репозитория, поэтому работают и исходники, и design/preview.html.
"""
import http.server
import socketserver
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8124
ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        print(f"prokop site → http://127.0.0.1:{PORT}/site/prototype/index.html")
        print(f"  исходники  → http://127.0.0.1:{PORT}/site/prototype/index.html")
        print("  Ctrl+C — остановить")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nостановлено")
