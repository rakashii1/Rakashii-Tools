from http.server import BaseHTTPRequestHandler
import os
import sys

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from _shared import download_video, read_json_body, send_file_response, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            data = read_json_body(self)
            url = data.get("url", "").strip()
            if not url:
                send_json(self, {"error": "No URL provided"}, 400)
                return

            path, filename = download_video(
                url,
                data.get("format", "max"),
                data.get("format_id"),
                data.get("title", ""),
            )
            send_file_response(self, path, filename)
        except Exception as error:
            send_json(self, {"error": str(error)}, 400)
