#!/usr/bin/env python3
"""Локальный просмотр лендинга prokop. Без внешних зависимостей.

    python serve.py            # http://127.0.0.1:8124/site/prototype/index.html
    python serve.py 9000       # другой порт

Отдаёт корень репозитория, поэтому работают и исходники, и design/preview.html.
Число тестов в прототипе подставляется из site/tools/test-count.json — тот же
источник, что у сборщика: второго экземпляра числа в проекте нет.
"""
import http.server
import json
import socketserver
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8124
ROOT = Path(__file__).resolve().parent.parent
TESTS_FILE = Path(__file__).resolve().parent / "tools" / "test-count.json"
TOKEN = b"{{TESTS}}"
HTML_SUFFIXES = {".html", ".htm"}


def test_count() -> bytes:
    """Число тестов из записи прогона. Файла нет — знак вопроса, а не выдуманное число."""
    try:
        data = json.loads(TESTS_FILE.read_text(encoding="utf-8"))
        return str(int(data["count"])).encode("ascii")
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.stderr.write(f"serve.py: не прочитал {TESTS_FILE}: {error}\n")
        return b"?"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        target = ROOT / unquote(urlsplit(self.path).path).lstrip("/")
        if target.is_dir():
            target = target / "index.html"
        if target.suffix in HTML_SUFFIXES and target.is_file():
            body = target.read_bytes().replace(TOKEN, test_count())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

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
        print(f"  сборка     → http://127.0.0.1:{PORT}/site/dist/index.html")
        print(f"  тесты      → {TESTS_FILE.relative_to(ROOT)}")
        print("  Ctrl+C — остановить")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nостановлено")
