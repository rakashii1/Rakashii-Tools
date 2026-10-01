import json
import threading
import time
from http.server import BaseHTTPRequestHandler


clients = {}
clients_lock = threading.Lock()
presence_ttl_seconds = 15
tool_labels = {
    "views-calculator": "Views and Earnings Calculator",
    "video-downloader": "Video Downloader",
    "drive-clipper": "Drive Clipper",
}


def send_json(request_handler, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    request_handler.send_response(status)
    request_handler.send_header("Content-Type", "application/json")
    request_handler.send_header("Cache-Control", "no-store")
    request_handler.send_header("Access-Control-Allow-Origin", "*")
    request_handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    request_handler.send_header("Content-Length", str(len(body)))
    request_handler.end_headers()
    request_handler.wfile.write(body)


def read_presence(request_handler):
    length = int(request_handler.headers.get("content-length", "0") or 0)
    if not length:
        return "", ""
    data = json.loads(request_handler.rfile.read(length).decode("utf-8") or "{}")
    client_id = str(data.get("clientId", "")).strip()[:128]
    tool = str(data.get("tool", "")).strip()[:64]
    return client_id, tool


def get_presence(client_id="", tool=""):
    now = time.time()
    with clients_lock:
        expired_clients = [
            key for key, client in clients.items()
            if now - client["lastSeen"] > presence_ttl_seconds
        ]
        for key in expired_clients:
            clients.pop(key, None)

        if client_id:
            clients[client_id] = {"lastSeen": now, "tool": tool if tool in tool_labels else ""}

        counts = {tool_name: 0 for tool_name in tool_labels}
        for client in clients.values():
            active_tool = client.get("tool", "")
            if active_tool in counts:
                counts[active_tool] += 1
        return {"count": len(clients), "counts": counts}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        send_json(self, {"ok": True, **get_presence()})

    def do_POST(self):
        try:
            client_id, tool = read_presence(self)
            if not client_id:
                send_json(self, {"error": "No client ID provided"}, 400)
                return
            send_json(self, {"ok": True, **get_presence(client_id, tool)})
        except Exception as error:
            send_json(self, {"error": str(error)}, 400)
