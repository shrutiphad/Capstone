"""
Mock OTA extranet — run alongside your service to exercise integration resilience.
  python mock_ota/mock_ota_server.py   # serves on :9000

Behavior (intentionally flaky, like a real OTA):
  GET  /rates?property_id=&page=   -> paginated rate list; ~20% of calls return 429 (Retry-After) or 500
  POST /availability               -> accept an availability push; ~15% return 429; duplicate push_id is a no-op (idempotent)
Your booking workflow should push availability here and survive the failures.
"""
import json, random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

random.seed(7)  # deterministic-ish for grading
RATES = {
    "hotel_a": [{"room_type": "deluxe", "date": f"2026-06-{d:02d}", "price_inr": 3000 + d*20} for d in range(1, 25)],
    "hotel_b": [{"room_type": "standard", "date": f"2026-06-{d:02d}", "price_inr": 850 + d*5} for d in range(1, 25)],
}
PAGE = 8
_seen_push = set()

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != "/rates":
            return self._send(404, {"error": "not found"})
        roll = random.random()
        if roll < 0.12:
            return self._send(429, {"error": "rate_limited"}, {"Retry-After": "2"})
        if roll < 0.20:
            return self._send(500, {"error": "upstream"})
        q = parse_qs(u.query)
        pid = (q.get("property_id") or ["hotel_a"])[0]
        page = int((q.get("page") or ["0"])[0])
        rows = RATES.get(pid, [])
        chunk = rows[page*PAGE:(page+1)*PAGE]
        nxt = page+1 if (page+1)*PAGE < len(rows) else None
        self._send(200, {"property_id": pid, "page": page, "rates": chunk, "next_page": nxt})

    def do_POST(self):
        if urlparse(self.path).path != "/availability":
            return self._send(404, {"error": "not found"})
        if random.random() < 0.15:
            return self._send(429, {"error": "rate_limited"}, {"Retry-After": "2"})
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln) or "{}")
        pid_key = body.get("push_id")
        if pid_key in _seen_push:
            return self._send(200, {"status": "duplicate_ignored", "push_id": pid_key})
        _seen_push.add(pid_key)
        self._send(200, {"status": "accepted", "push_id": pid_key})


if __name__ == "__main__":
    print("Mock OTA on http://localhost:9000  (/rates, /availability)")
    HTTPServer(("0.0.0.0", 9000), H).serve_forever()
