from http.server import BaseHTTPRequestHandler
import os
import sys

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from _shared import get_playlist_urls, read_json_body, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            data = read_json_body(self)
            url = data.get("url", "").strip()
            if not url:
                send_json(self, {"error": "No URL provided"}, 400)
                return
            send_json(self, {"urls": get_playlist_urls(url)})
        except Exception as error:
            send_json(self, {"error": str(error)}, 400)
