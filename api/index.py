from http.server import BaseHTTPRequestHandler
import os
import sys

API_DIR = os.path.dirname(__file__)
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from info import handler as InfoHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        InfoHandler.do_GET(self)
