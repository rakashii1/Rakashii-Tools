import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from _drive_handlers import handle_get, handle_post


class handler(BaseHTTPRequestHandler):
    def action(self):
        params = parse_qs(urlparse(self.path).query)
        explicit = params.get("action", [""])[0]
        if explicit:
            return explicit
        return "callback" if params.get("code") else "status"

    def do_GET(self):
        handle_get(self, self.action())

    def do_POST(self):
        handle_post(self, self.action())
