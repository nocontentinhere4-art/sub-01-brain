"""Pod-side file server: PUT /in/<name> stores an upload, GET /<name> serves /out/<name>. No auth (short-lived pod,
nothing secret on it). Exits after 60 minutes so a forgotten pod stops working even before it is deleted."""
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory="/out", **k)

    def do_PUT(self):
        name = os.path.basename(self.path)
        n = int(self.headers.get("Content-Length", 0))
        tmp = f"/in/.{name}.part"
        with open(tmp, "wb") as f:
            while n > 0:
                chunk = self.rfile.read(min(n, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                n -= len(chunk)
        os.replace(tmp, f"/in/{name}")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


threading.Thread(target=lambda: (time.sleep(3600), os._exit(0)), daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
